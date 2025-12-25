"""
Batch Enrollment Service
Handles lead enrollment in batches
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from bson import ObjectId

from ..config.database import get_database
from .batch_service import batch_service

logger = logging.getLogger(__name__)

class BatchEnrollmentService:
    """Service for batch enrollment operations"""
    
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
    
    async def generate_enrollment_id(self) -> str:
        """Generate unique enrollment ID (ENR-001, ENR-002, etc.)"""
        db = self.get_db()
        
        try:
            counter = await db.counters.find_one_and_update(
                {"_id": "enrollment_id"},
                {"$inc": {"sequence": 1}},
                upsert=True,
                return_document=True
            )
            
            sequence = counter.get("sequence", 1)
            enrollment_id = f"ENR-{sequence:03d}"
            
            return enrollment_id
            
        except Exception as e:
            logger.error(f"Error generating enrollment ID: {e}")
            return f"ENR-{int(datetime.utcnow().timestamp())}"
    
    # ============================================================================
    # ENROLLMENT OPERATIONS
    # ============================================================================
    
    async def enroll_lead(
        self,
        batch_id: str,
        lead_id: str,
        enrolled_by: str,
        enrolled_by_name: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Enroll a single lead in a batch
        
        Args:
            batch_id: Batch identifier
            lead_id: Lead identifier
            enrolled_by: User ID enrolling the lead
            enrolled_by_name: Name of enrolling user
            notes: Optional enrollment notes
            
        Returns:
            Created enrollment document
        """
        db = self.get_db()
        
        try:
            # Check if batch exists and has capacity
            capacity_check = await batch_service.check_capacity(batch_id)
            
            if not capacity_check["available"]:
                raise ValueError(f"Batch is full or not found: {capacity_check.get('reason', 'No capacity')}")
            
            # Check if lead exists
            lead = await db.leads.find_one(
                {"lead_id": lead_id},
                {"name": 1, "email": 1}
            )
            
            if not lead:
                raise ValueError(f"Lead {lead_id} not found")
            
            # Check if already enrolled
            existing = await db.batch_enrollments.find_one({
                "batch_id": batch_id,
                "lead_id": lead_id,
                "enrollment_status": {"$ne": "dropped"}
            })
            
            if existing:
                raise ValueError(f"Lead {lead_id} is already enrolled in batch {batch_id}")
            
            # Get batch details
            batch = await batch_service.get_batch_by_id(batch_id)
            
            # Generate enrollment ID
            enrollment_id = await self.generate_enrollment_id()
            
            # Create enrollment document
            enrollment_doc = {
                "_id": ObjectId(),
                "enrollment_id": enrollment_id,
                "batch_id": batch_id,
                "batch_name": batch["batch_name"],
                "lead_id": lead_id,
                "lead_name": lead["name"],
                "lead_email": lead["email"],
                "enrollment_date": datetime.utcnow(),
                "enrollment_status": "enrolled",
                "enrolled_by": enrolled_by,
                "enrolled_by_name": enrolled_by_name,
                "attendance_count": 0,
                "total_sessions_held": 0,
                "attendance_percentage": 0.0,
                "dropped_reason": None,
                "notes": notes,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            # Insert enrollment
            await db.batch_enrollments.insert_one(enrollment_doc)
            
            # Update batch enrollment count
            await batch_service.update_enrollment_count(batch_id, increment=1)
            
            # Update lead's enrolled_batches array
            await db.leads.update_one(
                {"lead_id": lead_id},
                {
                    "$addToSet": {"enrolled_batches": batch_id},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            
            logger.info(f"✅ Enrolled lead {lead_id} in batch {batch_id}")
            
            # Log timeline activity
            try:
                from .timeline_service import timeline_service
                await timeline_service.log_activity(
                    lead_id=lead_id,
                    activity_type="batch_enrolled",
                    description=f"Enrolled in batch: {batch['batch_name']}",
                    created_by=ObjectId(enrolled_by),
                    metadata={
                        "batch_id": batch_id,
                        "batch_name": batch["batch_name"],
                        "enrollment_id": enrollment_id
                    }
                )
            except Exception as timeline_error:
                logger.warning(f"Failed to log timeline activity: {timeline_error}")
            
            return enrollment_doc
            
        except Exception as e:
            logger.error(f"Error enrolling lead: {e}")
            raise
    
    async def bulk_enroll(
        self,
        batch_id: str,
        lead_ids: List[str],
        enrolled_by: str,
        enrolled_by_name: str,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Enroll multiple leads in a batch
        
        Returns:
            Summary with successful and failed enrollments
        """
        results = {
            "successful": [],
            "failed": [],
            "total": len(lead_ids),
            "success_count": 0,
            "failed_count": 0
        }
        
        for lead_id in lead_ids:
            try:
                enrollment = await self.enroll_lead(
                    batch_id=batch_id,
                    lead_id=lead_id,
                    enrolled_by=enrolled_by,
                    enrolled_by_name=enrolled_by_name,
                    notes=notes
                )
                
                results["successful"].append({
                    "lead_id": lead_id,
                    "enrollment_id": enrollment["enrollment_id"]
                })
                results["success_count"] += 1
                
            except Exception as e:
                results["failed"].append({
                    "lead_id": lead_id,
                    "error": str(e)
                })
                results["failed_count"] += 1
                logger.warning(f"Failed to enroll lead {lead_id}: {e}")
        
        logger.info(f"✅ Bulk enrollment complete: {results['success_count']}/{results['total']} successful")
        
        return results
    
    async def remove_enrollment(
        self,
        enrollment_id: str,
        reason: Optional[str] = None
    ) -> bool:
        """
        Remove a lead from a batch (mark as dropped)
        
        Args:
            enrollment_id: Enrollment identifier
            reason: Reason for dropping
            
        Returns:
            True if successful
        """
        db = self.get_db()
        
        try:
            enrollment = await db.batch_enrollments.find_one({"enrollment_id": enrollment_id})
            
            if not enrollment:
                raise ValueError(f"Enrollment {enrollment_id} not found")
            
            # Update enrollment status
            result = await db.batch_enrollments.update_one(
                {"enrollment_id": enrollment_id},
                {
                    "$set": {
                        "enrollment_status": "dropped",
                        "dropped_reason": reason,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                # Update batch enrollment count
                await batch_service.update_enrollment_count(enrollment["batch_id"], increment=-1)
                
                # Remove from lead's enrolled_batches
                await db.leads.update_one(
                    {"lead_id": enrollment["lead_id"]},
                    {
                        "$pull": {"enrolled_batches": enrollment["batch_id"]},
                        "$set": {"updated_at": datetime.utcnow()}
                    }
                )
                
                logger.info(f"✅ Removed enrollment {enrollment_id}")
                
                # Log timeline activity
                try:
                    from .timeline_service import timeline_service
                    await timeline_service.log_activity(
                        lead_id=enrollment["lead_id"],
                        activity_type="batch_dropped",
                        description=f"Dropped from batch: {enrollment['batch_name']}",
                        created_by=None,
                        metadata={
                            "batch_id": enrollment["batch_id"],
                            "reason": reason
                        }
                    )
                except Exception as timeline_error:
                    logger.warning(f"Failed to log timeline activity: {timeline_error}")
                
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error removing enrollment: {e}")
            raise
    
    # ============================================================================
    # ENROLLMENT QUERIES
    # ============================================================================
    
    async def get_batch_students(
        self,
        batch_id: str,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all students enrolled in a batch"""
        db = self.get_db()
        
        try:
            query = {"batch_id": batch_id}
            
            if status:
                query["enrollment_status"] = status
            else:
                query["enrollment_status"] = {"$ne": "dropped"}
            
            cursor = db.batch_enrollments.find(query).sort("enrollment_date", -1)
            enrollments = await cursor.to_list(length=None)
            
            return enrollments
            
        except Exception as e:
            logger.error(f"Error fetching batch students: {e}")
            return []
    
    async def get_lead_batches(
        self,
        lead_id: str,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all batches a lead is enrolled in"""
        db = self.get_db()
        
        try:
            query = {"lead_id": lead_id}
            
            if status:
                query["enrollment_status"] = status
            
            cursor = db.batch_enrollments.find(query).sort("enrollment_date", -1)
            enrollments = await cursor.to_list(length=None)
            
            return enrollments
            
        except Exception as e:
            logger.error(f"Error fetching lead batches: {e}")
            return []
    
    async def update_attendance_stats(
        self,
        enrollment_id: str,
        attended: bool
    ) -> bool:
        """
        Update attendance statistics for an enrollment
        
        Args:
            enrollment_id: Enrollment identifier
            attended: True if attended, False if absent
            
        Returns:
            True if updated successfully
        """
        db = self.get_db()
        
        try:
            # Get current enrollment
            enrollment = await db.batch_enrollments.find_one({"enrollment_id": enrollment_id})
            
            if not enrollment:
                return False
            
            # Update attendance count
            update_doc = {
                "$inc": {
                    "total_sessions_held": 1
                }
            }
            
            if attended:
                update_doc["$inc"]["attendance_count"] = 1
            
            # Update enrollment
            await db.batch_enrollments.update_one(
                {"enrollment_id": enrollment_id},
                update_doc
            )
            
            # Recalculate attendance percentage
            updated_enrollment = await db.batch_enrollments.find_one({"enrollment_id": enrollment_id})
            
            if updated_enrollment["total_sessions_held"] > 0:
                attendance_percentage = (
                    updated_enrollment["attendance_count"] / 
                    updated_enrollment["total_sessions_held"]
                ) * 100
                
                await db.batch_enrollments.update_one(
                    {"enrollment_id": enrollment_id},
                    {
                        "$set": {
                            "attendance_percentage": round(attendance_percentage, 2),
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating attendance stats: {e}")
            return False

# Singleton instance
batch_enrollment_service = BatchEnrollmentService()