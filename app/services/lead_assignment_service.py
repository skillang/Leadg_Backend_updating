# app/services/lead_assignment_service.py
# Updated Lead Assignment Service with Selective Round Robin & Multi-User Assignment

from typing import Optional, Dict, Any, List
from datetime import datetime
from bson import ObjectId
import logging

from ..config.database import get_database
from .user_lead_array_service import user_lead_array_service

logger = logging.getLogger(__name__)

class LeadAssignmentService:
    """Service for lead assignment and round-robin logic with selective assignment"""
    
    def __init__(self):
        pass
    
    def get_db(self):
        """Get database connection"""
        return get_database()
    
    # ============================================================================
    # 🆕 NEW: SELECTIVE ROUND ROBIN METHODS
    # ============================================================================
    
    async def get_next_assignee_selective_round_robin(self, selected_user_emails: List[str]) -> Optional[str]:
        """
        Get next user for round-robin assignment from SELECTED users only
        
        Args:
            selected_user_emails: List of user emails to include in round robin
            
        Returns:
            str: Email of selected user, or None if no valid users
        """
        db = self.get_db()
        
        try:
            if not selected_user_emails:
                logger.warning("No users selected for round-robin assignment")
                return None
            
            # Get only the selected active users
            active_users = await db.users.find(
                {
                    "email": {"$in": selected_user_emails},
                    "role": "user", 
                    "is_active": True
                },
                {"email": 1, "_id": 1, "first_name": 1, "last_name": 1, "total_assigned_leads": 1}
            ).to_list(None)
            
            if not active_users:
                logger.warning(f"No active users found from selected list: {selected_user_emails}")
                return None
            
            logger.info(f"Found {len(active_users)} active users from selection for round-robin")
            
            # Use total_assigned_leads from user document (fast!)
            user_lead_counts = {}
            for user in active_users:
                user_email = user["email"]
                lead_count = user.get("total_assigned_leads", 0)
                user_lead_counts[user_email] = lead_count
                logger.info(f"Selected user {user_email} has {lead_count} leads")
            
            # Find user with minimum leads among selected users
            min_leads = min(user_lead_counts.values())
            users_with_min_leads = [
                email for email, count in user_lead_counts.items() 
                if count == min_leads
            ]
            
            # If multiple users have same minimum, pick the one assigned longest ago
            if len(users_with_min_leads) > 1:
                logger.info(f"Multiple selected users with {min_leads} leads: {users_with_min_leads}")
                
                last_assigned_times = {}
                for user_email in users_with_min_leads:
                    last_lead = await db.leads.find_one(
                        {"assigned_to": user_email},
                        sort=[("created_at", -1)]
                    )
                    last_assigned_times[user_email] = last_lead["created_at"] if last_lead else datetime.min
                
                selected_user = min(last_assigned_times.keys(), key=lambda x: last_assigned_times[x])
            else:
                selected_user = users_with_min_leads[0]
            
            logger.info(f"Selective round-robin selected: {selected_user}")
            return selected_user
            
        except Exception as e:
            logger.error(f"Error in selective round-robin assignment: {str(e)}")
            return None
    
    async def get_next_assignee_round_robin(self, selected_user_emails: Optional[List[str]] = None) -> Optional[str]:
        """
        Get next user for round-robin assignment
        
        Args:
            selected_user_emails: Optional list of user emails to limit round robin to.
                                If provided, only these users will be considered.
                                If None or empty, all active users will be considered.
        
        Returns:
            str: Email of selected user, or None if no valid users
        """
        # If selected users provided, use selective round robin
        if selected_user_emails:
            return await self.get_next_assignee_selective_round_robin(selected_user_emails)
        
        # Otherwise, use original round robin logic for all active users
        db = self.get_db()
        
        try:
            # Get all active users with 'user' role
            active_users = await db.users.find(
                {"role": "user", "is_active": True},
                {"email": 1, "_id": 1, "first_name": 1, "last_name": 1, "total_assigned_leads": 1}
            ).to_list(None)
            
            if not active_users:
                logger.warning("No active users found for round-robin assignment")
                return None
            
            logger.info(f"Found {len(active_users)} active users for round-robin")
            
            # Use total_assigned_leads from user document (fast!)
            user_lead_counts = {}
            for user in active_users:
                user_email = user["email"]
                lead_count = user.get("total_assigned_leads", 0)
                user_lead_counts[user_email] = lead_count
                logger.info(f"User {user_email} has {lead_count} leads")
            
            # Find user with minimum leads
            min_leads = min(user_lead_counts.values())
            users_with_min_leads = [
                email for email, count in user_lead_counts.items() 
                if count == min_leads
            ]
            
            # If multiple users have same minimum, pick the one assigned longest ago
            if len(users_with_min_leads) > 1:
                logger.info(f"Multiple users with {min_leads} leads: {users_with_min_leads}")
                
                last_assigned_times = {}
                for user_email in users_with_min_leads:
                    last_lead = await db.leads.find_one(
                        {"assigned_to": user_email},
                        sort=[("created_at", -1)]
                    )
                    last_assigned_times[user_email] = last_lead["created_at"] if last_lead else datetime.min
                
                selected_user = min(last_assigned_times.keys(), key=lambda x: last_assigned_times[x])
            else:
                selected_user = users_with_min_leads[0]
            
            logger.info(f"Round-robin selected: {selected_user}")
            return selected_user
            
        except Exception as e:
            logger.error(f"Error in round-robin assignment: {str(e)}")
            return None
    
    # ============================================================================
    # 🆕 NEW: MULTI-USER ASSIGNMENT METHODS
    # ============================================================================
    
    async def assign_lead_to_multiple_users(self, lead_id: str, user_emails: List[str], assigned_by: str, reason: str = "Multi-user assignment") -> Dict[str, Any]:
        """
        Assign a lead to multiple users
        
        Args:
            lead_id: Lead ID to assign
            user_emails: List of user emails to assign the lead to
            assigned_by: Email of admin making the assignment
            reason: Reason for assignment
            
        Returns:
            Dict with success status and details
        """
        db = self.get_db()
        
        try:
            if not user_emails:
                return {"success": False, "message": "No users provided for assignment"}
            
            # Validate all users exist and are active
            valid_users = await db.users.find(
                {"email": {"$in": user_emails}, "is_active": True},
                {"email": 1, "first_name": 1, "last_name": 1}
            ).to_list(None)
            
            valid_user_emails = [user["email"] for user in valid_users]
            invalid_users = set(user_emails) - set(valid_user_emails)
            
            if invalid_users:
                logger.warning(f"Invalid/inactive users in assignment: {invalid_users}")
            
            if not valid_user_emails:
                return {"success": False, "message": "No valid active users found"}
            
            # Get user names for assignment history
            user_names = {}
            for user in valid_users:
                user_email = user["email"]
                user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user_email
                user_names[user_email] = user_name
            
            # 🆕 NEW: Get lead details for notifications
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                return {"success": False, "message": "Lead not found"}
            
            lead_name = lead.get("name", "Unknown Lead")
            
            # Create assignment history entries for each user
            assignment_entries = []
            for user_email in valid_user_emails:
                assignment_entries.append({
                    "assigned_to": user_email,
                    "assigned_to_name": user_names[user_email],
                    "assigned_by": assigned_by,
                    "assignment_method": "multi_user_manual",
                    "assigned_at": datetime.utcnow(),
                    "reason": reason,
                    "is_multi_assignment": True,
                    "co_assignees": [email for email in valid_user_emails if email != user_email]
                })
            
            # Update lead document with multiple assignees
            primary_assignee = valid_user_emails[0]  # First user is primary
            co_assignees = valid_user_emails[1:] if len(valid_user_emails) > 1 else []
            
            result = await db.leads.update_one(
                {"lead_id": lead_id},
                {
                    "$set": {
                        "assigned_to": primary_assignee,  # Primary assignee (for backward compatibility)
                        "assigned_to_name": user_names[primary_assignee],
                        "co_assignees": co_assignees,  # 🆕 NEW: Additional assignees
                        "co_assignees_names": [user_names[email] for email in co_assignees],  # 🆕 NEW: Names
                        "assignment_method": "multi_user_manual",
                        "is_multi_assigned": True,  # 🆕 NEW: Flag for multi-assignment
                        "updated_at": datetime.utcnow()
                    },
                    "$push": {
                        "assignment_history": {"$each": assignment_entries}
                    }
                }
            )
            
            if result.modified_count > 0:
                # Add lead to each user's array
                for user_email in valid_user_emails:
                    await user_lead_array_service.add_lead_to_user_array(user_email, lead_id)
                
                logger.info(f"Lead {lead_id} assigned to multiple users: {valid_user_emails}")
                
                # 🔥 UPDATED: Send notifications (prevents admin duplicates)
                try:
                    from ..services.realtime_service import realtime_manager
                    
                    notification_data = {
                        "lead_name": lead_name,
                        "lead_email": lead.get("email"),
                        "lead_phone": lead.get("contact_number"),
                        "category": lead.get("category"),
                        "source": lead.get("source"),
                        "assignment_method": "multi_user_manual",
                        "co_assigned": True,
                        "primary_assignee": primary_assignee,
                        "co_assignees": co_assignees,
                        "total_assignees": len(valid_user_emails)
                    }
                    
                    # 🔥 STEP 1: Send to assigned users ONLY (no admin duplication)
                    for user_email in valid_user_emails:
                        authorized_users = [{"email": user_email, "name": user_names[user_email]}]
                        await realtime_manager.notify_lead_assigned(lead_id, notification_data, authorized_users)
                    
                    logger.info(f"✅ Multi-assignment notifications sent to {len(valid_user_emails)} users for lead {lead_id}")
                    
                    # 🔥 STEP 2: Send to admins SEPARATELY (directly save to DB to avoid duplication)
                    admin_users = await db.users.find(
                        {"role": "admin", "is_active": True},
                        {"email": 1, "first_name": 1, "last_name": 1}
                    ).to_list(None)
                    
                    admin_notification_count = 0
                    timestamp = datetime.utcnow().timestamp()
                    
                    for admin in admin_users:
                        admin_email = admin["email"]
                        # Skip if admin is already in the assigned users
                        if admin_email not in valid_user_emails:
                            admin_name = f"{admin.get('first_name', '')} {admin.get('last_name', '')}".strip() or admin_email
                            
                            # Create admin-specific notification data
                            admin_notification_data = {
                                **notification_data,
                                "assigned_users": valid_user_emails,
                                "admin_view": True
                            }
                            
                            # 🔥 Save DIRECTLY to notification_history (bypass _save_lead_notification_to_history)
                            history_doc = {
                                "notification_id": f"{admin_email}_lead_{lead_id}_{timestamp}",
                                "user_email": admin_email,
                                "notification_type": "lead_assigned",
                                "lead_id": lead_id,
                                "lead_name": lead_name,
                                "message_preview": f"New lead assigned: {lead_name}",
                                "lead_email": lead.get("email"),
                                "lead_phone": lead.get("contact_number"),
                                "category": lead.get("category"),
                                "source": lead.get("source"),
                                "created_at": datetime.utcnow(),
                                "read_at": None,
                                "original_data": admin_notification_data
                            }
                            
                            await db.notification_history.update_one(
                                {"notification_id": history_doc["notification_id"]},
                                {"$setOnInsert": history_doc},
                                upsert=True
                            )
                            
                            # Send real-time notification via SSE
                            await realtime_manager._send_to_user(admin_email, {
                                "type": "lead_assigned",
                                "lead_id": lead_id,
                                "lead_name": lead_name,
                                "timestamp": datetime.utcnow().isoformat(),
                                **admin_notification_data
                            })
                            
                            admin_notification_count += 1
                    
                    logger.info(f"✅ Admin notifications sent to {admin_notification_count} admins for multi-assignment of lead {lead_id}")
                    
                except Exception as notif_error:
                    logger.warning(f"⚠️ Failed to send multi-assignment notifications: {notif_error}")
                    import traceback
                    logger.warning(f"Notification error traceback: {traceback.format_exc()}")
                    # Don't fail the assignment if notification fails
                
                return {
                    "success": True,
                    "message": f"Lead assigned to {len(valid_user_emails)} users successfully",
                    "assigned_users": valid_user_emails,
                    "invalid_users": list(invalid_users) if invalid_users else [],
                    "primary_assignee": primary_assignee,
                    "co_assignees": co_assignees
                }
            
            return {"success": False, "message": "Failed to update lead assignment"}
            
        except Exception as e:
            logger.error(f"Error in multi-user assignment: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"success": False, "message": f"Assignment failed: {str(e)}"}
    async def remove_user_from_multi_assignment(self, lead_id: str, user_email: str, removed_by: str, reason: str = "Removed from assignment") -> bool:
        """
        Remove a user from a multi-user assignment
        
        Args:
            lead_id: Lead ID
            user_email: User email to remove
            removed_by: Admin performing the removal
            reason: Reason for removal
            
        Returns:
            bool: Success status
        """
        db = self.get_db()
        
        try:
            # Get current lead
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                return False
            
            current_assignee = lead.get("assigned_to")
            co_assignees = lead.get("co_assignees", [])
            
            # Check if user is assigned to this lead
            if user_email not in [current_assignee] + co_assignees:
                logger.warning(f"User {user_email} is not assigned to lead {lead_id}")
                return False
            
            # If removing primary assignee, promote first co-assignee
            if user_email == current_assignee and co_assignees:
                new_primary = co_assignees[0]
                new_co_assignees = co_assignees[1:]
                
                # Get new primary user name
                new_primary_user = await db.users.find_one({"email": new_primary})
                new_primary_name = f"{new_primary_user.get('first_name', '')} {new_primary_user.get('last_name', '')}".strip() or new_primary
                
                update_doc = {
                    "$set": {
                        "assigned_to": new_primary,
                        "assigned_to_name": new_primary_name,
                        "co_assignees": new_co_assignees,
                        "co_assignees_names": [lead.get("co_assignees_names", [])[i] for i in range(1, len(lead.get("co_assignees_names", [])))],
                        "updated_at": datetime.utcnow()
                    }
                }
            elif user_email in co_assignees:
                # Remove from co_assignees
                new_co_assignees = [email for email in co_assignees if email != user_email]
                co_assignees_names = lead.get("co_assignees_names", [])
                
                # Remove corresponding name
                try:
                    remove_index = co_assignees.index(user_email)
                    new_co_assignees_names = [name for i, name in enumerate(co_assignees_names) if i != remove_index]
                except (ValueError, IndexError):
                    new_co_assignees_names = co_assignees_names
                
                update_doc = {
                    "$set": {
                        "co_assignees": new_co_assignees,
                        "co_assignees_names": new_co_assignees_names,
                        "is_multi_assigned": len(new_co_assignees) > 0,
                        "updated_at": datetime.utcnow()
                    }
                }
            else:
                # Last user being removed
                update_doc = {
                    "$set": {
                        "assigned_to": None,
                        "assigned_to_name": None,
                        "co_assignees": [],
                        "co_assignees_names": [],
                        "is_multi_assigned": False,
                        "updated_at": datetime.utcnow()
                    }
                }
            
            # Add removal to assignment history
            update_doc["$push"] = {
                "assignment_history": {
                    "action": "removed_from_assignment",
                    "removed_user": user_email,
                    "removed_by": removed_by,
                    "removed_at": datetime.utcnow(),
                    "reason": reason
                }
            }
            
            result = await db.leads.update_one({"lead_id": lead_id}, update_doc)
            
            if result.modified_count > 0:
                # Remove lead from user's array
                await user_lead_array_service.remove_lead_from_user_array(user_email, lead_id)
                logger.info(f"User {user_email} removed from lead {lead_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error removing user from assignment: {str(e)}")
            return False
    
    # ============================================================================
    # EXISTING METHODS (MAINTAINED FOR BACKWARD COMPATIBILITY)
    # ============================================================================
    
    async def get_next_round_robin_user(self) -> Optional[str]:
        """LEGACY METHOD: Maintained for backward compatibility"""
        return await self.get_next_assignee_round_robin()
    
    async def assign_lead_to_user(self, lead_id: str, user_email: str, assigned_by: str, reason: str = "Auto-assignment") -> bool:
        """Assign a lead to a single user and update user array (EXISTING METHOD)"""
        db = self.get_db()
        
        try:
            # Get user info
            user = await db.users.find_one({"email": user_email, "is_active": True})
            if not user:
                logger.error(f"User {user_email} not found or inactive")
                return False
            
            user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user_email
            
            # Update lead document (single assignment)
            result = await db.leads.update_one(
                {"lead_id": lead_id},
                {
                    "$set": {
                        "assigned_to": user_email,
                        "assigned_to_name": user_name,
                        "assignment_method": "round_robin",
                        "co_assignees": [],  # Clear any multi-assignments
                        "co_assignees_names": [],
                        "is_multi_assigned": False,
                        "updated_at": datetime.utcnow()
                    },
                    "$push": {
                        "assignment_history": {
                            "assigned_to": user_email,
                            "assigned_to_name": user_name,
                            "assigned_by": assigned_by,
                            "assignment_method": "round_robin",
                            "assigned_at": datetime.utcnow(),
                            "reason": reason
                        }
                    }
                }
            )
            
            if result.modified_count > 0:
                # Add to user's assigned_leads array
                await user_lead_array_service.add_lead_to_user_array(user_email, lead_id)
                logger.info(f"Lead {lead_id} assigned to {user_email}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error assigning lead: {str(e)}")
            return False
    
    async def reassign_lead(self, lead_id: str, new_user_email: str, reassigned_by: str, reason: str = "Manual reassignment") -> bool:
        """Reassign a lead to a different user (EXISTING METHOD)"""
        db = self.get_db()
        
        try:
            # Get current lead
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                return False
            
            old_user_email = lead.get("assigned_to")
            old_co_assignees = lead.get("co_assignees", [])
            
            # Get new user info
            new_user = await db.users.find_one({"email": new_user_email, "is_active": True})
            if not new_user:
                logger.error(f"New assignee {new_user_email} not found")
                return False
            
            new_user_name = f"{new_user.get('first_name', '')} {new_user.get('last_name', '')}".strip() or new_user_email
            
            # Update lead document (single reassignment)
            result = await db.leads.update_one(
                {"lead_id": lead_id},
                {
                    "$set": {
                        "assigned_to": new_user_email,
                        "assigned_to_name": new_user_name,
                        "assignment_method": "manual_reassignment",
                        "co_assignees": [],  # Clear multi-assignments on reassignment
                        "co_assignees_names": [],
                        "is_multi_assigned": False,
                        "updated_at": datetime.utcnow()
                    },
                    "$push": {
                        "assignment_history": {
                            "assigned_to": new_user_email,
                            "assigned_to_name": new_user_name,
                            "assigned_by": reassigned_by,
                            "assignment_method": "manual_reassignment",
                            "assigned_at": datetime.utcnow(),
                            "reason": reason,
                            "previous_assignee": old_user_email,
                            "previous_assignee_name": lead.get("assigned_to_name", "Unassigned"),
                            "previous_co_assignees": old_co_assignees
                        }
                    }
                }
            )
            
            if result.modified_count > 0:
                # Update user arrays - remove from all previous assignees
                if old_user_email:
                    await user_lead_array_service.remove_lead_from_user_array(old_user_email, lead_id)
                
                for co_assignee in old_co_assignees:
                    await user_lead_array_service.remove_lead_from_user_array(co_assignee, lead_id)
                
                # Add to new user
                await user_lead_array_service.add_lead_to_user_array(new_user_email, lead_id)
                
                logger.info(f"Lead {lead_id} reassigned from {old_user_email} to {new_user_email}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error reassigning lead: {str(e)}")
            return False
    
    async def get_round_robin_stats(self) -> Dict[str, Any]:
        """Get round-robin assignment statistics using user arrays (EXISTING METHOD)"""
        db = self.get_db()
        
        try:
            # Get all active users with their lead counts from user documents
            active_users = await db.users.find(
                {"role": "user", "is_active": True},
                {"email": 1, "first_name": 1, "last_name": 1, "total_assigned_leads": 1}
            ).to_list(None)
            
            stats = {
                "total_active_users": len(active_users),
                "user_lead_distribution": [],
                "total_leads": 0,
                "unassigned_leads": 0,
                "average_leads_per_user": 0,
                "distribution_variance": 0
            }
            
            if not active_users:
                return stats
            
            # Use the fast user array data
            lead_counts = []
            for user in active_users:
                user_email = user["email"]
                lead_count = user.get("total_assigned_leads", 0)
                
                user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                if not user_name:
                    user_name = user_email
                
                user_stats = {
                    "user_email": user_email,
                    "user_name": user_name,
                    "lead_count": lead_count
                }
                stats["user_lead_distribution"].append(user_stats)
                lead_counts.append(lead_count)
                stats["total_leads"] += lead_count
            
            # Calculate unassigned leads
            stats["unassigned_leads"] = await db.leads.count_documents({"assigned_to": None})
            
            # Calculate distribution metrics
            if lead_counts:
                stats["average_leads_per_user"] = sum(lead_counts) / len(lead_counts)
                avg = stats["average_leads_per_user"]
                variance = sum((count - avg) ** 2 for count in lead_counts) / len(lead_counts)
                stats["distribution_variance"] = variance
            
            # Sort by lead count for easy viewing
            stats["user_lead_distribution"].sort(key=lambda x: x["lead_count"])
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting round-robin stats: {str(e)}")
            return {"error": str(e)}

# Global service instance
lead_assignment_service = LeadAssignmentService()