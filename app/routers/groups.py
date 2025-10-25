# app/routers/groups.py
from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from typing import Dict, Any, List, Optional
from datetime import datetime
from bson import ObjectId
import logging

from ..models.group import (
    GroupCreate, GroupUpdate, GroupAddLeads, GroupRemoveLeads,
    GroupResponse, GroupWithLeadsResponse, GroupListResponse, GroupDeleteResponse
)
from ..utils.dependencies import get_admin_user, get_current_active_user
from ..config.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Groups"])

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def generate_group_id(db) -> str:
    """Generate unique group ID like GRP-001, GRP-002, etc."""
    try:
        # Find the last created group
        last_group = await db.lead_groups.find_one(
            sort=[("created_at", -1)]
        )
        
        if last_group and "group_id" in last_group:
            # Extract number from last group_id (e.g., "GRP-001" -> 1)
            last_num = int(last_group["group_id"].split("-")[1])
            new_num = last_num + 1
        else:
            new_num = 1
        
        # Format with leading zeros (GRP-001, GRP-002, etc.)
        return f"GRP-{new_num:03d}"
        
    except Exception as e:
        logger.error(f"Error generating group ID: {e}")
        # Fallback to timestamp-based ID
        return f"GRP-{int(datetime.utcnow().timestamp())}"

async def validate_lead_ids(db, lead_ids: List[str]) -> tuple[bool, List[str]]:
    """
    Validate that lead IDs exist (regardless of status)
    Returns: (all_valid: bool, invalid_ids: List[str])
    """
    try:
        if not lead_ids:
            return True, []
        
        # Find all leads with these IDs (removed status filter)
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

# ============================================================================
# CREATE GROUP
# ============================================================================

@router.post("/", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    group_data: GroupCreate,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Create a new group (Admin only)
    
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
            "created_by": str(current_user["_id"]),  # Store ID internally
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "updated_by": None
        }
        
        # Insert into database
        result = await db.lead_groups.insert_one(group_doc)
        
        logger.info(f"✅ Group created: {group_id} by {current_user.get('email')}")
        
        # Return response with user names (not IDs)
        return GroupResponse(
            group_id=group_doc["group_id"],
            name=group_doc["name"],
            description=group_doc["description"],
            lead_ids=group_doc["lead_ids"],
            lead_count=group_doc["lead_count"],
            created_by_name=created_by_name,  # ✅ Send name instead of ID
            created_at=group_doc["created_at"],
            updated_at=group_doc["updated_at"],
            updated_by_name=None  # ✅ Send name instead of ID
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating group: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create group: {str(e)}"
        )

# ============================================================================
# GET ALL GROUPS (with pagination and search) - ✅ UPDATED WITH AGGREGATION
# ============================================================================

@router.get("/", response_model=GroupListResponse)
async def get_groups(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search by group name"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get all groups with pagination and search
    
    - **page**: Page number (default: 1)
    - **limit**: Items per page (default: 20, max: 100)
    - **search**: Optional search by group name
    """
    try:
        db = get_database()
        
        # Build match query
        match_query = {}
        if search:
            match_query["name"] = {"$regex": search, "$options": "i"}
        
        # Get total count
        total = await db.lead_groups.count_documents(match_query)
        
        # Calculate skip for pagination
        skip = (page - 1) * limit
        
        # 🔥 AGGREGATION PIPELINE - Populate user names
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
            
            # ✅ Create response with names (no IDs)
            group_responses.append(GroupResponse(
                group_id=group["group_id"],
                name=group["name"],
                description=group.get("description", ""),
                lead_ids=group.get("lead_ids", []),
                lead_count=group.get("lead_count", 0),
                created_by_name=created_by_name,  # ✅ Name instead of ID
                created_at=group["created_at"],
                updated_at=group["updated_at"],
                updated_by_name=updated_by_name  # ✅ Name instead of ID
            ))
        
        return GroupListResponse(
            groups=group_responses,
            total=total,
            page=page,
            limit=limit,
            has_next=skip + limit < total,  # ✅ Added has_next
            has_prev=page > 1  # ✅ Added has_prev
        )
        
    except Exception as e:
        logger.error(f"❌ Error fetching groups: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch groups: {str(e)}"
        )

# ============================================================================
# GET SINGLE GROUP BY ID (with populated lead details)
# ============================================================================

@router.get("/{group_id}", response_model=GroupWithLeadsResponse)
async def get_group_with_leads(
    group_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get group details with populated lead information
    
    - **group_id**: Group ID (e.g., GRP-001)
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
        
        # Get creator and updater names
        created_by_name = await get_user_name_from_id(db, group["created_by"])
        updated_by_name = await get_user_name_from_id(db, group.get("updated_by")) if group.get("updated_by") else None
        
        # Fetch lead details
        leads = []
        if group.get("lead_ids"):
            lead_cursor = db.leads.find(
                {"lead_id": {"$in": group["lead_ids"]}},
                {
                    "lead_id": 1,
                    "name": 1,
                    "email": 1,
                    "contact_number": 1,
                    "stage": 1,
                    "assigned_to": 1,
                    "status": 1
                }
            )
            
            async for lead in lead_cursor:
                # Get assigned user name
                assigned_to_name = None
                if lead.get("assigned_to"):
                    assigned_user = await db.users.find_one({"email": lead["assigned_to"]})
                    if assigned_user:
                        first_name = assigned_user.get('first_name', '')
                        last_name = assigned_user.get('last_name', '')
                        assigned_to_name = f"{first_name} {last_name}".strip()
                        if not assigned_to_name:
                            assigned_to_name = assigned_user.get('email', 'Unknown')
                
                leads.append({
                    "lead_id": lead["lead_id"],
                    "name": lead["name"],
                    "email": lead["email"],
                    "contact_number": lead.get("contact_number", ""),
                    "stage": lead.get("stage", "new"),
                    "status": lead.get("status", "open"),
                    "assigned_to_name": assigned_to_name
                })
        
        return GroupWithLeadsResponse(
            group_id=group["group_id"],
            name=group["name"],
            description=group.get("description", ""),
            lead_ids=group.get("lead_ids", []),
            lead_count=group.get("lead_count", 0),
            created_by_name=created_by_name,  # ✅ Name instead of ID
            created_at=group["created_at"],
            updated_at=group["updated_at"],
            updated_by_name=updated_by_name,  # ✅ Name instead of ID
            leads=leads
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching group details: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch group details: {str(e)}"
        )

# ============================================================================
# UPDATE GROUP - ✅ UPDATED: Only name and description (NO lead_ids replacement)
# ============================================================================

@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: str,
    group_data: GroupUpdate,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Update group details (Admin only)
    
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
        
        # ❌ REMOVED: lead_ids replacement logic
        # Users must use /add or /remove endpoints to manage leads
        
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
            created_by_name=created_by_name,  # ✅ Name instead of ID
            created_at=updated_group["created_at"],
            updated_at=updated_group["updated_at"],
            updated_by_name=updated_by_name  # ✅ Name instead of ID
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating group: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update group: {str(e)}"
        )

# ============================================================================
# ADD LEADS TO GROUP - ✅ This is the PRIMARY way to add leads
# ============================================================================

@router.post("/{group_id}/leads/add", response_model=GroupResponse)
async def add_leads_to_group(
    group_id: str,
    lead_data: GroupAddLeads,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Add leads to an existing group (Admin only)
    
    - **lead_ids**: Array of lead IDs to add (in request body)
    - Duplicates are automatically handled (no duplicates in final array)
    
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
        
        # Validate lead IDs
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
            created_by_name=created_by_name,  # ✅ Name instead of ID
            created_at=updated_group["created_at"],
            updated_at=updated_group["updated_at"],
            updated_by_name=updated_by_name  # ✅ Name instead of ID
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error adding leads to group: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add leads: {str(e)}"
        )

# ============================================================================
# REMOVE LEADS FROM GROUP
# ============================================================================

@router.post("/{group_id}/leads/remove", response_model=GroupResponse)
async def remove_leads_from_group(
    group_id: str,
    lead_data: GroupRemoveLeads,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Remove leads from a group (Admin only)
    
    - **lead_ids**: Array of lead IDs to remove (in request body)
    
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
            created_by_name=created_by_name,  # ✅ Name instead of ID
            created_at=updated_group["created_at"],
            updated_at=updated_group["updated_at"],
            updated_by_name=updated_by_name  # ✅ Name instead of ID
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error removing leads from group: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to remove leads: {str(e)}"
        )

# ============================================================================
# DELETE GROUP
# ============================================================================

@router.delete("/{group_id}", response_model=GroupDeleteResponse)
async def delete_group(
    group_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Delete a group (Admin only)
    
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