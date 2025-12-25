"""
Batch Service
Core business logic for batch management
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..config.database import get_database
from ..models.batch import BatchCreate, BatchUpdate, BatchStatus

logger = logging.getLogger(__name__)

class BatchService:
    """Service for batch management operations"""
    
    def __init__(self):
        self.db: AsyncIOMotorDatabase = None
    
    def get_db(self) -> AsyncIOMotorDatabase:
        """Get database instance"""
        if self.db is None:
            self.db = get_database()
        return self.db
    
    # ============================================================================
    # ID GENERATION
    # ============================================================================
    
    async def generate_batch_id(self) -> str:
        """
        Generate unique batch ID (BATCH-001, BATCH-002, etc.)
        Uses MongoDB counter pattern
        """
        db = self.get_db()
        
        try:
            # Use counters collection for sequence
            counter = await db.counters.find_one_and_update(
                {"_id": "batch_id"},
                {"$inc": {"sequence": 1}},
                upsert=True,
                return_document=True
            )
            
            sequence = counter.get("sequence", 1)
            batch_id = f"BATCH-{sequence:03d}"  # BATCH-001, BATCH-002, etc.
            
            return batch_id
            
        except Exception as e:
            logger.error(f"Error generating batch ID: {e}")
            # Fallback to timestamp-based ID
            return f"BATCH-{int(datetime.utcnow().timestamp())}"
    
    # ============================================================================
    # BATCH CRUD OPERATIONS
    # ============================================================================
    
    async def create_batch(
        self,
        batch_data: BatchCreate,
        created_by: str,
        created_by_name: str
    ) -> Dict[str, Any]:
        """
        Create a new batch with auto-generated sessions
        
        Args:
            batch_data: Batch creation data
            created_by: User ID creating the batch
            created_by_name: Name of creator
            
        Returns:
            Created batch document
        """
        db = self.get_db()
        
        try:
            # Get trainer details
            trainer = await db.users.find_one(
                {"_id": ObjectId(batch_data.trainer_id)},
                {"email": 1, "first_name": 1, "last_name": 1}
            )
            
            if not trainer:
                raise ValueError(f"Trainer with ID {batch_data.trainer_id} not found")
            
            trainer_name = f"{trainer.get('first_name', '')} {trainer.get('last_name', '')}".strip()
            
            # Generate batch ID
            batch_id = await self.generate_batch_id()
            
            # Calculate total sessions and end date
            total_sessions = batch_data.duration_weeks * len(batch_data.class_days)
            start_date = datetime.strptime(batch_data.start_date, '%Y-%m-%d')
            end_date = start_date + timedelta(weeks=batch_data.duration_weeks)
            
            # Create batch document
            batch_doc = {
                "_id": ObjectId(),
                "batch_id": batch_id,
                "batch_name": batch_data.batch_name,
                "batch_type": batch_data.batch_type,
                "start_date": batch_data.start_date,
                "end_date": end_date.strftime('%Y-%m-%d'),
                "duration_weeks": batch_data.duration_weeks,
                "class_days": [day.value for day in batch_data.class_days],
                "class_time": batch_data.class_time,
                "total_sessions": total_sessions,
                "max_capacity": batch_data.max_capacity,
                "current_enrollment": 0,
                "trainer": {
                    "user_id": batch_data.trainer_id,
                    "name": trainer_name,
                    "email": trainer["email"]
                },
                "status": BatchStatus.SCHEDULED.value,
                "description": batch_data.description,
                "created_by": created_by,
                "created_by_name": created_by_name,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            # Insert batch
            await db.batches.insert_one(batch_doc)
            
            logger.info(f"✅ Created batch {batch_id} by {created_by_name}")
            
            # Auto-generate sessions
            from .batch_session_service import BatchSessionService
            session_service = BatchSessionService()
            await session_service.generate_sessions_for_batch(batch_id)
            
            logger.info(f"✅ Generated {total_sessions} sessions for batch {batch_id}")
            
            return batch_doc
            
        except Exception as e:
            logger.error(f"Error creating batch: {e}")
            raise
    
    async def get_batch_by_id(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get batch by batch_id"""
        db = self.get_db()
        
        try:
            batch = await db.batches.find_one({"batch_id": batch_id})
            return batch
            
        except Exception as e:
            logger.error(f"Error fetching batch {batch_id}: {e}")
            return None
    
    async def update_batch(
        self,
        batch_id: str,
        update_data: BatchUpdate,
        updated_by: str
    ) -> Optional[Dict[str, Any]]:
        """
        Update batch details
        
        Args:
            batch_id: Batch identifier
            update_data: Fields to update
            updated_by: User ID making the update
            
        Returns:
            Updated batch document
        """
        db = self.get_db()
        
        try:
            # Build update document
            update_doc = {}
            
            if update_data.batch_name is not None:
                update_doc["batch_name"] = update_data.batch_name
            
            if update_data.batch_type is not None:
                update_doc["batch_type"] = update_data.batch_type
            
            if update_data.class_time is not None:
                update_doc["class_time"] = update_data.class_time
            
            if update_data.max_capacity is not None:
                update_doc["max_capacity"] = update_data.max_capacity
            
            if update_data.status is not None:
                update_doc["status"] = update_data.status
            
            if update_data.description is not None:
                update_doc["description"] = update_data.description
            
            # Update trainer if provided
            if update_data.trainer_id is not None:
                trainer = await db.users.find_one(
                    {"_id": ObjectId(update_data.trainer_id)},
                    {"email": 1, "first_name": 1, "last_name": 1}
                )
                
                if trainer:
                    trainer_name = f"{trainer.get('first_name', '')} {trainer.get('last_name', '')}".strip()
                    update_doc["trainer"] = {
                        "user_id": update_data.trainer_id,
                        "name": trainer_name,
                        "email": trainer["email"]
                    }
            
            if not update_doc:
                logger.warning(f"No fields to update for batch {batch_id}")
                return await self.get_batch_by_id(batch_id)
            
            # Add updated timestamp
            update_doc["updated_at"] = datetime.utcnow()
            
            # Perform update
            result = await db.batches.find_one_and_update(
                {"batch_id": batch_id},
                {"$set": update_doc},
                return_document=True
            )
            
            if result:
                logger.info(f"✅ Updated batch {batch_id}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error updating batch {batch_id}: {e}")
            raise
    
    async def delete_batch(self, batch_id: str, force: bool = False) -> bool:
        """
        Delete a batch
        
        Args:
            batch_id: Batch identifier
            force: If True, delete even with enrollments
            
        Returns:
            True if deleted successfully
        """
        db = self.get_db()
        
        try:
            # Check for enrollments
            enrollment_count = await db.batch_enrollments.count_documents({
                "batch_id": batch_id,
                "enrollment_status": {"$ne": "dropped"}
            })
            
            if enrollment_count > 0 and not force:
                raise ValueError(
                    f"Cannot delete batch with {enrollment_count} active enrollments. "
                    "Use force=True to delete anyway."
                )
            
            # Delete batch
            result = await db.batches.delete_one({"batch_id": batch_id})
            
            if result.deleted_count > 0:
                logger.info(f"✅ Deleted batch {batch_id}")
                
                # Also delete related data
                await db.batch_sessions.delete_many({"batch_id": batch_id})
                await db.batch_attendance.delete_many({"batch_id": batch_id})
                
                if force and enrollment_count > 0:
                    await db.batch_enrollments.delete_many({"batch_id": batch_id})
                
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error deleting batch {batch_id}: {e}")
            raise
    
    # ============================================================================
    # BATCH LISTING & FILTERING
    # ============================================================================
    
    async def list_batches(
        self,
        filters: Dict[str, Any],
        page: int = 1,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> Dict[str, Any]:
        """
        List batches with filtering and pagination
        
        Args:
            filters: Filter criteria (status, batch_type, trainer_id, etc.)
            page: Page number
            limit: Items per page
            sort_by: Field to sort by
            sort_order: 'asc' or 'desc'
            
        Returns:
            Paginated batch list with metadata
        """
        db = self.get_db()
        
        try:
            # Build query
            query = {}
            
            if filters.get("batch_type"):
                query["batch_type"] = filters["batch_type"]
            
            if filters.get("status"):
                query["status"] = filters["status"]
            
            if filters.get("trainer_id"):
                query["trainer.user_id"] = filters["trainer_id"]
            
            if filters.get("search"):
                query["batch_name"] = {"$regex": filters["search"], "$options": "i"}
            
            # Date range filters
            if filters.get("start_date_from") or filters.get("start_date_to"):
                date_query = {}
                if filters.get("start_date_from"):
                    date_query["$gte"] = filters["start_date_from"]
                if filters.get("start_date_to"):
                    date_query["$lte"] = filters["start_date_to"]
                query["start_date"] = date_query
            
            # Count total
            total = await db.batches.count_documents(query)
            
            # Calculate pagination
            skip = (page - 1) * limit
            total_pages = (total + limit - 1) // limit
            
            # Sort
            sort_direction = -1 if sort_order == "desc" else 1
            
            # Fetch batches
            cursor = db.batches.find(query).sort(sort_by, sort_direction).skip(skip).limit(limit)
            batches = await cursor.to_list(length=limit)
            
            return {
                "batches": batches,
                "pagination": {
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "total_pages": total_pages,
                    "has_next": page < total_pages,
                    "has_prev": page > 1
                }
            }
            
        except Exception as e:
            logger.error(f"Error listing batches: {e}")
            raise
    
    async def get_trainer_batches(
        self,
        trainer_id: str,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all batches for a specific trainer"""
        db = self.get_db()
        
        try:
            query = {"trainer.user_id": trainer_id}
            
            if status:
                query["status"] = status
            
            cursor = db.batches.find(query).sort("start_date", -1)
            batches = await cursor.to_list(length=None)
            
            return batches
            
        except Exception as e:
            logger.error(f"Error fetching trainer batches: {e}")
            return []
    
    # ============================================================================
    # BATCH CAPACITY MANAGEMENT
    # ============================================================================
    
    async def update_enrollment_count(self, batch_id: str, increment: int = 1) -> bool:
        """
        Update current enrollment count
        
        Args:
            batch_id: Batch identifier
            increment: Amount to increment (+1 for enroll, -1 for remove)
            
        Returns:
            True if updated successfully
        """
        db = self.get_db()
        
        try:
            result = await db.batches.update_one(
                {"batch_id": batch_id},
                {
                    "$inc": {"current_enrollment": increment},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Error updating enrollment count for batch {batch_id}: {e}")
            return False
    
    async def check_capacity(self, batch_id: str) -> Dict[str, Any]:
        """
        Check if batch has available capacity
        
        Returns:
            Dict with capacity info
        """
        db = self.get_db()
        
        try:
            batch = await db.batches.find_one(
                {"batch_id": batch_id},
                {"max_capacity": 1, "current_enrollment": 1}
            )
            
            if not batch:
                return {"available": False, "reason": "Batch not found"}
            
            max_capacity = batch.get("max_capacity", 0)
            current_enrollment = batch.get("current_enrollment", 0)
            available_seats = max_capacity - current_enrollment
            
            return {
                "available": available_seats > 0,
                "max_capacity": max_capacity,
                "current_enrollment": current_enrollment,
                "available_seats": available_seats,
                "is_full": available_seats <= 0
            }
            
        except Exception as e:
            logger.error(f"Error checking capacity for batch {batch_id}: {e}")
            return {"available": False, "reason": str(e)}
    
    # ============================================================================
    # BATCH STATISTICS
    # ============================================================================
    
    async def get_batch_stats(self, batch_id: str) -> Dict[str, Any]:
        """Get comprehensive statistics for a batch"""
        db = self.get_db()
        
        try:
            # Get batch details
            batch = await self.get_batch_by_id(batch_id)
            
            if not batch:
                return {"error": "Batch not found"}
            
            # Get enrollment stats
            total_enrolled = await db.batch_enrollments.count_documents({
                "batch_id": batch_id,
                "enrollment_status": "enrolled"
            })
            
            total_dropped = await db.batch_enrollments.count_documents({
                "batch_id": batch_id,
                "enrollment_status": "dropped"
            })
            
            total_completed = await db.batch_enrollments.count_documents({
                "batch_id": batch_id,
                "enrollment_status": "completed"
            })
            
            # Get session stats
            total_sessions = await db.batch_sessions.count_documents({"batch_id": batch_id})
            completed_sessions = await db.batch_sessions.count_documents({
                "batch_id": batch_id,
                "session_status": "completed"
            })
            
            pending_attendance = await db.batch_sessions.count_documents({
                "batch_id": batch_id,
                "session_status": "completed",
                "attendance_taken": False
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
                "batch_id": batch_id,
                "batch_name": batch["batch_name"],
                "status": batch["status"],
                "enrollment": {
                    "max_capacity": batch["max_capacity"],
                    "current_enrolled": total_enrolled,
                    "dropped": total_dropped,
                    "completed": total_completed,
                    "available_seats": batch["max_capacity"] - total_enrolled
                },
                "sessions": {
                    "total": total_sessions,
                    "completed": completed_sessions,
                    "pending": total_sessions - completed_sessions,
                    "pending_attendance": pending_attendance
                },
                "attendance": {
                    "average_percentage": round(avg_attendance, 2)
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting batch stats: {e}")
            return {"error": str(e)}
    
    async def get_all_batches_summary(self) -> Dict[str, Any]:
        """Get summary statistics for all batches"""
        db = self.get_db()
        
        try:
            # Count by status
            status_pipeline = [
                {"$group": {"_id": "$status", "count": {"$sum": 1}}}
            ]
            
            status_counts = await db.batches.aggregate(status_pipeline).to_list(None)
            
            # Count by type
            type_pipeline = [
                {"$group": {"_id": "$batch_type", "count": {"$sum": 1}}}
            ]
            
            type_counts = await db.batches.aggregate(type_pipeline).to_list(None)
            
            # Total enrollments
            total_enrollments = await db.batch_enrollments.count_documents({
                "enrollment_status": "enrolled"
            })
            
            return {
                "total_batches": await db.batches.count_documents({}),
                "by_status": {item["_id"]: item["count"] for item in status_counts},
                "by_type": {item["_id"]: item["count"] for item in type_counts},
                "total_enrollments": total_enrollments
            }
            
        except Exception as e:
            logger.error(f"Error getting batches summary: {e}")
            return {"error": str(e)}

# Singleton instance
batch_service = BatchService()