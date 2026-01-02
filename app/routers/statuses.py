# app/routers/statuses.py - NEW FILE FOR STATUS API ENDPOINTS

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Dict, Any
import logging

from ..models.lead_status import StatusCreate, StatusUpdate, StatusResponse, StatusListResponse
from ..services.status_service import status_service
from ..utils.dependencies import get_current_active_user, get_admin_user, get_user_with_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["statuses"])

# ============================================================================
# PUBLIC ENDPOINTS (All authenticated users can view statuses)
# ============================================================================

@router.get("/", response_model=StatusListResponse)
async def get_all_statuses(
    include_lead_count: bool = Query(False, description="Include lead count for each status"),
    active_only: bool = Query(True, description="Only return active statuses"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("status.view"))
):
    """
    🔄 RBAC-ENABLED: Get all statuses
    
    **Required Permission:** `status.view`
    
    Used for dropdowns in lead creation/editing
    """
    try:
        logger.info(f"Getting statuses for user: {current_user.get('email')}")
        
        statuses = await status_service.get_all_statuses(
            include_lead_count=include_lead_count,
            active_only=active_only
        )
        
        # Get ALL statuses first to get accurate counts
        all_statuses = await status_service.get_all_statuses(
            include_lead_count=False,
            active_only=False
        )
        
        # Count totals from ALL statuses
        total_statuses = len(all_statuses)
        active_count = sum(1 for s in all_statuses if s.get("is_active", True))
        inactive_count = total_statuses - active_count
        
        return StatusListResponse(
            statuses=statuses,
            total=len(statuses),
            active_count=active_count,
            inactive_count=inactive_count
        )
        
    except Exception as e:
        logger.error(f"Error getting statuses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get statuses: {str(e)}"
        )

@router.get("/inactive", response_model=StatusListResponse)
async def get_inactive_statuses(
    include_lead_count: bool = Query(False, description="Include lead count for each status"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("status.view"))
):
    """
    🔄 RBAC-ENABLED: Get all inactive/deactivated statuses that can be reactivated
    
    **Required Permission:** `status.view`
    
    Useful for admin to see what statuses can be restored
    """
    try:
        logger.info(f"Getting inactive statuses for user: {current_user.get('email')}")
        
        # Get ALL statuses first to get accurate counts
        all_statuses = await status_service.get_all_statuses(
            include_lead_count=include_lead_count,
            active_only=False
        )
        
        # Filter to only inactive statuses
        inactive_statuses = [status for status in all_statuses if not status.get("is_active", True)]
        
        # Count totals from ALL statuses
        total_statuses = len(all_statuses)
        active_count = sum(1 for status in all_statuses if status.get("is_active", True))
        inactive_count = total_statuses - active_count
        
        return StatusListResponse(
            statuses=inactive_statuses,
            total=len(inactive_statuses),
            active_count=active_count,
            inactive_count=inactive_count
        )
        
    except Exception as e:
        logger.error(f"Error getting inactive statuses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get inactive statuses: {str(e)}"
        )

@router.get("/active", response_model=StatusListResponse)
async def get_active_statuses(
    include_lead_count: bool = Query(False, description="Include lead count for each status"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("status.view"))
):
    """
    🔄 RBAC-ENABLED: Get all active statuses (explicitly active only)
    
    **Required Permission:** `status.view`
    
    Useful for lead creation dropdowns
    """
    try:
        logger.info(f"Getting active statuses for user: {current_user.get('email')}")
        
        # Get ALL statuses first to get accurate counts
        all_statuses = await status_service.get_all_statuses(
            include_lead_count=include_lead_count,
            active_only=False
        )
        
        # Filter to only active statuses
        active_statuses = [status for status in all_statuses if status.get("is_active", True)]
        
        # Count totals from ALL statuses
        total_statuses = len(all_statuses)
        active_count = len(active_statuses)
        inactive_count = total_statuses - active_count
        
        return StatusListResponse(
            statuses=active_statuses,
            total=len(active_statuses),
            active_count=active_count,
            inactive_count=inactive_count
        )
        
    except Exception as e:
        logger.error(f"Error getting active statuses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get active statuses: {str(e)}"
        )

@router.get("/{status_id}", response_model=StatusResponse)
async def get_status_by_id(
    status_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("status.view"))
):
    """
    🔄 RBAC-ENABLED: Get a specific status by ID
    
    **Required Permission:** `status.view`
    """
    try:
        status = await status_service.get_status_by_id(status_id)
        return StatusResponse(**status)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error getting status {status_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get status: {str(e)}"
        )

# ============================================================================
# ADMIN-ONLY ENDPOINTS (Status management)
# ============================================================================

@router.post("/", response_model=Dict[str, Any])
async def create_status(
    status_data: StatusCreate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("status.create"))
):
    """
    🔄 RBAC-ENABLED: Create a new status
    
    **Required Permission:** `status.create`
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Creating status '{status_data.name}' by admin: {user_email}")
        
        result = await status_service.create_status(status_data, user_email)
        
        return {
            "success": True,
            "message": result["message"],
            "status": result["status"]
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error creating status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create status: {str(e)}"
        )

@router.put("/{status_id}", response_model=Dict[str, Any])
async def update_status(
    status_id: str,
    status_data: StatusUpdate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("status.edit"))
):
    """
    🔄 RBAC-ENABLED: Update an existing status
    
    **Required Permission:** `status.edit`
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Updating status {status_id} by admin: {user_email}")
        
        result = await status_service.update_status(status_id, status_data, user_email)
        
        return {
            "success": True,
            "message": result["message"],
            "status": result["status"]
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error updating status {status_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update status: {str(e)}"
        )

@router.patch("/{status_id}/activate", response_model=Dict[str, Any])
async def activate_status(
    status_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("status.edit"))
):
    """
    🔄 RBAC-ENABLED: Activate a deactivated status
    
    **Required Permission:** `status.edit`
    """
    try:
        from ..config.database import get_database
        from bson import ObjectId
        from datetime import datetime
        
        user_email = current_user.get("email", "unknown")
        logger.info(f"Activating status {status_id} by admin: {user_email}")
        
        db = get_database()
        
        # Check if status exists
        status = await db.lead_statuses.find_one({"_id": ObjectId(status_id)})
        if not status:
            raise ValueError(f"Status with ID {status_id} not found")
        
        # Update status to active
        result = await db.lead_statuses.update_one(
            {"_id": ObjectId(status_id)},
            {
                "$set": {
                    "is_active": True,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        if result.modified_count == 0:
            return {
                "success": True,
                "message": f"Status '{status['name']}' was already active",
                "action": "no_change"
            }
        
        logger.info(f"Status '{status['name']}' activated by {user_email}")
        
        return {
            "success": True,
            "message": f"Status '{status['name']}' activated successfully",
            "action": "activated"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error activating status {status_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate status: {str(e)}"
        )

@router.patch("/{status_id}/deactivate", response_model=Dict[str, Any])
async def deactivate_status(
    status_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("status.edit"))
):
    """
    🔄 RBAC-ENABLED: Deactivate a status without deleting it
    
    **Required Permission:** `status.edit`
    """

    try:
        from ..config.database import get_database
        from bson import ObjectId
        from datetime import datetime
        
        user_email = current_user.get("email", "unknown")
        logger.info(f"Deactivating status {status_id} by admin: {user_email}")
        
        db = get_database()
        
        # Check if status exists
        status = await db.lead_statuses.find_one({"_id": ObjectId(status_id)})
        if not status:
            raise ValueError(f"Status with ID {status_id} not found")
        
        # Check if this is the only active status
        active_count = await db.lead_statuses.count_documents({"is_active": True})
        if active_count <= 1 and status.get("is_active", True):
            raise ValueError("Cannot deactivate the last active status")
        
        # Update status to inactive
        result = await db.lead_statuses.update_one(
            {"_id": ObjectId(status_id)},
            {
                "$set": {
                    "is_active": False,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        if result.modified_count == 0:
            return {
                "success": True,
                "message": f"Status '{status['name']}' was already inactive",
                "action": "no_change"
            }
        
        logger.info(f"Status '{status['name']}' deactivated by {user_email}")
        
        return {
            "success": True,
            "message": f"Status '{status['name']}' deactivated successfully",
            "action": "deactivated"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error deactivating status {status_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deactivate status: {str(e)}"
        )

@router.delete("/{status_id}", response_model=Dict[str, Any])
async def delete_status(
    status_id: str,
    force: bool = Query(False, description="Force delete even if status has leads"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("status.delete"))
):
    """
    🔄 RBAC-ENABLED: Delete a status
    
    **Required Permission:** `status.delete`
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Deleting status {status_id} by admin: {user_email} (force={force})")
        
        result = await status_service.delete_status(status_id, user_email, force)
        
        return {
            "success": True,
            "message": result["message"],
            "action": result["action"],
            "lead_count": result["lead_count"]
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error deleting status {status_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete status: {str(e)}"
        )

@router.patch("/reorder", response_model=Dict[str, Any])
async def reorder_statuses(
    status_orders: List[Dict[str, Any]],
    current_user: Dict[str, Any] = Depends(get_user_with_permission("status.edit"))
):
    """
    🔄 RBAC-ENABLED: Reorder statuses by updating sort_order
    
    **Required Permission:** `status.edit`
    
    Request body example:
    [
        {"id": "status_id_1", "sort_order": 1},
        {"id": "status_id_2", "sort_order": 2},
        {"id": "status_id_3", "sort_order": 3}
    ]
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Reordering statuses by admin: {user_email}")
        
        result = await status_service.reorder_statuses(status_orders, user_email)
        
        return {
            "success": True,
            "message": result["message"],
            "updated_count": result["updated_count"]
        }
        
    except Exception as e:
        logger.error(f"Error reordering statuses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reorder statuses: {str(e)}"
        )

# ============================================================================
# UTILITY ENDPOINTS
# ============================================================================

@router.get("/default/name")
async def get_default_status_name(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("status.view"))
):
    """
    🔄 RBAC-ENABLED: Get the default status name for new leads
    
    **Required Permission:** `status.view`
    """
    try:
        from ..models.lead_status import StatusHelper
        
        default_status = await StatusHelper.get_default_status()
        
        return {
            "success": True,
            "default_status": default_status
        }
        
    except Exception as e:
        logger.error(f"Error getting default status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get default status: {str(e)}"
        )

@router.post("/setup/defaults")
async def setup_default_statuses(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("status.create"))
):
    """
    🔄 RBAC-ENABLED: Setup default statuses if none exist
    
    **Required Permission:** `status.create`
    """
    try:
        from ..models.lead_status import StatusHelper
        
        user_email = current_user.get("email", "unknown")
        logger.info(f"Setting up default statuses by admin: {user_email}")
        
        created_count = await StatusHelper.create_default_statuses()
        
        if created_count:
            return {
                "success": True,
                "message": f"Created {created_count} default statuses",
                "created_count": created_count
            }
        else:
            return {
                "success": True,
                "message": "Default statuses already exist or admin must create manually",
                "created_count": 0
            }
        
    except Exception as e:
        logger.error(f"Error setting up default statuses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to setup default statuses: {str(e)}"
        )# app/routers/statuses.py - NEW FILE FOR STATUS API ENDPOINTS

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Dict, Any
import logging

from ..models.lead_status import StatusCreate, StatusUpdate, StatusResponse, StatusListResponse
from ..services.status_service import status_service
from ..utils.dependencies import get_current_active_user, get_admin_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["statuses"])

# ============================================================================
# PUBLIC ENDPOINTS (All authenticated users can view statuses)
# ============================================================================

@router.get("/", response_model=StatusListResponse)
async def get_all_statuses(
    include_lead_count: bool = Query(False, description="Include lead count for each status"),
    active_only: bool = Query(True, description="Only return active statuses"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get all statuses (visible to all authenticated users)
    Used for dropdowns in lead creation/editing
    """
    try:
        logger.info(f"Getting statuses for user: {current_user.get('email')}")
        
        statuses = await status_service.get_all_statuses(
            include_lead_count=include_lead_count,
            active_only=active_only
        )
        
        # Get ALL statuses first to get accurate counts
        all_statuses = await status_service.get_all_statuses(
            include_lead_count=False,
            active_only=False
        )
        
        # Count totals from ALL statuses
        total_statuses = len(all_statuses)
        active_count = sum(1 for s in all_statuses if s.get("is_active", True))
        inactive_count = total_statuses - active_count
        
        return StatusListResponse(
            statuses=statuses,
            total=len(statuses),
            active_count=active_count,
            inactive_count=inactive_count
        )
        
    except Exception as e:
        logger.error(f"Error getting statuses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get statuses: {str(e)}"
        )

@router.get("/inactive", response_model=StatusListResponse)
async def get_inactive_statuses(
    include_lead_count: bool = Query(False, description="Include lead count for each status"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get all inactive/deactivated statuses that can be reactivated
    Useful for admin to see what statuses can be restored
    """
    try:
        logger.info(f"Getting inactive statuses for user: {current_user.get('email')}")
        
        # Get ALL statuses first to get accurate counts
        all_statuses = await status_service.get_all_statuses(
            include_lead_count=include_lead_count,
            active_only=False
        )
        
        # Filter to only inactive statuses
        inactive_statuses = [status for status in all_statuses if not status.get("is_active", True)]
        
        # Count totals from ALL statuses
        total_statuses = len(all_statuses)
        active_count = sum(1 for status in all_statuses if status.get("is_active", True))
        inactive_count = total_statuses - active_count
        
        return StatusListResponse(
            statuses=inactive_statuses,
            total=len(inactive_statuses),
            active_count=active_count,
            inactive_count=inactive_count
        )
        
    except Exception as e:
        logger.error(f"Error getting inactive statuses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get inactive statuses: {str(e)}"
        )

@router.get("/active", response_model=StatusListResponse)
async def get_active_statuses(
    include_lead_count: bool = Query(False, description="Include lead count for each status"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get all active statuses (explicitly active only)
    Useful for lead creation dropdowns
    """
    try:
        logger.info(f"Getting active statuses for user: {current_user.get('email')}")
        
        # Get ALL statuses first to get accurate counts
        all_statuses = await status_service.get_all_statuses(
            include_lead_count=include_lead_count,
            active_only=False
        )
        
        # Filter to only active statuses
        active_statuses = [status for status in all_statuses if status.get("is_active", True)]
        
        # Count totals from ALL statuses
        total_statuses = len(all_statuses)
        active_count = len(active_statuses)
        inactive_count = total_statuses - active_count
        
        return StatusListResponse(
            statuses=active_statuses,
            total=len(active_statuses),
            active_count=active_count,
            inactive_count=inactive_count
        )
        
    except Exception as e:
        logger.error(f"Error getting active statuses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get active statuses: {str(e)}"
        )

@router.get("/{status_id}", response_model=StatusResponse)
async def get_status_by_id(
    status_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """Get a specific status by ID"""
    try:
        status = await status_service.get_status_by_id(status_id)
        return StatusResponse(**status)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error getting status {status_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get status: {str(e)}"
        )

# ============================================================================
# ADMIN-ONLY ENDPOINTS (Status management)
# ============================================================================

@router.post("/", response_model=Dict[str, Any])
async def create_status(
    status_data: StatusCreate,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """Create a new status (Admin only)"""
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Creating status '{status_data.name}' by admin: {user_email}")
        
        result = await status_service.create_status(status_data, user_email)
        
        return {
            "success": True,
            "message": result["message"],
            "status": result["status"]
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error creating status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create status: {str(e)}"
        )

@router.put("/{status_id}", response_model=Dict[str, Any])
async def update_status(
    status_id: str,
    status_data: StatusUpdate,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """Update an existing status (Admin only)"""
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Updating status {status_id} by admin: {user_email}")
        
        result = await status_service.update_status(status_id, status_data, user_email)
        
        return {
            "success": True,
            "message": result["message"],
            "status": result["status"]
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error updating status {status_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update status: {str(e)}"
        )

@router.patch("/{status_id}/activate", response_model=Dict[str, Any])
async def activate_status(
    status_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """Activate a deactivated status (Admin only)"""
    try:
        from ..config.database import get_database
        from bson import ObjectId
        from datetime import datetime
        
        user_email = current_user.get("email", "unknown")
        logger.info(f"Activating status {status_id} by admin: {user_email}")
        
        db = get_database()
        
        # Check if status exists
        status = await db.lead_statuses.find_one({"_id": ObjectId(status_id)})
        if not status:
            raise ValueError(f"Status with ID {status_id} not found")
        
        # Update status to active
        result = await db.lead_statuses.update_one(
            {"_id": ObjectId(status_id)},
            {
                "$set": {
                    "is_active": True,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        if result.modified_count == 0:
            return {
                "success": True,
                "message": f"Status '{status['name']}' was already active",
                "action": "no_change"
            }
        
        logger.info(f"Status '{status['name']}' activated by {user_email}")
        
        return {
            "success": True,
            "message": f"Status '{status['name']}' activated successfully",
            "action": "activated"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error activating status {status_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate status: {str(e)}"
        )

@router.patch("/{status_id}/deactivate", response_model=Dict[str, Any])
async def deactivate_status(
    status_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """Deactivate a status without deleting it (Admin only)"""
    try:
        from ..config.database import get_database
        from bson import ObjectId
        from datetime import datetime
        
        user_email = current_user.get("email", "unknown")
        logger.info(f"Deactivating status {status_id} by admin: {user_email}")
        
        db = get_database()
        
        # Check if status exists
        status = await db.lead_statuses.find_one({"_id": ObjectId(status_id)})
        if not status:
            raise ValueError(f"Status with ID {status_id} not found")
        
        # Check if this is the only active status
        active_count = await db.lead_statuses.count_documents({"is_active": True})
        if active_count <= 1 and status.get("is_active", True):
            raise ValueError("Cannot deactivate the last active status")
        
        # Update status to inactive
        result = await db.lead_statuses.update_one(
            {"_id": ObjectId(status_id)},
            {
                "$set": {
                    "is_active": False,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        if result.modified_count == 0:
            return {
                "success": True,
                "message": f"Status '{status['name']}' was already inactive",
                "action": "no_change"
            }
        
        logger.info(f"Status '{status['name']}' deactivated by {user_email}")
        
        return {
            "success": True,
            "message": f"Status '{status['name']}' deactivated successfully",
            "action": "deactivated"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error deactivating status {status_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deactivate status: {str(e)}"
        )

@router.delete("/{status_id}", response_model=Dict[str, Any])
async def delete_status(
    status_id: str,
    force: bool = Query(False, description="Force delete even if status has leads"),
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """Delete a status (Admin only)"""
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Deleting status {status_id} by admin: {user_email} (force={force})")
        
        result = await status_service.delete_status(status_id, user_email, force)
        
        return {
            "success": True,
            "message": result["message"],
            "action": result["action"],
            "lead_count": result["lead_count"]
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error deleting status {status_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete status: {str(e)}"
        )

@router.patch("/reorder", response_model=Dict[str, Any])
async def reorder_statuses(
    status_orders: List[Dict[str, Any]],
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Reorder statuses by updating sort_order (Admin only)
    
    Request body example:
    [
        {"id": "status_id_1", "sort_order": 1},
        {"id": "status_id_2", "sort_order": 2},
        {"id": "status_id_3", "sort_order": 3}
    ]
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Reordering statuses by admin: {user_email}")
        
        result = await status_service.reorder_statuses(status_orders, user_email)
        
        return {
            "success": True,
            "message": result["message"],
            "updated_count": result["updated_count"]
        }
        
    except Exception as e:
        logger.error(f"Error reordering statuses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reorder statuses: {str(e)}"
        )

# ============================================================================
# UTILITY ENDPOINTS
# ============================================================================

@router.get("/default/name")
async def get_default_status_name(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """Get the default status name for new leads"""
    try:
        from ..models.lead_status import StatusHelper
        
        default_status = await StatusHelper.get_default_status()
        
        return {
            "success": True,
            "default_status": default_status
        }
        
    except Exception as e:
        logger.error(f"Error getting default status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get default status: {str(e)}"
        )

@router.post("/setup/defaults")
async def setup_default_statuses(
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """Setup default statuses if none exist (Admin only)"""
    try:
        from ..models.lead_status import StatusHelper
        
        user_email = current_user.get("email", "unknown")
        logger.info(f"Setting up default statuses by admin: {user_email}")
        
        created_count = await StatusHelper.create_default_statuses()
        
        if created_count:
            return {
                "success": True,
                "message": f"Created {created_count} default statuses",
                "created_count": created_count
            }
        else:
            return {
                "success": True,
                "message": "Default statuses already exist or admin must create manually",
                "created_count": 0
            }
        
    except Exception as e:
        logger.error(f"Error setting up default statuses: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to setup default statuses: {str(e)}"
        )