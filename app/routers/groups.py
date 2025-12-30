# app/routers/groups.py - RBAC-Enabled Lead Group Management
# 🔄 UPDATED: Role checks replaced with RBAC permission checks (108 permissions)
# ✅ All endpoints now use permission-based access control

from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from app.decorators.timezone_decorator import convert_dates_to_ist
from app.services.rbac_service import RBACService
from typing import Dict, Any, List, Optional
from datetime import datetime
from bson import ObjectId
import logging

from ..models.group import (
    GroupCreate, GroupUpdate, GroupAddLeads, GroupRemoveLeads,
    GroupResponse, GroupWithLeadsResponse, GroupListResponse, GroupDeleteResponse
)
from ..utils.dependencies import get_current_active_user, get_user_with_permission
from ..config.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Groups"])

# Initialize RBAC service
rbac_service = RBACService()


# =====================================
# HELPER FUNCTIONS
# =====================================

async def generate_group_id(db) -> str:
    """Generate unique group ID like GRP-001, GRP-002, etc."""
    try:
        last_group = await db.lead_groups.find_one(
            sort=[("created_at", -1)]
        )
        
        if last_group and "group_id" in last_group:
            last_num = int(last_group["group_id"].split("-")[1])
            new_num = last_num + 1
        else:
            new_num = 1
        
        return f"GRP-{new_num:03d}"
        
    except Exception as e:
        logger.error(f"Error generating group ID: {e}")
        return f"GRP-{int(datetime.utcnow().timestamp())}"


async def validate_lead_ids(db, lead_ids: List[str]) -> tuple[bool, List[str]]:
    """
    Validate that lead IDs exist (regardless of status)
    Returns: (all_valid: bool, invalid_ids: List[str])
    """
    try:
        if not lead_ids:
            return True, []
        
        valid_leads = await db.leads.find(
            {"lead_id": {"$in": lead_ids}}
        ).to_list(length=None)
        
        valid_lead_ids = [lead["lead_id"] for lead in valid_leads]
        invalid_ids = [lid for lid in lead_ids if lid not in valid_lead_ids]
        
        return len(invalid_ids) == 0, invalid_ids
        
    except Exception as e:
        logger.error(f"Error validating lead IDs: {e}")
        return False, lead_ids


async def get_user_name_from_id(db, user_id: str) -> str:
    """
    Get user's full name from user ID (ObjectId string)
    Returns: Full name or "Unknown User"
    """
    try:
        if not user_id:
            return "Unknown User"
        
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        if user:
            first_name = user.get('first_name', '')
            last_name = user.get('last_name', '')
            full_name = f"{first_name} {last_name}".strip()
            return full_name if full_name else user.get('email', 'Unknown User')
        else:
            return "Unknown User"
    except Exception as e:
        logger.error(f"Error getting user name for ID {user_id}: {e}")
        return "Unknown User"


# =====================================
# RBAC-ENABLED GROUP CRUD OPERATIONS
# =====================================

@router.post("/", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
@convert_dates_to_ist()
async def create_group(
    group_data: GroupCreate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("group.add"))
):
    """
    🔄 RBAC-ENABLED: Create a new group
    
    **Required Permission:** `group.add`
    
    - **name**: Group name (required, unique)
    - **description**: Optional description
    - **lead_ids**: Optional array of lead IDs to add
    """
    try:
        db = get_database()
        
        # Check if group name already exists
        existing = await db.lead_groups.find_one({
            "name": group_data.name
        })
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Group with name '{group_data.name}' already exists"
            )
        
        # Validate lead IDs if provided
        if group_data.lead_ids:
            all_valid, invalid_ids = await validate_lead_ids(db, group_data.lead_ids)
            if not all_valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid lead IDs: {', '.join(invalid_ids)}"
                )
        
        # Generate unique group ID
        group_id = await generate_group_id(db)
        
        # Get creator name
        created_by_name = await get_user_name_from_id(db, str(current_user["_id"]))
        
        # Create group document
        group_doc = {
            "group_id": group_id,
            "name": group_data.name,
            "description": group_data.description or "",
            "lead_ids": group_data.lead_ids or [],
            "lead_count": len(group_data.lead_ids) if group_data.lead_ids else 0,
            "created_by": str(current_user["_id"]),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "updated_by": None
        }
        
        # Insert into database
        result = await db.lead_groups.insert_one(group_doc)
        
        logger.info(f"✅ Group created: {group_id} by {current_user.get('email')}")
        
        return GroupResponse(
            group_id=group_doc["group_id"],
            name=group_doc["name"],
            description=group_doc["description"],
            lead_ids=group_doc["lead_ids"],
            lead_count=group_doc["lead_count"],
            created_by_name=created_by_name,
            created_at=group_doc["created_at"],
            updated_at=group_doc["updated_at"],
            updated_by_name=None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating group: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create group: {str(e)}"
        )


@router.get("/", response_model=GroupListResponse)
@convert_dates_to_ist()
async def get_groups(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by group name"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("group.view"))
):
    """
    🔄 RBAC-ENABLED: Get all groups with pagination and search
    
    **Required Permission:**
    - `group.view` - View own groups
    - `group.view_all` - View all groups (admin)
    
    - **page**: Page number (default: 1)
    - **limit**: Items per page (default: 20, max: 100)
    - **search**: Optional search by group name
    """
    try:
        db = get_database()
        
        # Build match query
        match_query = {}
        
        # Check if user has view_all permission
        has_view_all = await rbac_service.check_permission(current_user, "group.view_all")
        
        if not has_view_all:
            # Regular users can only see their own groups
            user_id = str(current_user.get("_id"))
            match_query["created_by"] = user_id
            logger.info(f"User {current_user.get('email')} accessing own groups only")
        else:
            logger.info(f"Admin {current_user.get('email')} accessing all groups")
            
        if search:
            match_query["name"] = {"$regex": search, "$options": "i"}
        
        # Get total count
        total = await db.lead_groups.count_documents(match_query)
        
        # Calculate skip for pagination
        skip = (page - 1) * limit
        
        # Aggregation pipeline - Populate user names
        pipeline = [
            {"$match": match_query},
            {"$sort": {"created_at": -1}},
            {"$skip": skip},
            {"$limit": limit},
            # Lookup creator info
            {
                "$lookup": {
                    "from": "users",
                    "let": {"creator_id": {"$toObjectId": "$created_by"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$creator_id"]}}},
                        {"$project": {"first_name": 1, "last_name": 1, "email": 1}}
                    ],
                    "as": "creator_info"
                }
            },
            # Lookup updater info
            {
                "$lookup": {
                    "from": "users",
                    "let": {"updater_id": {"$toObjectId": "$updated_by"}},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$updater_id"]}}},
                        {"$project": {"first_name": 1, "last_name": 1, "email": 1}}
                    ],
                    "as": "updater_info"
                }
            }
        ]
        
        # Execute aggregation
        cursor = db.lead_groups.aggregate(pipeline)
        groups = await cursor.to_list(length=limit)
        
        # Format response
        group_responses = []
        for group in groups:
            # Extract creator name
            creator_info = group.get("creator_info", [])
            if creator_info:
                creator = creator_info[0]
                first_name = creator.get('first_name', '')
                last_name = creator.get('last_name', '')
                created_by_name = f"{first_name} {last_name}".strip()
                if not created_by_name:
                    created_by_name = creator.get('email', 'Unknown User')
            else:
                created_by_name = "Unknown User"
            
            # Extract updater name
            updater_info = group.get("updater_info", [])
            updated_by_name = None
            if updater_info:
                updater = updater_info[0]
                first_name = updater.get('first_name', '')
                last_name = updater.get('last_name', '')
                updated_by_name = f"{first_name} {last_name}".strip()
                if not updated_by_name:
                    updated_by_name = updater.get('email', None)
            
            group_responses.append(GroupResponse(
                group_id=group["group_id"],
                name=group["name"],
                description=group.get("description", ""),
                lead_ids=group.get("lead_ids", []),
                lead_count=group.get("lead_count", 0),
                created_by_name=created_by_name,
                created_at=group["created_at"],
                updated_at=group["updated_at"],
                updated_by_name=updated_by_name
            ))
        
        return GroupListResponse(
            groups=group_responses,
            pagination={
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
                "has_next": skip + limit < total,
                "has_prev": page > 1
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Error fetching groups: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch groups: {str(e)}"
        )


@router.get("/{group_id}", response_model=GroupResponse)
@convert_dates_to_ist()
async def get_group_with_leads(
    group_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("group.view"))
):
    """
    🔄 RBAC-ENABLED: Get group details (without populated lead details)
    
    **Required Permission:** `group.view`
    
    - **group_id**: Group ID (e.g., GRP-001)
    
    NOTE: This endpoint returns group info without lead details.
    To get lead details, use GET /leads/ with filters.
    """
    try:
        db = get_database()
        
        # Find group
        group = await db.lead_groups.find_one({"group_id": group_id})
        
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID '{group_id}' not found"
            )
        
        # Check if user has view_all permission or owns the group
        has_view_all = await rbac_service.check_permission(current_user, "group.view_all")
        user_id = str(current_user.get("_id"))
        
        if not has_view_all and group["created_by"] != user_id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to view this group"
            )
        
        # Get creator and updater names
        created_by_name = await get_user_name_from_id(db, group["created_by"])
        updated_by_name = await get_user_name_from_id(db, group.get("updated_by")) if group.get("updated_by") else None
        
        return GroupResponse(
            group_id=group["group_id"],
            name=group["name"],
            description=group.get("description", ""),
            lead_ids=group.get("lead_ids", []),
            lead_count=group.get("lead_count", 0),
            created_by_name=created_by_name,
            created_at=group["created_at"],
            updated_at=group["updated_at"],
            updated_by_name=updated_by_name
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching group details: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch group details: {str(e)}"
        )


@router.put("/{group_id}", response_model=GroupResponse)
@convert_dates_to_ist()
async def update_group(
    group_id: str,
    group_data: GroupUpdate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("group.update"))
):
    """
    🔄 RBAC-ENABLED: Update group details
    
    **Required Permission:** `group.update`
    
    - **name**: Optional new name
    - **description**: Optional new description
    
    NOTE: To add or remove leads, use /groups/{group_id}/leads/add or /groups/{group_id}/leads/remove endpoints
    """
    try:
        db = get_database()
        
        # Find group
        group = await db.lead_groups.find_one({"group_id": group_id})
        
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID '{group_id}' not found"
            )
        
        # Build update dictionary (ONLY name and description)
        update_fields = {}
        
        if group_data.name is not None:
            # Check if new name already exists (excluding current group)
            existing = await db.lead_groups.find_one({
                "name": group_data.name,
                "group_id": {"$ne": group_id}
            })
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Group with name '{group_data.name}' already exists"
                )
            update_fields["name"] = group_data.name
        
        if group_data.description is not None:
            update_fields["description"] = group_data.description
        
        if not update_fields:
            raise HTTPException(
                status_code=400,
                detail="No fields to update. Provide name or description."
            )
        
        # Add update metadata
        update_fields["updated_at"] = datetime.utcnow()
        update_fields["updated_by"] = str(current_user["_id"])
        
        # Update group
        await db.lead_groups.update_one(
            {"group_id": group_id},
            {"$set": update_fields}
        )
        
        # Fetch updated group and populate user names
        updated_group = await db.lead_groups.find_one({"group_id": group_id})
        
        # Get creator and updater names
        created_by_name = await get_user_name_from_id(db, updated_group["created_by"])
        updated_by_name = await get_user_name_from_id(db, updated_group.get("updated_by")) if updated_group.get("updated_by") else None
        
        logger.info(f"✅ Group updated: {group_id} by {current_user.get('email')}")
        
        return GroupResponse(
            group_id=updated_group["group_id"],
            name=updated_group["name"],
            description=updated_group.get("description", ""),
            lead_ids=updated_group.get("lead_ids", []),
            lead_count=updated_group.get("lead_count", 0),
            created_by_name=created_by_name,
            created_at=updated_group["created_at"],
            updated_at=updated_group["updated_at"],
            updated_by_name=updated_by_name
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating group: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update group: {str(e)}"
        )


@router.post("/{group_id}/leads/add", response_model=GroupResponse)
async def add_leads_to_group(
    group_id: str,
    lead_data: GroupAddLeads,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("group.manage_leads"))
):
    """
    🔄 RBAC-ENABLED: Add leads to a group
    
    **Required Permission:** `group.manage_leads`
    
    - **lead_ids**: Array of lead IDs to add (in request body)
    - Users can add their assigned leads to groups
    - Admins with group.view_all can add any leads
    - Duplicates are automatically handled
    
    Example Request Body:
    {
        "lead_ids": ["NS-1", "SA-5", "WA-10"]
    }
    """
    try:
        db = get_database()
        
        # Find group
        group = await db.lead_groups.find_one({"group_id": group_id})
        
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID '{group_id}' not found"
            )
        
        # Check if user has view_all permission
        has_view_all = await rbac_service.check_permission(current_user, "group.view_all")
        
        if not has_view_all:
            # Regular users can only add their assigned leads
            user_email = current_user.get("email")
            
            for lead_id in lead_data.lead_ids:
                lead = await db.leads.find_one({"lead_id": lead_id})
                if not lead:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Lead '{lead_id}' not found"
                    )
                
                # Check if lead is assigned to current user or co-assigned
                is_assigned = (
                    lead.get("assigned_to") == user_email or
                    user_email in lead.get("co_assignees", [])
                )
                
                if not is_assigned:
                    raise HTTPException(
                        status_code=403,
                        detail=f"You can only add leads assigned to you. Lead '{lead_id}' is not assigned to you."
                    )
        
        # Validate lead IDs exist
        all_valid, invalid_ids = await validate_lead_ids(db, lead_data.lead_ids)
        if not all_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid lead IDs: {', '.join(invalid_ids)}"
            )
        
        # Add leads (avoid duplicates using set)
        current_leads = set(group.get("lead_ids", []))
        new_leads = set(lead_data.lead_ids)
        updated_leads = list(current_leads.union(new_leads))
        
        # Calculate how many leads were actually added
        added_count = len(updated_leads) - len(current_leads)
        
        # Update group
        await db.lead_groups.update_one(
            {"group_id": group_id},
            {
                "$set": {
                    "lead_ids": updated_leads,
                    "lead_count": len(updated_leads),
                    "updated_at": datetime.utcnow(),
                    "updated_by": str(current_user["_id"])
                }
            }
        )
        
        # Fetch updated group and populate user names
        updated_group = await db.lead_groups.find_one({"group_id": group_id})
        
        # Get creator and updater names
        created_by_name = await get_user_name_from_id(db, updated_group["created_by"])
        updated_by_name = await get_user_name_from_id(db, updated_group.get("updated_by")) if updated_group.get("updated_by") else None
        
        logger.info(f"✅ {added_count} leads added to group: {group_id} by {current_user.get('email')}")
        
        return GroupResponse(
            group_id=updated_group["group_id"],
            name=updated_group["name"],
            description=updated_group.get("description", ""),
            lead_ids=updated_group.get("lead_ids", []),
            lead_count=updated_group.get("lead_count", 0),
            created_by_name=created_by_name,
            created_at=updated_group["created_at"],
            updated_at=updated_group["updated_at"],
            updated_by_name=updated_by_name
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error adding leads to group: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add leads: {str(e)}"
        )


@router.post("/{group_id}/leads/remove", response_model=GroupResponse)
async def remove_leads_from_group(
    group_id: str,
    lead_data: GroupRemoveLeads,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("group.manage_leads"))
):
    """
    🔄 RBAC-ENABLED: Remove leads from a group
    
    **Required Permission:** `group.manage_leads`
    
    - **lead_ids**: Array of lead IDs to remove (in request body)
    - Users can remove their assigned leads from groups
    - Admins with group.view_all can remove any leads
    
    Example Request Body:
    {
        "lead_ids": ["NS-1", "SA-5"]
    }
    """
    try:
        db = get_database()
        
        # Find group
        group = await db.lead_groups.find_one({"group_id": group_id})
        
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID '{group_id}' not found"
            )
        
        # Check if user has view_all permission
        has_view_all = await rbac_service.check_permission(current_user, "group.view_all")
        
        if not has_view_all:
            # Regular users can only remove their assigned leads
            user_email = current_user.get("email")
            
            for lead_id in lead_data.lead_ids:
                lead = await db.leads.find_one({"lead_id": lead_id})
                if not lead:
                    continue  # Skip if lead not found
                
                # Check if lead is assigned to current user or co-assigned
                is_assigned = (
                    lead.get("assigned_to") == user_email or
                    user_email in lead.get("co_assignees", [])
                )
                
                if not is_assigned:
                    raise HTTPException(
                        status_code=403,
                        detail=f"You can only remove leads assigned to you. Lead '{lead_id}' is not assigned to you."
                    )
        
        # Remove leads using set difference
        current_leads = set(group.get("lead_ids", []))
        leads_to_remove = set(lead_data.lead_ids)
        updated_leads = list(current_leads - leads_to_remove)
        
        # Calculate how many leads were actually removed
        removed_count = len(current_leads) - len(updated_leads)
        
        # Update group
        await db.lead_groups.update_one(
            {"group_id": group_id},
            {
                "$set": {
                    "lead_ids": updated_leads,
                    "lead_count": len(updated_leads),
                    "updated_at": datetime.utcnow(),
                    "updated_by": str(current_user["_id"])
                }
            }
        )
        
        # Fetch updated group and populate user names
        updated_group = await db.lead_groups.find_one({"group_id": group_id})
        
        # Get creator and updater names
        created_by_name = await get_user_name_from_id(db, updated_group["created_by"])
        updated_by_name = await get_user_name_from_id(db, updated_group.get("updated_by")) if updated_group.get("updated_by") else None
        
        logger.info(f"✅ {removed_count} leads removed from group: {group_id} by {current_user.get('email')}")
        
        return GroupResponse(
            group_id=updated_group["group_id"],
            name=updated_group["name"],
            description=updated_group.get("description", ""),
            lead_ids=updated_group.get("lead_ids", []),
            lead_count=updated_group.get("lead_count", 0),
            created_by_name=created_by_name,
            created_at=updated_group["created_at"],
            updated_at=updated_group["updated_at"],
            updated_by_name=updated_by_name
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error removing leads from group: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to remove leads: {str(e)}"
        )


@router.delete("/{group_id}", response_model=GroupDeleteResponse)
async def delete_group(
    group_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("group.delete"))
):
    """
    🔄 RBAC-ENABLED: Delete a group
    
    **Required Permission:** `group.delete`
    
    - **group_id**: Group ID to delete
    - This is a hard delete (permanent removal)
    """
    try:
        db = get_database()
        
        # Find group
        group = await db.lead_groups.find_one({"group_id": group_id})
        
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID '{group_id}' not found"
            )
        
        # Delete group
        result = await db.lead_groups.delete_one({"group_id": group_id})
        
        if result.deleted_count == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Failed to delete group '{group_id}'"
            )
        
        logger.info(f"✅ Group deleted: {group_id} by {current_user.get('email')}")
        
        return GroupDeleteResponse(
            success=True,
            message=f"Group '{group['name']}' deleted successfully",
            group_id=group_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting group: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete group: {str(e)}"
        )