# app/routers/emails.py
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from bson import ObjectId
import logging
import asyncio
import aiohttp
from fastapi import status as http_status

from ..config.database import get_database
from ..config.settings import settings
from ..utils.dependencies import get_current_active_user, get_admin_user, get_user_with_permission
from ..models.email import (
    EmailRequest, BulkEmailRequest, EmailResponse,
    EmailHistoryResponse, EmailHistoryItem,
    ScheduledEmailsResponse, ScheduledEmailItem,
    EmailStatsResponse, EmailStats
)
from ..services.email_service import get_email_service
from ..services.zepto_client import test_zepto_connection

logger = logging.getLogger(__name__)

# Create router (following your CRM pattern - no prefix here)
router = APIRouter(tags=["emails"])

# ============================================================================
# EMAIL TEMPLATES ENDPOINTS
# ============================================================================

@router.get("/templates")
async def get_email_templates(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("email.send_single"))
):
    """
    Fetch email templates from CMS
    
    **Required Permission:** `email.send_single`
    
    Returns available templates for dropdown selection
    """
    try:
        logger.info(f"Fetching email templates for user: {current_user.get('email')}")
        
        # Fetch templates from CMS using aiohttp
        import aiohttp
        cms_url = f"{settings.cms_base_url}/{settings.email_templates_endpoint}"  # Use email-specific endpoint
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(cms_url) as response:
                    if response.status == 200:
                        cms_data = await response.json()
                        
                        # Format templates for frontend
                        templates = []
                        for item in cms_data.get("data", []):
                            template = {
                                "key": item.get("key"),
                                "name": item.get("Template_Name"),
                                "subject": item.get("subject", ""),
                                "description": item.get("description", ""),
                                "template_type": item.get("template_type", "email"),
                                "is_active": item.get("is_active", True)
                            }
                            
                            # Only include active email templates
                            if template["key"] and template["name"] and template.get("is_active"):
                                templates.append(template)
                        
                        logger.info(f"Successfully fetched {len(templates)} email templates from CMS")
                        
                        return {
                            "success": True,
                            "templates": templates,
                            "total": len(templates),
                            "message": f"Found {len(templates)} email templates"
                        }
                    else:
                        logger.error(f"CMS API error: {response.status}")
                        return {
                            "success": False,
                            "templates": [],
                            "total": 0,
                            "error": f"CMS API returned status {response.status}"
                        }
                        
            except aiohttp.ClientError as e:
                logger.error(f"Network error fetching templates: {e}")
                return {
                    "success": False,
                    "templates": [],
                    "total": 0,
                    "error": f"Network error: {str(e)}"
                }
                
    except Exception as e:
        logger.error(f"Error fetching email templates: {e}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch email templates: {str(e)}"
        )

@router.post("/leads/{lead_id}/send")
async def send_email_to_lead(
    lead_id: str,
    email_request: EmailRequest,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("email.send_single"))
):
    """
    Send email to a single lead
    
    **Required Permission:** `email.send_single`
    
    Users can only email leads assigned to them, admins can email any lead
    """
    try:
        logger.info(f"Email request for lead {lead_id} by user {current_user.get('email')}")
        
        result = await get_email_service().send_single_lead_email(
            lead_id=lead_id,
            email_request=email_request,
            current_user=current_user
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        return {
            "success": True,
            "data": {
                "email_id": result.get("email_id"),
                "lead_id": lead_id,
                "message": result.get("message"),
                "scheduled": result.get("scheduled", False),
                "scheduled_time": result.get("scheduled_time"),
                "created_at": result.get("created_at")
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in send_email_to_lead: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send email: {str(e)}"
        )

# ============================================================================
# BULK EMAIL ENDPOINTS
# ============================================================================

@router.post("/bulk-send")
async def send_bulk_email(
    bulk_request: BulkEmailRequest,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("email.send_bulk"))
):
    """
    Send bulk email to multiple leads
    
    **Required Permission:** `email.send_bulk`
    
    Users can send to assigned leads, admins can send to any leads
    """
    try:
        logger.info(f"Bulk email request for {len(bulk_request.lead_ids)} leads by user {current_user.get('email')}")
        
        result = await get_email_service().send_bulk_lead_email(
            bulk_request=bulk_request,
            current_user=current_user
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=result["error"]
            )
        
        response_data = {
            "success": True,
            "data": {
                "email_id": result.get("email_id"),
                "message": result.get("message"),
                "total_recipients": result.get("total_recipients", 0),
                "scheduled": result.get("scheduled", False),
                "scheduled_time": result.get("scheduled_time"),
                "created_at": result.get("created_at")
            }
        }
        
        # Add warning for permission filtering (users only)
        if "warning" in result:
            response_data["data"]["warning"] = result["warning"]
            response_data["data"]["total_requested"] = result.get("total_requested")
            response_data["data"]["total_processed"] = result.get("total_processed")
            response_data["data"]["denied_count"] = result.get("denied_count")
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in send_bulk_email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send bulk email: {str(e)}"
        )

# ============================================================================
# EMAIL HISTORY ENDPOINTS
# ============================================================================

@router.get("/leads/{lead_id}/history")
async def get_lead_email_history(
    lead_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=50, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status: sent, failed, pending, cancelled"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("email.single_history"))
):
    """
    Get email history for a specific lead
    
    **Required Permission:** `email.single_history`
    
    Users can only see history for assigned leads, admins see all
    """
    try:
        db = get_database()
        
        # Check lead exists and permission (following your CRM pattern)
        lead = await db.leads.find_one({"lead_id": lead_id})
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lead {lead_id} not found"
            )
        
        # Permission check
        user_role = current_user.get("role")
        if user_role != "admin":
            assigned_to = lead.get("assigned_to")
            current_user_email = current_user.get("email")
            
            if assigned_to != current_user_email:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only view email history for leads assigned to you"
                )
        
        # Build query
        query = {
            "$or": [
                {"lead_id": lead_id},  # Single lead emails
                {"lead_ids": lead_id}  # Bulk emails containing this lead
            ]
        }
        
        if status:
            query["status"] = status
        
        # Get total count
        total = await db.crm_lead_emails.count_documents(query)
        
        # Get emails with pagination
        skip = (page - 1) * limit
        emails_cursor = db.crm_lead_emails.find(query).sort("created_at", -1).skip(skip).limit(limit)
        emails = await emails_cursor.to_list(None)
        
        # Format response
        email_history = []
        for email in emails:
            # Find recipient info for this lead
            recipient_email = lead["email"]
            recipient_name = lead["name"]
            recipient_status = "pending"
            sent_at = None
            error = None
            
            # Look for specific recipient info
            for recipient in email.get("recipients", []):
                if recipient.get("lead_id") == lead_id:
                    recipient_status = recipient.get("status", "pending")
                    sent_at = recipient.get("sent_at")
                    error = recipient.get("error")
                    break
            
            history_item = EmailHistoryItem(
                email_id=email["email_id"],
                template_key=email["template_key"],
                template_name=email.get("template_name"),
                sender_email=email["sender_email"],
                recipient_email=recipient_email,
                recipient_name=recipient_name,
                status=recipient_status,
                scheduled=email.get("is_scheduled", False),
                scheduled_time=email.get("scheduled_time"),
                sent_at=sent_at,
                error=error,
                created_by_name=email["created_by_name"],
                created_at=email["created_at"]
            )
            email_history.append(history_item)
        
        return EmailHistoryResponse(
            lead_id=lead_id,
            emails=email_history,
            total=total,
            page=page,
            limit=limit
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting email history for lead {lead_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get email history: {str(e)}"
        )

# ============================================================================
# SCHEDULED EMAILS ENDPOINTS
# ============================================================================

@router.get("/scheduled")
async def get_scheduled_emails(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status: str = Query("pending", description="Filter by status: pending, sent, failed, cancelled"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("email.bulk_history"))
):
    """
    Get scheduled emails
    
    **Required Permission:** `email.bulk_history`
    
    Users see only their scheduled emails, admins see all
    """
    try:
        db = get_database()
        
        # Build query with permission filtering
        query = {
            "is_scheduled": True
        }
        
        # Add status filter
        if status:
            query["status"] = status
        
        # Permission filtering (following your CRM pattern)
        user_role = current_user.get("role")
        if user_role != "admin":
            # Users see only their scheduled emails
            user_id = str(current_user.get("_id") or current_user.get("id"))
            query["created_by"] = ObjectId(user_id)
        
        # Get total count
        total = await db.crm_lead_emails.count_documents(query)
        pending_count = await db.crm_lead_emails.count_documents({
            **query,
            "status": "pending"
        }) if status != "pending" else total
        
        # Get scheduled emails with pagination
        skip = (page - 1) * limit
        emails_cursor = db.crm_lead_emails.find(query).sort("scheduled_time", 1).skip(skip).limit(limit)
        emails = await emails_cursor.to_list(None)
        
        # Format response
        scheduled_emails = []
        for email in emails:
            scheduled_item = ScheduledEmailItem(
                email_id=email["email_id"],
                template_key=email["template_key"],
                template_name=email.get("template_name"),
                sender_email=email["sender_email"],
                total_recipients=email["total_recipients"],
                lead_id=email.get("lead_id"),
                lead_ids=email.get("lead_ids"),
                scheduled_time=email["scheduled_time"],
                status=email["status"],
                created_by_name=email["created_by_name"],
                created_at=email["created_at"]
            )
            scheduled_emails.append(scheduled_item)
        
        return ScheduledEmailsResponse(
            emails=scheduled_emails,
            total=total,
            pending_count=pending_count,
            page=page,
            limit=limit
        )
        
    except Exception as e:
        logger.error(f"Error getting scheduled emails: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get scheduled emails: {str(e)}"
        )

@router.delete("/scheduled/{email_id}")
async def cancel_scheduled_email(
    email_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("email.send_bulk"))
):
    """
    Cancel a scheduled email
    
    **Required Permission:** `email.send_bulk`
    
    Users can only cancel their own emails, admins can cancel any
    """
    try:
        db = get_database()
        
        # Find the scheduled email
        email = await db.crm_lead_emails.find_one({"email_id": email_id})
        if not email:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email {email_id} not found"
            )
        
        # Check if email is cancellable
        if email.get("status") != "pending":
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot cancel email with status '{email.get('status')}'. Only pending emails can be cancelled."
            )
        
        if not email.get("is_scheduled"):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Email is not scheduled and cannot be cancelled"
            )
        
        # Permission check (following your CRM pattern)
        user_role = current_user.get("role")
        if user_role != "admin":
            email_creator = email.get("created_by")
            current_user_id = str(current_user.get("_id") or current_user.get("id"))
            
            if email_creator != current_user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only cancel emails created by you"
                )
        
        # Cancel the email
        await db.crm_lead_emails.update_one(
            {"email_id": email_id},
            {
                "$set": {
                    "status": "cancelled",
                    "cancelled_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"Email {email_id} cancelled by user {current_user.get('email')}")
        
        return {
            "success": True,
            "message": f"Email {email_id} has been cancelled successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling email {email_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel email: {str(e)}"
        )

# ============================================================================
# EMAIL STATISTICS ENDPOINTS
# ============================================================================

@router.get("/stats")
async def get_email_statistics(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("email.bulk_history"))
):
    """
    Get email usage statistics
    
    **Required Permission:** `email.bulk_history`
    
    Users see their stats, admins see global stats
    """
    try:
        db = get_database()
        
        # Base query with permission filtering
        base_query = {}
        user_role = current_user.get("role")
        
        if user_role != "admin":
            # Users see only their stats
            user_id = str(current_user.get("_id") or current_user.get("id"))
            base_query["created_by"] = user_id
        
        # Calculate date ranges
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        month_start = today_start - timedelta(days=30)
        
        # Get statistics
        stats = EmailStats()
        
        # Emails sent today
        today_query = {**base_query, "status": "sent", "sent_at": {"$gte": today_start}}
        stats.emails_sent_today = await db.crm_lead_emails.count_documents(today_query)
        
        # Emails sent this week
        week_query = {**base_query, "status": "sent", "sent_at": {"$gte": week_start}}
        stats.emails_sent_week = await db.crm_lead_emails.count_documents(week_query)
        
        # Emails sent this month
        month_query = {**base_query, "status": "sent", "sent_at": {"$gte": month_start}}
        stats.emails_sent_month = await db.crm_lead_emails.count_documents(month_query)
        
        # Scheduled emails
        scheduled_query = {**base_query, "status": "pending", "is_scheduled": True}
        stats.emails_scheduled = await db.crm_lead_emails.count_documents(scheduled_query)
        
        # Failed emails today
        failed_query = {**base_query, "status": "failed", "created_at": {"$gte": today_start}}
        stats.emails_failed_today = await db.crm_lead_emails.count_documents(failed_query)
        
        # Top template (most used)
        pipeline = [
            {"$match": {**base_query, "status": "sent"}},
            {"$group": {"_id": "$template_key", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 1}
        ]
        
        top_template_result = await db.crm_lead_emails.aggregate(pipeline).to_list(1)
        if top_template_result:
            stats.top_template = top_template_result[0]["_id"]
            stats.top_template_count = top_template_result[0]["count"]
        
        # Delivery rate calculation
        total_sent = await db.crm_lead_emails.count_documents({**base_query, "status": "sent"})
        total_failed = await db.crm_lead_emails.count_documents({**base_query, "status": "failed"})
        total_attempts = total_sent + total_failed
        
        if total_attempts > 0:
            stats.delivery_rate = round((total_sent / total_attempts) * 100, 2)
        
        return EmailStatsResponse(
            success=True,
            stats=stats,
            user_specific=(user_role != "admin")
        )
        
    except Exception as e:
        logger.error(f"Error getting email statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get email statistics: {str(e)}"
        )
    
# Add this to app/routers/emails.py

# Add this to app/routers/emails.py
@router.get("/bulk-history")
async def get_bulk_email_history(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status: sent, failed, pending, cancelled"),
    search: Optional[str] = Query(None, description="Search by template name or email ID"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("email.bulk_history"))
):
    """
    Get ALL bulk email history - SAME pattern as WhatsApp bulk jobs
    
    **Required Permission:** `email.bulk_history`
    
    Permission Rules (IDENTICAL to WhatsApp):
    - email.bulk_history: Can see bulk email jobs they created
    - Admins with broader access: Can see all bulk email jobs
    """
    try:
        db = get_database()
        
        # Build query - only get bulk emails (emails with multiple lead_ids)
        query = {
            "lead_ids": {"$exists": True, "$ne": None, "$ne": []}  # ✅ Fix: Check for None too
        }
        
       
        user_role = current_user.get("role")
        
        if user_role != "admin":
            # Users can only see their own jobs (stored as string, not ObjectId)
            user_id = str(current_user.get("_id"))
            query["created_by"] = user_id  # Match created_by field
            logger.info(f"Non-admin user {current_user.get('email')} filtering jobs by created_by: {user_id}")
        else:
            logger.info(f"Admin user {current_user.get('email')} can see all jobs")
        
        # Add status filter
        if status_filter:
            query["status"] = status_filter
        
        # Add search filter
        if search:
            query["$or"] = [
                {"email_id": {"$regex": search, "$options": "i"}},
                {"template_name": {"$regex": search, "$options": "i"}},
                {"template_key": {"$regex": search, "$options": "i"}}
            ]
        
       
        total = await db.crm_lead_emails.count_documents(query)
        
        
        skip = (page - 1) * limit
        total_pages = (total + limit - 1) // limit if total > 0 else 1  # ✅ Fix: Handle zero total
        has_next = page < total_pages
        has_prev = page > 1
        
        # Get bulk emails with pagination
        emails_cursor = db.crm_lead_emails.find(query).sort("created_at", -1).skip(skip).limit(limit)
        emails = await emails_cursor.to_list(None)
        
       
        bulk_emails = []
        for email in emails:
            # ✅ Fix: Safely get recipients and lead_ids with default empty list
            recipients = email.get("recipients", []) or []
            lead_ids = email.get("lead_ids", []) or []
            
            # Calculate success/failed counts from recipients
            success_count = sum(1 for r in recipients if r.get("status") == "sent")
            failed_count = sum(1 for r in recipients if r.get("status") == "failed")
            pending_count = sum(1 for r in recipients if r.get("status") == "pending")
            
            # Calculate progress percentage
            total_recipients = email.get("total_recipients", 0)
            processed = success_count + failed_count
            progress_percentage = (processed / total_recipients * 100) if total_recipients > 0 else 0
            
            bulk_email = {
                "email_id": email.get("email_id", ""),
                "template_key": email.get("template_key", ""),
                "template_name": email.get("template_name", ""),
                "sender_email": email.get("sender_email", ""),
                "total_recipients": total_recipients,
                "success_count": success_count,
                "failed_count": failed_count,
                "pending_count": pending_count,
                "progress_percentage": round(progress_percentage, 2),
                "status": email.get("status", "pending"),
                "is_scheduled": email.get("is_scheduled", False),
                "scheduled_time": email.get("scheduled_time"),
                "sent_at": email.get("sent_at"),
                "created_by_name": email.get("created_by_name", "Unknown"),
                "created_at": email.get("created_at"),
                "completed_at": email.get("completed_at"),
                "lead_count": len(lead_ids)  # ✅ Fix: Now safe because lead_ids defaults to []
            }
            bulk_emails.append(bulk_email)
        
        # ✅ UNIVERSAL PAGINATION RESPONSE (matches PaginationMeta interface)
        return {
            "success": True,
            "bulk_emails": bulk_emails,
            "pagination": {
                "total": total,           # Total records
                "page": page,             # Current page (1-based)
                "limit": limit,           # Items per page
                "pages": total_pages,     # Total pages (consistent naming)
                "has_next": has_next,     # Boolean: more pages available
                "has_prev": has_prev      # Boolean: previous pages available
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting bulk email history: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,  # ✅ Fix: Use http_status
            detail=f"Failed to get bulk email history: {str(e)}"
        )
