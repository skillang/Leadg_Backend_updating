# app/routers/course_levels.py - NEW FILE FOR COURSE LEVEL API ENDPOINTS

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Dict, Any
import logging
from ..config.database import get_database
from bson import ObjectId
from datetime import datetime
from ..models.course_level import CourseLevelCreate, CourseLevelUpdate, CourseLevelResponse, CourseLevelListResponse
from ..services.course_level_service import course_level_service
from ..utils.dependencies import get_current_active_user, get_admin_user, get_user_with_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["course-levels"])

# ============================================================================
# PUBLIC ENDPOINTS (All authenticated users can view course levels)
# ============================================================================

@router.get("/", response_model=CourseLevelListResponse)
async def get_all_course_levels(
    include_lead_count: bool = Query(False, description="Include lead count for each course level"),
    active_only: bool = Query(True, description="Only return active course levels"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("course_level.view"))
):
    """
    🔄 RBAC-ENABLED: Get all course levels
    
    **Required Permission:** `course_level.view`
    
    Used for dropdowns in lead creation/editing
    """
    try:
        logger.info(f"Getting course levels for user: {current_user.get('email')}")
        
        course_levels = await course_level_service.get_all_course_levels(
            include_lead_count=include_lead_count,
            active_only=active_only
        )
        
        # Count totals
        total = len(course_levels)
        active_count = sum(1 for cl in course_levels if cl.get("is_active", True))
        inactive_count = total - active_count
        
        return CourseLevelListResponse(
            course_levels=course_levels,
            total=total,
            active_count=active_count,
            inactive_count=inactive_count
        )
        
    except Exception as e:
        logger.error(f"Error getting course levels: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get course levels: {str(e)}"
        )

@router.get("/inactive", response_model=CourseLevelListResponse)
async def get_inactive_course_levels(
    include_lead_count: bool = Query(False, description="Include lead count for each course level"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("course_level.view"))
):
    """
    🔄 RBAC-ENABLED: Get all inactive course levels
    
    **Required Permission:** `course_level.view`
    """
    try:
        logger.info(f"Getting inactive course levels for user: {current_user.get('email')}")
        
        # Get ALL course levels first
        all_course_levels = await course_level_service.get_all_course_levels(
            include_lead_count=include_lead_count,
            active_only=False
        )
        
        # Filter to only inactive course levels
        inactive_course_levels = [cl for cl in all_course_levels if not cl.get("is_active", True)]
        
        # Count totals from ALL course levels
        total_course_levels = len(all_course_levels)
        active_count = sum(1 for cl in all_course_levels if cl.get("is_active", True))
        inactive_count = total_course_levels - active_count
        
        return CourseLevelListResponse(
            course_levels=inactive_course_levels,
            total=len(inactive_course_levels),
            active_count=active_count,
            inactive_count=inactive_count
        )
        
    except Exception as e:
        logger.error(f"Error getting inactive course levels: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get inactive course levels: {str(e)}"
        )

@router.get("/active", response_model=CourseLevelListResponse)
async def get_active_course_levels(
    include_lead_count: bool = Query(False, description="Include lead count for each course level"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("course_level.view"))
):
    """
    🔄 RBAC-ENABLED: Get all active course levels (explicitly active only)
    
    **Required Permission:** `course_level.view`
    
    Useful for lead creation dropdowns
    """
    try:
        logger.info(f"Getting active course levels for user: {current_user.get('email')}")
        
        # Get ALL course levels first to get accurate counts
        all_course_levels = await course_level_service.get_all_course_levels(
            include_lead_count=include_lead_count,
            active_only=False
        )
        
        # Filter to only active course levels
        active_course_levels = [cl for cl in all_course_levels if cl.get("is_active", True)]
        
        # Count totals from ALL course levels
        total_course_levels = len(all_course_levels)
        active_count = len(active_course_levels)
        inactive_count = total_course_levels - active_count
        
        return CourseLevelListResponse(
            course_levels=active_course_levels,
            total=len(active_course_levels),
            active_count=active_count,
            inactive_count=inactive_count
        )
        
    except Exception as e:
        logger.error(f"Error getting active course levels: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get active course levels: {str(e)}"
        )

@router.get("/{course_level_id}", response_model=CourseLevelResponse)
async def get_course_level_by_id(
    course_level_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("course_level.view"))
):
    """
    🔄 RBAC-ENABLED: Get a specific course level by ID
    
    **Required Permission:** `course_level.view`
    """
    try:
        course_level = await course_level_service.get_course_level_by_id(course_level_id)
        return CourseLevelResponse(**course_level)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error getting course level {course_level_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get course level: {str(e)}"
        )

# ============================================================================
# ADMIN-ONLY ENDPOINTS (Course level management)
# ============================================================================

@router.post("/", response_model=Dict[str, Any])
async def create_course_level(
    course_level_data: CourseLevelCreate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("course_level.create"))
):
    """
    🔄 RBAC-ENABLED: Create a new course level
    
    **Required Permission:** `course_level.create`
    """
   
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Creating course level '{course_level_data.name}' by admin: {user_email}")
        
        result = await course_level_service.create_course_level(course_level_data, user_email)
        
        return {
            "success": True,
            "message": result["message"],
            "course_level": result["course_level"]
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error creating course level: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create course level: {str(e)}"
        )

@router.put("/{course_level_id}", response_model=Dict[str, Any])
async def update_course_level(
    course_level_id: str,
    course_level_data: CourseLevelUpdate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("course_level.edit"))
):
    """
    🔄 RBAC-ENABLED: Update an existing course level
    
    **Required Permission:** `course_level.edit`
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Updating course level {course_level_id} by admin: {user_email}")
        
        result = await course_level_service.update_course_level(course_level_id, course_level_data, user_email)
        
        return {
            "success": True,
            "message": result["message"],
            "course_level": result["course_level"]
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error updating course level {course_level_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update course level: {str(e)}"
        )

@router.patch("/{course_level_id}/activate", response_model=Dict[str, Any])
async def activate_course_level(
    course_level_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("course_level.edit"))
):
    """
    🔄 RBAC-ENABLED: Activate a deactivated course level
    
    **Required Permission:** `course_level.edit`
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Activating course level {course_level_id} by admin: {user_email}")
        
        db = get_database()
        
        # Check if course level exists
        course_level = await db.course_levels.find_one({"_id": ObjectId(course_level_id)})
        if not course_level:
            raise ValueError(f"Course level with ID {course_level_id} not found")
        
        # Update course level to active
        result = await db.course_levels.update_one(
            {"_id": ObjectId(course_level_id)},
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
                "message": f"Course level '{course_level['name']}' was already active",
                "action": "no_change"
            }
        
        logger.info(f"Course level '{course_level['name']}' activated by {user_email}")
        
        return {
            "success": True,
            "message": f"Course level '{course_level['name']}' activated successfully",
            "action": "activated"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error activating course level {course_level_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to activate course level: {str(e)}"
        )

@router.patch("/{course_level_id}/deactivate", response_model=Dict[str, Any])
async def deactivate_course_level(
    course_level_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("course_level.edit"))
):
    """
    🔄 RBAC-ENABLED: Deactivate a course level without deleting it
    
    **Required Permission:** `course_level.edit`
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Deactivating course level {course_level_id} by admin: {user_email}")
        
        db = get_database()
        
        # Check if course level exists
        course_level = await db.course_levels.find_one({"_id": ObjectId(course_level_id)})
        if not course_level:
            raise ValueError(f"Course level with ID {course_level_id} not found")
        
        # Check if this is the only active course level
        active_count = await db.course_levels.count_documents({"is_active": True})
        if active_count <= 1 and course_level.get("is_active", True):
            raise ValueError("Cannot deactivate the last active course level")
        
        # Update course level to inactive
        result = await db.course_levels.update_one(
            {"_id": ObjectId(course_level_id)},
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
                "message": f"Course level '{course_level['name']}' was already inactive",
                "action": "no_change"
            }
        
        logger.info(f"Course level '{course_level['name']}' deactivated by {user_email}")
        
        return {
            "success": True,
            "message": f"Course level '{course_level['name']}' deactivated successfully",
            "action": "deactivated"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error deactivating course level {course_level_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deactivate course level: {str(e)}"
        )

@router.delete("/{course_level_id}", response_model=Dict[str, Any])
async def delete_course_level(
    course_level_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("course_level.delete"))
):
    """
    🔄 RBAC-ENABLED: Delete a course level (only if no leads are using it)
    
    **Required Permission:** `course_level.delete`
    """
    try:
        user_email = current_user.get("email", "unknown")
        logger.info(f"Deleting course level {course_level_id} by admin: {user_email}")
        
        result = await course_level_service.delete_course_level(course_level_id, user_email)
        
        return {
            "success": True,
            "message": result["message"]
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error deleting course level {course_level_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete course level: {str(e)}"
        )