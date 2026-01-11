# app/routers/bulk_whatsapp.py
# 🔄 UPDATED FILE - Simplified to match email pattern (removed preview, simplified job creation)

import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse

from app.models.bulk_whatsapp import (
    CreateBulkWhatsAppRequest,
    CancelBulkJobRequest,
    BulkJobResponse,
    BulkJobStatusResponse,
    BulkJobListResponse,
    BulkStatsResponse
)
from app.services.bulk_whatsapp_service import get_bulk_whatsapp_service
from app.services.bulk_whatsapp_processor import get_bulk_whatsapp_processor
from app.utils.dependencies import get_current_user, get_admin_user, get_user_with_permission
from app.config.database import get_database
import logging

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# Get service instances
bulk_service = get_bulk_whatsapp_service()
bulk_processor = get_bulk_whatsapp_processor()

# ================================
# BULK JOB MANAGEMENT ENDPOINTS (SIMPLIFIED)
# ================================

@router.post("/jobs", response_model=BulkJobResponse)
async def create_bulk_whatsapp_job(
    request: CreateBulkWhatsAppRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("whatsapp.send_bulk"))
):
    """
    Create bulk WhatsApp job - SIMPLIFIED like your email system
    
    **Required Permission:** `whatsapp.send_bulk`
    
    Request body should contain:
    {
        "job_name": "Follow-up Campaign",
        "message_type": "template",
        "template_name": "nursing_promo_form_wa",
        "lead_ids": ["LD-1001", "LD-1002", "LD-1003"],
        "scheduled_time": "2024-07-30 18:00:00"  // Optional
    }
    
    Permission Rules:
    - Users with whatsapp.send_bulk: Can send to assigned leads
    - Admins with whatsapp.view_all: Can send to any leads
    """
    try:
        logger.info(f"Creating bulk WhatsApp job: {request.job_name} by {current_user.get('email')}")
        
        # 1. Create job using service (same as email)
        job_response = await bulk_service.create_bulk_job(request, current_user)
        
        # 2. Schedule processing (same pattern as email)
        if request.scheduled_time:
            # For scheduled jobs, the scheduler will handle processing
            logger.info(f"Job {job_response.job_id} scheduled for {request.scheduled_time}")
        else:
            # For immediate jobs, start processing in background (same as email)
            background_tasks.add_task(bulk_processor.process_bulk_job, job_response.job_id)
            logger.info(f"Job {job_response.job_id} queued for immediate processing")
        
        return job_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating bulk WhatsApp job: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create bulk job: {str(e)}")

@router.get("/jobs/{job_id}", response_model=BulkJobStatusResponse)
async def get_bulk_job_status(
    job_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("whatsapp.view_bulk"))
):
    """
    Get bulk job status and progress - SAME as your email status endpoint
    
    **Required Permission:** `whatsapp.view_bulk`
    
    Permission Rules:
    - whatsapp.view_bulk: Can view jobs they created
    - whatsapp.view_all: Can view any job (admin)
    """
    try:
        job_data = await bulk_service.get_bulk_job(job_id, current_user)
        
        # Calculate estimated completion time
        if job_data["status"] == "processing":
            processed = job_data["processed_count"]
            total = job_data["total_recipients"]
            
            if processed > 0:
                # Estimate based on current progress
                time_per_message = 3  # Average 3 seconds per message
                remaining_messages = total - processed
                estimated_seconds = remaining_messages * time_per_message
                estimated_completion = datetime.utcnow().timestamp() + estimated_seconds
                job_data["estimated_completion"] = datetime.fromtimestamp(estimated_completion)
        
        return BulkJobStatusResponse(**job_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status {job_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")

@router.get("/jobs", response_model=BulkJobListResponse)
async def list_bulk_jobs(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("whatsapp.view_bulk"))
):
    """
    List bulk jobs with pagination - SAME pattern as your email listing
    
    **Required Permission:** `whatsapp.view_bulk`
    
    Permission Rules:
    - whatsapp.view_bulk: Can see jobs they created
    - whatsapp.view_all: Can see all jobs (admin)
    """
    try:
        db = get_database()
        
        # Build query based on permissions (same as email)
        query = {}
        user_role = current_user.get("role")
        
        if user_role != "admin":
            # Users can only see their own jobs
            user_id = str(current_user.get("_id"))
            query["created_by"] = user_id
            logger.info(f"Non-admin user {current_user.get('email')} filtering jobs by created_by: {user_id}")
        else:
            logger.info(f"Admin user {current_user.get('email')} can see all jobs")
                
        # Apply status filter
        if status:
            query["status"] = status
        
        # Calculate pagination
        skip = (page - 1) * limit
        
        # Get total count
        total_jobs = await db.bulk_whatsapp_jobs.count_documents(query)
        
        # Get jobs with pagination
        jobs_cursor = db.bulk_whatsapp_jobs.find(query).sort("created_at", -1).skip(skip).limit(limit)
        jobs = await jobs_cursor.to_list(length=limit)
        # Format jobs for response
        job_list = []
        for job in jobs:
            # Calculate progress percentage
            total = job.get("total_recipients", 0)
            processed = job.get("processed_count", 0)
            progress_percentage = (processed / total * 100) if total > 0 else 0
            
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
            
            # Add timezone-converted scheduled time if exists
            if job.get("scheduled_time"):
                from app.utils.timezone_helper import TimezoneHandler
                timezone_data = TimezoneHandler.format_scheduled_time_response(job["scheduled_time"])
                job_data.update(timezone_data)
            
            job_list.append(BulkJobStatusResponse(**job_data))
        
        # Calculate pagination info
        total_pages = (total_jobs + limit - 1) // limit
        
        return {
            "jobs": job_list,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_jobs,
                "pages": (total_jobs + limit - 1) // limit,
                "has_next": skip + limit < total_jobs,
                "has_prev": page > 1
            }
        }
        
    except Exception as e:
        logger.error(f"Error listing bulk jobs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list jobs: {str(e)}")

@router.post("/jobs/{job_id}/cancel")
async def cancel_bulk_job(
    job_id: str,
    request: Optional[CancelBulkJobRequest] = None,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("whatsapp.send_bulk"))
):
    """
    Cancel bulk job - SAME as email cancellation
    
    **Required Permission:** `whatsapp.send_bulk`
    
    Permission Rules:
    - whatsapp.send_bulk: Can cancel jobs they created
    - whatsapp.view_all: Can cancel any job (admin)
    """
    try:
        reason = request.reason if request else None
        result = await bulk_service.cancel_bulk_job(job_id, current_user, reason)
        
        # Also stop if currently processing
        await bulk_processor.stop_job(job_id)
        
        return JSONResponse(content=result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")

# ================================
# STATISTICS AND MONITORING ENDPOINTS
# ================================

@router.get("/stats", response_model=BulkStatsResponse)
async def get_bulk_stats(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("whatsapp.view_bulk"))
):
    """
    Get bulk messaging statistics - SAME pattern as email stats
    
    **Required Permission:** `whatsapp.view_bulk`
    
    Permission Rules:
    - whatsapp.view_bulk: Gets statistics for their jobs only
    - whatsapp.view_all: Gets system-wide statistics (admin)
    """
    try:
        db = get_database()
        
        # Build query based on permissions
        base_query = {}
        user_role = current_user.get("role")
        
        if user_role != "admin":
            user_id = str(current_user.get("_id"))
            base_query["created_by"] = user_id
            logger.info(f"Non-admin user {current_user.get('email')} getting stats for created_by: {user_id}")
        else:
            logger.info(f"Admin user {current_user.get('email')} getting system-wide stats")
        # Get job counts by status
        pipeline = [
            {"$match": base_query},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1},
                "total_recipients": {"$sum": "$total_recipients"},
                "success_count": {"$sum": "$success_count"},
                "failed_count": {"$sum": "$failed_count"}
            }}
        ]
        
        stats_result = await db.bulk_whatsapp_jobs.aggregate(pipeline).to_list(length=None)
        
        # Initialize counters
        total_jobs = 0
        active_jobs = 0
        completed_jobs = 0
        failed_jobs = 0
        total_messages_sent = 0
        total_messages_failed = 0
        
        # Process results
        for stat in stats_result:
            status = stat["_id"]
            count = stat["count"]
            
            total_jobs += count
            total_messages_sent += stat.get("success_count", 0)
            total_messages_failed += stat.get("failed_count", 0)
            
            if status in ["pending", "processing"]:
                active_jobs += count
            elif status == "completed":
                completed_jobs += count
            elif status == "failed":
                failed_jobs += count
        
        # Calculate success rate
        total_messages = total_messages_sent + total_messages_failed
        success_rate = (total_messages_sent / total_messages * 100) if total_messages > 0 else 0
        
        # Get today's stats
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_query = {**base_query, "created_at": {"$gte": today_start}}
        
        jobs_today = await db.bulk_whatsapp_jobs.count_documents(today_query)
        
        # Get today's message counts
        today_pipeline = [
            {"$match": today_query},
            {"$group": {
                "_id": None,
                "messages_sent": {"$sum": "$success_count"}
            }}
        ]
        
        today_stats = await db.bulk_whatsapp_jobs.aggregate(today_pipeline).to_list(1)
        messages_sent_today = today_stats[0]["messages_sent"] if today_stats else 0
        
        # Get next scheduled job (admin only)
        next_scheduled_job = None
        if user_role == "admin":
            next_job_cursor = db.bulk_whatsapp_jobs.find({
                "status": "pending",
                "is_scheduled": True,
                "scheduled_time": {"$gt": datetime.utcnow()}
            }).sort("scheduled_time", 1).limit(1)
            
            next_jobs = await next_job_cursor.to_list(1)
            if next_jobs:
                job = next_jobs[0]
                next_scheduled_job = {
                    "job_id": job["job_id"],
                    "job_name": job["job_name"],
                    "scheduled_time": job["scheduled_time"],
                    "total_recipients": job["total_recipients"]
                }
        
        return BulkStatsResponse(
            total_jobs=total_jobs,
            active_jobs=active_jobs,
            completed_jobs=completed_jobs,
            failed_jobs=failed_jobs,
            total_messages_sent=total_messages_sent,
            total_messages_failed=total_messages_failed,
            success_rate=round(success_rate, 2),
            jobs_today=jobs_today,
            messages_sent_today=messages_sent_today,
            next_scheduled_job=next_scheduled_job
        )
        
    except Exception as e:
        logger.error(f"Error getting bulk stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")

@router.get("/active-jobs")
async def get_active_jobs(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("whatsapp.view_all"))
):
    """
    Get currently processing jobs - Admin only for monitoring
    
    **Required Permission:** `whatsapp.view_all`
    """
    try:
        active_jobs = await bulk_processor.get_active_jobs()
        
        return {
            "success": True,
            "active_jobs": active_jobs,
            "total_active": len(active_jobs)
        }
        
    except Exception as e:
        logger.error(f"Error getting active jobs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get active jobs: {str(e)}")

# ================================
# TEMPLATE AND VALIDATION ENDPOINTS
# ================================

@router.get("/templates")
async def get_whatsapp_templates(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("whatsapp.send_bulk"))
):
    """
    Get available WhatsApp templates - Reuse existing endpoint logic
    
    **Required Permission:** `whatsapp.send_bulk`
    """
    try:
        # Import existing WhatsApp router function
        from app.routers.whatsapp import get_available_templates
        
        # Call existing function (same template fetching logic)
        templates_response = await get_available_templates(current_user)
        
        return templates_response
        
    except Exception as e:
        logger.error(f"Error getting templates: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get templates: {str(e)}")

@router.post("/validate-phone-numbers")
async def validate_phone_numbers(
    phone_numbers: List[str],
    current_user: Dict[str, Any] = Depends(get_user_with_permission("whatsapp.send_bulk"))
):
    """
    Validate phone numbers for WhatsApp messaging
    
    **Required Permission:** `whatsapp.send_bulk`
    """
    try:
        from app.models.bulk_whatsapp import validate_phone_number
        
        results = []
        for phone in phone_numbers:
            is_valid = validate_phone_number(phone)
            results.append({
                "phone_number": phone,
                "is_valid": is_valid,
                "formatted": phone.replace("+", "").replace("-", "").replace(" ", "") if is_valid else None
            })
        
        valid_count = sum(1 for r in results if r["is_valid"])
        
        return {
            "success": True,
            "results": results,
            "total_numbers": len(phone_numbers),
            "valid_numbers": valid_count,
            "invalid_numbers": len(phone_numbers) - valid_count
        }
        
    except Exception as e:
        logger.error(f"Error validating phone numbers: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to validate phone numbers: {str(e)}")