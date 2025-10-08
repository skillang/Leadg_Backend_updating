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
    

    async def notify_task_assigned(self, lead_id: str, task_data: Dict[str, Any], authorized_users: List[Dict[str, Any]]):
        """
        🆕 NEW: Notify authorized users about task assignment
        Called by task_service when tasks are created/assigned
        """
        try:
            for user in authorized_users:
                user_email = user["email"]
                
                # Create notification
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
                
                # Save to notification history
                await self._save_task_notification_to_history(user_email, notification)
                
                # Send to all user's connections
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

    async def _save_task_notification_to_history(self, user_email: str, notification: Dict[str, Any]):
        """
        🆕 NEW: Save task notification to history
        """
        try:
            from ..config.database import get_database
            db = get_database()
            
            task_id = notification.get("task_id")
            if not task_id:
                task_id = str(uuid.uuid4())
            
            history_doc = {
                "notification_id": f"{user_email}_task_{task_id}",
                "user_email": user_email,
                "notification_type": "task_assigned",
                "lead_id": notification.get("lead_id"),
                "lead_name": notification.get("lead_name"),
                "message_preview": f"Task: {notification.get('task_title')}",
                "task_id": task_id,
                "task_title": notification.get("task_title"),
                "task_type": notification.get("task_type"),
                "priority": notification.get("priority"),
                "created_at": datetime.utcnow(),
                "read_at": None,
                "original_data": notification
            }
            
            # Use upsert to prevent duplicates
            await db.notification_history.update_one(
                {"notification_id": history_doc["notification_id"]},
                {"$setOnInsert": history_doc},
                upsert=True
            )
            
            logger.debug(f"💾 Task notification saved to history for {user_email}")
            
        except Exception as e:
            logger.error(f"Error saving task notification to history: {str(e)}")

    async def _save_lead_notification_to_history(self, user_email: str, notification: Dict[str, Any]):
        """
        🆕 NEW: Save lead notification to history
        """
        try:
            from ..config.database import get_database
            db = get_database()
            
            lead_id = notification.get("lead_id")
            timestamp = datetime.utcnow().timestamp()
            
            history_doc = {
                "notification_id": f"{user_email}_lead_{lead_id}_{timestamp}",
                "user_email": user_email,
                "notification_type": "lead_assigned",
                "lead_id": lead_id,
                "lead_name": notification.get("lead_name"),
                "message_preview": f"New lead assigned: {notification.get('lead_name')}",
                "lead_email": notification.get("lead_email"),
                "lead_phone": notification.get("lead_phone"),
                "category": notification.get("category"),
                "source": notification.get("source"),
                "created_at": datetime.utcnow(),
                "read_at": None,
                "original_data": notification
            }
            
            # Use upsert to prevent duplicates
            await db.notification_history.update_one(
                {"notification_id": history_doc["notification_id"]},
                {"$setOnInsert": history_doc},
                upsert=True
            )
            
            logger.debug(f"💾 Lead notification saved to history for {user_email}")
            
        except Exception as e:
            logger.error(f"Error saving lead notification to history: {str(e)}")
    async def _send_to_user(self, user_email: str, notification: Dict[str, Any]):
        """
        Send notification to all of user's active connections
        Handles connection failures gracefully
        """
        if user_email not in self.user_connections:
            return
        
        failed_connections = set()
        
        # Send to all user's connections
        for queue in self.user_connections[user_email].copy():
            try:
                # Add timestamp if not present
                if "timestamp" not in notification:
                    notification["timestamp"] = datetime.utcnow().isoformat()
                
                # Try to send notification
                await asyncio.wait_for(queue.put(notification), timeout=1.0)
                
                # Update last activity for this connection
                self._update_connection_activity(user_email, queue)
                
            except asyncio.TimeoutError:
                # Queue is full or unresponsive, mark for removal
                failed_connections.add(queue)
                logger.warning(f"⚠️ Connection timeout for user {user_email}, removing stale connection")
                
            except Exception as e:
                # Connection is broken, mark for removal
                failed_connections.add(queue)
                logger.warning(f"⚠️ Failed to send notification to {user_email}: {str(e)}")
        
        # Remove failed connections
        for queue in failed_connections:
            await self.disconnect_user(user_email, queue)
    
    def _update_connection_activity(self, user_email: str, queue: asyncio.Queue):
        """Update last activity timestamp for connection"""
        try:
            queue_id = id(queue)
            for metadata in self.connection_metadata.get(user_email, {}).values():
                if metadata.get("queue_id") == queue_id:
                    metadata["last_activity"] = datetime.utcnow()
                    break
        except Exception as e:
            logger.debug(f"Error updating connection activity: {str(e)}")

    def _update_connection_activity(self, user_email: str, queue: asyncio.Queue):
        """Update last activity timestamp for connection"""
        try:
            queue_id = id(queue)
            for metadata in self.connection_metadata.get(user_email, {}).values():
                if metadata.get("queue_id") == queue_id:
                    metadata["last_activity"] = datetime.utcnow()
                    break
        except Exception as e:
            logger.debug(f"Error updating connection activity: {str(e)}")

    # 🆕 ADD THIS NEW METHOD HERE:
    
    async def _save_notification_to_history(self, lead_id: str, notification_data: Dict[str, Any]):
        """
        Save notification to history only for users assigned to the lead
        """
        try:
            from ..config.database import get_database
            db = get_database()
            
            # Get the lead to find assigned users
            lead = await db.leads.find_one(
                {"lead_id": lead_id},
                {"assigned_to": 1, "co_assignees": 1}
            )
            
            if not lead:
                logger.warning(f"Lead {lead_id} not found for notification history")
                return
                
            # Get assigned users only
            assigned_users = []
            if lead.get("assigned_to"):
                assigned_users.append(lead["assigned_to"])
            if lead.get("co_assignees"):
                assigned_users.extend(lead["co_assignees"])
            
            if not assigned_users:
                logger.warning(f"No assigned users found for lead {lead_id}")
                return
            
            # Save notification for each assigned user
            for user_email in assigned_users:
                message_id = notification_data.get("message_id")
                if not message_id:
                    message_id = str(uuid.uuid4())

                history_doc = {
                    "notification_id": f"{user_email}_{message_id}",  # Unique per user+message
                    "user_email": user_email,
                    "notification_type": notification_data.get("type", "unknown"),
                    "lead_id": lead_id,
                    "lead_name": notification_data.get("lead_name"),
                    "message_preview": notification_data.get("message_preview", ""),
                    "message_id": message_id,
                    "direction": notification_data.get("direction"),
                    "created_at": datetime.utcnow(),
                    "read_at": None,
                    "original_data": notification_data
                }
                
                # Use upsert to prevent duplicates
                await db.notification_history.update_one(
                    {"notification_id": history_doc["notification_id"]},
                    {"$setOnInsert": history_doc},
                    upsert=True
                )
                
            logger.debug(f"💾 Notification saved to history for {len(assigned_users)} assigned users")
            
        except Exception as e:
            logger.error(f"Error saving notification to history: {str(e)}")
            # Don't fail the notification if history save fails
        
    # ============================================================================
    # MONITORING AND STATISTICS
    # ============================================================================
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get real-time connection statistics"""
        try:
            total_connections = sum(len(connections) for connections in self.user_connections.values())
            total_users = len(self.user_connections)
            total_unread_leads = sum(len(unread) for unread in self.user_unread_leads.values())
            
            # Calculate average connections per user
            avg_connections = total_connections / total_users if total_users > 0 else 0
            
            # Get users with most connections
            top_users = sorted(
                [(user, len(connections)) for user, connections in self.user_connections.items()],
                key=lambda x: x[1],
                reverse=True
            )[:5]
            
            return {
                "total_connections": total_connections,
                "total_users": total_users,
                "total_unread_leads": total_unread_leads,
                "average_connections_per_user": round(avg_connections, 2),
                "top_connected_users": [{"user": user, "connections": count} for user, count in top_users],
                "last_updated": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting connection stats: {str(e)}")
            return {"error": str(e)}
    
    def get_user_connection_info(self, user_email: str) -> Dict[str, Any]:
        """Get connection information for specific user"""
        try:
            if user_email not in self.user_connections:
                return {
                    "connected": False,
                    "connections": 0,
                    "unread_leads": []
                }
            
            connections = len(self.user_connections[user_email])
            unread_leads = list(self.user_unread_leads.get(user_email, set()))
            
            # Get connection details
            connection_details = []
            for conn_id, metadata in self.connection_metadata.get(user_email, {}).items():
                connection_details.append({
                    "connection_id": conn_id,
                    "connected_at": metadata["connected_at"].isoformat(),
                    "last_activity": metadata["last_activity"].isoformat(),
                    "user_agent": metadata.get("user_agent"),
                    "timezone": metadata.get("timezone", "UTC")
                })
            
            return {
                "connected": True,
                "connections": connections,
                "unread_leads": unread_leads,
                "unread_count": len(unread_leads),
                "connection_details": connection_details
            }
            
        except Exception as e:
            logger.error(f"Error getting user connection info: {str(e)}")
            return {"error": str(e)}
    
    async def broadcast_system_notification(self, notification: Dict[str, Any], target_users: Optional[List[str]] = None):
        """
        Broadcast system-wide notification (e.g., maintenance, updates)
        If target_users is None, sends to all connected users
        """
        try:
            target_user_emails = target_users if target_users else list(self.user_connections.keys())
            
            notification.update({
                "type": "system_notification",
                "timestamp": datetime.utcnow().isoformat()
            })
            
            for user_email in target_user_emails:
                await self._send_to_user(user_email, notification)
            
            logger.info(f"📢 System notification sent to {len(target_user_emails)} users")
            
        except Exception as e:
            logger.error(f"Error broadcasting system notification: {str(e)}")
    
    # ============================================================================
    # CLEANUP AND SHUTDOWN
    # ============================================================================
    
    async def shutdown(self):
        """Gracefully shutdown the real-time manager"""
        try:
            # Cancel cleanup task
            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
            
            # Send shutdown notification to all users
            shutdown_notification = {
                "type": "system_shutdown",
                "message": "Server is shutting down, you will be automatically reconnected",
                "timestamp": datetime.utcnow().isoformat()
            }
            
            for user_email in list(self.user_connections.keys()):
                await self._send_to_user(user_email, shutdown_notification)
            
            # Clear all connections
            total_connections = sum(len(connections) for connections in self.user_connections.values())
            self.user_connections.clear()
            self.user_unread_leads.clear()
            self.connection_metadata.clear()
            
            logger.info(f"🛑 Real-time manager shutdown complete, cleaned up {total_connections} connections")
            
        except Exception as e:
            logger.error(f"Error during real-time manager shutdown: {str(e)}")

# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

# Create singleton instance
realtime_manager = RealtimeNotificationManager()

# Cleanup function for graceful shutdown
async def cleanup_realtime_manager():
    """Cleanup function for application shutdown"""
    await realtime_manager.shutdown()