# app/routers/groups.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
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
            created_by=group_doc["created_by"],
            created_at=group_doc["created_at"],
            updated_at=group_doc["updated_at"],
            updated_by=group_doc["updated_by"]
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
# GET ALL GROUPS (with pagination and search)
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
        
        # Build query
        query = {}
        if search:
            query["name"] = {"$regex": search, "$options": "i"}
        
        # Get total count
        total = await db.lead_groups.count_documents(query)
        
        # Calculate skip for pagination
        skip = (page - 1) * limit
        
        # Fetch groups with pagination
        cursor = db.lead_groups.find(query).skip(skip).limit(limit).sort("created_at", -1)
        groups = await cursor.to_list(length=limit)
        
        # Format response
        group_responses = []
        for group in groups:
            group_responses.append(GroupResponse(
                group_id=group["group_id"],
                name=group["name"],
                description=group.get("description", ""),
                lead_ids=group.get("lead_ids", []),
                lead_count=group.get("lead_count", 0),
                created_by=group["created_by"],
                created_at=group["created_at"],
                updated_at=group["updated_at"],
                updated_by=group.get("updated_by")
            ))
        
        return GroupListResponse(
            success=True,
            groups=group_responses,
            total=total,
            page=page,
            limit=limit
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
        
        # Fetch lead details
        leads = []
        if group.get("lead_ids"):
            cursor = db.leads.find({
                "lead_id": {"$in": group["lead_ids"]}
            })
            lead_docs = await cursor.to_list(length=None)
            
            # Format lead data for response
            leads = [
                {
                    "lead_id": lead["lead_id"],
                    "name": lead["name"],
                    "email": lead.get("email", ""),
                    "contact_number": lead.get("contact_number", ""),
                    "stage": lead.get("stage", ""),
                    "assigned_to_name": lead.get("assigned_to_name", "Unassigned"),
                    "category": lead.get("category", "")
                }
                for lead in lead_docs
            ]
        
        return GroupWithLeadsResponse(
            group_id=group["group_id"],
            name=group["name"],
            description=group.get("description", ""),
            lead_ids=group.get("lead_ids", []),
            lead_count=group.get("lead_count", 0),
            created_by=group["created_by"],
            created_at=group["created_at"],
            updated_at=group["updated_at"],
            updated_by=group.get("updated_by"),
            leads=leads
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching group: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch group: {str(e)}"
        )

# ============================================================================
# UPDATE GROUP
# ============================================================================

@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: str,
    update_data: GroupUpdate,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Update group details (Admin only)
    
    - **name**: Optional new name
    - **description**: Optional new description
    - **lead_ids**: Optional replacement of all lead IDs
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
        
        # Build update document
        update_doc = {
            "updated_at": datetime.utcnow(),
            "updated_by": str(current_user["_id"])
        }
        
        # Update name if provided
        if update_data.name:
            # Check name uniqueness (excluding current group)
            existing = await db.lead_groups.find_one({
                "name": update_data.name,
                "group_id": {"$ne": group_id}
            })
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Group with name '{update_data.name}' already exists"
                )
            update_doc["name"] = update_data.name
        
        # Update description if provided
        if update_data.description is not None:
            update_doc["description"] = update_data.description
        
        # Update lead_ids if provided
        if update_data.lead_ids is not None:
            # Validate lead IDs
            all_valid, invalid_ids = await validate_lead_ids(db, update_data.lead_ids)
            if not all_valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid lead IDs: {', '.join(invalid_ids)}"
                )
            update_doc["lead_ids"] = update_data.lead_ids
            update_doc["lead_count"] = len(update_data.lead_ids)
        
        # Update group in database
        await db.lead_groups.update_one(
            {"group_id": group_id},
            {"$set": update_doc}
        )
        
        # Fetch updated group
        updated_group = await db.lead_groups.find_one({"group_id": group_id})
        
        logger.info(f"✅ Group updated: {group_id} by {current_user.get('email')}")
        
        return GroupResponse(
            group_id=updated_group["group_id"],
            name=updated_group["name"],
            description=updated_group.get("description", ""),
            lead_ids=updated_group.get("lead_ids", []),
            lead_count=updated_group.get("lead_count", 0),
            created_by=updated_group["created_by"],
            created_at=updated_group["created_at"],
            updated_at=updated_group["updated_at"],
            updated_by=updated_group.get("updated_by")
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
# ADD LEADS TO GROUP
# ============================================================================

@router.post("/{group_id}/leads/add", response_model=GroupResponse)
async def add_leads_to_group(
    group_id: str,
    lead_data: GroupAddLeads,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Add leads to an existing group (Admin only)
    
    - **lead_ids**: Array of lead IDs to add
    - Duplicates are automatically handled (no duplicates in final array)
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
        
        # Fetch updated group
        updated_group = await db.lead_groups.find_one({"group_id": group_id})
        
        logger.info(f"✅ Leads added to group: {group_id} by {current_user.get('email')}")
        
        return GroupResponse(
            group_id=updated_group["group_id"],
            name=updated_group["name"],
            description=updated_group.get("description", ""),
            lead_ids=updated_group.get("lead_ids", []),
            lead_count=updated_group.get("lead_count", 0),
            created_by=updated_group["created_by"],
            created_at=updated_group["created_at"],
            updated_at=updated_group["updated_at"],
            updated_by=updated_group.get("updated_by")
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
    
    - **lead_ids**: Array of lead IDs to remove
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
        
        # Fetch updated group
        updated_group = await db.lead_groups.find_one({"group_id": group_id})
        
        logger.info(f"✅ Leads removed from group: {group_id} by {current_user.get('email')}")
        
        return GroupResponse(
            group_id=updated_group["group_id"],
            name=updated_group["name"],
            description=updated_group.get("description", ""),
            lead_ids=updated_group.get("lead_ids", []),
            lead_count=updated_group.get("lead_count", 0),
            created_by=updated_group["created_by"],
            created_at=updated_group["created_at"],
            updated_at=updated_group["updated_at"],
            updated_by=updated_group.get("updated_by")
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