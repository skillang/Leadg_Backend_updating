# app/services/bulk_whatsapp_service.py
# 🔄 UPDATED FILE - Simplified to match email pattern + SCHEDULER INTEGRATION

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from bson import ObjectId
import logging
from fastapi import HTTPException

from app.config.database import get_database
from app.services.whatsapp_message_service import WhatsAppMessageService
# 🆕 ADD: Import the scheduler
from app.utils import timezone_helper
from app.utils.whatsapp_scheduler import get_whatsapp_scheduler
from app.models.bulk_whatsapp import (
    CreateBulkWhatsAppRequest, 
    BulkWhatsAppJob, 
    BulkWhatsAppRecipient,
    BulkJobResponse,
    validate_phone_number,
    BulkJobStatus
)
from app.utils.timezone_helper import TimezoneHandler

logger = logging.getLogger(__name__)

class BulkWhatsAppService:
    """
    Core business logic for bulk WhatsApp messaging
    SIMPLIFIED PATTERN - Same as your email service (no complex filtering)
    """
    
    def __init__(self):
        self.collection_name = "bulk_whatsapp_jobs"

    @property
    def db(self):
        """Get database connection when needed (lazy initialization like email service)"""
        return get_database()

    @property  
    def whatsapp_service(self):
        """Get WhatsApp service when needed (lazy initialization)"""
        return WhatsAppMessageService()
    
    # 🆕 ADD: Scheduler property
    @property
    def scheduler(self):
        """Get WhatsApp scheduler when needed (lazy initialization)"""
        return get_whatsapp_scheduler()
    
    async def create_bulk_job(
        self, 
        request: CreateBulkWhatsAppRequest, 
        current_user: Dict[str, Any]
    ) -> BulkJobResponse:
        """
        Create bulk WhatsApp job - SIMPLIFIED like your email service
        
        Args:
            request: Bulk job creation request (with lead_ids like email)
            current_user: Current authenticated user
            
        Returns:
            BulkJobResponse with job details
        """
        try:
            logger.info(f"Creating bulk WhatsApp job: {request.job_name} by {current_user.get('email')}")
            
            # 1. Get recipients by lead IDs (SIMPLIFIED - same as email)
            recipients = await self.get_recipients_by_lead_ids(request.lead_ids, current_user)
            
            if not recipients:
                raise HTTPException(
                    status_code=400, 
                    detail="No valid recipients found. Check lead IDs and permissions."
                )
            
            # 2. Handle scheduling (SAME TIMEZONE LOGIC as your email)
            scheduled_utc = None
            is_scheduled = False
            
            if request.scheduled_time:
                # Validate future time (Frontend sends IST, we convert to UTC)
                is_valid, error_msg = TimezoneHandler.validate_future_time_ist(request.scheduled_time)
                if not is_valid:
                    raise HTTPException(status_code=400, detail=error_msg)
                
                # Convert IST to UTC for database storage (SAME as email)
                scheduled_utc = TimezoneHandler.ist_to_utc(request.scheduled_time)
                is_scheduled = True
                
                logger.info(f"Job scheduled for UTC: {scheduled_utc} (original IST: {request.scheduled_time})")
            
            # 3. Generate unique job ID (SAME PATTERN as email)
            job_id = f"bulk_whatsapp_{int(datetime.utcnow().timestamp())}"
            
            # 4. Create job document (SIMPLIFIED STRUCTURE like your email)
            job_doc = {
                "_id": ObjectId(),
                "job_id": job_id,
                "job_name": request.job_name,
                
                # Message configuration
                "message_type": request.message_type,
                "template_name": request.template_name,
                "message_content": request.message_content,
                
                # Recipients (simplified - just the list like email)
                "total_recipients": len(recipients),
                "recipients": [recipient.dict() for recipient in recipients],
                "lead_ids": request.lead_ids,  # Store original lead IDs
                
                # Progress tracking (SAME as email)
                "processed_count": 0,
                "success_count": 0,
                "failed_count": 0,
                "skipped_count": 0,
                "status": BulkJobStatus.PENDING,
                
                # Scheduling (SAME as email)
                "is_scheduled": is_scheduled,
                "scheduled_time": scheduled_utc,  # Store UTC time in MongoDB
                
                # Processing settings
                "batch_size": request.batch_size,
                "delay_between_messages": request.delay_between_messages,
                "max_retries": 3,
                
                # Results and error tracking
                "results": [],
                "error_message": None,
                
                # Audit fields (SAME as email)
                "created_by": str(current_user.get("_id")),
                "created_by_name": f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip() or current_user.get('email', 'Unknown'),
                "created_at": datetime.utcnow(),
                "started_at": None,
                "completed_at": None,
                "cancelled_at": None,
                "updated_at": datetime.utcnow()
            }
            
            # 5. Save to database (SAME as email)
            await self.db[self.collection_name].insert_one(job_doc)
            
            # 6. Log activity for scheduling (SAME as email logging)
            await self._log_bulk_job_activity(job_doc, "bulk_whatsapp_job_created")
            
            # 🆕 CRITICAL FIX: Schedule the job if it's scheduled
            if is_scheduled:
                try:
                    scheduler_success = await self.scheduler.schedule_whatsapp_job(job_id, scheduled_utc)
                    if not scheduler_success:
                        logger.error(f"Failed to schedule job {job_id} in scheduler")
                        # Mark job as failed
                        await self.db[self.collection_name].update_one(
                            {"job_id": job_id},
                            {"$set": {
                                "status": BulkJobStatus.FAILED,
                                "error_message": "Failed to schedule job execution",
                                "updated_at": datetime.utcnow()
                            }}
                        )
                        raise HTTPException(status_code=500, detail="Failed to schedule job execution")
                    else:
                        logger.info(f"✅ Job {job_id} successfully scheduled in APScheduler for {scheduled_utc}")
                except Exception as scheduler_error:
                    logger.error(f"Scheduler error for job {job_id}: {str(scheduler_error)}")
                    # Mark job as failed
                    await self.db[self.collection_name].update_one(
                        {"job_id": job_id},
                        {"$set": {
                            "status": BulkJobStatus.FAILED,
                            "error_message": f"Scheduler error: {str(scheduler_error)}",
                            "updated_at": datetime.utcnow()
                        }}
                    )
                    raise HTTPException(status_code=500, detail=f"Failed to schedule job: {str(scheduler_error)}")
            
            logger.info(f"Bulk WhatsApp job created: {job_id} with {len(recipients)} recipients")
            
            # 7. Format response (SAME as email response format)
            response_data = {
                "success": True,
                "job_id": job_id,
                "total_recipients": len(recipients),
                "scheduled": is_scheduled
            }
            
            if is_scheduled:
                # Include both timezone formats (SAME as email)
                timezone_data = TimezoneHandler.format_scheduled_time_response(scheduled_utc)
                response_data.update({
                    "message": f"Bulk WhatsApp job scheduled for {timezone_data['scheduled_time_ist_display']}",
                    "scheduled_time_ist": timezone_data["scheduled_time_ist_display"],
                    "scheduled_time_utc": scheduled_utc
                })
            else:
                response_data["message"] = f"Bulk WhatsApp job created with {len(recipients)} recipients"
            
            return BulkJobResponse(**response_data)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating bulk WhatsApp job: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to create bulk job: {str(e)}")
    
    async def get_recipients_by_lead_ids(
        self, 
        lead_ids: List[str], 
        current_user: Dict[str, Any]
    ) -> List[BulkWhatsAppRecipient]:
        """
        Get recipients by lead IDs - SIMPLIFIED like email system
        
        Args:
            lead_ids: List of lead IDs to send messages to
            current_user: Current authenticated user
            
        Returns:
            List of valid recipients for the user
        """
        try:
            user_role = current_user.get("role")
            user_email = current_user.get("email")
            
            logger.info(f"Getting recipients for {len(lead_ids)} leads as {user_role} user: {user_email}")
            
            # Build query to get leads by IDs
            query = {
                "lead_id": {"$in": lead_ids},
                "$or": [
                    {"contact_number": {"$exists": True, "$ne": "", "$ne": None}},
                    {"phone_number": {"$exists": True, "$ne": "", "$ne": None}}
                ]
            }
            
            # 🔐 PERMISSION CHECK (SAME as your email system)
            if user_role != "admin":
                # Regular users can ONLY send to their assigned leads
                query["assigned_to"] = user_email
                logger.info(f"Regular user - limited to assigned leads only")
            else:
                logger.info("Admin user - can access all leads")
            
            # Get leads from database
            leads = await self.db.leads.find(query).to_list(length=None)
            
            logger.info(f"Found {len(leads)} leads matching criteria")
            
            # Check for missing leads (permission or not found)
            found_lead_ids = {lead.get("lead_id") for lead in leads}
            missing_lead_ids = set(lead_ids) - found_lead_ids
            
            if missing_lead_ids:
                logger.warning(f"Missing leads (no permission or not found): {missing_lead_ids}")
            
            # Convert to recipients format (SAME as email recipients format)
            recipients = []
            for lead in leads:
                # Get phone number from either field
                phone = lead.get("contact_number") or lead.get("phone_number") or ""
                
                if not validate_phone_number(phone):
                    logger.warning(f"Skipping lead {lead.get('lead_id')} - invalid phone: {phone}")
                    continue
                
                recipient = BulkWhatsAppRecipient(
                    lead_id=lead.get("lead_id"),
                    phone_number=phone,
                    lead_name=lead.get("name", ""),
                    email=lead.get("email", ""),
                    status="pending"
                )
                recipients.append(recipient)
            
            logger.info(f"Created {len(recipients)} valid recipients")
            return recipients
            
        except Exception as e:
            logger.error(f"Error getting recipients by lead IDs: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get recipients: {str(e)}")
    
    async def get_bulk_job(self, job_id: str, current_user: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get bulk job details with permission check - SAME as email job retrieval
        
        Args:
            job_id: Job identifier
            current_user: Current authenticated user
            
        Returns:
            Job details dictionary
        """
        try:
            # Get job from database
            job = await self.db[self.collection_name].find_one({"job_id": job_id})
            
            if not job:
                raise HTTPException(status_code=404, detail="Bulk job not found")
            
            # Permission check (SAME as email)
            user_role = current_user.get("role")
            user_id = str(current_user.get("_id"))

            if user_role != "admin" and job.get("created_by") != user_id:
                logger.warning(f"User {current_user.get('email')} attempted to access job {job_id} created by {job.get('created_by')}")
                raise HTTPException(status_code=403, detail="Access denied - you can only view jobs you created")
                        
            # Calculate progress percentage
            total = job.get("total_recipients", 0)
            processed = job.get("processed_count", 0)
            progress_percentage = (processed / total * 100) if total > 0 else 0
            
            # Format response (include both timezone formats like email)
            job_data = {
                "job_id": job["job_id"],
                "job_name": job["job_name"],
                "message_type": job["message_type"],
                "template_name": job.get("template_name"),
                "status": job["status"],
                "total_recipients": total,
                "processed_count": processed,
                "success_count": job.get("success_count", 0),
                "failed_count": job.get("failed_count", 0),
                "skipped_count": job.get("skipped_count", 0),
                "progress_percentage": round(progress_percentage, 2),
                "is_scheduled": job.get("is_scheduled", False),
                "created_at": job["created_at"],
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "created_by_name": job.get("created_by_name")
            }
            
            # Include timezone-converted scheduled time
            if job.get("scheduled_time"):
                timezone_data = TimezoneHandler.format_scheduled_time_response(job["scheduled_time"])
                job_data.update(timezone_data)
            
            return job_data
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting bulk job {job_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get job details: {str(e)}")
    
    async def cancel_bulk_job(self, job_id: str, current_user: Dict[str, Any], reason: str = None) -> Dict[str, Any]:
        """
        Cancel bulk job - SAME as email cancellation + SCHEDULER INTEGRATION
        
        Args:
            job_id: Job identifier
            current_user: Current authenticated user
            reason: Cancellation reason
            
        Returns:
            Cancellation result
        """
        try:
            # Get and validate job
            job = await self.db[self.collection_name].find_one({"job_id": job_id})
            
            if not job:
                raise HTTPException(status_code=404, detail="Bulk job not found")
            
            # Permission check
            user_role = current_user.get("role")
            user_id = str(current_user.get("_id"))

            if user_role != "admin" and job.get("created_by") != user_id:
                logger.warning(f"User {current_user.get('email')} attempted to cancel job {job_id} created by {job.get('created_by')}")
                raise HTTPException(status_code=403, detail="Access denied - you can only cancel jobs you created")
                           
            
            # Check if job can be cancelled
            current_status = job.get("status")
            if current_status in [BulkJobStatus.COMPLETED, BulkJobStatus.FAILED, BulkJobStatus.CANCELLED]:
                raise HTTPException(status_code=400, detail=f"Cannot cancel job with status: {current_status}")
            
            # 🆕 CRITICAL FIX: Cancel scheduled job if it's scheduled
            if job.get("is_scheduled") and current_status == BulkJobStatus.PENDING:
                try:
                    scheduler_cancelled = await self.scheduler.cancel_scheduled_job(job_id)
                    if scheduler_cancelled:
                        logger.info(f"✅ Cancelled scheduled job {job_id} from APScheduler")
                    else:
                        logger.warning(f"Failed to cancel scheduled job {job_id} from APScheduler (may not exist)")
                except Exception as scheduler_error:
                    logger.error(f"Error cancelling scheduled job {job_id}: {str(scheduler_error)}")
                    # Continue with database cancellation even if scheduler fails
            
            # Update job status
            update_data = {
                "status": BulkJobStatus.CANCELLED,
                "cancelled_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            if reason:
                update_data["cancellation_reason"] = reason
            
            await self.db[self.collection_name].update_one(
                {"job_id": job_id},
                {"$set": update_data}
            )
            
            # Log activity
            await self._log_bulk_job_activity({**job, **update_data}, "bulk_whatsapp_job_cancelled")
            
            logger.info(f"Bulk WhatsApp job cancelled: {job_id} by {current_user.get('email')}")
            
            return {
                "success": True,
                "message": f"Bulk job '{job['job_name']}' cancelled successfully",
                "job_id": job_id
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error cancelling bulk job {job_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")
    
    # 🆕 ADD: Reschedule job method
    async def reschedule_bulk_job(
        self, 
        job_id: str, 
        new_scheduled_time: datetime, 
        current_user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Reschedule an existing bulk job
        
        Args:
            job_id: Job identifier
            new_scheduled_time: New scheduled time in IST
            current_user: Current authenticated user
            
        Returns:
            Reschedule result
        """
        try:
            # Get and validate job
            job = await self.db[self.collection_name].find_one({"job_id": job_id})
            
            if not job:
                raise HTTPException(status_code=404, detail="Bulk job not found")
            
            # Permission check
            user_role = current_user.get("role")
            user_id = str(current_user.get("_id"))

            if user_role != "admin" and job.get("created_by") != user_id:
                raise HTTPException(status_code=403, detail="Access denied - you can only reschedule jobs you created")
            
            # Check if job can be rescheduled
            if job.get("status") != BulkJobStatus.PENDING:
                raise HTTPException(status_code=400, detail=f"Cannot reschedule job with status: {job.get('status')}")
            
            # Validate new time
            is_valid, error_msg = TimezoneHelper.validate_future_time_ist(new_scheduled_time)
            if not is_valid:
                raise HTTPException(status_code=400, detail=error_msg)
            
            # Convert to UTC
            new_scheduled_utc = TimezoneHelper.ist_to_utc(new_scheduled_time)
            
            # Reschedule in scheduler
            try:
                scheduler_success = await self.scheduler.reschedule_job(job_id, new_scheduled_utc)
                if not scheduler_success:
                    raise HTTPException(status_code=500, detail="Failed to reschedule job in scheduler")
            except Exception as scheduler_error:
                logger.error(f"Scheduler error rescheduling job {job_id}: {str(scheduler_error)}")
                raise HTTPException(status_code=500, detail=f"Failed to reschedule job: {str(scheduler_error)}")
            
            # Update database
            await self.db[self.collection_name].update_one(
                {"job_id": job_id},
                {"$set": {
                    "scheduled_time": new_scheduled_utc,
                    "updated_at": datetime.utcnow()
                }}
            )
            
            logger.info(f"Job {job_id} rescheduled for {new_scheduled_utc} UTC")
            
            # Format response
            timezone_data = TimezoneHelper.format_scheduled_time_response(new_scheduled_utc)
            
            return {
                "success": True,
                "message": f"Job rescheduled for {timezone_data['scheduled_time_ist_display']}",
                "job_id": job_id,
                "new_scheduled_time_utc": new_scheduled_utc,
                "new_scheduled_time_ist": timezone_data["scheduled_time_ist_display"]
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error rescheduling bulk job {job_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to reschedule job: {str(e)}")
    
    async def list_bulk_jobs(
        self, 
        current_user: Dict[str, Any],
        status_filter: Optional[str] = None,
        limit: int = 50,
        skip: int = 0
    ) -> Dict[str, Any]:
        """
        List bulk jobs with filtering and pagination
        
        Args:
            current_user: Current authenticated user
            status_filter: Filter by job status
            limit: Number of jobs to return
            skip: Number of jobs to skip
            
        Returns:
            List of bulk jobs with pagination info
        """
        try:
            user_role = current_user.get("role")
            
            # Build query
            query = {}
            
            # Permission check - non-admin users can only see their own jobs
            if user_role != "admin":
                user_id = str(current_user.get("_id"))
                query["created_by"] = user_id
                logger.info(f"Non-admin user {current_user.get('email')} filtering by created_by: {user_id}")
            else:
                logger.info(f"Admin user {current_user.get('email')} can see all jobs")
            # Status filter
            if status_filter:
                query["status"] = status_filter
            
            # Get total count
            total_count = await self.db[self.collection_name].count_documents(query)
            
            # Get jobs with pagination
            jobs_cursor = self.db[self.collection_name].find(query).sort("created_at", -1).skip(skip).limit(limit)
            jobs = await jobs_cursor.to_list(length=None)
            
            # Format jobs for response
            formatted_jobs = []
            for job in jobs:
                job_data = {
                    "job_id": job["job_id"],
                    "job_name": job["job_name"],
                    "message_type": job["message_type"],
                    "template_name": job.get("template_name"),
                    "status": job["status"],
                    "total_recipients": job.get("total_recipients", 0),
                    "success_count": job.get("success_count", 0),
                    "failed_count": job.get("failed_count", 0),
                    "is_scheduled": job.get("is_scheduled", False),
                    "created_at": job["created_at"],
                    "created_by_name": job.get("created_by_name"),
                    "completed_at": job.get("completed_at")
                }
                
                # Add scheduled time if exists
                if job.get("scheduled_time"):
                    timezone_data = timezone_helper.format_scheduled_time_response(job["scheduled_time"])
                    job_data.update(timezone_data)
                
                formatted_jobs.append(job_data)
            
            return {
                "jobs": formatted_jobs,
                "total_count": total_count,
                "limit": limit,
                "skip": skip,
                "has_more": total_count > (skip + limit)
            }
            
        except Exception as e:
            logger.error(f"Error listing bulk jobs: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to list jobs: {str(e)}")
    
    # ================================
    # PRIVATE HELPER METHODS (SIMPLIFIED)
    # ================================
    
    async def _log_bulk_job_activity(self, job_doc: Dict[str, Any], activity_type: str):
        """
        Log bulk job activities - SAME as your email activity logging
        
        Args:
            job_doc: Job document
            activity_type: Type of activity
        """
        try:
            # Get all lead IDs from recipients
            lead_ids = job_doc.get("lead_ids", [])
            
            activities = []
            
            # Create activity for each lead (SAME as email)
            for lead_id in lead_ids:
                activity = {
                    "_id": ObjectId(),
                    "lead_id": lead_id,
                    "activity_type": activity_type,
                    "description": self._get_activity_description(job_doc, activity_type),
                    "metadata": {
                        "job_id": job_doc["job_id"],
                        "job_name": job_doc["job_name"],
                        "message_type": job_doc["message_type"],
                        "template_name": job_doc.get("template_name"),
                        "total_recipients": job_doc.get("total_recipients", 0),
                        "is_scheduled": job_doc.get("is_scheduled", False)
                    },
                    "created_by": ObjectId(job_doc["created_by"]) if job_doc.get("created_by") and ObjectId.is_valid(job_doc["created_by"]) else None,
                    "created_by_name": job_doc.get("created_by_name"),
                    "created_at": datetime.utcnow()
                }
                activities.append(activity)
            
            # Insert activities (SAME as email)
            if activities:
                await self.db.lead_activities.insert_many(activities)
                logger.info(f"Logged {len(activities)} bulk WhatsApp activities")
                
        except Exception as e:
            logger.error(f"Error logging bulk job activities: {e}")
    
    def _get_activity_description(self, job_doc: Dict[str, Any], activity_type: str) -> str:
        """Generate activity description based on type"""
        job_name = job_doc.get("job_name", "Bulk WhatsApp")
        
        descriptions = {
            "bulk_whatsapp_job_created": f"Added to bulk WhatsApp job: {job_name}",
            "bulk_whatsapp_job_scheduled": f"Scheduled for bulk WhatsApp job: {job_name}",
            "bulk_whatsapp_job_cancelled": f"Bulk WhatsApp job cancelled: {job_name}",
            "bulk_whatsapp_sent": f"WhatsApp message sent via bulk job: {job_name}",
            "bulk_whatsapp_failed": f"WhatsApp message failed in bulk job: {job_name}",
            "bulk_whatsapp_completed": f"Bulk WhatsApp job completed: {job_name}",
            "bulk_whatsapp_job_failed": f"Bulk WhatsApp job failed: {job_name}"
        }
        
        return descriptions.get(activity_type, f"Bulk WhatsApp activity: {activity_type}")

# ================================
# SERVICE INSTANCE
# ================================

# Global service instance (same pattern as your email service)
_bulk_whatsapp_service = None

def get_bulk_whatsapp_service() -> BulkWhatsAppService:
    """Get bulk WhatsApp service instance with lazy initialization"""
    global _bulk_whatsapp_service
    if _bulk_whatsapp_service is None:
        _bulk_whatsapp_service = BulkWhatsAppService()
    return _bulk_whatsapp_service

# Helper function for easy import
bulk_whatsapp_service = get_bulk_whatsapp_service()