# app/routers/stages.py - NEW FILE FOR STAGE API ENDPOINTS

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Dict, Any
import logging
from ..config.database import get_database
from bson import ObjectId
from datetime import datetime
from ..models.lead_stage import StageCreate, StageUpdate, StageResponse, StageListResponse
from ..services.stage_service import stage_service
from ..utils.dependencies import get_current_active_user, get_admin_user, get_user_with_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stages"])

# ============================================================================
# PUBLIC ENDPOINTS (All authenticated users can view stages)
# ============================================================================

@router.get("/", response_model=StageListResponse)
async def get_all_stages(
    include_lead_count: bool = Query(False, description="Include lead count for each stage"),
    active_only: bool = Query(True, description="Only return active stages"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("stage.view"))
):
    """
    🔄 RBAC-ENABLED: Get all stages
    
    **Required Permission:** `stage.view`
    
    Used for dropdowns in lead creation/editing
    """
    try:
        logger.info(f"Getting stages for user: {current_user.get('email')}")
        
        stages = await stage_service.get_all_stages(
            include_lead_count=include_lead_count,
            active_only=active_only
        )
        
        # Count totals
        total = len(stages)
        active_count = sum(1 for s in stages if s.get("is_active", True))
        inactive_count = total - active_count
        
        return StageListResponse(
            stages=stages,
            total=total,
            active_count=active_count,
            inactive_count=inactive_count
        )
        
    except Exception as e:
        logger.error(f"Error getting stages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stages: {str(e)}"
        )

@router.get("/inactive", response_model=StageListResponse)
async def get_inactive_stages(
    include_lead_count: bool = Query(False, description="Include lead count for each stage"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("stage.view"))
):
    """
    🔄 RBAC-ENABLED: Get all inactive/deactivated stages that can be reactivated
    
    **Required Permission:** `stage.view`
    
    Useful for admin to see what stages can be restored
    """
    try:
        logger.info(f"Getting inactive stages for user: {current_user.get('email')}")
        
        # Get ALL stages first to get accurate counts
        all_stages = await stage_service.get_all_stages(
            include_lead_count=include_lead_count,
            active_only=False  # Get all stages
        )
        
        # Filter to only inactive stages
        inactive_stages = [stage for stage in all_stages if not stage.get("is_active", True)]
        
        # Count totals from ALL stages
        total_stages = len(all_stages)
        active_count = sum(1 for stage in all_stages if stage.get("is_active", True))
        inactive_count = total_stages - active_count
        
        return StageListResponse(
            stages=inactive_stages,
            total=len(inactive_stages),  # Total inactive stages returned
            active_count=active_count,   # ✅ FIXED: Total active stages in system
            inactive_count=inactive_count  # ✅ FIXED: Total inactive stages in system
        )
        
    except Exception as e:
        logger.error(f"Error getting inactive stages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get inactive stages: {str(e)}"
        )

@router.get("/active", response_model=StageListResponse)
async def get_active_stages(
    include_lead_count: bool = Query(False, description="Include lead count for each stage"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("stage.view"))
):
    """
    🔄 RBAC-ENABLED: Get all active stages (explicitly active only)
    
    **Required Permission:** `stage.view`
    
    Useful for lead creation dropdowns
    """
    try:
        logger.info(f"Getting active stages for user: {current_user.get('email')}")
        
        # Get ALL stages first to get accurate counts
        all_stages = await stage_service.get_all_stages(
            include_lead_count=include_lead_count,
            active_only=False  # Get all stages
        )
        
        # Filter to only active stages
        active_stages = [stage for stage in all_stages if stage.get("is_active", True)]
        
        # Count totals from ALL stages
        total_stages = len(all_stages)
        active_count = len(active_stages)
        inactive_count = total_stages - active_count
        
        return StageListResponse(
            stages=active_stages,
            total=len(active_stages),  # Total active stages returned
            active_count=active_count,   # ✅ FIXED: Total active stages in system
            inactive_count=inactive_count  # ✅ FIXED: Total inactive stages in system
        )
        
    except Exception as e:
        logger.error(f"Error getting active stages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get active stages: {str(e)}"
        )

@router.get("/{stage_id}", response_model=StageResponse)
async def get_stage_by_id(
    stage_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("stage.view"))
):
    """
    🔄 RBAC-ENABLED: Get a specific stage by ID
    
    **Required Permission:** `stage.view`
    """
    try:
        stage = await stage_service.get_stage_by_id(stage_id)
        return StageResponse(**stage)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error getting stage {stage_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stage: {str(e)}"
        )

# ============================================================================
# ADMIN-ONLY ENDPOINTS (Stage management)
# ============================================================================

@router.post("/", response_model=Dict[str, Any])
async def create_stage(
    stage_data: StageCreate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("stage.create"))
):
    """
    🔄 RBAC-ENABLED: Create a new stage
    
    **Required Permission:** `stage.create`
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Creating stage '{stage_data.name}' by admin: {user_email}")
        
        result = await stage_service.create_stage(stage_data, user_email)
        
        return {
            "success": True,
            "message": result["message"],
            "stage": result["stage"]
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error creating stage: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create stage: {str(e)}"
        )

@router.put("/{stage_id}", response_model=Dict[str, Any])
async def update_stage(
    stage_id: str,
    stage_data: StageUpdate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("stage.edit"))
):
    """
    🔄 RBAC-ENABLED: Update an existing stage
    
    **Required Permission:** `stage.edit`
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Updating stage {stage_id} by admin: {user_email}")
        
        result = await stage_service.update_stage(stage_id, stage_data, user_email)
        
        return {
            "success": True,
            "message": result["message"],
            "stage": result["stage"]
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error updating stage {stage_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update stage: {str(e)}"
        )

@router.patch("/{stage_id}/activate", response_model=Dict[str, Any])
async def activate_stage(
    stage_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("stage.edit"))
):
    """
    🔄 RBAC-ENABLED: Activate a deactivated stage
    
    **Required Permission:** `stage.edit`
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Activating stage {stage_id} by admin: {user_email}")
        
        db = get_database()
        
        # Check if stage exists
        stage = await db.lead_stages.find_one({"_id": ObjectId(stage_id)})
        if not stage:
            raise ValueError(f"Stage with ID {stage_id} not found")
        
        # Update stage to active
        result = await db.lead_stages.update_one(
            {"_id": ObjectId(stage_id)},
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
                "message": f"Stage '{stage['name']}' was already active",
                "action": "no_change"
            }
        
        logger.info(f"Stage '{stage['name']}' activated by {user_email}")
        
        return {
            "success": True,
            "message": f"Stage '{stage['name']}' activated successfully",
            "action": "activated"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error activating stage {stage_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate stage: {str(e)}"
        )

@router.patch("/{stage_id}/deactivate", response_model=Dict[str, Any])
async def deactivate_stage(
    stage_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("stage.edit"))
):
    """
    🔄 RBAC-ENABLED: Deactivate a stage without deleting it
    
    **Required Permission:** `stage.edit`
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Deactivating stage {stage_id} by admin: {user_email}")
        
        db = get_database()
        
        # Check if stage exists
        stage = await db.lead_stages.find_one({"_id": ObjectId(stage_id)})
        if not stage:
            raise ValueError(f"Stage with ID {stage_id} not found")
        
        # Check if this is the only active stage
        active_count = await db.lead_stages.count_documents({"is_active": True})
        if active_count <= 1 and stage.get("is_active", True):
            raise ValueError("Cannot deactivate the last active stage")
        
        # Update stage to inactive
        result = await db.lead_stages.update_one(
            {"_id": ObjectId(stage_id)},
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
                "message": f"Stage '{stage['name']}' was already inactive",
                "action": "no_change"
            }
        
        logger.info(f"Stage '{stage['name']}' deactivated by {user_email}")
        
        return {
            "success": True,
            "message": f"Stage '{stage['name']}' deactivated successfully",
            "action": "deactivated"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error deactivating stage {stage_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deactivate stage: {str(e)}"
        )

@router.delete("/{stage_id}", response_model=Dict[str, Any])
async def delete_stage(
    stage_id: str,
    force: bool = Query(False, description="Force delete even if stage has leads"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("stage.delete"))
):
    """
    🔄 RBAC-ENABLED: Delete a stage
    
    **Required Permission:** `stage.delete`
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Deleting stage {stage_id} by admin: {user_email} (force={force})")
        
        result = await stage_service.delete_stage(stage_id, user_email, force)
        
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
        logger.error(f"Error deleting stage {stage_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete stage: {str(e)}"
        )

@router.patch("/reorder", response_model=Dict[str, Any])
async def reorder_stages(
    stage_orders: List[Dict[str, Any]],
    current_user: Dict[str, Any] = Depends(get_user_with_permission("stage.edit"))
):
    """
    🔄 RBAC-ENABLED: Reorder stages by updating sort_order
    
    **Required Permission:** `stage.edit`
    
    Request body example:
    [
        {"id": "stage_id_1", "sort_order": 1},
        {"id": "stage_id_2", "sort_order": 2},
        {"id": "stage_id_3", "sort_order": 3}
    ]
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Reordering stages by admin: {user_email}")
        
        result = await stage_service.reorder_stages(stage_orders, user_email)
        
        return {
            "success": True,
            "message": result["message"],
            "updated_count": result["updated_count"]
        }
        
    except Exception as e:
        logger.error(f"Error reordering stages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reorder stages: {str(e)}"
        )

# ============================================================================
# UTILITY ENDPOINTS
# ============================================================================

@router.get("/default/name")
async def get_default_stage_name(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("stage.view"))
):
    """
    🔄 RBAC-ENABLED: Get the default stage name for new leads
    
    **Required Permission:** `stage.view`
    """
    try:
        from ..models.lead_stage import StageHelper
        
        default_stage = await StageHelper.get_default_stage()
        
        return {
            "success": True,
            "default_stage": default_stage
        }
        
    except Exception as e:
        logger.error(f"Error getting default stage: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get default stage: {str(e)}"
        )

@router.post("/setup/defaults")
async def setup_default_stages(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("stage.create"))
):
    """
    🔄 RBAC-ENABLED: Setup default stages if none exist
    
    **Required Permission:** `stage.create`
    """
    try:
        from ..models.lead_stage import StageHelper
        
        user_email = current_user.get("email", "unknown")
        logger.info(f"Setting up default stages by admin: {user_email}")
        
        created_count = await StageHelper.create_default_stages()
        
        if created_count:
            return {
                "success": True,
                "message": f"Created {created_count} default stages",
                "created_count": created_count
            }
        else:
            return {
                "success": True,
                "message": "Default stages already exist",
                "created_count": 0
            }
        
    except Exception as e:
        logger.error(f"Error setting up default stages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to setup default stages: {str(e)}"
        )