# app/services/email_service.py
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from bson import ObjectId
import logging
import asyncio

from ..config.database import get_database
from app.services.communication_service import CommunicationService
from ..config.settings import settings
from ..models.email import (
    EmailRequest, BulkEmailRequest, EmailResponse, 
    EmailDocument, EmailRecipient, EmailHistoryItem,
    ScheduledEmailItem, EmailStats
)
from ..services.zepto_client import zepto_client
from ..utils.dependencies import get_current_active_user

logger = logging.getLogger(__name__)

class EmailService:
    """Main email service handling all email operations"""
    
    def __init__(self):
        self.db = get_database()
        self.zepto_client = zepto_client
        # Use separate collection for FastAPI emails
        self.collection_name = "crm_lead_emails"  # Different from old "scheduledemails"
    
    # ========================================================================
    # EMAIL ID GENERATION (Following your lead_id pattern)
    # ========================================================================
    
    async def generate_email_id(self) -> str:
        """Generate next EMAIL-XXXX ID (following your LD-XXXX pattern)"""
        try:
            # Find highest existing email ID in our collection
            last_email = await self.db[self.collection_name].find_one(
                {}, 
                sort=[("email_id", -1)]
            )
            
            if last_email and "email_id" in last_email:
                # Extract number from EMAIL-1000 format
                last_number = int(last_email["email_id"].split("-")[1])
                next_number = last_number + 1
            else:
                next_number = 1000  # Start from EMAIL-1000 (like your LD-1000)
            
            return f"EMAIL-{next_number}"
            
        except Exception as e:
            logger.error(f"Error generating email ID: {e}")
            # Fallback to timestamp-based ID
            timestamp = int(datetime.utcnow().timestamp())
            return f"EMAIL-{timestamp}"
    
    # ========================================================================
    # SINGLE LEAD EMAIL
    # ========================================================================
    
    async def send_single_lead_email(
        self, 
        lead_id: str, 
        email_request: EmailRequest,
        current_user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send email to a single lead"""
        try:
            logger.info(f"Sending email to lead {lead_id} using template {email_request.template_key}")
            
            # Get lead data
            lead = await self.db.leads.find_one({"lead_id": lead_id})
            if not lead:
                return {
                    "success": False,
                    "error": f"Lead {lead_id} not found"
                }
            
            # Check permission (following your CRM pattern)
            user_role = current_user.get("role")
            if user_role != "admin":
                assigned_to = lead.get("assigned_to")
                current_user_email = current_user.get("email")
                
                if assigned_to != current_user_email:
                    return {
                        "success": False,
                        "error": "You can only send emails to leads assigned to you"
                    }
            
            # Generate email ID
            email_id = await self.generate_email_id()
            
            # Prepare recipient
            recipient = EmailRecipient(
                email=lead["email"],
                name=lead["name"],
                lead_id=lead_id,
                status="pending"
            )
            
            # Format sender email
            sender_email = self.zepto_client.format_sender_email(email_request.sender_email_prefix)
            
            # Create email document (following your CRM document pattern)
            email_doc = EmailDocument(
                email_id=email_id,
                lead_id=lead_id,
                email_type="single",
                template_key=email_request.template_key,
                sender_email=sender_email,
                recipients=[recipient],
                status="pending",
                is_scheduled=bool(email_request.scheduled_time),
                scheduled_time=email_request.scheduled_time,
                total_recipients=1,
                created_by=str(current_user.get("_id") or current_user.get("id")),
                created_by_name=f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip()
            )
            
            if email_request.scheduled_time:
                # Schedule email for later
                return await self._schedule_email(email_doc)
            else:
                # Send immediately
                return await self._send_email_immediately(email_doc)
                
        except Exception as e:
            logger.error(f"Error in send_single_lead_email: {e}")
            return {
                "success": False,
                "error": f"Failed to send email: {str(e)}"
            }
    
    # ========================================================================
    # BULK LEAD EMAIL
    # ========================================================================
    
    async def send_bulk_lead_email(
        self,
        bulk_request: BulkEmailRequest,
        current_user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send email to multiple leads (Users can send to assigned leads, Admins to any leads)"""
        try:
            logger.info(f"Sending bulk email to {len(bulk_request.lead_ids)} leads")
            
            # Get leads data with assignment info
            leads_cursor = self.db.leads.find(
                {"lead_id": {"$in": bulk_request.lead_ids}},
                {"lead_id": 1, "name": 1, "email": 1, "assigned_to": 1}
            )
            leads = await leads_cursor.to_list(None)
            
            if not leads:
                return {
                    "success": False,
                    "error": "No valid leads found for the provided IDs"
                }
            
            # Permission filtering (following your CRM pattern)
            user_role = current_user.get("role")
            current_user_email = current_user.get("email")
            
            if user_role != "admin":
                # Filter leads to only those assigned to current user
                allowed_leads = []
                denied_leads = []
                
                for lead in leads:
                    if lead.get("assigned_to") == current_user_email:
                        allowed_leads.append(lead)
                    else:
                        denied_leads.append(lead["lead_id"])
                
                if not allowed_leads:
                    return {
                        "success": False,
                        "error": "You can only send bulk emails to leads assigned to you. None of the selected leads are assigned to you."
                    }
                
                if denied_leads:
                    logger.warning(f"User {current_user_email} attempted to email unassigned leads: {denied_leads}")
                    # Continue with allowed leads, but inform user
                    leads = allowed_leads
                    logger.info(f"Bulk email filtered: {len(allowed_leads)} allowed, {len(denied_leads)} denied")
            
            # Continue with allowed leads only
            
            if not leads:
                return {
                    "success": False,
                    "error": "No valid leads found for the provided IDs"
                }
            
            # Generate email ID
            email_id = await self.generate_email_id()
            
            # Prepare recipients
            recipients = []
            for lead in leads:
                recipient = EmailRecipient(
                    email=lead["email"],
                    name=lead["name"],
                    lead_id=lead["lead_id"],
                    status="pending"
                )
                recipients.append(recipient)
            
            # Format sender email
            sender_email = self.zepto_client.format_sender_email(bulk_request.sender_email_prefix)
            
            # Create email document
            actual_lead_ids = [lead["lead_id"] for lead in leads]
            email_doc = EmailDocument(
                email_id=email_id,
                lead_ids=actual_lead_ids,  # Use actual filtered lead IDs
                email_type="bulk",
                template_key=bulk_request.template_key,
                sender_email=sender_email,
                recipients=recipients,
                status="pending",
                is_scheduled=bool(bulk_request.scheduled_time),
                scheduled_time=bulk_request.scheduled_time,
                total_recipients=len(recipients),
                created_by=str(current_user.get("_id") or current_user.get("id")),
                created_by_name=f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip()
            )
            
            # Send result with permission info
            send_result = None
            if bulk_request.scheduled_time:
                # Schedule bulk email
                send_result = await self._schedule_email(email_doc)
            else:
                # Send immediately
                send_result = await self._send_email_immediately(email_doc)
            
            # Add permission info to response
            if user_role != "admin" and len(leads) < len(bulk_request.lead_ids):
                denied_count = len(bulk_request.lead_ids) - len(leads)
                send_result["warning"] = f"Email sent to {len(leads)} leads. {denied_count} leads were skipped (not assigned to you)."
                send_result["total_requested"] = len(bulk_request.lead_ids)
                send_result["total_processed"] = len(leads)
                send_result["denied_count"] = denied_count
            
            return send_result
                
        except Exception as e:
            logger.error(f"Error in send_bulk_lead_email: {e}")
            return {
                "success": False,
                "error": f"Failed to send bulk email: {str(e)}"
            }
    
    # ========================================================================
    # EMAIL SENDING LOGIC
    # ========================================================================
    
    async def _send_email_immediately(self, email_doc: EmailDocument) -> Dict[str, Any]:
        """Send email immediately using ZeptoMail"""
        try:
            # Prepare clean document for database (matching your schema)
            email_dict = {
                "_id": ObjectId(),
                "email_id": email_doc.email_id,
                "lead_id": email_doc.lead_id,
                "lead_ids": email_doc.lead_ids,
                "email_type": email_doc.email_type,
                "template_key": email_doc.template_key,
                "template_name": email_doc.template_name,
                "sender_email": email_doc.sender_email,
                "recipients": [r.dict() for r in email_doc.recipients],
                "status": "pending",
                "is_scheduled": False,
                "scheduled_time": None,
                "sent_at": None,
                "cancelled_at": None,
                "total_recipients": email_doc.total_recipients,
                "sent_count": 0,
                "failed_count": 0,
                "error_message": None,
                "created_by": ObjectId(email_doc.created_by),
                "created_by_name": email_doc.created_by_name,
                "created_at": datetime.utcnow(),  # Store UTC
                "updated_at": datetime.utcnow()   # Store UTC
            }
            
            await self.db[self.collection_name].insert_one(email_dict)
            logger.info(f"Email document {email_doc.email_id} saved to database")
            
            if email_doc.email_type == "single":
                # Send single email
                result = await self._send_single_email_via_zepto(email_doc)
            else:
                # Send bulk emails
                result = await self._send_bulk_email_via_zepto(email_doc)
            
            # Update email document with results
            await self._update_email_status(email_doc.email_id, result)
            
            # Log activities for each lead (following your activity logging pattern)
            await self._log_email_activities(email_doc, result)
            
            return {
                "success": result.get("success", False),
                "email_id": email_doc.email_id,
                "message": result.get("message", "Email processing completed"),
                "total_recipients": email_doc.total_recipients,
                "sent_count": result.get("successful_count", 1 if result.get("success") else 0),
                "failed_count": result.get("failed_count", 0 if result.get("success") else 1),
                "scheduled": False,
                "created_at": email_doc.created_at,
                "details": result.get("data", {})  # Include ZeptoMail response
            }
            
        except Exception as e:
            logger.error(f"Error sending email immediately: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _schedule_email(self, email_doc: EmailDocument) -> Dict[str, Any]:
        """Schedule email for future sending with proper timezone handling"""
        try:
            # Validate schedule time
            if not email_doc.scheduled_time:
                return {
                    "success": False,
                    "error": "Scheduled time is required"
                }
            
            # TIMEZONE HANDLING: Frontend sends IST time, MongoDB stores UTC
            # Convert IST to UTC for storage (subtract 5.5 hours)
            from datetime import timezone, timedelta
            
            ist_offset = timedelta(hours=5, minutes=30)
            scheduled_ist = email_doc.scheduled_time
            
            # Convert IST to UTC for MongoDB storage
            scheduled_utc = scheduled_ist - ist_offset
            
            # Validate future time in UTC
            now_utc = datetime.utcnow()
            if scheduled_utc <= now_utc:
                return {
                    "success": False,
                    "error": f"Scheduled time must be in the future. IST: {scheduled_ist.strftime('%Y-%m-%d %H:%M:%S')}, UTC: {scheduled_utc.strftime('%Y-%m-%d %H:%M:%S')}, Current UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}"
                }
            
            logger.info(f"Timezone conversion: IST {scheduled_ist} → UTC {scheduled_utc}")
            
            # Prepare clean document for database (store UTC time)
            email_dict = {
                "_id": ObjectId(),
                "email_id": email_doc.email_id,
                "lead_id": email_doc.lead_id,
                "lead_ids": email_doc.lead_ids,
                "email_type": email_doc.email_type,
                "template_key": email_doc.template_key,
                "template_name": email_doc.template_name,
                "sender_email": email_doc.sender_email,
                "recipients": [r.dict() for r in email_doc.recipients],
                "status": "pending",
                "is_scheduled": True,
                "scheduled_time": scheduled_utc,  # Store UTC time in MongoDB
                "sent_at": None,
                "cancelled_at": None,
                "total_recipients": email_doc.total_recipients,
                "sent_count": 0,
                "failed_count": 0,
                "error_message": None,
                "created_by": ObjectId(email_doc.created_by),
                "created_by_name": email_doc.created_by_name,
                "created_at": datetime.utcnow(),  # Store UTC
                "updated_at": datetime.utcnow()   # Store UTC
            }
            
            await self.db[self.collection_name].insert_one(email_dict)
            logger.info(f"Email {email_doc.email_id} scheduled for UTC: {scheduled_utc} (original IST: {scheduled_ist})")
            
            # Log scheduling activities
            await self._log_scheduled_email_activities_at_schedule_time(email_doc)
            
            return {
                "success": True,
                "email_id": email_doc.email_id,
                "message": f"Email scheduled for {scheduled_ist.strftime('%Y-%m-%d %H:%M:%S')} IST",
                "total_recipients": email_doc.total_recipients,
                "scheduled": True,
                "scheduled_time": scheduled_utc,  # Return UTC for consistency with MongoDB
                "scheduled_time_ist": scheduled_ist,  # Also return IST for frontend display
                "created_at": datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error scheduling email: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _log_scheduled_email_activities_at_schedule_time(self, email_doc: EmailDocument):
        """Log activity when email is scheduled (before it's sent)"""
        try:
            activities = []
            
            if email_doc.email_type == "single":
                # Single lead scheduling activity
                lead_id = email_doc.lead_id
                if lead_id:
                    template_display = await self._get_template_display_name(email_doc.template_key)
                    
                    activity = {
                        "_id": ObjectId(),
                        "lead_id": lead_id,
                        "activity_type": "email_scheduled",
                        "description": f"Email scheduled using template '{template_display}' for {email_doc.scheduled_time.strftime('%Y-%m-%d %H:%M')} IST",
                        "metadata": {
                            "email_id": email_doc.email_id,
                            "template_key": email_doc.template_key,
                            "template_name": template_display,
                            "sender_email": email_doc.sender_email,
                            "scheduled_time": email_doc.scheduled_time,
                            "scheduled": True
                        },
                        "created_by": ObjectId(email_doc.created_by),
                        "created_by_name": email_doc.created_by_name,
                        "created_at": datetime.utcnow()
                    }
                    activities.append(activity)
            else:
                # Bulk email scheduling activities
                for lead_id in email_doc.lead_ids:
                    template_display = await self._get_template_display_name(email_doc.template_key)
                    
                    activity = {
                        "_id": ObjectId(),
                        "lead_id": lead_id,
                        "activity_type": "bulk_email_scheduled",
                        "description": f"Bulk email scheduled using template '{template_display}' for {email_doc.scheduled_time.strftime('%Y-%m-%d %H:%M')} IST",
                        "metadata": {
                            "email_id": email_doc.email_id,
                            "template_key": email_doc.template_key,
                            "template_name": template_display,
                            "sender_email": email_doc.sender_email,
                            "scheduled_time": email_doc.scheduled_time,
                            "total_recipients": email_doc.total_recipients,
                            "scheduled": True
                        },
                        "created_by": ObjectId(email_doc.created_by),
                        "created_by_name": email_doc.created_by_name,
                        "created_at": datetime.utcnow()
                    }
                    activities.append(activity)
            
            # Insert all activities
            if activities:
                await self.db.lead_activities.insert_many(activities)
                logger.info(f"Logged {len(activities)} email scheduling activities")
                
        except Exception as e:
            logger.error(f"Error logging email scheduling activities: {e}")
    async def _send_single_email_via_zepto(self, email_doc: EmailDocument) -> Dict[str, Any]:
        """Send single email via ZeptoMail"""
        recipient = email_doc.recipients[0]
        
        result = await self.zepto_client.send_template_email(
            template_key=email_doc.template_key,
            sender_email=email_doc.sender_email,
            recipient_email=recipient.email,
            recipient_name=recipient.name,
            merge_data={"username": recipient.name}
        )
        
        return {
            "success": result["success"],
            "successful_count": 1 if result["success"] else 0,
            "failed_count": 0 if result["success"] else 1,
            "message": "Email sent successfully" if result["success"] else f"Email failed: {result.get('error')}",
            "results": [result]
        }
    
    async def _send_bulk_email_via_zepto(self, email_doc: EmailDocument) -> Dict[str, Any]:
        """Send bulk emails via ZeptoMail"""
        recipients_data = []
        for recipient in email_doc.recipients:
            recipients_data.append({
                "email": recipient.email,
                "name": recipient.name,
                "merge_data": {"username": recipient.name}
            })
        
        return await self.zepto_client.send_bulk_template_email(
            template_key=email_doc.template_key,
            sender_email=email_doc.sender_email,
            recipients=recipients_data
        )
    
    # ========================================================================
    # DATABASE UPDATES
    # ========================================================================
    
    async def _update_email_status(self, email_id: str, send_result: Dict[str, Any]):
        """Update email status in database based on send results"""
        try:
            # Handle successful sends
            if send_result.get("success", False):
                update_data = {
                    "updated_at": datetime.utcnow(),
                    "sent_at": datetime.utcnow(),
                    "status": "sent",
                    "sent_count": send_result.get("successful_count", 1),
                    "failed_count": send_result.get("failed_count", 0)
                }
            else:
                # Handle failed sends
                update_data = {
                    "updated_at": datetime.utcnow(),
                    "status": "failed",
                    "sent_count": send_result.get("successful_count", 0),
                    "failed_count": send_result.get("failed_count", 1)
                }
                
                # Extract error message
                error_msg = "Unknown error"
                if "error" in send_result:
                    if isinstance(send_result["error"], dict):
                        error_msg = send_result["error"].get("message", str(send_result["error"]))
                    else:
                        error_msg = str(send_result["error"])
                elif "message" in send_result:
                    error_msg = send_result["message"]
                    
                update_data["error_message"] = error_msg
            
            # Update individual recipients status if available
            if "results" in send_result and send_result["results"]:
                try:
                    # Get current email document
                    email_doc = await self.db.lead_emails.find_one({"email_id": email_id})
                    if email_doc and "recipients" in email_doc:
                        updated_recipients = []
                        results = send_result["results"]
                        
                        for i, recipient in enumerate(email_doc["recipients"]):
                            # Update recipient status if we have result data
                            if i < len(results):
                                result = results[i]
                                recipient["status"] = result.get("status", "failed")
                                recipient["sent_at"] = result.get("sent_at", datetime.utcnow() if result.get("status") == "sent" else None)
                                recipient["error"] = result.get("error")
                            updated_recipients.append(recipient)
                        
                        update_data["recipients"] = updated_recipients
                except Exception as e:
                    logger.warning(f"Failed to update individual recipient status: {e}")
            
            # Update the email document
            await self.db[self.collection_name].update_one(
                {"email_id": email_id},
                {"$set": update_data}
            )
            
            logger.info(f"Email {email_id} status updated: {update_data['status']}")
            
        except Exception as e:
            logger.error(f"Error updating email status for {email_id}: {e}")
            # Don't raise the error - this shouldn't fail the main operation
    
    # ========================================================================
    # ACTIVITY LOGGING (Following your CRM pattern)
    # ========================================================================
    
    async def _log_email_activities(self, email_doc: EmailDocument, send_result: Dict[str, Any]):
            """Log email activities to lead_activities collection"""
            try:
                activities = []
                
                if email_doc.email_type == "single":
                    # Single lead activity
                    lead_id = email_doc.lead_id
                    recipient = email_doc.recipients[0]

                    # 🔥 REMOVE THIS CALL - it's causing the duplicate
                    # Update last_contacted if email was successful
                    # if send_result["success"]:
                    #     await CommunicationService.log_email_communication(
                    #         lead_id=lead_id,
                    #         email_subject=email_doc.template_key,
                    #         template_key=email_doc.template_key
                    #     )
                    
                    # Get template name instead of template key for better display
                    template_display = await self._get_template_display_name(email_doc.template_key)
                    
                    activity = {
                        "_id": ObjectId(),
                        "lead_id": lead_id,
                        "activity_type": "email_sent" if send_result["success"] else "email_failed",
                        "description": f"Email {'sent' if send_result['success'] else 'failed'} using template '{template_display}'",
                        "metadata": {
                            "email_id": email_doc.email_id,
                            "template_key": email_doc.template_key,
                            "template_name": template_display,  # Add template name for better display
                            "sender_email": email_doc.sender_email,
                            "recipient_email": recipient.email,
                            "scheduled": email_doc.is_scheduled,
                            "success": send_result["success"]
                        },
                        "created_by": ObjectId(email_doc.created_by),
                        "created_by_name": email_doc.created_by_name,
                        "created_at": datetime.utcnow()
                    }
                    activities.append(activity)
                    
                else:
                    # Bulk email activities (one per lead)
                    for lead_id in email_doc.lead_ids:
                        # 🔥 REMOVE THIS CALL - it's causing the duplicate
                        # if send_result["success"]:
                        #     await CommunicationService.log_email_communication(
                        #         lead_id=lead_id,
                        #         template_key=email_doc.template_key
                        #     )
                        
                        # Get template name for better display
                        template_display = await self._get_template_display_name(email_doc.template_key)
                        
                        activity = {
                            "_id": ObjectId(),
                            "lead_id": lead_id,
                            "activity_type": "bulk_email_sent",
                            "description": f"Included in bulk email campaign using template '{template_display}'",
                            "metadata": {
                                "email_id": email_doc.email_id,
                                "template_key": email_doc.template_key,
                                "template_name": template_display,  # Add template name
                                "sender_email": email_doc.sender_email,
                                "total_recipients": email_doc.total_recipients,
                                "bulk_campaign": True,
                                "success": send_result["success"]
                            },
                            "created_by": ObjectId(email_doc.created_by),
                            "created_by_name": email_doc.created_by_name,
                            "created_at": datetime.utcnow()
                        }
                        activities.append(activity)
                
                # Insert all activities
                if activities:
                    await self.db.lead_activities.insert_many(activities)
                    logger.info(f"Logged {len(activities)} email activities")
                    
            except Exception as e:
                logger.error(f"Error logging email activities: {e}")


    
    async def _log_scheduled_email_activities(self, email_doc: Dict[str, Any], results: list, success: bool):
            """Log email activities to lead_activities collection"""
            try:
                activities = []
                
                if email_doc.get("email_type") == "single":
                    # Single lead activity
                    lead_id = email_doc.get("lead_id")
                    if lead_id:
                        # 🔥 REMOVE THIS CALL - it's causing the duplicate
                        # if success:
                        #     await CommunicationService.log_email_communication(
                        #         lead_id=lead_id,
                        #         template_key=email_doc.get("template_key")
                        #     )
                        
                        # Get template name for better display
                        template_display = await self._get_template_display_name(email_doc.get("template_key"))
                        
                        activity = {
                            "_id": ObjectId(),
                            "lead_id": lead_id,
                            "activity_type": "scheduled_email_sent" if success else "scheduled_email_failed",
                            "description": f"Scheduled email {'sent' if success else 'failed'} using template '{template_display}'",
                            "metadata": {
                                "email_id": email_doc["email_id"],
                                "template_key": email_doc.get("template_key"),
                                "template_name": template_display,  # Add template name
                                "sender_email": email_doc.get("sender_email"),
                                "scheduled": True,
                                "success": success,
                                "recipients_count": len(results)
                            },
                            "created_by": email_doc.get("created_by"),
                            "created_by_name": email_doc.get("created_by_name"),
                            "created_at": datetime.utcnow()
                        }
                        activities.append(activity)
                else:
                    # Bulk email activities
                    lead_ids = email_doc.get("lead_ids", [])
                    for lead_id in lead_ids:
                        # 🔥 REMOVE THIS CALL - it's causing the duplicate
                        # if success:
                        #     await CommunicationService.log_email_communication(
                        #         lead_id=lead_id,
                        #         template_key=email_doc.get("template_key")
                        #     )
                        
                        # Get template name for better display
                        template_display = await self._get_template_display_name(email_doc.get("template_key"))
                        
                        activity = {
                            "_id": ObjectId(),
                            "lead_id": lead_id,
                            "activity_type": "scheduled_bulk_email_sent" if success else "scheduled_bulk_email_failed",
                            "description": f"Scheduled bulk email {'sent' if success else 'failed'} using template '{template_display}'",
                            "metadata": {
                                "email_id": email_doc["email_id"],
                                "template_key": email_doc.get("template_key"),
                                "template_name": template_display,  # Add template name
                                "sender_email": email_doc.get("sender_email"),
                                "total_recipients": email_doc.get("total_recipients"),
                                "scheduled": True,
                                "success": success
                            },
                            "created_by": email_doc.get("created_by"),
                            "created_by_name": email_doc.get("created_by_name"),
                            "created_at": datetime.utcnow()
                        }
                        activities.append(activity)

                # Insert all activities
                if activities:
                    await self.db.lead_activities.insert_many(activities)
                    logger.info(f"Logged {len(activities)} scheduled email activities")
                    
            except Exception as e:
                logger.error(f"Error logging scheduled email activities: {e}")

    async def _get_template_display_name(self, template_key: str) -> str:
        """Get human-readable template name from CMS using template key"""
        try:
            if not template_key:
                return "Unknown Template"
            
            # Fetch template from CMS to get the display name
            import aiohttp
            from app.config.settings import settings
            
            cms_url = f"{settings.cms_base_url}/{settings.email_templates_endpoint}"
            
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(cms_url) as response:
                        if response.status == 200:
                            cms_data = await response.json()
                            
                            # Find template with matching key
                            for template in cms_data.get("data", []):
                                if template.get("key") == template_key:
                                    return template.get("Template_Name", template_key)
                            
                            # If not found in CMS, return a cleaned version of the key
                            return self._clean_template_key(template_key)
                        else:
                            # CMS not available, clean the key
                            return self._clean_template_key(template_key)
                            
                except Exception as e:
                    logger.error(f"Error fetching template from CMS: {e}")
                    return self._clean_template_key(template_key)
                    
        except Exception as e:
            logger.error(f"Error getting template display name: {e}")
            return template_key or "Unknown Template"

    def _clean_template_key(self, template_key: str) -> str:
        """Clean template key for display when CMS is not available"""
        if not template_key:
            return "Unknown Template"
        
        # If it's a long cryptic key, just return "Email Template"
        if len(template_key) > 50:
            return "Email Template"
        
        # If it's a readable key, clean it up
        return template_key.replace("_", " ").replace("-", " ").title()

# Global email service instance - using lazy initialization
_email_service = None

def get_email_service() -> EmailService:
    """Get email service instance with lazy initialization"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service

# Helper function for easy import
email_service = get_email_service