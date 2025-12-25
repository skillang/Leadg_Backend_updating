"""
Batch Session Service
Manages individual sessions within batches
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from bson import ObjectId

from ..config.database import get_database
from .batch_service import batch_service

logger = logging.getLogger(__name__)

class BatchSessionService:
    """Service for batch session operations"""
    
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
    
    async def generate_session_id(self) -> str:
        """Generate unique session ID (SES-001, SES-002, etc.)"""
        db = self.get_db()
        
        try:
            counter = await db.counters.find_one_and_update(
                {"_id": "session_id"},
                {"$inc": {"sequence": 1}},
                upsert=True,
                return_document=True
            )
            
            sequence = counter.get("sequence", 1)
            session_id = f"SES-{sequence:03d}"
            
            return session_id
            
        except Exception as e:
            logger.error(f"Error generating session ID: {e}")
            return f"SES-{int(datetime.utcnow().timestamp())}"
    
    # ============================================================================
    # SESSION GENERATION
    # ============================================================================
    
    async def generate_sessions_for_batch(self, batch_id: str) -> int:
        """
        Auto-generate all sessions for a batch based on schedule
        
        Args:
            batch_id: Batch identifier
            
        Returns:
            Number of sessions created
        """
        db = self.get_db()
        
        try:
            # Get batch details
            batch = await batch_service.get_batch_by_id(batch_id)
            
            if not batch:
                raise ValueError(f"Batch {batch_id} not found")
            
            # Parse start date
            start_date = datetime.strptime(batch["start_date"], '%Y-%m-%d')
            duration_weeks = batch["duration_weeks"]
            class_days = batch["class_days"]
            class_time = batch["class_time"]
            
            # Map day names to weekday numbers (Monday=0, Sunday=6)
            day_mapping = {
                "Monday": 0,
                "Tuesday": 1,
                "Wednesday": 2,
                "Thursday": 3,
                "Friday": 4,
                "Saturday": 5,
                "Sunday": 6
            }
            
            class_weekdays = [day_mapping[day] for day in class_days]
            
            # Generate session dates
            session_dates = []
            current_date = start_date
            end_date = start_date + timedelta(weeks=duration_weeks)
            
            while current_date < end_date:
                if current_date.weekday() in class_weekdays:
                    session_dates.append(current_date)
                current_date += timedelta(days=1)
            
            # Create session documents
            sessions = []
            for index, session_date in enumerate(session_dates, start=1):
                session_id = await self.generate_session_id()
                
                session_doc = {
                    "_id": ObjectId(),
                    "session_id": session_id,
                    "batch_id": batch_id,
                    "batch_name": batch["batch_name"],
                    "session_number": index,
                    "session_date": session_date.strftime('%Y-%m-%d'),
                    "session_time": class_time,
                    "session_status": "scheduled",
                    "topic": None,
                    "notes": None,
                    "recording_link": None,
                    "attendance_taken": False,
                    "total_students": 0,
                    "present_count": 0,
                    "absent_count": 0,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
                
                sessions.append(session_doc)
            
            # Bulk insert sessions
            if sessions:
                await db.batch_sessions.insert_many(sessions)
                logger.info(f"✅ Generated {len(sessions)} sessions for batch {batch_id}")
            
            return len(sessions)
            
        except Exception as e:
            logger.error(f"Error generating sessions: {e}")
            raise
    
    # ============================================================================
    # SESSION OPERATIONS
    # ============================================================================
    
    async def get_session_by_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by session_id"""
        db = self.get_db()
        
        try:
            session = await db.batch_sessions.find_one({"session_id": session_id})
            return session
            
        except Exception as e:
            logger.error(f"Error fetching session: {e}")
            return None
    
    async def update_session(
        self,
        session_id: str,
        update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update session details"""
        db = self.get_db()
        
        try:
            # Add updated timestamp
            update_data["updated_at"] = datetime.utcnow()
            
            result = await db.batch_sessions.find_one_and_update(
                {"session_id": session_id},
                {"$set": update_data},
                return_document=True
            )
            
            if result:
                logger.info(f"✅ Updated session {session_id}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error updating session: {e}")
            raise
    
    async def mark_session_completed(
        self,
        session_id: str,
        notes: Optional[str] = None
    ) -> bool:
        """Mark a session as completed"""
        db = self.get_db()
        
        try:
            update_doc = {
                "session_status": "completed",
                "updated_at": datetime.utcnow()
            }
            
            if notes:
                update_doc["notes"] = notes
            
            result = await db.batch_sessions.update_one(
                {"session_id": session_id},
                {"$set": update_doc}
            )
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Error marking session completed: {e}")
            return False
    
    async def cancel_session(
        self,
        session_id: str,
        reason: Optional[str] = None
    ) -> bool:
        """Cancel a session"""
        db = self.get_db()
        
        try:
            update_doc = {
                "session_status": "cancelled",
                "notes": reason,
                "updated_at": datetime.utcnow()
            }
            
            result = await db.batch_sessions.update_one(
                {"session_id": session_id},
                {"$set": update_doc}
            )
            
            if result.modified_count > 0:
                logger.info(f"✅ Cancelled session {session_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error cancelling session: {e}")
            return False
    
    # ============================================================================
    # SESSION QUERIES
    # ============================================================================
    
    async def get_batch_sessions(
        self,
        batch_id: str,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all sessions for a batch"""
        db = self.get_db()
        
        try:
            query = {"batch_id": batch_id}
            
            if status:
                query["session_status"] = status
            
            cursor = db.batch_sessions.find(query).sort("session_number", 1)
            sessions = await cursor.to_list(length=None)
            
            return sessions
            
        except Exception as e:
            logger.error(f"Error fetching batch sessions: {e}")
            return []
    
    async def get_today_sessions(self) -> List[Dict[str, Any]]:
        """Get all sessions scheduled for today"""
        db = self.get_db()
        
        try:
            today = datetime.utcnow().strftime('%Y-%m-%d')
            
            cursor = db.batch_sessions.find({
                "session_date": today,
                "session_status": {"$ne": "cancelled"}
            }).sort("session_time", 1)
            
            sessions = await cursor.to_list(length=None)
            
            return sessions
            
        except Exception as e:
            logger.error(f"Error fetching today's sessions: {e}")
            return []
    
    async def get_pending_attendance_sessions(
        self,
        batch_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get completed sessions where attendance hasn't been taken"""
        db = self.get_db()
        
        try:
            query = {
                "session_status": "completed",
                "attendance_taken": False
            }
            
            if batch_id:
                query["batch_id"] = batch_id
            
            cursor = db.batch_sessions.find(query).sort("session_date", -1)
            sessions = await cursor.to_list(length=None)
            
            return sessions
            
        except Exception as e:
            logger.error(f"Error fetching pending attendance sessions: {e}")
            return []
    
    async def update_session_attendance_stats(
        self,
        session_id: str,
        present_count: int,
        absent_count: int
    ) -> bool:
        """Update attendance statistics for a session"""
        db = self.get_db()
        
        try:
            result = await db.batch_sessions.update_one(
                {"session_id": session_id},
                {
                    "$set": {
                        "attendance_taken": True,
                        "present_count": present_count,
                        "absent_count": absent_count,
                        "total_students": present_count + absent_count,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Error updating session stats: {e}")
            return False

# Singleton instance
batch_session_service = BatchSessionService()