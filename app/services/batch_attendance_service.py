"""
Batch Attendance Service
Manages attendance marking and tracking
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from bson import ObjectId

from ..config.database import get_database
from .batch_session_service import batch_session_service
from .batch_enrollment_service import batch_enrollment_service

logger = logging.getLogger(__name__)

class BatchAttendanceService:
    """Service for attendance operations"""
    
    def __init__(self):
        self.db = None
    
    def get_db(self):
        """Get database instance"""
        if self.db is None:
            from ..config.database import get_database
            self.db = get_database()
        return self.db
    
    # ============================================================================
    # ID GENERATION
    # ============================================================================
    
    async def generate_attendance_id(self) -> str:
        """Generate unique attendance ID (ATT-001, ATT-002, etc.)"""
        db = self.get_db()
        
        try:
            counter = await db.counters.find_one_and_update(
                {"_id": "attendance_id"},
                {"$inc": {"sequence": 1}},
                upsert=True,
                return_document=True
            )
            
            sequence = counter.get("sequence", 1)
            attendance_id = f"ATT-{sequence:03d}"
            
            return attendance_id
            
        except Exception as e:
            logger.error(f"Error generating attendance ID: {e}")
            return f"ATT-{int(datetime.utcnow().timestamp())}"
    
    # ============================================================================
    # ATTENDANCE MARKING
    # ============================================================================
    
    async def mark_attendance(
        self,
        session_id: str,
        attendance_records: List[Dict[str, str]],
        marked_by: str,
        marked_by_name: str
    ) -> Dict[str, Any]:
        """
        Mark attendance for a session
        
        Args:
            session_id: Session identifier
            attendance_records: List of {lead_id, attendance_status}
            marked_by: User ID marking attendance
            marked_by_name: Name of user
            
        Returns:
            Summary of marked attendance
        """
        db = self.get_db()
        
        try:
            # Get session details
            session = await batch_session_service.get_session_by_id(session_id)
            
            if not session:
                raise ValueError(f"Session {session_id} not found")
            
            batch_id = session["batch_id"]
            session_number = session["session_number"]
            session_date = session["session_date"]
            batch_name = session["batch_name"]
            
            # Check if attendance already taken
            existing_count = await db.batch_attendance.count_documents({"session_id": session_id})
            
            if existing_count > 0:
                raise ValueError(f"Attendance already taken for session {session_id}")
            
            # Create attendance documents
            attendance_docs = []
            present_count = 0
            absent_count = 0
            
            for record in attendance_records:
                lead_id = record["lead_id"]
                status = record["attendance_status"]
                
                # Get lead details
                lead = await db.leads.find_one(
                    {"lead_id": lead_id},
                    {"name": 1, "email": 1}
                )
                
                if not lead:
                    logger.warning(f"Lead {lead_id} not found, skipping")
                    continue
                
                # Generate attendance ID
                attendance_id = await self.generate_attendance_id()
                
                # Create attendance document
                attendance_doc = {
                    "_id": ObjectId(),
                    "attendance_id": attendance_id,
                    "session_id": session_id,
                    "session_number": session_number,
                    "session_date": session_date,
                    "batch_id": batch_id,
                    "batch_name": batch_name,
                    "lead_id": lead_id,
                    "lead_name": lead["name"],
                    "lead_email": lead["email"],
                    "attendance_status": status,
                    "marked_by": marked_by,
                    "marked_by_name": marked_by_name,
                    "marked_at": datetime.utcnow(),
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
                
                attendance_docs.append(attendance_doc)
                
                # Count present/absent
                if status == "present":
                    present_count += 1
                else:
                    absent_count += 1
                
                # Update enrollment attendance stats
                enrollment = await db.batch_enrollments.find_one({
                    "batch_id": batch_id,
                    "lead_id": lead_id
                })
                
                if enrollment:
                    await batch_enrollment_service.update_attendance_stats(
                        enrollment["enrollment_id"],
                        attended=(status == "present")
                    )
            
            # Bulk insert attendance records
            if attendance_docs:
                await db.batch_attendance.insert_many(attendance_docs)
            
            # Update session stats
            await batch_session_service.update_session_attendance_stats(
                session_id,
                present_count,
                absent_count
            )
            
            logger.info(f"✅ Marked attendance for session {session_id}: {present_count} present, {absent_count} absent")
            
            return {
                "session_id": session_id,
                "batch_id": batch_id,
                "total_marked": len(attendance_docs),
                "present_count": present_count,
                "absent_count": absent_count,
                "marked_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error marking attendance: {e}")
            raise
    
    async def update_attendance(
        self,
        attendance_id: str,
        new_status: str
    ) -> bool:
        """
        Update a single attendance record (fix mistakes)
        
        Args:
            attendance_id: Attendance record identifier
            new_status: New status (present/absent)
            
        Returns:
            True if updated successfully
        """
        db = self.get_db()
        
        try:
            # Get current attendance
            attendance = await db.batch_attendance.find_one({"attendance_id": attendance_id})
            
            if not attendance:
                raise ValueError(f"Attendance record {attendance_id} not found")
            
            old_status = attendance["attendance_status"]
            
            if old_status == new_status:
                logger.info(f"Status unchanged for {attendance_id}")
                return True
            
            # Update attendance record
            result = await db.batch_attendance.update_one(
                {"attendance_id": attendance_id},
                {
                    "$set": {
                        "attendance_status": new_status,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                # Update session stats
                session = await batch_session_service.get_session_by_id(attendance["session_id"])
                
                if session:
                    if new_status == "present":
                        # Changed from absent to present
                        await batch_session_service.update_session_attendance_stats(
                            attendance["session_id"],
                            session["present_count"] + 1,
                            session["absent_count"] - 1
                        )
                    else:
                        # Changed from present to absent
                        await batch_session_service.update_session_attendance_stats(
                            attendance["session_id"],
                            session["present_count"] - 1,
                            session["absent_count"] + 1
                        )
                
                # Update enrollment stats
                enrollment = await db.batch_enrollments.find_one({
                    "batch_id": attendance["batch_id"],
                    "lead_id": attendance["lead_id"]
                })
                
                if enrollment:
                    # Recalculate attendance percentage
                    if new_status == "present":
                        new_attendance_count = enrollment["attendance_count"] + 1
                    else:
                        new_attendance_count = enrollment["attendance_count"] - 1
                    
                    attendance_percentage = (
                        new_attendance_count / enrollment["total_sessions_held"]
                    ) * 100
                    
                    await db.batch_enrollments.update_one(
                        {"enrollment_id": enrollment["enrollment_id"]},
                        {
                            "$set": {
                                "attendance_count": new_attendance_count,
                                "attendance_percentage": round(attendance_percentage, 2),
                                "updated_at": datetime.utcnow()
                            }
                        }
                    )
                
                logger.info(f"✅ Updated attendance {attendance_id}: {old_status} → {new_status}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error updating attendance: {e}")
            raise
    
    # ============================================================================
    # ATTENDANCE QUERIES
    # ============================================================================
    
    async def get_session_attendance(
        self,
        session_id: str
    ) -> List[Dict[str, Any]]:
        """Get all attendance records for a session"""
        db = self.get_db()
        
        try:
            cursor = db.batch_attendance.find({"session_id": session_id})
            attendance_records = await cursor.to_list(length=None)
            
            return attendance_records
            
        except Exception as e:
            logger.error(f"Error fetching session attendance: {e}")
            return []
    
    async def get_student_attendance(
        self,
        lead_id: str,
        batch_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get attendance records for a student"""
        db = self.get_db()
        
        try:
            query = {"lead_id": lead_id}
            
            if batch_id:
                query["batch_id"] = batch_id
            
            cursor = db.batch_attendance.find(query).sort("session_date", 1)
            attendance_records = await cursor.to_list(length=None)
            
            return attendance_records
            
        except Exception as e:
            logger.error(f"Error fetching student attendance: {e}")
            return []
    
    async def get_batch_attendance_report(
        self,
        batch_id: str
    ) -> Dict[str, Any]:
        """
        Generate comprehensive attendance report for a batch
        
        Returns:
            Report with student-wise and session-wise attendance
        """
        db = self.get_db()
        
        try:
            # Get all students in batch
            enrollments = await batch_enrollment_service.get_batch_students(batch_id)
            
            # Get all sessions
            sessions = await batch_session_service.get_batch_sessions(batch_id)
            
            # Build attendance matrix
            student_attendance = []
            
            for enrollment in enrollments:
                lead_id = enrollment["lead_id"]
                
                # Get attendance records for this student
                attendance_records = await self.get_student_attendance(lead_id, batch_id)
                
                student_attendance.append({
                    "lead_id": lead_id,
                    "lead_name": enrollment["lead_name"],
                    "lead_email": enrollment["lead_email"],
                    "total_sessions": len(sessions),
                    "sessions_held": len([s for s in sessions if s["session_status"] == "completed"]),
                    "attended": len([a for a in attendance_records if a["attendance_status"] == "present"]),
                    "absent": len([a for a in attendance_records if a["attendance_status"] == "absent"]),
                    "attendance_percentage": enrollment["attendance_percentage"]
                })
            
            # Session-wise summary
            session_summary = []
            
            for session in sessions:
                if session["attendance_taken"]:
                    session_summary.append({
                        "session_id": session["session_id"],
                        "session_number": session["session_number"],
                        "session_date": session["session_date"],
                        "present_count": session["present_count"],
                        "absent_count": session["absent_count"],
                        "total_students": session["total_students"]
                    })
            
            return {
                "batch_id": batch_id,
                "total_students": len(enrollments),
                "total_sessions": len(sessions),
                "sessions_completed": len([s for s in sessions if s["session_status"] == "completed"]),
                "student_attendance": student_attendance,
                "session_summary": session_summary
            }
            
        except Exception as e:
            logger.error(f"Error generating batch attendance report: {e}")
            return {"error": str(e)}

# Singleton instance
batch_attendance_service = BatchAttendanceService()