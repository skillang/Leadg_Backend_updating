# app/services/realtime_service.py - SSE Connection Manager for Real-time WhatsApp Notifications

import asyncio
import json
import logging
import uuid
from typing import Dict, Set, List, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

class RealtimeNotificationManager:
    """
    Real-time notification manager using Server-Sent Events (SSE)
    Handles WhatsApp message notifications with zero polling
    """
    
    def __init__(self):
        # Track active SSE connections per user
        # Format: {user_email: Set[asyncio.Queue]}
        self.user_connections: Dict[str, Set[asyncio.Queue]] = defaultdict(set)
        
        # Track unread message states per user
        # Format: {user_email: Set[lead_id]}
        self.user_unread_leads: Dict[str, Set[str]] = defaultdict(set)
        
        # Connection metadata for debugging and monitoring
        # Format: {user_email: {connection_id: connection_info}}
        self.connection_metadata: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        
        # Background task for connection cleanup
        self._cleanup_task: Optional[asyncio.Task] = None
        self._start_cleanup_task()
    
    def _start_cleanup_task(self):
        """Start background task for cleaning up stale connections"""
        try:
            loop = asyncio.get_event_loop()
            self._cleanup_task = loop.create_task(self._periodic_cleanup())
        except RuntimeError:
            # No event loop running, cleanup will be done manually
            logger.warning("No event loop running, periodic cleanup disabled")
    
    async def _periodic_cleanup(self):
        """Periodically clean up stale connections (every 5 minutes)"""
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes
                await self._cleanup_stale_connections()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {str(e)}")
    
    async def _cleanup_stale_connections(self):
        """Remove connections that are no longer responsive"""
        try:
            stale_count = 0
            
            for user_email in list(self.user_connections.keys()):
                connections_to_remove = set()
                
                for queue in list(self.user_connections[user_email]):
                    try:
                        # Test if queue is still responsive
                        if queue.qsize() > 100:  # Queue too full, likely stale
                            connections_to_remove.add(queue)
                            stale_count += 1
                    except Exception:
                        # Queue is broken, remove it
                        connections_to_remove.add(queue)
                        stale_count += 1
                
                # Remove stale connections
                for queue in connections_to_remove:
                    self.user_connections[user_email].discard(queue)
                
                # Remove user if no connections left
                if not self.user_connections[user_email]:
                    del self.user_connections[user_email]
                    if user_email in self.user_unread_leads:
                        del self.user_unread_leads[user_email]
                    if user_email in self.connection_metadata:
                        del self.connection_metadata[user_email]
            
            if stale_count > 0:
                logger.info(f"🧹 Cleaned up {stale_count} stale real-time connections")
                
        except Exception as e:
            logger.error(f"Error cleaning up stale connections: {str(e)}")
    
    # ============================================================================
    # CONNECTION MANAGEMENT
    # ============================================================================
    
    async def connect_user(self, user_email: str, connection_metadata: Optional[Dict[str, Any]] = None) -> asyncio.Queue:
        """
        User connects to SSE stream
        Returns a queue for sending notifications to this specific connection
        """
        try:
            # Initialize user data if not exists
            if user_email not in self.user_connections:
                self.user_connections[user_email] = set()
                self.user_unread_leads[user_email] = set()
                self.connection_metadata[user_email] = {}
            
            # Create new queue for this connection
            queue = asyncio.Queue(maxsize=50)  # Limit queue size to prevent memory issues
            
            # Add connection
            self.user_connections[user_email].add(queue)
            
            # Store connection metadata
            connection_id = f"conn_{datetime.utcnow().timestamp()}_{id(queue)}"
            self.connection_metadata[user_email][connection_id] = {
                "connected_at": datetime.utcnow(),
                "last_activity": datetime.utcnow(),
                "user_agent": connection_metadata.get("user_agent") if connection_metadata else None,
                "timezone": connection_metadata.get("timezone", "UTC") if connection_metadata else "UTC",
                "queue_id": id(queue)
            }
            
            # Load user's current unread leads from database
            await self._load_user_unread_leads(user_email)
            
            # Send initial sync notification
            if self.user_unread_leads[user_email]:
                initial_sync = {
                    "type": "unread_leads_sync",
                    "unread_leads": list(self.user_unread_leads[user_email]),
                    "total_unread_count": len(self.user_unread_leads[user_email]),
                    "sync_timestamp": datetime.utcnow().isoformat()
                }
                await queue.put(initial_sync)
            
            # Send connection established notification
            connection_established = {
                "type": "connection_established",
                "user_email": user_email,
                "connection_id": connection_id,
                "timestamp": datetime.utcnow().isoformat(),
                "initial_unread_leads": list(self.user_unread_leads[user_email])
            }
            await queue.put(connection_established)
            
            logger.info(f"🔗 User {user_email} connected to real-time notifications (total connections: {len(self.user_connections[user_email])})")
            
            return queue
            
        except Exception as e:
            logger.error(f"Error connecting user {user_email}: {str(e)}")
            raise
    
    async def disconnect_user(self, user_email: str, queue: asyncio.Queue):
        """
        User disconnects from SSE stream
        Clean up the specific connection
        """
        try:
            if user_email in self.user_connections:
                self.user_connections[user_email].discard(queue)
                
                # Remove connection metadata
                metadata_to_remove = None
                for conn_id, metadata in self.connection_metadata.get(user_email, {}).items():
                    if metadata.get("queue_id") == id(queue):
                        metadata_to_remove = conn_id
                        break
                
                if metadata_to_remove:
                    del self.connection_metadata[user_email][metadata_to_remove]
                
                # If no more connections, clean up user data
                if not self.user_connections[user_email]:
                    del self.user_connections[user_email]
                    # Keep unread state for when user reconnects
                    # del self.user_unread_leads[user_email]
                    if user_email in self.connection_metadata:
                        del self.connection_metadata[user_email]
                    
                    logger.info(f"🔌 User {user_email} fully disconnected from real-time notifications")
                else:
                    logger.info(f"🔌 User {user_email} connection closed (remaining: {len(self.user_connections[user_email])})")
            
        except Exception as e:
            logger.error(f"Error disconnecting user {user_email}: {str(e)}")
    
    async def _load_user_unread_leads(self, user_email: str):
        """Load user's unread leads from database"""
        try:
            from ..config.database import get_database
            
            db = get_database()
            
            # Get user info to determine role
            user = await db.users.find_one({"email": user_email})
            if not user:
                return
            
            user_role = user.get("role", "user")
            
            # Build query based on user permissions
            if user_role == "admin":
                # Admin sees all leads with unread messages
                query = {"whatsapp_has_unread": True}
            else:
                # Regular user sees only assigned leads with unread messages
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
                {"lead_id": 1}
            ).to_list(None)
            
            # Update user's unread leads set
            self.user_unread_leads[user_email] = {lead["lead_id"] for lead in unread_leads}
            
            logger.debug(f"📖 Loaded {len(self.user_unread_leads[user_email])} unread leads for {user_email}")
            
        except Exception as e:
            logger.error(f"Error loading unread leads for {user_email}: {str(e)}")
    
    # ============================================================================
    # NOTIFICATION BROADCASTING
    # ============================================================================
    
    async def notify_new_message(self, lead_id: str, message_data: Dict[str, Any], authorized_users: List[Dict[str, Any]]):
        """
        Instantly notify authorized users about new WhatsApp message
        This is called by WhatsApp message service when incoming messages are processed
        """
        try:
            for user in authorized_users:
                user_email = user["email"]
                
                # Add to user's unread leads
                if user_email in self.user_unread_leads:
                    self.user_unread_leads[user_email].add(lead_id)
                else:
                    self.user_unread_leads[user_email] = {lead_id}
                
                # Create notification
                notification = {
                    "type": "new_whatsapp_message",
                    "lead_id": lead_id,
                    "lead_name": message_data.get("lead_name"),
                    "message_preview": message_data.get("message_preview", ""),
                    "timestamp": message_data.get("timestamp"),
                    "direction": message_data.get("direction"),
                    "message_id": message_data.get("message_id"),
                    "unread_leads": list(self.user_unread_leads[user_email])
                }
                
                # 🆕 NEW: Save notification to history
                await self._save_notification_to_history(lead_id, message_data)
                
                # Send to all user's connections
                await self._send_to_user(user_email, notification)
            
            logger.info(f"🔔 New message notification sent to {len(authorized_users)} users for lead {lead_id}")
            
        except Exception as e:
            logger.error(f"Error notifying new message: {str(e)}")
    
    async def mark_lead_as_read(self, user_email: str, lead_id: str):
        """
        Mark lead as read for user (icon changes from green to grey)
        Broadcasts update to all user's connections
        """
        try:
            # Remove from user's unread leads
            if user_email in self.user_unread_leads:
                self.user_unread_leads[user_email].discard(lead_id)
                
                # Create notification
                notification = {
                    "type": "lead_marked_read",
                    "lead_id": lead_id,
                    "marked_by_user": user_email,
                    "unread_leads": list(self.user_unread_leads[user_email])
                }
                
                # Send to user's connections
                await self._send_to_user(user_email, notification)
                
                logger.info(f"📋 Lead {lead_id} marked as read for user {user_email}")
            
        except Exception as e:
            logger.error(f"Error marking lead as read: {str(e)}")
    

    async def _send_to_user(self, user_email: str, notification: Dict[str, Any]):
        """
        Send notification to all active connections for a specific user
        Internal method used by notify_* methods
        """
        try:
            if user_email not in self.user_connections:
                logger.debug(f"No active connections for user {user_email}, skipping notification")
                return
            
            # Get all active queues for this user
            user_queues = self.user_connections.get(user_email, set())
            
            if not user_queues:
                logger.debug(f"No queues found for user {user_email}")
                return
            
            # Send notification to all user's connections
            disconnected_queues = set()
            
            for queue in user_queues:
                try:
                    # Non-blocking put with timeout
                    await asyncio.wait_for(queue.put(notification), timeout=1.0)
                    logger.debug(f"📤 Notification sent to {user_email} via queue {id(queue)}")
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Queue timeout for {user_email}, marking for removal")
                    disconnected_queues.add(queue)
                except asyncio.QueueFull:
                    logger.warning(f"⚠️ Queue full for {user_email}, dropping notification")
                    disconnected_queues.add(queue)
                except Exception as e:
                    logger.error(f"❌ Error sending to queue for {user_email}: {str(e)}")
                    disconnected_queues.add(queue)
            
            # Clean up disconnected queues
            if disconnected_queues:
                for queue in disconnected_queues:
                    self.user_connections[user_email].discard(queue)
                
                logger.info(f"🧹 Removed {len(disconnected_queues)} stale connections for {user_email}")
                
                # Clean up user if no connections left
                if not self.user_connections[user_email]:
                    del self.user_connections[user_email]
                    if user_email in self.user_unread_leads:
                        del self.user_unread_leads[user_email]
            
            logger.info(f"✅ Notification delivered to {len(user_queues) - len(disconnected_queues)} connections for {user_email}")
            
        except Exception as e:
            logger.error(f"❌ Error in _send_to_user for {user_email}: {str(e)}")
    
    async def notify_task_assigned(self, lead_id: str, task_data: Dict[str, Any], authorized_users: List[Dict[str, Any]]):
        """
        🔄 UPDATED: Notify authorized users about task assignment
        Now creates ONE unified notification instead of separate ones
        """
        try:
            # Extract user emails from authorized_users
            user_emails = [user["email"] for user in authorized_users]
            
            # Create unified notification (single record for all users + admins)
            await self._create_unified_notification(
                notification_type="task_assigned",
                user_email=user_emails[0] if user_emails else None,
                lead_id=lead_id,
                notification_data={
                    "lead_name": task_data.get("lead_name", "Unknown Lead"),
                    "task_title": task_data.get("task_title"),
                    "task_type": task_data.get("task_type"),
                    "task_id": task_data.get("task_id"),
                    "priority": task_data.get("priority", "medium"),
                    "due_date": task_data.get("due_date"),
                    "reassigned": task_data.get("reassigned", False),
                    "reassigned_by": task_data.get("reassigned_by")
                },
                authorized_users=[{"email": email, "name": ""} for email in user_emails],  # ✅ Correct
                task_id=task_data.get("task_id"),  
                include_admins=True
            )
            
            # Send real-time notification to connected users
            for user in authorized_users:
                user_email = user["email"]
                
                notification = {
                    "type": "task_assigned",
                    "lead_id": lead_id,
                    "lead_name": task_data.get("lead_name", "Unknown Lead"),
                    "task_title": task_data.get("task_title"),
                    "task_type": task_data.get("task_type"),
                    "task_id": task_data.get("task_id"),
                    "priority": task_data.get("priority", "medium"),
                    "due_date": task_data.get("due_date"),
                    "reassigned": task_data.get("reassigned", False),
                    "reassigned_by": task_data.get("reassigned_by"),
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                await self._send_to_user(user_email, notification)
            
            logger.info(f"🔔 Task assignment notification sent to {len(authorized_users)} users for lead {lead_id}")
            
        except Exception as e:
            logger.error(f"Error notifying task assignment: {str(e)}")

    async def notify_lead_assigned(self, lead_id: str, lead_data: Dict[str, Any], authorized_users: List[Dict[str, Any]]):
        """
        🆕 NEW: Notify authorized users about lead assignment
        Called by lead_service when leads are created/assigned
        """
        try:
            for user in authorized_users:
                user_email = user["email"]
                
                # Create notification
                notification = {
                    "type": "lead_assigned",
                    "lead_id": lead_id,
                    "lead_name": lead_data.get("lead_name"),
                    "lead_email": lead_data.get("lead_email"),
                    "lead_phone": lead_data.get("lead_phone"),
                    "category": lead_data.get("category"),
                    "source": lead_data.get("source"),
                    "assignment_method": lead_data.get("assignment_method"),
                    "reassigned": lead_data.get("reassigned", False),
                    "previous_assignee": lead_data.get("previous_assignee"),
                    "bulk_creation": lead_data.get("bulk_creation", False),
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                # Save to notification history
                await self._save_lead_notification_to_history(user_email, notification)
                
                # Send to all user's connections
                await self._send_to_user(user_email, notification)
            
            logger.info(f"🔔 Lead assignment notification sent to {len(authorized_users)} users for lead {lead_id}")
            
        except Exception as e:
            logger.error(f"Error notifying lead assignment: {str(e)}")


    async def notify_lead_reassigned(self, lead_id: str, lead_data: Dict[str, Any], authorized_users: List[Dict[str, Any]]):
        """
        🔄 UPDATED: Notify authorized users about lead reassignment
        Now creates ONE unified notification instead of separate ones
        """
        try:
            # Extract user emails from authorized_users
            user_emails = [user["email"] for user in authorized_users]
            
            # Create unified notification (single record for all users + admins)
            await self._create_unified_notification(
                notification_type="lead_reassigned",
                user_email=user_emails[0] if user_emails else None,
                lead_id=lead_id,
                notification_data={
                    "lead_name": lead_data.get("lead_name"),
                    "lead_email": lead_data.get("lead_email"),
                    "lead_phone": lead_data.get("lead_phone"),
                    "category": lead_data.get("category"),
                    "source": lead_data.get("source"),
                    "reassigned_from": lead_data.get("reassigned_from"),
                    "reassigned": True
                },
                authorized_users=[{"email": email, "name": user["name"]} for email, user in zip(user_emails, authorized_users)],  # ✅ Correct
                include_admins=True
            )
            
            # Send real-time notification to connected users
            for user in authorized_users:
                user_email = user["email"]
                
                notification = {
                    "type": "lead_reassigned",
                    "lead_id": lead_id,
                    "lead_name": lead_data.get("lead_name"),
                    "lead_email": lead_data.get("lead_email"),
                    "lead_phone": lead_data.get("lead_phone"),
                    "category": lead_data.get("category"),
                    "source": lead_data.get("source"),
                    "reassigned_from": lead_data.get("reassigned_from"),
                    "reassigned": True,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                await self._send_to_user(user_email, notification)
            
            logger.info(f"🔔 Lead reassignment notification sent to {len(authorized_users)} users for lead {lead_id}")
            
        except Exception as e:
            logger.error(f"Error notifying lead reassignment: {str(e)}")


    async def _create_unified_notification(
        self, 
        notification_type: str,
        user_email: str,  # 🔥 ADD THIS
        lead_id: str,
        notification_data: Dict[str, Any],
        authorized_users: List[Dict[str, str]],  # 🔥 RENAME FROM assigned_users
        task_id: Optional[str] = None,  # 🔥 ADD THIS
        include_admins: bool = True
    ) -> None:
        """
        🆕 UPDATED: Create a single unified notification for multiple users
        Eliminates duplicate notifications by creating ONE record visible to all relevant users
        
        Args:
            notification_type: Type of notification (lead_assigned, task_assigned, etc.)
            user_email: Primary user email (assigned user)
            lead_id: Lead ID associated with the notification
            notification_data: Data payload for the notification
            authorized_users: List of user dicts with email/name who can see this notification
            task_id: Optional task ID for task notifications
            include_admins: Whether to include admin users in the notification
        """
        try:
            from ..config.database import get_database
            from datetime import datetime
            import uuid
            
            db = get_database()
            
            # Generate unique notification ID
            notification_id = str(uuid.uuid4())
            
            # Step 1: Collect all target users from authorized_users
            visible_to_users = [user["email"] for user in authorized_users]
            
            # Step 2: Add admin users if requested
            admin_emails = []
            if include_admins:
                admin_users = await db.users.find(
                    {"role": "admin", "is_active": True},
                    {"email": 1}
                ).to_list(None)
                admin_emails = [admin["email"] for admin in admin_users]
            
            # Step 3: Combine all users and remove duplicates
            all_target_users = list(set(visible_to_users + admin_emails))
            
            if not all_target_users:
                logger.warning(f"No target users found for {notification_type} notification")
                return
            
            # Step 4: Determine message preview based on notification type
            message_preview = ""
            if notification_type == "lead_assigned":
                message_preview = f"New lead assigned: {notification_data.get('lead_name', 'Unknown')}"
            elif notification_type == "lead_reassigned":
                message_preview = f"Lead reassigned: {notification_data.get('lead_name', 'Unknown')}"
            elif notification_type == "task_assigned":
                message_preview = f"Task: {notification_data.get('task_title', 'New Task')}"
            elif notification_type == "whatsapp_unread":
                message_preview = notification_data.get("message_preview", "New message")
            
            # Step 5: Create the unified notification document
            unified_doc = {
                "notification_id": notification_id,
                "notification_type": notification_type,
                "user_email": user_email,  # Primary assigned user
                "lead_id": lead_id,
                "lead_name": notification_data.get("lead_name"),
                "message_preview": message_preview,
                
                # 🔥 Multi-user visibility
                "visible_to_users": visible_to_users,  # Array of emails who can see it
                "visible_to_admins": include_admins,   # Flag for admin visibility
                
                # 🔥 Multi-user read tracking
                "read_by": {},  # Format: {user_email: timestamp}
                
                # Common fields
                "lead_email": notification_data.get("lead_email"),
                "lead_phone": notification_data.get("lead_phone"),
                "category": notification_data.get("category"),
                "source": notification_data.get("source"),
                
                # Task-specific fields (if task notification)
                "task_id": task_id,
                "task_title": notification_data.get("task_title"),
                "task_type": notification_data.get("task_type"),
                "priority": notification_data.get("priority"),
                "due_date": notification_data.get("due_date"),
                
                # WhatsApp-specific fields
                "message_id": notification_data.get("message_id"),
                "direction": notification_data.get("direction"),
                
                # Reassignment fields
                "reassigned": notification_data.get("reassigned", False),
                "reassigned_from": notification_data.get("reassigned_from"),
                "previous_assignee": notification_data.get("previous_assignee"),
                
                # Timestamps
                "created_at": datetime.utcnow(),
                "read_at": None,  # Deprecated, use read_by instead
                
                # Original data for reference
                "original_data": notification_data
            }
            
            # Step 6: Remove None values to keep document clean
            unified_doc = {k: v for k, v in unified_doc.items() if v is not None}
            
            # Step 7: Save to database (single record)
            result = await db.notification_history.insert_one(unified_doc)
            
            logger.info(f"✅ Unified notification created: {notification_id} for {notification_type}, visible to {len(all_target_users)} users")
            
            return notification_id
            
        except Exception as e:
            logger.error(f"❌ Error creating unified notification: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None




# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

# Create singleton instance
realtime_manager = RealtimeNotificationManager()

# Cleanup function for graceful shutdown
async def cleanup_realtime_manager():
    """Cleanup function for application shutdown"""
    await realtime_manager.shutdown()