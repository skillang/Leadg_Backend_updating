"""
Batch Enrollment API Routes
Handles lead enrollment in batches
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

from ..models.batch_enrollment import (
    BatchEnrollmentCreate,
    BatchBulkEnrollmentCreate,
    BatchEnrollmentUpdate,
    BatchEnrollmentResponse,
    EnrollmentStatus
)
from ..services.batch_enrollment_service import batch_enrollment_service
from ..services.batch_service import batch_service
from ..utils.dependencies import get_current_user, get_user_with_permission
from bson import ObjectId

router = APIRouter(prefix="/enrollments", tags=["Batch Enrollments"])
logger = logging.getLogger(__name__)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def format_enrollment_response(enrollment_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Format enrollment document for API response"""
    if not enrollment_doc:
        return None
    
    return {
        "id": str(enrollment_doc["_id"]),
        "enrollment_id": enrollment_doc["enrollment_id"],
        "batch_id": enrollment_doc["batch_id"],
        "batch_name": enrollment_doc["batch_name"],
        "lead_id": enrollment_doc["lead_id"],
        "lead_name": enrollment_doc["lead_name"],
        "lead_email": enrollment_doc["lead_email"],
        "enrollment_date": enrollment_doc["enrollment_date"].isoformat() if isinstance(enrollment_doc["enrollment_date"], datetime) else enrollment_doc["enrollment_date"],
        "enrollment_status": enrollment_doc["enrollment_status"],
        "enrolled_by": enrollment_doc["enrolled_by"],
        "enrolled_by_name": enrollment_doc["enrolled_by_name"],
        "attendance_count": enrollment_doc.get("attendance_count", 0),
        "total_sessions_held": enrollment_doc.get("total_sessions_held", 0),
        "attendance_percentage": enrollment_doc.get("attendance_percentage", 0.0),
        "dropped_reason": enrollment_doc.get("dropped_reason"),
        "notes": enrollment_doc.get("notes"),
        "created_at": enrollment_doc["created_at"].isoformat() if isinstance(enrollment_doc["created_at"], datetime) else enrollment_doc["created_at"],
        "updated_at": enrollment_doc["updated_at"].isoformat() if isinstance(enrollment_doc["updated_at"], datetime) else enrollment_doc["updated_at"]
    }

# ============================================================================
# ENROLLMENT ENDPOINTS
# ============================================================================

@router.post("/", status_code=status.HTTP_201_CREATED)
async def enroll_lead(
    enrollment_data: BatchEnrollmentCreate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("batch.update"))
):
    """
    Enroll a single lead in a batch
    
    Required permission: batch.enroll_students
    
    This will:
    1. Check batch capacity
    2. Check for duplicate enrollment
    3. Create enrollment record
    4. Update batch enrollment count
    5. Update lead's enrolled_batches array
    6. Log timeline activity
    """
    try:
        logger.info(f"Enrolling lead {enrollment_data.lead_id} in batch {enrollment_data.batch_id}")
        
        user_name = f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip()
        
        # Enroll lead
        enrollment_doc = await batch_enrollment_service.enroll_lead(
            batch_id=enrollment_data.batch_id,
            lead_id=enrollment_data.lead_id,
            enrolled_by=str(current_user["_id"]),
            enrolled_by_name=user_name,
            notes=enrollment_data.notes
        )
        
        # Format response
        response = format_enrollment_response(enrollment_doc)
        
        return {
            "success": True,
            "message": f"Lead {enrollment_data.lead_id} enrolled successfully",
            "data": response
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error enrolling lead: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enroll lead: {str(e)}"
        )

@router.post("/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_enroll_leads(
    bulk_data: BatchBulkEnrollmentCreate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("batch.update"))
):
    """
    Enroll multiple leads in a batch
    
    Required permission: batch.enroll_students
    
    Returns summary with successful and failed enrollments
    """
    try:
        logger.info(f"Bulk enrolling {len(bulk_data.lead_ids)} leads in batch {bulk_data.batch_id}")
        
        user_name = f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip()
        
        # Bulk enroll
        results = await batch_enrollment_service.bulk_enroll(
            batch_id=bulk_data.batch_id,
            lead_ids=bulk_data.lead_ids,
            enrolled_by=str(current_user["_id"]),
            enrolled_by_name=user_name,
            notes=bulk_data.notes
        )
        
        return {
            "success": True,
            "message": f"Enrolled {results['success_count']}/{results['total']} leads successfully",
            "data": results
        }
        
    except Exception as e:
        logger.error(f"Error in bulk enrollment: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enroll leads: {str(e)}"
        )

@router.delete("/{enrollment_id}")
async def remove_enrollment(
    enrollment_id: str,
    reason: Optional[str] = Query(None, description="Reason for removing enrollment"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("batch.update"))
):
    """
    Remove a lead from a batch (mark as dropped)
    
    Required permission: batch.remove_students
    
    This will:
    1. Update enrollment status to 'dropped'
    2. Decrease batch enrollment count
    3. Remove from lead's enrolled_batches
    4. Log timeline activity
    """
    try:
        logger.info(f"Removing enrollment {enrollment_id}")
        
        # Remove enrollment
        removed = await batch_enrollment_service.remove_enrollment(
            enrollment_id=enrollment_id,
            reason=reason
        )
        
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Enrollment {enrollment_id} not found"
            )
        
        return {
            "success": True,
            "message": f"Enrollment {enrollment_id} removed successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing enrollment: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove enrollment: {str(e)}"
        )

# ============================================================================
# ENROLLMENT QUERIES
# ============================================================================

@router.get("/batch/{batch_id}/students")
async def get_batch_students(
    batch_id: str,
    enrollment_status: Optional[EnrollmentStatus] = Query(None, description="Filter by enrollment status"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("batch.view"))
):
    """
    Get all students enrolled in a batch
    
    Required permission: batch.view
    
    By default, returns only active enrollments (not dropped)
    """
    try:
        # Check batch access
        batch = await batch_service.get_batch_by_id(batch_id)
        
        if not batch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Batch {batch_id} not found"
            )
        
        # Fetch enrollments
        enrollments = await batch_enrollment_service.get_batch_students(
            batch_id=batch_id,
            status=enrollment_status
        )
        
        # Format response
        formatted_enrollments = [format_enrollment_response(e) for e in enrollments]
        
        return {
            "success": True,
            "data": formatted_enrollments,
            "total": len(formatted_enrollments)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching batch students: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch students: {str(e)}"
        )

@router.get("/lead/{lead_id}/batches")
async def get_lead_batches(
    lead_id: str,
    enrollment_status: Optional[EnrollmentStatus] = Query(None, description="Filter by enrollment status"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("batch.view"))
):
    """
    Get all batches a lead is enrolled in
    
    Required permission: batch.view
    
    Shows enrollment history with attendance stats
    """
    try:
        # Fetch enrollments
        enrollments = await batch_enrollment_service.get_lead_batches(
            lead_id=lead_id,
            status=enrollment_status
        )
        
        # Format response
        formatted_enrollments = [format_enrollment_response(e) for e in enrollments]
        
        return {
            "success": True,
            "data": formatted_enrollments,
            "total": len(formatted_enrollments)
        }
        
    except Exception as e:
        logger.error(f"Error fetching lead batches: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch lead batches: {str(e)}"
        )

@router.get("/{enrollment_id}")
async def get_enrollment(
    enrollment_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("batch.view"))
):
    """
    Get detailed information about a specific enrollment
    
    Required permission: batch.view
    """
    try:
        from ..config.database import get_database
        db = get_database()
        
        enrollment = await db.batch_enrollments.find_one({"enrollment_id": enrollment_id})
        
        if not enrollment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Enrollment {enrollment_id} not found"
            )
        
        # Format response
        response = format_enrollment_response(enrollment)
        
        return {
            "success": True,
            "data": response
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching enrollment: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch enrollment: {str(e)}"
        )

@router.put("/{enrollment_id}")
async def update_enrollment(
    enrollment_id: str,
    update_data: BatchEnrollmentUpdate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("batch.update"))
):
    """
    Update enrollment details (status, dropped reason, etc.)
    
    Required permission: batch.update
    """

    try:
        from ..config.database import get_database
        db = get_database()
        
        # Build update document
        update_doc = {}
        
        if update_data.enrollment_status is not None:
            update_doc["enrollment_status"] = update_data.enrollment_status
        
        if update_data.dropped_reason is not None:
            update_doc["dropped_reason"] = update_data.dropped_reason
        
        if not update_doc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )
        
        update_doc["updated_at"] = datetime.utcnow()
        
        # Update enrollment
        result = await db.batch_enrollments.find_one_and_update(
            {"enrollment_id": enrollment_id},
            {"$set": update_doc},
            return_document=True
        )
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Enrollment {enrollment_id} not found"
            )
        
        # Format response
        response = format_enrollment_response(result)
        
        return {
            "success": True,
            "message": f"Enrollment {enrollment_id} updated successfully",
            "data": response
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating enrollment: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update enrollment: {str(e)}"
        )