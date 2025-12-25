"""
Batch Management API Routes
Handles batch CRUD operations, listing, and statistics
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

from ..models.batch import (
    BatchCreate,
    BatchUpdate,
    BatchResponse,
    BatchFilterParams,
    BatchStatus,
    BatchType
)
from ..services.batch_service import batch_service
from ..services.batch_session_service import batch_session_service
from ..config.auth import get_current_user, check_permission
from bson import ObjectId

router = APIRouter(prefix="/batches", tags=["Batches"])
logger = logging.getLogger(__name__)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def format_batch_response(batch_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Format batch document for API response"""
    if not batch_doc:
        return None
    
    return {
        "id": str(batch_doc["_id"]),
        "batch_id": batch_doc["batch_id"],
        "batch_name": batch_doc["batch_name"],
        "batch_type": batch_doc["batch_type"],
        "start_date": batch_doc["start_date"],
        "end_date": batch_doc["end_date"],
        "duration_weeks": batch_doc["duration_weeks"],
        "class_days": batch_doc["class_days"],
        "class_time": batch_doc["class_time"],
        "total_sessions": batch_doc["total_sessions"],
        "max_capacity": batch_doc["max_capacity"],
        "current_enrollment": batch_doc.get("current_enrollment", 0),
        "trainer": {
            "user_id": batch_doc["trainer"]["user_id"],
            "name": batch_doc["trainer"]["name"],
            "email": batch_doc["trainer"]["email"]
        },
        "status": batch_doc["status"],
        "description": batch_doc.get("description"),
        "created_by": batch_doc["created_by"],
        "created_by_name": batch_doc["created_by_name"],
        "created_at": batch_doc["created_at"].isoformat() if isinstance(batch_doc["created_at"], datetime) else batch_doc["created_at"],
        "updated_at": batch_doc["updated_at"].isoformat() if isinstance(batch_doc["updated_at"], datetime) else batch_doc["updated_at"]
    }

def convert_objectid_to_str(obj):
    """Recursively convert ObjectId to string in nested structures"""
    if isinstance(obj, ObjectId):
        return str(obj)
    elif isinstance(obj, dict):
        return {key: convert_objectid_to_str(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_objectid_to_str(item) for item in obj]
    else:
        return obj

# ============================================================================
# BATCH CRUD ENDPOINTS
# ============================================================================

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_batch(
    batch_data: BatchCreate,
    current_user: Dict[str, Any] = Depends(check_permission("batch.create"))
):
    """
    Create a new batch with auto-generated sessions
    
    Required permission: batch.create
    
    This will:
    1. Create the batch
    2. Auto-generate all sessions based on schedule
    3. Return batch details
    """
    try:
        logger.info(f"Creating batch by user: {current_user['email']}")
        
        # Create batch
        batch_doc = await batch_service.create_batch(
            batch_data=batch_data,
            created_by=str(current_user["_id"]),
            created_by_name=current_user.get("first_name", "") + " " + current_user.get("last_name", "")
        )
        
        # Format response
        response = format_batch_response(batch_doc)
        
        return {
            "success": True,
            "message": f"Batch '{batch_data.batch_name}' created successfully with {batch_doc['total_sessions']} sessions",
            "data": response
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error creating batch: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create batch: {str(e)}"
        )

@router.get("/")
async def list_batches(
    # Filters
    batch_type: Optional[BatchType] = None,
    status: Optional[BatchStatus] = None,
    trainer_id: Optional[str] = None,
    start_date_from: Optional[str] = None,
    start_date_to: Optional[str] = None,
    search: Optional[str] = None,
    
    # Pagination
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    
    # Sorting
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    List batches with filtering, pagination, and sorting
    
    Permissions:
    - batch.read_all: See all batches
    - batch.read_own: See only batches where user is trainer
    
    Filters:
    - batch_type: Filter by type (demo, training, etc.)
    - status: Filter by status (active, completed, etc.)
    - trainer_id: Filter by trainer
    - start_date_from/to: Date range filter
    - search: Search in batch name
    """
    try:
        # Check permissions
        has_read_all = current_user.get("permissions", {}).get("batch.read_all", False)
        has_read_own = current_user.get("permissions", {}).get("batch.read_own", False)
        
        if not has_read_all and not has_read_own:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No permission to view batches"
            )
        
        # Build filters
        filters = {}
        
        if batch_type:
            filters["batch_type"] = batch_type
        
        if status:
            filters["status"] = status
        
        if search:
            filters["search"] = search
        
        if start_date_from:
            filters["start_date_from"] = start_date_from
        
        if start_date_to:
            filters["start_date_to"] = start_date_to
        
        # If user has only read_own permission, filter by trainer
        if has_read_own and not has_read_all:
            filters["trainer_id"] = str(current_user["_id"])
        elif trainer_id:
            # Admin can filter by any trainer
            filters["trainer_id"] = trainer_id
        
        # Fetch batches
        result = await batch_service.list_batches(
            filters=filters,
            page=page,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order
        )
        
        # Format batches
        formatted_batches = [format_batch_response(batch) for batch in result["batches"]]
        
        return {
            "success": True,
            "data": formatted_batches,
            "pagination": result["pagination"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing batches: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list batches: {str(e)}"
        )

@router.get("/{batch_id}")
async def get_batch(
    batch_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get detailed information about a specific batch
    
    Permissions checked:
    - batch.read_all OR
    - batch.read_own (if user is the trainer)
    """
    try:
        # Fetch batch
        batch = await batch_service.get_batch_by_id(batch_id)
        
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch {batch_id} not found"
            )
        
        # Check permissions
        has_read_all = current_user.get("permissions", {}).get("batch.read_all", False)
        has_read_own = current_user.get("permissions", {}).get("batch.read_own", False)
        
        if not has_read_all:
            # Check if user is the trainer
            if has_read_own and batch["trainer"]["user_id"] == str(current_user["_id"]):
                pass  # Allow access
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No permission to view this batch"
                )
        
        # Format response
        response = format_batch_response(batch)
        
        return {
            "success": True,
            "data": response
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching batch: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch batch: {str(e)}"
        )

@router.put("/{batch_id}")
async def update_batch(
    batch_id: str,
    update_data: BatchUpdate,
    current_user: Dict[str, Any] = Depends(check_permission("batch.update"))
):
    """
    Update batch details
    
    Required permission: batch.update
    
    Note: Cannot update start_date, duration_weeks, or class_days after creation
    """
    try:
        logger.info(f"Updating batch {batch_id} by user: {current_user['email']}")
        
        # Update batch
        updated_batch = await batch_service.update_batch(
            batch_id=batch_id,
            update_data=update_data,
            updated_by=str(current_user["_id"])
        )
        
        if not updated_batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch {batch_id} not found"
            )
        
        # Format response
        response = format_batch_response(updated_batch)
        
        return {
            "success": True,
            "message": f"Batch {batch_id} updated successfully",
            "data": response
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating batch: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update batch: {str(e)}"
        )

@router.delete("/{batch_id}")
async def delete_batch(
    batch_id: str,
    force: bool = Query(False, description="Force delete even with enrollments"),
    current_user: Dict[str, Any] = Depends(check_permission("batch.delete"))
):
    """
    Delete a batch
    
    Required permission: batch.delete
    
    By default, cannot delete batches with active enrollments.
    Use force=true to override.
    """
    try:
        logger.info(f"Deleting batch {batch_id} by user: {current_user['email']} (force={force})")
        
        # Delete batch
        deleted = await batch_service.delete_batch(batch_id, force=force)
        
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch {batch_id} not found"
            )
        
        return {
            "success": True,
            "message": f"Batch {batch_id} deleted successfully"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting batch: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete batch: {str(e)}"
        )

# ============================================================================
# BATCH SESSIONS ENDPOINTS
# ============================================================================

@router.get("/{batch_id}/sessions")
async def get_batch_sessions(
    batch_id: str,
    session_status: Optional[str] = Query(None, description="Filter by session status"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get all sessions for a batch
    
    Returns sessions sorted by session_number
    """
    try:
        # Check batch access
        batch = await batch_service.get_batch_by_id(batch_id)
        
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch {batch_id} not found"
            )
        
        # Fetch sessions
        sessions = await batch_session_service.get_batch_sessions(
            batch_id=batch_id,
            status=session_status
        )
        
        # Convert ObjectIds to strings
        sessions = convert_objectid_to_str(sessions)
        
        return {
            "success": True,
            "data": sessions,
            "total": len(sessions)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching batch sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch sessions: {str(e)}"
        )

@router.get("/{batch_id}/sessions/pending-attendance")
async def get_pending_attendance_sessions(
    batch_id: str,
    current_user: Dict[str, Any] = Depends(check_permission("attendance.mark"))
):
    """
    Get sessions where attendance hasn't been marked yet
    
    Useful for trainers to see which sessions need attendance
    """
    try:
        sessions = await batch_session_service.get_pending_attendance_sessions(batch_id)
        
        sessions = convert_objectid_to_str(sessions)
        
        return {
            "success": True,
            "data": sessions,
            "total": len(sessions)
        }
        
    except Exception as e:
        logger.error(f"Error fetching pending attendance sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch pending sessions: {str(e)}"
        )

# ============================================================================
# BATCH STATISTICS ENDPOINTS
# ============================================================================

@router.get("/{batch_id}/stats")
async def get_batch_statistics(
    batch_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get comprehensive statistics for a batch
    
    Includes:
    - Enrollment stats
    - Session progress
    - Average attendance
    """
    try:
        stats = await batch_service.get_batch_stats(batch_id)
        
        if "error" in stats:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=stats["error"]
            )
        
        return {
            "success": True,
            "data": stats
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching batch stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch batch statistics: {str(e)}"
        )

@router.get("/summary/all")
async def get_all_batches_summary(
    current_user: Dict[str, Any] = Depends(check_permission("batch.read_all"))
):
    """
    Get summary statistics for all batches
    
    Required permission: batch.read_all
    
    Returns:
    - Total batches
    - Breakdown by status
    - Breakdown by type
    - Total enrollments
    """
    try:
        summary = await batch_service.get_all_batches_summary()
        
        return {
            "success": True,
            "data": summary
        }
        
    except Exception as e:
        logger.error(f"Error fetching batches summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch summary: {str(e)}"
        )

@router.get("/{batch_id}/capacity")
async def check_batch_capacity(
    batch_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Check available capacity in a batch
    
    Returns:
    - Max capacity
    - Current enrollment
    - Available seats
    - Is full (boolean)
    """
    try:
        capacity = await batch_service.check_capacity(batch_id)
        
        return {
            "success": True,
            "data": capacity
        }
        
    except Exception as e:
        logger.error(f"Error checking batch capacity: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check capacity: {str(e)}"
        )

# ============================================================================
# TRAINER-SPECIFIC ENDPOINTS
# ============================================================================

@router.get("/my/batches")
async def get_my_batches(
    status: Optional[BatchStatus] = None,
    current_user: Dict[str, Any] = Depends(check_permission("batch.read_own"))
):
    """
    Get all batches where current user is the trainer
    
    Required permission: batch.read_own
    """
    try:
        batches = await batch_service.get_trainer_batches(
            trainer_id=str(current_user["_id"]),
            status=status
        )
        
        formatted_batches = [format_batch_response(batch) for batch in batches]
        
        return {
            "success": True,
            "data": formatted_batches,
            "total": len(formatted_batches)
        }
        
    except Exception as e:
        logger.error(f"Error fetching trainer batches: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch your batches: {str(e)}"
        )

@router.get("/today/sessions")
async def get_today_sessions(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get all sessions scheduled for today
    
    Useful for trainer dashboard
    """
    try:
        sessions = await batch_session_service.get_today_sessions()
        
        # Filter by trainer if user has read_own permission only
        has_read_all = current_user.get("permissions", {}).get("batch.read_all", False)
        
        if not has_read_all:
            # Filter sessions by trainer
            user_id = str(current_user["_id"])
            filtered_sessions = []
            
            for session in sessions:
                batch = await batch_service.get_batch_by_id(session["batch_id"])
                if batch and batch["trainer"]["user_id"] == user_id:
                    filtered_sessions.append(session)
            
            sessions = filtered_sessions
        
        sessions = convert_objectid_to_str(sessions)
        
        return {
            "success": True,
            "data": sessions,
            "total": len(sessions)
        }
        
    except Exception as e:
        logger.error(f"Error fetching today's sessions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch today's sessions: {str(e)}"
        )