"""
Batch Attendance API Routes - RBAC-Enabled
Handles attendance marking and tracking
🔄 UPDATED: Permission checks replaced with RBAC (108 permissions)
✅ All endpoints now use permission-based access control
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

from ..models.batch_attendance import (
    BatchAttendanceCreate,
    BatchAttendanceUpdate,
    BatchAttendanceResponse,
    AttendanceRecord,
    StudentAttendanceSummary,
    SessionAttendanceSummary,
    AttendanceStatus
)
from ..services.batch_attendance_service import batch_attendance_service
from ..services.batch_session_service import batch_session_service
from ..services.rbac_service import RBACService
from ..utils.dependencies import get_user_with_permission
from bson import ObjectId

router = APIRouter(prefix="/attendance", tags=["Batch Attendance"])
logger = logging.getLogger(__name__)

# Initialize RBAC service
rbac_service = RBACService()


# =====================================
# HELPER FUNCTIONS
# =====================================

def format_attendance_response(attendance_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Format attendance document for API response"""
    if not attendance_doc:
        return None
    
    return {
        "id": str(attendance_doc["_id"]),
        "attendance_id": attendance_doc["attendance_id"],
        "session_id": attendance_doc["session_id"],
        "session_number": attendance_doc["session_number"],
        "session_date": attendance_doc["session_date"],
        "batch_id": attendance_doc["batch_id"],
        "batch_name": attendance_doc["batch_name"],
        "lead_id": attendance_doc["lead_id"],
        "lead_name": attendance_doc["lead_name"],
        "lead_email": attendance_doc["lead_email"],
        "attendance_status": attendance_doc["attendance_status"],
        "marked_by": attendance_doc["marked_by"],
        "marked_by_name": attendance_doc["marked_by_name"],
        "marked_at": attendance_doc["marked_at"].isoformat() if isinstance(attendance_doc["marked_at"], datetime) else attendance_doc["marked_at"],
        "created_at": attendance_doc["created_at"].isoformat() if isinstance(attendance_doc["created_at"], datetime) else attendance_doc["created_at"],
        "updated_at": attendance_doc["updated_at"].isoformat() if isinstance(attendance_doc["updated_at"], datetime) else attendance_doc["updated_at"]
    }


# =====================================
# RBAC-ENABLED ATTENDANCE MARKING
# =====================================

@router.post("/mark", status_code=status.HTTP_201_CREATED)
async def mark_session_attendance(
    attendance_data: BatchAttendanceCreate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("attendance.mark"))
):
    """
    🔄 RBAC-ENABLED: Mark attendance for a session
    
    **Required Permission:** `attendance.mark`
    
    This will:
    1. Create attendance records for all students
    2. Update session attendance stats
    3. Update each student's enrollment attendance stats
    
    Note: Attendance can only be marked once per session
    """
    try:
        logger.info(f"Marking attendance for session {attendance_data.session_id}")
        
        # Check if session exists
        session = await batch_session_service.get_session_by_id(attendance_data.session_id)
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {attendance_data.session_id} not found"
            )
        
        user_name = f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip()
        
        # Convert attendance records to dict format
        attendance_records = [
            {
                "lead_id": record.lead_id,
                "attendance_status": record.attendance_status
            }
            for record in attendance_data.attendance_records
        ]
        
        # Mark attendance
        result = await batch_attendance_service.mark_attendance(
            session_id=attendance_data.session_id,
            attendance_records=attendance_records,
            marked_by=str(current_user["_id"]),
            marked_by_name=user_name
        )
        
        return {
            "success": True,
            "message": f"Attendance marked for session {attendance_data.session_id}",
            "data": result
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking attendance: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark attendance: {str(e)}"
        )


@router.put("/{attendance_id}")
async def update_attendance_record(
    attendance_id: str,
    update_data: BatchAttendanceUpdate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("attendance.update"))
):
    """
    🔄 RBAC-ENABLED: Update a single attendance record (fix mistakes)
    
    **Required Permission:** `attendance.update`
    
    This will:
    1. Update the attendance status
    2. Recalculate session stats
    3. Recalculate student's attendance percentage
    """
    try:
        logger.info(f"Updating attendance {attendance_id} to {update_data.attendance_status}")
        
        # Update attendance
        updated = await batch_attendance_service.update_attendance(
            attendance_id=attendance_id,
            new_status=update_data.attendance_status
        )
        
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Attendance record {attendance_id} not found"
            )
        
        return {
            "success": True,
            "message": f"Attendance record {attendance_id} updated successfully"
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating attendance: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update attendance: {str(e)}"
        )


# =====================================
# RBAC-ENABLED ATTENDANCE QUERY
# =====================================

@router.get("/session/{session_id}")
async def get_session_attendance(
    session_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("attendance.view"))
):
    """
    🔄 RBAC-ENABLED: Get all attendance records for a session
    
    **Required Permission:** `attendance.view`
    
    Returns attendance for all students in that session
    """
    try:
        # Check if session exists
        session = await batch_session_service.get_session_by_id(session_id)
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found"
            )
        
        # Fetch attendance
        attendance_records = await batch_attendance_service.get_session_attendance(session_id)
        
        # Format response
        formatted_records = [format_attendance_response(record) for record in attendance_records]
        
        return {
            "success": True,
            "data": formatted_records,
            "total": len(formatted_records),
            "session_info": {
                "session_id": session["session_id"],
                "batch_id": session["batch_id"],
                "session_number": session["session_number"],
                "session_date": session["session_date"],
                "attendance_taken": session["attendance_taken"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching session attendance: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch attendance: {str(e)}"
        )


@router.get("/student/{lead_id}")
async def get_student_attendance(
    lead_id: str,
    batch_id: Optional[str] = Query(None, description="Filter by specific batch"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("attendance.view"))
):
    """
    🔄 RBAC-ENABLED: Get all attendance records for a student
    
    **Required Permission:** `attendance.view`
    
    Shows attendance history across all batches or specific batch
    """
    try:
        # Fetch attendance
        attendance_records = await batch_attendance_service.get_student_attendance(
            lead_id=lead_id,
            batch_id=batch_id
        )
        
        # Format response
        formatted_records = [format_attendance_response(record) for record in attendance_records]
        
        return {
            "success": True,
            "data": formatted_records,
            "total": len(formatted_records)
        }
        
    except Exception as e:
        logger.error(f"Error fetching student attendance: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch student attendance: {str(e)}"
        )


# =====================================
# RBAC-ENABLED ATTENDANCE REPORTS
# =====================================

@router.get("/batch/{batch_id}/report")
async def get_batch_attendance_report(
    batch_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("attendance.view"))
):
    """
    🔄 RBAC-ENABLED: Generate comprehensive attendance report for a batch
    
    **Required Permission:** `attendance.view`
    
    Returns:
    - Student-wise attendance summary
    - Session-wise attendance summary
    - Overall statistics
    """
    try:
        report = await batch_attendance_service.get_batch_attendance_report(batch_id)
        
        if "error" in report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=report["error"]
            )
        
        return {
            "success": True,
            "data": report
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating attendance report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate report: {str(e)}"
        )


@router.get("/batch/{batch_id}/summary")
async def get_batch_attendance_summary(
    batch_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("attendance.view"))
):
    """
    🔄 RBAC-ENABLED: Get quick attendance summary for a batch
    
    **Required Permission:** `attendance.view`
    
    Returns aggregate statistics without detailed records
    """
    try:
        from ..config.database import get_database
        db = get_database()
        
        # Get basic stats
        total_sessions = await db.batch_sessions.count_documents({"batch_id": batch_id})
        completed_sessions = await db.batch_sessions.count_documents({
            "batch_id": batch_id,
            "session_status": "completed"
        })
        attendance_taken_sessions = await db.batch_sessions.count_documents({
            "batch_id": batch_id,
            "attendance_taken": True
        })
        
        # Get enrollment stats
        total_students = await db.batch_enrollments.count_documents({
            "batch_id": batch_id,
            "enrollment_status": "enrolled"
        })
        
        # Calculate average attendance
        attendance_pipeline = [
            {"$match": {"batch_id": batch_id}},
            {
                "$group": {
                    "_id": None,
                    "avg_attendance": {"$avg": "$attendance_percentage"}
                }
            }
        ]
        
        attendance_result = await db.batch_enrollments.aggregate(attendance_pipeline).to_list(1)
        avg_attendance = attendance_result[0]["avg_attendance"] if attendance_result else 0
        
        return {
            "success": True,
            "data": {
                "batch_id": batch_id,
                "total_students": total_students,
                "total_sessions": total_sessions,
                "completed_sessions": completed_sessions,
                "attendance_taken_sessions": attendance_taken_sessions,
                "pending_attendance_sessions": completed_sessions - attendance_taken_sessions,
                "average_attendance_percentage": round(avg_attendance, 2)
            }
        }
        
    except Exception as e:
        logger.error(f"Error fetching attendance summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch summary: {str(e)}"
        )


@router.get("/batch/{batch_id}/export")
async def export_batch_attendance(
    batch_id: str,
    format: str = Query("csv", description="Export format: csv or excel"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("attendance.export"))
):
    """
    🔄 RBAC-ENABLED: Export batch attendance data
    
    **Required Permission:** `attendance.export`
    
    Formats: csv, excel
    
    Note: This endpoint returns metadata. Actual file generation 
    should be done client-side or via separate export service.
    """
    try:
        # Get full report
        report = await batch_attendance_service.get_batch_attendance_report(batch_id)
        
        if "error" in report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=report["error"]
            )
        
        # Return report data that can be used for export
        return {
            "success": True,
            "message": f"Attendance data ready for {format} export",
            "data": report,
            "export_format": format
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting attendance: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export attendance: {str(e)}"
        )