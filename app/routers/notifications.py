# app/routers/notifications.py - WhatsApp Notification Management APIs

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime, timedelta
from app.utils.timezone_helper import TimezoneHandler 
from pydantic import BaseModel
from typing import Optional

from ..utils.dependencies import get_current_user, get_admin_user
from ..decorators.timezone_decorator import convert_notification_dates
from ..config.database import get_database
from ..services.realtime_service import realtime_manager
from ..schemas.whatsapp_chat import (
    BulkUnreadStatusResponse,
    UnreadStatusSummary,
    LeadUnreadStatusResponse,
    MarkLeadAsReadResponse,
    BulkMarkReadRequest,
    BulkMarkReadResponse
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WhatsApp Notifications"])

def extract_notification_uuid(notification_id: str) -> str:
    """
    Extract clean UUID from notification ID
    Handles both formats:
    - New: "task_8e3f3211-81d5-4100-8272-eb84d96d6ec7" -> "8e3f3211-81d5-4100-8272-eb84d96d6ec7"
    - Legacy: "lead_user@email.com_lead_DC-WB-9_1759933309.041334" -> keeps as-is (not in unified table)
    """
    # New unified format: prefix_uuid
    if notification_id.startswith(('task_', 'lead_', 'whatsapp_')):
        parts = notification_id.split('_', 1)
        if len(parts) > 1 and '-' in parts[1]:  # Has UUID format (contains dashes)
            return parts[1]
    
    # Return as-is for legacy or already clean UUIDs
    return notification_id
class UnifiedNotificationsRequest(BaseModel):
    """Request body for unified notifications with optional mark as read"""
    notification_ids: Optional[List[str]] = None
    mark_as_read: bool = False



# ============================================================================
# UNIFIED NOTIFICATION ENDPOINT (ALL TYPES) - WITH UNIVERSAL PAGINATION
# ============================================================================
# app/routers/notifications.py
# ✅ SOLUTION: Support both GET and POST on /unified

# ============================================================================
# SHARED LOGIC - Core function that both GET and POST will use
# ============================================================================

async def _fetch_unified_notifications(
    db,
    user_email: str,
    user_role: str,
    user_id: str,
    notification_type: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    mark_as_read_request: Optional[UnifiedNotificationsRequest] = None
):
    """
    Shared logic for fetching notifications
    Used by both GET and POST endpoints
    """
    
    # ========== MARK AS READ (if requested via POST) ==========
    marked_count = 0
    if mark_as_read_request and mark_as_read_request.mark_as_read and mark_as_read_request.notification_ids:
        logger.info(f"📖 Marking {len(mark_as_read_request.notification_ids)} notification(s) as read for {user_email}")
        
        # Extract clean UUIDs
        clean_notification_ids = [extract_notification_uuid(nid) for nid in mark_as_read_request.notification_ids]
        
        # Update unified notifications
        result = await db.notification_history.update_many(
            {
                "notification_id": {"$in": clean_notification_ids},
                "$or": [
                    {"visible_to_users": user_email},
                    {"visible_to_admins": True}
                ],
                f"read_by.{user_email}": {"$exists": False}
            },
            {
                "$set": {
                    f"read_by.{user_email}": datetime.utcnow()
                }
            }
        )
        marked_count = result.modified_count
        logger.info(f"✅ Marked {marked_count} unified notification(s) as read")
        
        # Handle legacy notifications
        legacy_result = await db.notification_history.update_many(
            {
                "notification_id": {"$in": mark_as_read_request.notification_ids},
                "user_email": user_email,
                "read_at": None
            },
            {
                "$set": {
                    "read_at": datetime.utcnow()
                }
            }
        )
        if legacy_result.modified_count > 0:
            marked_count += legacy_result.modified_count
            logger.info(f"✅ Also marked {legacy_result.modified_count} legacy notification(s) as read")
    
    all_notifications = []
    
    # ========== 1. WhatsApp Notifications ==========
    if not notification_type or notification_type in ["whatsapp", "all"]:
        whatsapp_query = {"whatsapp_has_unread": True}
        
        if user_role != "admin":
            whatsapp_query.update({
                "$or": [
                    {"assigned_to": user_email},
                    {"co_assignees": user_email}
                ]
            })
        
        whatsapp_leads = await db.leads.find(
            whatsapp_query,
            {"lead_id": 1, "name": 1, "unread_whatsapp_count": 1, "last_whatsapp_activity": 1}
        ).to_list(None)
        
        for lead in whatsapp_leads:
            all_notifications.append({
                "id": f"whatsapp_{lead['lead_id']}",
                "type": "whatsapp_unread",
                "title": f"{lead.get('unread_whatsapp_count', 0)} unread messages",
                "message": f"WhatsApp messages from {lead.get('name')}",
                "lead_id": lead["lead_id"],
                "lead_name": lead.get("name"),
                "timestamp": lead.get("last_whatsapp_activity") or datetime.utcnow(),
                "read": False,
                "priority": "medium",
                "metadata": {
                    "unread_count": lead.get("unread_whatsapp_count", 0)
                }
            })
    
    # ========== 2. Task Notifications ==========
    if not notification_type or notification_type in ["task", "all"]:
        task_query = {
            "$or": [
                {"user_email": user_email},
                {"visible_to_users": user_email},
            ],
            "notification_type": "task_assigned",
            f"read_by.{user_email}": {"$exists": False}
        }
        
        if user_role == "admin":
            task_query = {
                "$or": [
                    {"visible_to_users": user_email},
                    {"visible_to_admins": True}
                ],
                "notification_type": "task_assigned",
                f"read_by.{user_email}": {"$exists": False}
            }
        
        task_notifications = await db.notification_history.find(
            task_query,
            {
                "notification_id": 1,
                "lead_id": 1,
                "lead_name": 1,
                "task_id": 1,
                "task_title": 1,
                "task_type": 1,
                "priority": 1,
                "created_at": 1,
                "visible_to_users": 1,
                "original_data": 1
            }
        ).sort("created_at", -1).to_list(None)
        
        for task_notif in task_notifications:
            original_data = task_notif.get("original_data", {})
            visible_to_users = task_notif.get("visible_to_users", [])
            
            if user_role == "admin" and user_email not in visible_to_users:
                assigned_user = visible_to_users[0] if visible_to_users else "Unknown"
                message = f"Task '{task_notif.get('task_title', 'New Task')}' assigned to {assigned_user}"
            else:
                message = f"You have been assigned: {task_notif.get('task_title', 'New Task')}"
            
            all_notifications.append({
                "id": f"task_{task_notif['notification_id']}",
                "type": "task_assigned",
                "title": "Task Assigned",
                "message": message,
                "lead_id": task_notif.get("lead_id"),
                "lead_name": task_notif.get("lead_name"),
                "task_id": task_notif.get("task_id"),
                "timestamp": task_notif.get("created_at") or datetime.utcnow(),
                "read": False,
                "priority": task_notif.get("priority", "medium"),
                "metadata": {
                    "task_title": task_notif.get("task_title"),
                    "task_type": task_notif.get("task_type"),
                    "due_date": original_data.get("due_date"),
                    "reassigned": original_data.get("reassigned", False),
                    "assigned_users": visible_to_users if user_role == "admin" else None
                }
            })
    
    # ========== 3. Lead Notifications ==========
    if not notification_type or notification_type in ["lead", "all"]:
        lead_query = {
            "$or": [
                {"user_email": user_email},
                {"visible_to_users": user_email},
            ],
            "notification_type": {"$in": ["lead_assigned", "lead_reassigned"]},
            f"read_by.{user_email}": {"$exists": False}
        }
        
        if user_role == "admin":
            lead_query = {
                "$or": [
                    {"visible_to_users": user_email},
                    {"visible_to_admins": True}
                ],
                "notification_type": {"$in": ["lead_assigned", "lead_reassigned"]},
                f"read_by.{user_email}": {"$exists": False}
            }
        
        lead_notifications = await db.notification_history.find(
            lead_query,
            {
                "notification_id": 1,
                "notification_type": 1,
                "lead_id": 1,
                "lead_name": 1,
                "lead_email": 1,
                "category": 1,
                "source": 1,
                "created_at": 1,
                "visible_to_users": 1,
                "original_data": 1
            }
        ).sort("created_at", -1).to_list(None)
        
        for lead_notif in lead_notifications:
            original_data = lead_notif.get("original_data", {})
            visible_to_users = lead_notif.get("visible_to_users", [])
            is_reassignment = lead_notif.get("notification_type") == "lead_reassigned"
            
            if user_role == "admin" and user_email not in visible_to_users:
                assigned_user = visible_to_users[0] if visible_to_users else "Unknown"
                message = f"Lead '{lead_notif.get('lead_name')}' {'reassigned' if is_reassignment else 'assigned'} to {assigned_user}"
            else:
                message = f"Lead '{lead_notif.get('lead_name')}' has been {'reassigned to' if is_reassignment else 'assigned to'} you"
            
            all_notifications.append({
                "id": f"lead_{lead_notif['notification_id']}",
                "type": lead_notif.get("notification_type", "lead_assigned"),
                "title": "Lead Reassigned" if is_reassignment else "New Lead Assigned",
                "message": message,
                "lead_id": lead_notif.get("lead_id"),
                "lead_name": lead_notif.get("lead_name"),
                "timestamp": lead_notif.get("created_at") or datetime.utcnow(),
                "read": False,
                "priority": "high",
                "metadata": {
                    "lead_email": lead_notif.get("lead_email"),
                    "lead_phone": original_data.get("lead_phone"),
                    "category": lead_notif.get("category"),
                    "source": lead_notif.get("source"),
                    "reassigned": is_reassignment,
                    "reassigned_from": original_data.get("reassigned_from"),
                    "assigned_users": visible_to_users if user_role == "admin" else None
                }
            })
    
    # ========== Sort and Paginate ==========
    all_notifications.sort(key=lambda x: x.get("timestamp") or datetime.min, reverse=True)
    
    total_count = len(all_notifications)
    total_pages = (total_count + limit - 1) // limit
    
    skip = (page - 1) * limit
    paginated_notifications = all_notifications[skip:skip + limit]
    
    unread_count = len(paginated_notifications)
    
    notification_counts = {
        "whatsapp": len([n for n in all_notifications if n["type"] == "whatsapp_unread"]),
        "task": len([n for n in all_notifications if n["type"] == "task_assigned"]),
        "lead": len([n for n in all_notifications if n["type"] in ["lead_assigned", "lead_reassigned"]]),
        "total": total_count
    }
    
    pagination_response = {
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1
    }
    
    response = {
        "success": True,
        "notifications": paginated_notifications,
        "pagination": pagination_response,
        "unread_count": unread_count,
        "notification_counts": notification_counts,
        "user_role": user_role,
        "user_email": user_email,
        "filters": {
            "type": notification_type or "all",
            "page": page,
            "limit": limit
        },
        "generated_at": datetime.utcnow().isoformat()
    }
    
    # Add mark_as_read info if action was performed
    if mark_as_read_request and mark_as_read_request.mark_as_read:
        response["mark_as_read_result"] = {
            "marked_count": marked_count,
            "requested_count": len(mark_as_read_request.notification_ids) if mark_as_read_request.notification_ids else 0,
            "marked_at": datetime.utcnow().isoformat()
        }
    
    return response


# ============================================================================
# GET ENDPOINT - Read-only (just fetch)
# ============================================================================

@router.get("/unified")
async def get_unified_notifications_readonly(
    notification_type: Optional[str] = Query(None, description="Filter: whatsapp|task|lead|all"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    🔄 GET /unified - Fetch notifications (read-only)
    Use this to just VIEW notifications without marking as read
    """
    try:
        logger.info(f"📥 GET /notifications/unified - User: {current_user.get('email')}")
        
        from bson import ObjectId
        db = get_database()
        
        user_email = current_user.get("email")
        user_role = current_user.get("role")
        user_id = current_user.get("_id")
        
        # Call shared logic WITHOUT mark_as_read
        response = await _fetch_unified_notifications(
            db=db,
            user_email=user_email,
            user_role=user_role,
            user_id=user_id,
            notification_type=notification_type,
            page=page,
            limit=limit,
            mark_as_read_request=None  # ✅ No marking as read
        )
        
        logger.info(f"✅ GET returned {len(response['notifications'])} notifications")
        return response
        
    except Exception as e:
        logger.error(f"❌ Error in GET /unified: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to get notifications: {str(e)}")


# ============================================================================
# POST ENDPOINT - With optional mark as read
# ============================================================================

@router.post("/unified")
async def post_unified_notifications_with_actions(
    request: UnifiedNotificationsRequest = None,
    notification_type: Optional[str] = Query(None, description="Filter: whatsapp|task|lead|all"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    🔄 POST /unified - Fetch notifications AND optionally mark as read
    
    POST body (optional):
    {
        "notification_ids": ["task_uuid...", "lead_uuid..."],
        "mark_as_read": true
    }
    
    Use cases:
    - POST without body: Same as GET (just fetch)
    - POST with mark_as_read=true: Fetch + mark specified notifications as read
    """
    try:
        logger.info(f"📬 POST /notifications/unified - User: {current_user.get('email')}")
        
        from bson import ObjectId
        db = get_database()
        
        user_email = current_user.get("email")
        user_role = current_user.get("role")
        user_id = current_user.get("_id")
        
        # Call shared logic WITH mark_as_read option
        response = await _fetch_unified_notifications(
            db=db,
            user_email=user_email,
            user_role=user_role,
            user_id=user_id,
            notification_type=notification_type,
            page=page,
            limit=limit,
            mark_as_read_request=request  # ✅ Can mark as read if requested
        )
        
        if request and request.mark_as_read:
            logger.info(f"✅ POST completed with mark_as_read: {response.get('mark_as_read_result', {}).get('marked_count', 0)} marked")
        else:
            logger.info(f"✅ POST returned {len(response['notifications'])} notifications (no mark_as_read)")
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Error in POST /unified: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to process notifications: {str(e)}")
@router.get("/whatsapp/unread-status", response_model=BulkUnreadStatusResponse)
@convert_notification_dates() 
async def get_whatsapp_unread_status(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    🆕 Get unread WhatsApp status for all leads user can access
    Used for initial page load to set all WhatsApp icon states
    Returns leads that have unread messages (green icons)
    """
    try:
        db = get_database()
        
        user_role = current_user.get("role", "user")
        user_email = current_user.get("email", "")
        
        # Build query based on user permissions
        if user_role == "admin":
            # Admin sees all leads with WhatsApp activity
            query = {"whatsapp_has_unread": True}
        else:
            # Regular user sees only assigned leads
            query = {
                "$or": [
                    {"assigned_to": user_email},
                    {"co_assignees": user_email}
                ],
                "whatsapp_has_unread": True
            }
        
        # Get leads with unread messages
        unread_leads = await db.leads.find(
            query,
            {
                "lead_id": 1, 
                "name": 1, 
                "unread_whatsapp_count": 1,
                "last_whatsapp_activity": 1
            }
        ).to_list(None)
        
        # Format response
        unread_details = []
        total_unread_messages = 0
        
        
        for lead in unread_leads:
            lead_unread_count = lead.get("unread_whatsapp_count", 0)
            total_unread_messages += lead_unread_count
            
            # Convert last_whatsapp_activity from UTC to IST
            last_activity_utc = lead.get("last_whatsapp_activity")
            last_activity_ist = None
            if last_activity_utc:
                last_activity_ist = TimezoneHandler.utc_to_ist(last_activity_utc)
            
            unread_details.append(UnreadStatusSummary(
                lead_id=lead["lead_id"],
                lead_name=lead.get("name"),
                unread_count=lead_unread_count,
                last_activity=last_activity_ist  # ← Now IST
            ))
        
        return BulkUnreadStatusResponse(
            success=True,
            unread_leads=[lead["lead_id"] for lead in unread_leads],
            unread_details=unread_details,
            total_unread_leads=len(unread_leads),
            total_unread_messages=total_unread_messages,
            user_role=user_role
        )
        
    except Exception as e:
        logger.error(f"Error getting unread status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get unread status: {str(e)}")

@router.get("/whatsapp/{lead_id}/unread-status", response_model=LeadUnreadStatusResponse)
async def get_lead_whatsapp_unread_status(
    lead_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    🆕 Get unread WhatsApp status for a specific lead
    Returns whether the lead has unread messages (green/grey icon state)
    """
    try:
        # Check lead access permissions
        from ..services.whatsapp_message_service import whatsapp_message_service
        await whatsapp_message_service._check_lead_access(lead_id, current_user)
        
        db = get_database()
        
        # Get lead with unread status
        lead = await db.leads.find_one(
            {"lead_id": lead_id},
            {
                "name": 1,
                "whatsapp_has_unread": 1, 
                "unread_whatsapp_count": 1,
                "last_whatsapp_activity": 1
            }
        )
        
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        has_unread = lead.get("whatsapp_has_unread", False)
        unread_count = lead.get("unread_whatsapp_count", 0)
        
        return LeadUnreadStatusResponse(
            success=True,
            lead_id=lead_id,
            lead_name=lead.get("name"),
            has_unread=has_unread,
            unread_count=unread_count,
            icon_state="green" if has_unread else "grey",
            last_activity=lead.get("last_whatsapp_activity")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting lead unread status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get lead unread status: {str(e)}")

# ============================================================================
# WHATSAPP MARK-AS-READ ENDPOINTS
# ============================================================================

@router.post("/whatsapp/{lead_id}/mark-read", response_model=MarkLeadAsReadResponse)
async def mark_whatsapp_lead_as_read(
    lead_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    🆕 Mark entire WhatsApp conversation as read for a lead
    Used when user clicks WhatsApp icon or opens chat modal
    Icon changes from green to grey, broadcasts real-time update
    """
    try:
        # Use WhatsApp message service to mark as read
        from ..services.whatsapp_message_service import whatsapp_message_service
        
        result = await whatsapp_message_service.mark_lead_as_read(
            lead_id=lead_id,
            current_user=current_user
        )
        
        return MarkLeadAsReadResponse(
            success=True,
            lead_id=lead_id,
            marked_messages=result.get("marked_messages", 0),
            icon_state="grey",
            message="WhatsApp conversation marked as read successfully"
        )
        
    except Exception as e:
        logger.error(f"Error marking WhatsApp lead as read: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to mark lead as read: {str(e)}")

@router.post("/whatsapp/bulk-mark-read", response_model=BulkMarkReadResponse)
async def bulk_mark_whatsapp_leads_as_read(
    request: BulkMarkReadRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    🆕 Mark multiple WhatsApp conversations as read
    Useful for "mark all as read" functionality
    """
    try:
        from ..services.whatsapp_message_service import whatsapp_message_service
        
        results = []
        processed_leads = 0
        failed_leads = 0
        total_messages_marked = 0
        
        for lead_id in request.lead_ids:
            try:
                # Mark individual lead as read
                result = await whatsapp_message_service.mark_lead_as_read(
                    lead_id=lead_id,
                    current_user=current_user
                )
                
                marked_count = result.get("marked_messages", 0)
                total_messages_marked += marked_count
                processed_leads += 1
                
                results.append({
                    "lead_id": lead_id,
                    "success": True,
                    "messages_marked": marked_count
                })
                
            except Exception as e:
                failed_leads += 1
                results.append({
                    "lead_id": lead_id,
                    "success": False,
                    "error": str(e)
                })
                logger.warning(f"Failed to mark lead {lead_id} as read: {str(e)}")
        
        return BulkMarkReadResponse(
            success=failed_leads == 0,  # Success if no failures
            processed_leads=processed_leads,
            failed_leads=failed_leads,
            results=results,
            total_messages_marked=total_messages_marked
        )
        
    except Exception as e:
        logger.error(f"Error in bulk mark as read: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to bulk mark as read: {str(e)}")

# ============================================================================
# WHATSAPP NOTIFICATION ANALYTICS
# ============================================================================

@router.get("/whatsapp/analytics")
@convert_notification_dates()
async def get_whatsapp_notification_analytics(
    days: int = Query(default=7, ge=1, le=30, description="Number of days to analyze"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    🆕 Get WhatsApp notification analytics
    Shows patterns of unread messages, response times, etc.
    """
    try:
        db = get_database()
        
        user_role = current_user.get("role", "user")
        user_email = current_user.get("email", "")
        
        # Date range for analysis
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Build base query for user permissions
        if user_role == "admin":
            base_filter = {}
            lead_filter = {}
        else:
            base_filter = {
                "$or": [
                    {"lead_id": {"$in": await _get_user_lead_ids(user_email, db)}},
                ]
            }
            lead_filter = {
                "$or": [
                    {"assigned_to": user_email},
                    {"co_assignees": user_email}
                ]
            }
        
        # Analytics queries
        analytics = {}
        
        # 1. Message volume by day
        daily_pipeline = [
            {
                "$match": {
                    **base_filter,
                    "timestamp": {"$gte": start_date, "$lte": end_date}
                }
            },
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$timestamp"
                        }
                    },
                    "incoming": {
                        "$sum": {"$cond": [{"$eq": ["$direction", "incoming"]}, 1, 0]}
                    },
                    "outgoing": {
                        "$sum": {"$cond": [{"$eq": ["$direction", "outgoing"]}, 1, 0]}
                    }
                }
            },
            {"$sort": {"_id": 1}}
        ]
        
        daily_messages = await db.whatsapp_messages.aggregate(daily_pipeline).to_list(None)
        analytics["daily_message_volume"] = daily_messages
        
        # 2. Current unread statistics
        total_unread = await db.whatsapp_messages.count_documents({
            **base_filter,
            "direction": "incoming",
            "is_read": False
        })
        
        leads_with_unread = await db.leads.count_documents({
            **lead_filter,
            "whatsapp_has_unread": True
        })
        
        analytics["current_unread"] = {
            "total_unread_messages": total_unread,
            "leads_with_unread": leads_with_unread
        }
        
        # 3. Response time analysis (average time to respond to incoming messages)
        # This is a simplified version - could be more sophisticated
        recent_conversations = await db.leads.find(
            {
                **lead_filter,
                "last_whatsapp_activity": {"$gte": start_date}
            },
            {"lead_id": 1, "last_whatsapp_activity": 1}
        ).limit(20).to_list(None)
        
        analytics["active_conversations"] = len(recent_conversations)
        
        # 4. Most active leads (by message count)
        active_leads_pipeline = [
            {
                "$match": {
                    **base_filter,
                    "timestamp": {"$gte": start_date}
                }
            },
            {
                "$group": {
                    "_id": "$lead_id",
                    "message_count": {"$sum": 1},
                    "last_message": {"$max": "$timestamp"}
                }
            },
            {"$sort": {"message_count": -1}},
            {"$limit": 10}
        ]
        
        active_leads = await db.whatsapp_messages.aggregate(active_leads_pipeline).to_list(None)
        
        # Enrich with lead names
        for lead_data in active_leads:
            lead = await db.leads.find_one(
                {"lead_id": lead_data["_id"]},
                {"name": 1}
            )
            lead_data["lead_name"] = lead.get("name", "Unknown") if lead else "Unknown"
        
        analytics["most_active_leads"] = active_leads
        
        return {
            "success": True,
            "analytics": analytics,
            "period": {
                "days": days,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "user_role": user_role,
            "generated_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting WhatsApp analytics: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get analytics: {str(e)}")

async def _get_user_lead_ids(user_email: str, db) -> List[str]:
    """Helper function to get lead IDs accessible by user"""
    try:
        user_leads = await db.leads.find(
            {
                "$or": [
                    {"assigned_to": user_email},
                    {"co_assignees": user_email}
                ]
            },
            {"lead_id": 1}
        ).to_list(None)
        
        return [lead["lead_id"] for lead in user_leads]
        
    except Exception as e:
        logger.error(f"Error getting user lead IDs: {str(e)}")
        return []

# ============================================================================
# NOTIFICATION PREFERENCES (FUTURE ENHANCEMENT)
# ============================================================================

@router.get("/preferences")
async def get_notification_preferences(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    🆕 Get user's notification preferences
    Future enhancement for customizable notifications
    """
    try:
        # For now, return default preferences
        # In future, this could be stored in user profile
        default_preferences = {
            "whatsapp_notifications": True,
            "email_notifications": False,
            "sound_notifications": True,
            "browser_notifications": True,
            "notification_frequency": "instant",  # instant, batched, daily_digest
            "quiet_hours": {
                "enabled": False,
                "start_time": "22:00",
                "end_time": "08:00"
            }
        }
        
        return {
            "success": True,
            "user_email": current_user.get("email"),
            "preferences": default_preferences,
            "last_updated": None,
            "message": "Default preferences (feature in development)"
        }
        
    except Exception as e:
        logger.error(f"Error getting notification preferences: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get preferences: {str(e)}")

@router.put("/preferences")
async def update_notification_preferences(
    preferences: Dict[str, Any],
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    🆕 Update user's notification preferences
    Future enhancement for customizable notifications
    """
    try:
        # For now, just return acknowledgment
        # In future, this would update user profile in database
        
        return {
            "success": True,
            "user_email": current_user.get("email"),
            "updated_preferences": preferences,
            "updated_at": datetime.utcnow().isoformat(),
            "message": "Preferences update feature in development"
        }
        
    except Exception as e:
        logger.error(f"Error updating notification preferences: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update preferences: {str(e)}")

# ============================================================================
# ADMIN NOTIFICATION MANAGEMENT
# ============================================================================

@router.get("/admin/overview")
async def get_admin_notification_overview(
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    🆕 Get comprehensive notification overview for admins
    Shows system-wide notification statistics and health
    """
    try:
        db = get_database()
        
        # Real-time connection stats
        realtime_stats = realtime_manager.get_connection_stats()
        
        # Database notification stats
        total_unread = await db.whatsapp_messages.count_documents({
            "direction": "incoming",
            "is_read": False
        })
        
        total_leads_with_unread = await db.leads.count_documents({
            "whatsapp_has_unread": True
        })
        
        # Recent activity (last 24 hours)
        yesterday = datetime.utcnow() - timedelta(days=1)
        recent_messages = await db.whatsapp_messages.count_documents({
            "timestamp": {"$gte": yesterday}
        })
        
        # User activity breakdown
        user_activity_pipeline = [
            {
                "$match": {
                    "whatsapp_has_unread": True
                }
            },
            {
                "$group": {
                    "_id": "$assigned_to",
                    "unread_leads": {"$sum": 1}
                }
            },
            {"$sort": {"unread_leads": -1}},
            {"$limit": 10}
        ]
        
        user_activity = await db.leads.aggregate(user_activity_pipeline).to_list(None)
        
        # System health indicators
        health_indicators = {
            "realtime_connections_healthy": realtime_stats.get("total_connections", 0) > 0,
            "database_responsive": True,  # If we got here, DB is working
            "notification_backlog_normal": total_unread < 100,  # Configurable threshold
            "recent_activity_normal": recent_messages > 0
        }
        
        overall_health = "healthy" if all(health_indicators.values()) else "warning"
        
        return {
            "success": True,
            "overview": {
                "system_health": overall_health,
                "health_indicators": health_indicators,
                "notification_stats": {
                    "total_unread_messages": total_unread,
                    "leads_with_unread": total_leads_with_unread,
                    "recent_messages_24h": recent_messages
                },
                "realtime_stats": realtime_stats,
                "user_activity": user_activity
            },
            "generated_at": datetime.utcnow().isoformat(),
            "generated_by": current_user.get("email")
        }
        
    except Exception as e:
        logger.error(f"Error getting admin notification overview: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get admin overview: {str(e)}")

@router.post("/admin/reset-unread/{lead_id}")
async def admin_reset_lead_unread_status(
    lead_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    🆕 Admin endpoint to reset unread status for a lead
    Useful for fixing inconsistent notification states
    """
    try:
        db = get_database()
        
        # Reset lead's unread status
        await db.leads.update_one(
            {"lead_id": lead_id},
            {
                "$set": {
                    "whatsapp_has_unread": False,
                    "unread_whatsapp_count": 0
                }
            }
        )
        
        # Mark all messages as read
        mark_result = await db.whatsapp_messages.update_many(
            {
                "lead_id": lead_id,
                "direction": "incoming",
                "is_read": False
            },
            {
                "$set": {
                    "is_read": True,
                    "read_at": datetime.utcnow(),
                    "read_by_user_id": "admin_reset",
                    "admin_reset": True
                }
            }
        )
        
        # Update real-time manager for all users
        for user_email in realtime_manager.user_unread_leads:
            realtime_manager.user_unread_leads[user_email].discard(lead_id)
            
            # Send real-time update
            await realtime_manager.mark_lead_as_read(user_email, lead_id)
        
        return {
            "success": True,
            "lead_id": lead_id,
            "messages_marked_read": mark_result.modified_count,
            "reset_by": current_user.get("email"),
            "reset_at": datetime.utcnow().isoformat(),
            "message": "Lead unread status reset successfully"
        }
        
    except Exception as e:
        logger.error(f"Error resetting lead unread status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to reset unread status: {str(e)}")

@router.post("/admin/system-maintenance")
async def trigger_system_maintenance(
    maintenance_type: str = "cleanup",
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    🆕 Admin endpoint for system maintenance operations
    Supports different maintenance operations for notification system
    """
    try:
        maintenance_results = {}
        
        if maintenance_type == "cleanup" or maintenance_type == "all":
            # Cleanup stale real-time connections
            stats_before = realtime_manager.get_connection_stats()
            await realtime_manager._cleanup_stale_connections()
            stats_after = realtime_manager.get_connection_stats()
            
            maintenance_results["connection_cleanup"] = {
                "connections_before": stats_before.get("total_connections", 0),
                "connections_after": stats_after.get("total_connections", 0),
                "cleaned_up": stats_before.get("total_connections", 0) - stats_after.get("total_connections", 0)
            }
        
        if maintenance_type == "sync" or maintenance_type == "all":
            # Sync unread status from database for all connected users
            sync_count = 0
            for user_email in realtime_manager.user_connections.keys():
                await realtime_manager._load_user_unread_leads(user_email)
                sync_count += 1
            
            maintenance_results["unread_sync"] = {
                "users_synced": sync_count
            }
        
        if maintenance_type == "health_check" or maintenance_type == "all":
            # Perform comprehensive health check
            db = get_database()
            
            # Check for inconsistent unread counts
            inconsistent_leads = await db.leads.aggregate([
                {
                    "$lookup": {
                        "from": "whatsapp_messages",
                        "let": {"lead_id": "$lead_id"},
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {"$eq": ["$lead_id", "$lead_id"]},
                                    "direction": "incoming",
                                    "is_read": False
                                }
                            },
                            {"$count": "actual_unread"}
                        ],
                        "as": "actual_unread_data"
                    }
                },
                {
                    "$addFields": {
                        "actual_unread": {
                            "$ifNull": [{"$arrayElemAt": ["$actual_unread_data.actual_unread", 0]}, 0]
                        }
                    }
                },
                {
                    "$match": {
                        "$expr": {
                            "$ne": ["$unread_whatsapp_count", "$actual_unread"]
                        }
                    }
                },
                {"$limit": 10}
            ]).to_list(None)
            
            maintenance_results["health_check"] = {
                "inconsistent_leads_found": len(inconsistent_leads),
                "sample_inconsistent_leads": [lead["lead_id"] for lead in inconsistent_leads[:5]]
            }
        
        return {
            "success": True,
            "maintenance_type": maintenance_type,
            "results": maintenance_results,
            "triggered_by": current_user.get("email"),
            "completed_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error during system maintenance: {str(e)}")
        raise HTTPException(status_code=500, detail=f"System maintenance failed: {str(e)}")

# ============================================================================
# NOTIFICATION TESTING ENDPOINTS
# ============================================================================

@router.get("/history")
@convert_notification_dates()
async def get_notification_history(
    limit: int = Query(default=10, ge=1, le=100, description="Number of notifications per page"),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),  # ✅ Changed from offset to page
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    notification_type: Optional[str] = Query(None, description="Filter by notification type"),
    search: Optional[str] = Query(None, description="Search by lead name"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
   
    try:
        db = get_database()
        user_email = current_user.get("email", "")
        logger.info(f"📧 Getting notification history for {user_email} - Page: {page}, Limit: {limit}")
        
        # Build query filters
        query = {}

        # Only filter by user_email for non-admin users
        if current_user.get("role") != "admin":
            query["user_email"] = user_email
            logger.info(f"🔒 User access - filtering by user_email: {user_email}")
        else:
            logger.info(f"👑 Admin access - showing all notifications")
        query["read_at"] = {"$ne": None}  # 🔥 FILTER: Only show read notifications
        logger.info(f"📖 History filter: Only showing read notifications")
        # Date range filter
        if date_from or date_to:
            date_filter = {}
            
            if date_from:
                try:
                    start_date = datetime.fromisoformat(date_from)
                    date_filter["$gte"] = start_date
                    logger.info(f"📅 Date filter from: {start_date}")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid date_from format. Use YYYY-MM-DD")
            
            if date_to:
                try:
                    # Add 23:59:59 to include the entire day
                    end_date = datetime.fromisoformat(date_to).replace(hour=23, minute=59, second=59)
                    date_filter["$lte"] = end_date
                    logger.info(f"📅 Date filter to: {end_date}")
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid date_to format. Use YYYY-MM-DD")
            
            query["created_at"] = date_filter
        
        # Notification type filter
        if notification_type:
            query["notification_type"] = notification_type
            logger.info(f"🔔 Filtering by type: {notification_type}")
        
        # Search by lead name filter (case-insensitive)
        if search:
            query["lead_name"] = {"$regex": search, "$options": "i"}
            logger.info(f"🔍 Searching for: {search}")
        
        logger.info(f"🔍 Final query: {query}")
        
        # Get total count for pagination
        total_count = await db.notification_history.count_documents(query)
        logger.info(f"📊 Total notifications found: {total_count}")
        
        # ✅ Calculate pagination using page-based system (Universal Pattern)
        skip = (page - 1) * limit
        total_pages = (total_count + limit - 1) // limit  # Ceiling division
        
        logger.info(f"📄 Pagination - Skip: {skip}, Total Pages: {total_pages}")
        
        # Get notifications with pagination
        notifications = await db.notification_history.find(
            query,
            {
                "notification_id": 1,
                "notification_type": 1,
                "lead_id": 1,
                "lead_name": 1,
                "message_preview": 1,
                "message_id": 1,
                "direction": 1,
                "created_at": 1,
                "read_at": 1,
                "_id": 0  # Exclude MongoDB _id
            }
        ).sort("created_at", -1).skip(skip).limit(limit).to_list(None)
        
        logger.info(f"📋 Retrieved {len(notifications)} notifications")
        
        # Format notifications for response
        formatted_notifications = []
        for notif in notifications:
            formatted_notifications.append({
                "id": notif["notification_id"],
                "type": notif["notification_type"],
                "lead_id": notif.get("lead_id"),
                "lead_name": notif.get("lead_name", "Unknown Lead"),
                "message": notif.get("message_preview", ""),
                "message_id": notif.get("message_id"),
                "direction": notif.get("direction"),
                "timestamp": notif["created_at"],
                "read": notif.get("read_at") is not None,
                "read_at": notif["read_at"].isoformat() if notif.get("read_at") else None
            })
        
        # ✅ UNIVERSAL PAGINATION PATTERN (Matches PaginationMeta interface)
        pagination_response = {
            "total": total_count,           # Total records
            "page": page,                   # Current page (1-based)
            "limit": limit,                 # Items per page
            "pages": total_pages,           # Total pages (consistent naming)
            "has_next": page < total_pages, # Boolean: more pages available
            "has_prev": page > 1            # Boolean: previous pages available
        }
        
        logger.info(f"✅ Returning {len(formatted_notifications)} notifications with pagination: {pagination_response}")
        
        return {
            "success": True,
            "notifications": formatted_notifications,
            "pagination": pagination_response,  # ✅ Universal pagination structure
            "filters": {
                "page": page,               # Include current page in filters
                "limit": limit,             # Include current limit in filters
                "date_from": date_from,
                "date_to": date_to,
                "notification_type": notification_type,
                "search": search
            },
            "summary": {
                "total_notifications": total_count,
                "current_page_count": len(formatted_notifications),
                "filtered": bool(date_from or date_to or notification_type or search),
                "user_email": user_email
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting notification history: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get notification history: {str(e)}")

# ============================================================================
# WEBHOOK INTEGRATION STATUS
# ============================================================================

@router.get("/webhook/status")
@convert_notification_dates()
async def get_webhook_integration_status(
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    🆕 Get WhatsApp webhook integration status
    Admin endpoint to check if webhooks are working properly
    """
    try:
        db = get_database()
        
        # Check recent webhook activity
        last_hour = datetime.utcnow() - timedelta(hours=1)
        last_24_hours = datetime.utcnow() - timedelta(days=1)
        
        recent_incoming = await db.whatsapp_messages.count_documents({
            "direction": "incoming",
            "timestamp": {"$gte": last_hour}
        })
        
        daily_incoming = await db.whatsapp_messages.count_documents({
            "direction": "incoming", 
            "timestamp": {"$gte": last_24_hours}
        })
        
        # Get last incoming message
        last_message = await db.whatsapp_messages.find_one(
            {"direction": "incoming"},
            sort=[("timestamp", -1)]
        )
        
        # Webhook health assessment
        webhook_health = "healthy"
        health_message = "Webhooks functioning normally"
        
        if not last_message:
            webhook_health = "no_data"
            health_message = "No incoming messages found"
        elif last_message["timestamp"] < datetime.utcnow() - timedelta(hours=24):
            webhook_health = "stale"
            health_message = "No recent incoming messages (>24h)"
        elif recent_incoming == 0 and daily_incoming < 5:
            webhook_health = "low_activity"
            health_message = "Very low incoming message activity"
        
        return {
            "success": True,
            "webhook_status": {
                "health": webhook_health,
                "message": health_message,
                "last_incoming_message": last_message["timestamp"].isoformat() if last_message else None,
                "activity": {
                    "last_hour": recent_incoming,
                    "last_24_hours": daily_incoming
                }
            },
            "realtime_integration": {
                "active_connections": realtime_manager.get_connection_stats().get("total_connections", 0),
                "notification_broadcasting": "enabled"
            },
            "checked_at": datetime.utcnow().isoformat(),
            "checked_by": current_user.get("email")
        }
        
    except Exception as e:
        logger.error(f"Error checking webhook status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to check webhook status: {str(e)}")