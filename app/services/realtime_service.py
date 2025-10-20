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
    def get_db(self):
        """Get database instance"""
        from app.config.database import get_database
        return get_database()
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
        Notify authorized users about task assignment
        Creates ONE unified notification instead of separate ones
        
        Args:
            lead_id: The lead ID
            task_data: Dictionary containing task information
            authorized_users: List of users to notify (format: [{"email": "user@example.com", "name": "User Name"}])
        """
        try:
            # Extract user emails from authorized_users
            user_emails = [user["email"] for user in authorized_users]
            
            logger.info(f"🔔 Starting task assignment notification for lead {lead_id}")
            logger.info(f"👥 Notifying {len(user_emails)} users: {user_emails}")
            
            # ✅ FIXED: Create unified notification with correct parameters
            await self._create_unified_notification(
                notification_type="task_assigned",
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
                assigned_users=user_emails,  # ✅ FIXED: Pass list of email strings
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
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    async def notify_lead_assigned(self, lead_id: str, lead_data: Dict[str, Any], authorized_users: List[Dict[str, Any]]):
        """
        Notify authorized users about lead assignment with unified notification
        """
        try:
            user_emails = [user["email"] for user in authorized_users]
            
            logger.info(f"🔔 Starting lead assignment notification for lead {lead_id}")
            logger.info(f"👥 Notifying {len(user_emails)} users: {user_emails}")
            
            # ✅ FIXED: Correct parameters
            await self._create_unified_notification(
                notification_type="lead_assigned",
                lead_id=lead_id,
                notification_data={
                    "lead_name": lead_data.get("lead_name"),
                    "lead_email": lead_data.get("lead_email"),
                    "lead_phone": lead_data.get("lead_phone"),
                    "category": lead_data.get("category"),
                    "source": lead_data.get("source"),
                    "assignment_method": lead_data.get("assignment_method"),
                    "co_assigned": lead_data.get("co_assigned", False),
                    "primary_assignee": lead_data.get("primary_assignee"),
                    "co_assignees": lead_data.get("co_assignees", []),
                    "total_assignees": lead_data.get("total_assignees", len(authorized_users)),
                    "reassigned": lead_data.get("reassigned", False),
                    "previous_assignee": lead_data.get("previous_assignee")
                },
                assigned_users=user_emails,  # ✅ List of email strings
                task_id=None,
                include_admins=True
            )
            
            # Send real-time notifications
            for user in authorized_users:
                user_email = user["email"]
                notification = {
                    "type": "lead_assigned",
                    "lead_id": lead_id,
                    "lead_name": lead_data.get("lead_name"),
                    "timestamp": datetime.utcnow().isoformat()
                }
                await self._send_to_user(user_email, notification)
            
            logger.info(f"🔔 Lead assignment notification sent to {len(authorized_users)} users")
            
        except Exception as e:
            logger.error(f"Error notifying lead assignment: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    async def notify_lead_reassigned(self, lead_id: str, lead_data: Dict[str, Any], authorized_users: List[Dict[str, Any]]):
        """
        🔄 FIXED: Notify authorized users about lead reassignment with unified notification
        Now creates ONE unified notification for all assigned users + admins
        
        Args:
            lead_id: The lead ID being reassigned
            lead_data: Dictionary containing lead information
            authorized_users: List of users to notify (format: [{"email": "user@example.com", "name": "User Name"}])
        """
        try:
            # Extract user emails from authorized_users
            user_emails = [user["email"] for user in authorized_users]
            
            logger.info(f"🔔 Starting lead reassignment notification for lead {lead_id}")
            logger.info(f"👥 Notifying {len(user_emails)} users: {user_emails}")
            
            # ✅ FIXED: Create unified notification with correct parameters (NO user_email parameter!)
            await self._create_unified_notification(
                notification_type="lead_reassigned",
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
                assigned_users=user_emails,  # ✅ FIXED: Correct parameter
                task_id=None,
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
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    async def _create_unified_notification(
        self, 
        notification_type: str,
        lead_id: str,
        notification_data: Dict[str, Any],
        assigned_users: List[str],  # ✅ Keep this as List[str] (emails only)
        task_id: Optional[str] = None,
        include_admins: bool = True
    ) -> Optional[Any]:
        """
        Create a single unified notification for multiple users
        
        Args:
            notification_type: Type of notification (lead_assigned, task_assigned, etc.)
            lead_id: Lead ID (required)
            notification_data: Dictionary containing notification details
            assigned_users: List of user EMAIL STRINGS (e.g., ["user1@email.com", "user2@email.com"])
            task_id: Optional task ID (for task notifications)
            include_admins: Whether to make notification visible to all admins
        """
        try:
            db = self.get_db()
            
            # Get all admin emails if include_admins is True
            visible_to_admins = False
            admin_emails = []
            
            if include_admins:
                admins = await db.users.find(
                    {"role": "admin", "is_active": True},
                    {"email": 1}
                ).to_list(None)
                admin_emails = [admin["email"] for admin in admins]
                visible_to_admins = True
                logger.info(f"📧 Found {len(admin_emails)} active admins for notification visibility")
            
            # Create unified notification document
            unified_notification = {
                "notification_id": str(uuid.uuid4()),
                "notification_type": notification_type,
                "lead_id": lead_id,
                "task_id": task_id,
                
                # Lead information
                "lead_name": notification_data.get("lead_name"),
                "lead_email": notification_data.get("lead_email"),
                "lead_phone": notification_data.get("lead_phone"),
                "category": notification_data.get("category"),
                "source": notification_data.get("source"),
                
                # ✅ Task-specific fields
                "task_title": notification_data.get("task_title"),
                "task_type": notification_data.get("task_type"),
                "priority": notification_data.get("priority"),
                "due_date": notification_data.get("due_date"),
                
                # Assignment information
                "assignment_method": notification_data.get("assignment_method"),
                "co_assigned": notification_data.get("co_assigned", False),
                "primary_assignee": notification_data.get("primary_assignee"),
                "co_assignees": notification_data.get("co_assignees", []),
                "total_assignees": notification_data.get("total_assignees", len(assigned_users)),
                
                # Reassignment info
                "reassigned": notification_data.get("reassigned", False),
                "reassigned_from": notification_data.get("reassigned_from"),
                "reassigned_by": notification_data.get("reassigned_by"),
                
                # Visibility control
                "visible_to_users": assigned_users,  # List of email strings
                "visible_to_admins": visible_to_admins,
                "admin_emails": admin_emails,
                
                # Read tracking
                "read_by": {},  # Format: {"user_email": datetime}
                
                # Metadata
                "created_at": datetime.utcnow(),
                "original_data": notification_data
            }
            
            # Insert the unified notification
            result = await db.notification_history.insert_one(unified_notification)
            
            logger.info(f"✅ Created unified notification {unified_notification['notification_id']} for {notification_type}")
            logger.info(f"📋 Lead: {lead_id}, Type: {notification_type}")
            logger.info(f"👥 Visible to {len(assigned_users)} assigned users: {assigned_users}")
            logger.info(f"👨‍💼 Visible to {len(admin_emails)} admins: {visible_to_admins}")
            
            if notification_data.get("co_assigned"):
                logger.info(f"🤝 Co-assignment - Primary: {notification_data.get('primary_assignee')}, Co-assignees: {notification_data.get('co_assignees', [])}")
            
            return result.inserted_id
            
        except Exception as e:
            logger.error(f"❌ Error creating unified notification: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
   
    # ============================================================================
    # UTILITY METHODS
    # ============================================================================
    
    async def broadcast_system_notification(self, notification: Dict[str, Any], target_users: Optional[List[str]] = None):
        """
        Broadcast system notification to all users or specific target users
        Used for maintenance notices, announcements, etc.
        """
        try:
            if target_users:
                # Send to specific users
                for user_email in target_users:
                    await self._send_to_user(user_email, notification)
                logger.info(f"📢 System notification sent to {len(target_users)} specific users")
            else:
                # Broadcast to all connected users
                total_sent = 0
                for user_email in list(self.user_connections.keys()):
                    await self._send_to_user(user_email, notification)
                    total_sent += 1
                logger.info(f"📢 System notification broadcasted to {total_sent} users")
                
        except Exception as e:
            logger.error(f"Error broadcasting system notification: {str(e)}")
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """
        Get statistics about active connections
        Used for monitoring and debugging
        """
        try:
            total_connections = sum(len(connections) for connections in self.user_connections.values())
            total_users = len(self.user_connections)
            total_unread_leads = sum(len(leads) for leads in self.user_unread_leads.values())
            
            # Get top connected users
            user_connection_counts = {
                user_email: len(connections) 
                for user_email, connections in self.user_connections.items()
            }
            top_users = sorted(user_connection_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            
            return {
                "total_connections": total_connections,
                "total_users": total_users,
                "total_unread_leads": total_unread_leads,
                "average_connections_per_user": round(total_connections / total_users, 2) if total_users > 0 else 0,
                "top_connected_users": [user[0] for user in top_users],
                "last_updated": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting connection stats: {str(e)}")
            return {
                "total_connections": 0,
                "total_users": 0,
                "total_unread_leads": 0,
                "error": str(e)
            }


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

# Create singleton instance
realtime_manager = RealtimeNotificationManager()

# Cleanup function for graceful shutdown
async def cleanup_realtime_manager():
    """Cleanup function for application shutdown"""
    try:
        logger.info("🛑 Shutting down real-time notification manager...")
        
        # Cancel cleanup task if running
        if realtime_manager._cleanup_task and not realtime_manager._cleanup_task.done():
            realtime_manager._cleanup_task.cancel()
            try:
                await realtime_manager._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Get stats before cleanup
        total_connections = sum(len(connections) for connections in realtime_manager.user_connections.values())
        
        if total_connections > 0:
            logger.info(f"📊 Disconnecting {total_connections} active connections")
        
        # Clear all connections
        realtime_manager.user_connections.clear()
        realtime_manager.user_unread_leads.clear()
        realtime_manager.connection_metadata.clear()
        
        logger.info("✅ Real-time notification manager shutdown complete")
        
    except Exception as e:
        logger.error(f"❌ Error during shutdown: {str(e)}")