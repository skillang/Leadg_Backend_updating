# app/services/task_service.py
from typing import List, Optional, Dict, Any, Union
from datetime import datetime, date, time, timedelta
from bson import ObjectId
import logging

from ..config.database import get_database
from ..models.task import TaskCreate, TaskUpdate, TaskStatus, TaskPriority
# from ..models.lead import LeadStatus

logger = logging.getLogger(__name__)

class TaskService:
    def __init__(self):
        pass
    
    async def create_task(self, lead_id: str, task_data: TaskCreate, created_by: str) -> Dict[str, Any]:
        """
        🔄 UPDATED: Create a new task with unified notification
        ONE notification for assigned user + admins automatically
        """
        try:
            logger.info(f"Creating task for lead_id: {lead_id}")
            logger.info(f"Task data: {task_data.dict()}")
            
            # Direct database call
            db = get_database()
            
            # Verify lead exists
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                raise ValueError(f"Lead {lead_id} not found")
            
            logger.info(f"Lead found: {lead.get('company_name')}")
            
            # 🔑 Get creator user details for timeline
            created_by_name = "Unknown User"
            created_by_email = ""
            if created_by:
                creator_user = await db.users.find_one({"_id": ObjectId(created_by)})
                if creator_user:
                    first_name = creator_user.get('first_name', '')
                    last_name = creator_user.get('last_name', '')
                    full_name = creator_user.get('full_name', '')
                    created_by_email = creator_user.get('email', '')
                    
                    # Build creator name
                    if first_name and last_name:
                        created_by_name = f"{first_name} {last_name}".strip()
                    elif full_name:
                        created_by_name = full_name
                    elif created_by_email:
                        created_by_name = created_by_email
                    
                    logger.info(f"Created by: {created_by_name}")
            
            # Get assigned user name if provided
            assigned_to_name = "Unassigned"
            assigned_to_email = ""
            if task_data.assigned_to:
                assigned_user = await db.users.find_one({"_id": ObjectId(task_data.assigned_to)})
                if assigned_user:
                    first_name = assigned_user.get('first_name', '')
                    last_name = assigned_user.get('last_name', '')
                    full_name = assigned_user.get('full_name', '')
                    assigned_to_email = assigned_user.get('email', '')
                    
                    # Build assigned user name
                    if first_name and last_name:
                        assigned_to_name = f"{first_name} {last_name}".strip()
                    elif full_name:
                        assigned_to_name = full_name
                    elif assigned_to_email:
                        assigned_to_name = assigned_to_email
                    
                    logger.info(f"Assigned to: {assigned_to_name}")
            
            # Convert dates to strings for MongoDB
            due_date_str = task_data.due_date.isoformat() if task_data.due_date else None
            due_time_str = task_data.due_time if isinstance(task_data.due_time, str) else str(task_data.due_time) if task_data.due_time else None
            
            # Create combined datetime for queries
            due_datetime = None
            if task_data.due_date:
                if task_data.due_time:
                    if isinstance(task_data.due_time, str):
                        hour, minute = map(int, task_data.due_time.split(':'))
                        due_datetime = datetime.combine(task_data.due_date, time(hour, minute))
                    else:
                        due_datetime = datetime.combine(task_data.due_date, task_data.due_time)
                else:
                    due_datetime = datetime.combine(task_data.due_date, time(23, 59))
            
            # Determine status
            status = "pending"
            if due_datetime and due_datetime < datetime.utcnow():
                status = "overdue"
            
            # Create task document
            task_doc = {
                "lead_id": lead["lead_id"],
                "lead_object_id": lead["_id"],
                "task_title": task_data.task_title,
                "task_description": task_data.task_description or "",
                "task_type": task_data.task_type,
                "priority": task_data.priority,
                "assigned_to": task_data.assigned_to,
                "assigned_to_name": assigned_to_name,
                "due_date": due_date_str,
                "due_time": due_time_str,
                "due_datetime": due_datetime,
                "status": status,
                "notes": task_data.notes or "",
                "created_by": ObjectId(created_by),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "completed_at": None,
                "completion_notes": ""
            }
            
            logger.info(f"Task document prepared for insert")
            
            # Insert task
            result = await db.lead_tasks.insert_one(task_doc)
            task_doc["id"] = str(result.inserted_id)
            task_doc["_id"] = str(result.inserted_id)
            
            logger.info(f"Task created successfully: {task_doc['id']}")
            
            # 🔥 UPDATED: Send unified notification (ONE for assigned user + admins)
            if task_data.assigned_to and assigned_to_email:
                try:
                    from ..services.realtime_service import realtime_manager
                    
                    notification_data = {
                        "lead_name": lead.get("name", "Unknown Lead"),
                        "task_title": task_data.task_title,
                        "task_type": task_data.task_type,
                        "priority": task_data.priority,
                        "due_date": due_date_str,
                        "task_id": str(result.inserted_id)
                    }
                    
                    authorized_users = [{"email": assigned_to_email, "name": assigned_to_name}]
                    
                    # ONE call creates notification for assigned user + admins automatically
                    await realtime_manager.notify_task_assigned(lead_id, notification_data, authorized_users)
                    
                    logger.info(f"✅ Unified task assignment notification created for {assigned_to_email}")
                except Exception as notif_error:
                    logger.warning(f"⚠️ Failed to send task notification: {notif_error}")
            
            # 🔥 ENHANCED TIMELINE LOGGING
            try:
                existing_activity = await db.lead_activities.find_one({
                    "lead_id": lead["lead_id"],
                    "activity_type": "task_created",
                    "metadata.task_id": str(result.inserted_id)
                })
                
                if not existing_activity:
                    if assigned_to_name != "Unassigned":
                        description = f"Task '{task_data.task_title}' created and assigned to {assigned_to_name}"
                    else:
                        description = f"Task '{task_data.task_title}' created"
                    
                    activity_metadata = {
                        "task_id": str(result.inserted_id),
                        "task_title": task_data.task_title,
                        "task_type": task_data.task_type,
                        "priority": task_data.priority,
                        "assigned_to": assigned_to_name,
                        "due_date": due_date_str,
                        "due_time": due_time_str,
                        "status": status,
                    }
                    
                    if task_data.task_description:
                        activity_metadata["task_description"] = task_data.task_description[:100] + "..." if len(task_data.task_description) > 100 else task_data.task_description
                    
                    if task_data.notes:
                        activity_metadata["notes"] = task_data.notes[:100] + "..." if len(task_data.notes) > 100 else task_data.notes
                    
                    activity_doc = {
                        "lead_id": lead["lead_id"],
                        "activity_type": "task_created",
                        "title": f"Task Created: {task_data.task_title}",
                        "description": description,
                        "created_by": ObjectId(created_by),
                        "created_by_name": created_by_name,
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                        "is_system_generated": True,
                        "metadata": activity_metadata
                    }
                    
                    activity_result = await db.lead_activities.insert_one(activity_doc)
                    logger.info(f"✅ Timeline activity logged successfully: {activity_result.inserted_id}")
                else:
                    logger.info("⚠️ Timeline activity already exists, skipping duplicate")
                    
            except Exception as activity_error:
                logger.warning(f"⚠️ Failed to log timeline activity: {activity_error}")
                import traceback
                logger.warning(f"Timeline logging error traceback: {traceback.format_exc()}")
            
            return task_doc
            
        except Exception as e:
            logger.error(f"Error creating task: {str(e)}")
            logger.error(f"Error type: {type(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise Exception(f"Failed to create task: {str(e)}")

    async def complete_task(self, task_id: str, completion_notes: Optional[str], user_id: str, user_role: str) -> bool:
        """Mark task as completed and log timeline activity - FIXED ACCESS CONTROL"""
        try:
            db = get_database()
            
            # Get current task first
            current_task = await db.lead_tasks.find_one({"_id": ObjectId(task_id)})
            if not current_task:
                return False
            
            # 🔑 LEAD-BASED ACCESS CONTROL (not task-based)
            if user_role != "admin":
                # Get the lead for this task
                lead = await db.leads.find_one({"lead_id": current_task["lead_id"]})
                if not lead:
                    return False
                
                # Get user info to check email
                user_info = await db.users.find_one({"_id": ObjectId(user_id)})
                if not user_info:
                    return False
                
                user_email = user_info.get("email", "")
                lead_assigned_to = lead.get("assigned_to", "")
                lead_co_assignees = lead.get("co_assignees", [])
                
                # Check if user has access to this lead
                has_lead_access = (
                    lead_assigned_to == user_email or 
                    user_email in lead_co_assignees
                )
                
                if not has_lead_access:
                    logger.warning(f"User {user_email} has no access to lead for task {task_id}")
                    return False
            
            # Get user details for timeline
            user_name = "Unknown User"
            user_details = await db.users.find_one({"_id": ObjectId(user_id)})
            if user_details:
                first_name = user_details.get('first_name', '')
                last_name = user_details.get('last_name', '')
                if first_name and last_name:
                    user_name = f"{first_name} {last_name}".strip()
                else:
                    user_name = user_details.get('email', 'Unknown User')
            
            # Update task
            update_data = {
                "status": "completed",
                "completed_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            if completion_notes:
                update_data["completion_notes"] = completion_notes
            
            result = await db.lead_tasks.update_one({"_id": ObjectId(task_id)}, {"$set": update_data})
            
            if result.modified_count > 0:
                # 🆕 NEW: Auto-remove task notification when completed
                try:
                    result = await db.notification_history.update_many(  # ← Changed from update_one
                        {
                            "task_id": str(task_id),
                            "notification_type": "task_assigned",
                            "read_at": None  # Only update unread notifications
                        },
                        {
                            "$set": {"read_at": datetime.utcnow()}
                        }
                    )
                    logger.info(f"✅ Task notification auto-removed for completed task {task_id} ({result.modified_count} notifications updated)")
                except Exception as notif_error:
                    logger.warning(f"⚠️ Failed to auto-remove task notification: {notif_error}")

                
                # 🔥 LOG TASK COMPLETION TIMELINE ACTIVITY
                try:
                    description = f"Task '{current_task['task_title']}' completed by {user_name}"
                    
                    activity_metadata = {
                        "task_id": str(current_task["_id"]),
                        "task_title": current_task["task_title"],
                        "task_type": current_task.get("task_type"),
                        "completed_by": user_name,
                    }
                    
                    if completion_notes:
                        activity_metadata["completion_notes"] = completion_notes[:200] + "..." if len(completion_notes) > 200 else completion_notes
                    
                    activity_doc = {
                        "lead_id": current_task["lead_id"],
                        "activity_type": "task_completed",
                        "title": f"Task Completed: {current_task['task_title']}",
                        "description": description,
                        "created_by": ObjectId(user_id),
                        "created_by_name": user_name,
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                        "is_system_generated": True,
                        "metadata": activity_metadata
                    }
                    
                    await db.lead_activities.insert_one(activity_doc)
                    logger.info("✅ Task completion timeline activity logged")
                    
                except Exception as activity_error:
                    logger.warning(f"⚠️ Failed to log task completion activity: {activity_error}")
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Error completing task: {str(e)}")
            return False

    async def update_task(self, task_id: str, task_data: TaskUpdate, user_id: str, user_role: str) -> bool:
        """Update a task and log timeline activity - FIXED ACCESS CONTROL WITH DETAILED CHANGES"""
        try:
            db = get_database()
            
            # Get current task first
            current_task = await db.lead_tasks.find_one({"_id": ObjectId(task_id)})
            if not current_task:
                return False
            
            # 🔑 LEAD-BASED ACCESS CONTROL (not task-based)
            if user_role != "admin":
                lead = await db.leads.find_one({"lead_id": current_task["lead_id"]})
                if not lead:
                    return False
                
                user_info = await db.users.find_one({"_id": ObjectId(user_id)})
                if not user_info:
                    return False
                
                user_email = user_info.get("email", "")
                lead_assigned_to = lead.get("assigned_to", "")
                lead_co_assignees = lead.get("co_assignees", [])
                
                has_lead_access = (
                    lead_assigned_to == user_email or 
                    user_email in lead_co_assignees
                )
                
                if not has_lead_access:
                    logger.warning(f"User {user_email} has no access to lead for task {task_id}")
                    return False
            
            # Get user details for timeline
            user_name = "Unknown User"
            user_details = await db.users.find_one({"_id": ObjectId(user_id)})
            if user_details:
                first_name = user_details.get('first_name', '')
                last_name = user_details.get('last_name', '')
                if first_name and last_name:
                    user_name = f"{first_name} {last_name}".strip()
                else:
                    user_name = user_details.get('email', 'Unknown User')
            
            # Prepare update data and track changes
            update_data = {}
            changes = []
            task_reassigned = False
            new_assignee_email = None
            new_assignee_name = None
            
            field_display_names = {
                "task_title": "Title",
                "task_description": "Description", 
                "task_type": "Type",
                "priority": "Priority",
                "assigned_to": "Assigned To",
                "due_date": "Due Date",
                "due_time": "Due Time",
                "status": "Status",
                "notes": "Notes"
            }
            
            for field, value in task_data.dict(exclude_unset=True).items():
                if value is not None:
                    old_value = current_task.get(field)
                    display_name = field_display_names.get(field, field.replace('_', ' ').title())
                    
                    if field == "due_date" and isinstance(value, date):
                        new_value = value.isoformat()
                        update_data[field] = new_value
                        if old_value != new_value:
                            old_display = old_value if old_value else "Not set"
                            new_display = new_value
                            changes.append(f"{display_name}: {old_display} → {new_display}")
                            
                    elif field == "due_time" and isinstance(value, time):
                        new_value = value.isoformat()
                        update_data[field] = new_value  
                        if old_value != new_value:
                            old_display = old_value if old_value else "Not set"
                            new_display = new_value
                            changes.append(f"{display_name}: {old_display} → {new_display}")
                            
                    elif field == "assigned_to":
                        update_data[field] = value
                        if old_value != value:
                            # Get old assigned user name
                            old_name = "Unassigned"
                            if old_value:
                                try:
                                    old_user = await db.users.find_one({"_id": ObjectId(old_value)})
                                    if old_user:
                                        old_first = old_user.get('first_name', '')
                                        old_last = old_user.get('last_name', '')
                                        if old_first and old_last:
                                            old_name = f"{old_first} {old_last}".strip()
                                        else:
                                            old_name = old_user.get('email', 'Unknown User')
                                except:
                                    old_name = "Unknown User"
                            
                            # Get new assigned user name  
                            new_name = "Unassigned"
                            if value:
                                try:
                                    new_user = await db.users.find_one({"_id": ObjectId(value)})
                                    if new_user:
                                        new_first = new_user.get('first_name', '')
                                        new_last = new_user.get('last_name', '')
                                        if new_first and new_last:
                                            new_name = f"{new_first} {new_last}".strip()
                                        else:
                                            new_name = new_user.get('email', 'Unknown User')
                                        
                                        # 🆕 Store for notification
                                        new_assignee_email = new_user.get('email')
                                        new_assignee_name = new_name
                                        task_reassigned = True
                                except:
                                    new_name = "Unknown User"
                            
                            changes.append(f"{display_name}: {old_name} → {new_name}")
                            update_data["assigned_to_name"] = new_name
                            
                    else:
                        update_data[field] = value
                        if old_value != value:
                            old_display = str(old_value) if old_value else "Not set"
                            new_display = str(value)
                            changes.append(f"{display_name}: {old_display} → {new_display}")
            
            if not update_data:
                return True
            
            update_data["updated_at"] = datetime.utcnow()
            
            # Update task
            result = await db.lead_tasks.update_one({"_id": ObjectId(task_id)}, {"$set": update_data})
            
            # 🔥 UPDATED: Send unified notification if task was reassigned
            if result.modified_count > 0 and task_reassigned and new_assignee_email:
                try:
                    from ..services.realtime_service import realtime_manager
                    
                    lead = await db.leads.find_one({"lead_id": current_task["lead_id"]})
                    lead_name = lead.get("name", "Unknown Lead") if lead else "Unknown Lead"
                    
                    notification_data = {
                        "lead_name": lead_name,
                        "task_title": current_task.get("task_title"),
                        "task_type": current_task.get("task_type"),
                        "priority": current_task.get("priority"),
                        "due_date": current_task.get("due_date"),
                        "task_id": str(current_task["_id"]),
                        "reassigned": True,
                        "reassigned_by": user_name
                    }
                    
                    authorized_users = [{"email": new_assignee_email, "name": new_assignee_name}]
                    
                    # ONE call creates notification for new assignee + admins automatically
                    await realtime_manager.notify_task_assigned(
                        current_task.get("lead_id"), 
                        notification_data, 
                        authorized_users
                    )
                    
                    logger.info(f"✅ Unified task reassignment notification created for {new_assignee_email}")
                except Exception as notif_error:
                    logger.warning(f"⚠️ Failed to send task reassignment notification: {notif_error}")
            
            if result.modified_count > 0 and changes:
                # 🔥 LOG TASK UPDATE TIMELINE ACTIVITY WITH DETAILED CHANGES
                try:
                    changes_text = "; ".join(changes[:5])
                    if len(changes) > 5:
                        changes_text += f" (+{len(changes) - 5} more)"
                    
                    description = f"Task '{current_task['task_title']}' updated. Changes: {changes_text}"
                    
                    activity_metadata = {
                        "task_id": str(current_task["_id"]),
                        "task_title": current_task["task_title"],
                        "changes": changes,
                        "changes_count": len(changes),
                        "updated_by": user_name,
                    }
                    
                    activity_doc = {
                        "lead_id": current_task["lead_id"],
                        "activity_type": "task_updated",
                        "description": description,
                        "created_by": ObjectId(user_id),
                        "created_by_name": user_name,
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                        "is_system_generated": True,
                        "metadata": activity_metadata
                    }
                    
                    await db.lead_activities.insert_one(activity_doc)
                    logger.info(f"✅ Task update timeline activity logged with {len(changes)} changes")
                    
                except Exception as activity_error:
                    logger.warning(f"⚠️ Failed to log task update activity: {activity_error}")
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Error updating task: {str(e)}")
            return False
    async def get_lead_tasks(self, lead_id: str, user_id: str, user_role: str, status_filter: Optional[str] = None, page: int = 1, limit: int = 20) -> Dict[str, Any]:
        """Get all tasks for a lead - FIXED ACCESS CONTROL"""
        try:
            logger.info(f"Getting tasks for lead: {lead_id}, user: {user_id}, role: {user_role}")
            
            db = get_database()
            
            # Get lead first to check access and get ObjectId
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                raise ValueError(f"Lead {lead_id} not found")
            
            # 🔑 LEAD ACCESS CONTROL (not task access control)
            if user_role != "admin":
                # Get user info to check email
                user_info = await db.users.find_one({"_id": ObjectId(user_id)})
                if not user_info:
                    raise ValueError("User not found")
                
                user_email = user_info.get("email", "")
                lead_assigned_to = lead.get("assigned_to", "")
                lead_co_assignees = lead.get("co_assignees", [])
                
                # Check if user has access to this lead (primary assignee or co-assignee)
                has_lead_access = (
                    lead_assigned_to == user_email or 
                    user_email in lead_co_assignees
                )
                
                if not has_lead_access:
                    logger.warning(f"User {user_email} has no access to lead {lead_id}")
                    logger.warning(f"Lead assigned to: {lead_assigned_to}")
                    logger.warning(f"Lead co-assignees: {lead_co_assignees}")
                    raise ValueError("You don't have access to this lead")
            
            # ✅ BUILD QUERY - Show ALL tasks for the lead (no user filtering on tasks)
            query = {"lead_object_id": lead["_id"]}
            
            # Status filtering only
            if status_filter and status_filter != "all":
                if status_filter == "overdue":
                    query["status"] = "overdue"
                elif status_filter == "due_today":
                    today = date.today().isoformat()
                    query["due_date"] = today
                    query["status"] = {"$nin": ["completed", "cancelled"]}
                elif status_filter == "pending":
                    query["status"] = {"$in": ["pending", "in_progress"]}
                else:
                    query["status"] = status_filter
            
            logger.info(f"Query: {query}")
            
            # Get ALL tasks for this lead
            skip = (page - 1) * limit
            total = await db.lead_tasks.count_documents(query)
            tasks_cursor = db.lead_tasks.find(query).sort("created_at", -1).skip(skip).limit(limit)
            tasks = await tasks_cursor.to_list(None)

            logger.info(f"Found {len(tasks)} tasks for page {page} (total: {total}) for lead {lead_id}")
            
            # Populate user names for each task
            # Populate user names for each task with efficient ObjectId conversion
            enriched_tasks = []
            for task in tasks:
                # Convert ONLY ObjectId fields to strings (in-place, efficient)
                task["id"] = str(task["_id"])
                task["created_by"] = str(task["created_by"]) if task.get("created_by") else ""
                task["assigned_to"] = str(task["assigned_to"]) if task.get("assigned_to") else None
                task["lead_object_id"] = str(task["lead_object_id"]) if task.get("lead_object_id") else ""
                
                # Remove the original _id to avoid duplication
                task.pop("_id", None)
                
                # Get creator name (same as before)
                try:
                    creator = await db.users.find_one({"_id": ObjectId(task["created_by"])})
                    if creator:
                        first_name = creator.get('first_name', '')
                        last_name = creator.get('last_name', '')
                        if first_name and last_name:
                            task["created_by_name"] = f"{first_name} {last_name}".strip()
                        else:
                            task["created_by_name"] = creator.get('email', 'Unknown User')
                    else:
                        task["created_by_name"] = "Unknown User"
                except Exception as e:
                    logger.warning(f"Could not get creator name: {e}")
                    task["created_by_name"] = "Unknown User"
                
                # Get assigned user name (same as before)
                if task.get("assigned_to"):
                    try:
                        assigned_user = await db.users.find_one({"_id": ObjectId(task["assigned_to"])})
                        if assigned_user:
                            first_name = assigned_user.get('first_name', '')
                            last_name = assigned_user.get('last_name', '')
                            if first_name and last_name:
                                task["assigned_to_name"] = f"{first_name} {last_name}".strip()
                            else:
                                task["assigned_to_name"] = assigned_user.get('email', 'Unknown User')
                        else:
                            task["assigned_to_name"] = "Unassigned"
                    except Exception as e:
                        logger.warning(f"Could not get assigned user name: {e}")
                        task["assigned_to_name"] = "Unassigned"
                else:
                    task["assigned_to_name"] = "Unassigned"
                
                # Add overdue status
                if task.get("due_datetime") and task["status"] not in ["completed", "cancelled"]:
                    task["is_overdue"] = task["due_datetime"] < datetime.utcnow()
                else:
                    task["is_overdue"] = False
                
                enriched_tasks.append(task)
            
            return {
                "tasks": enriched_tasks,
                "total": total,
                "stats": {}
            }
            
        except Exception as e:
            logger.error(f"Error getting lead tasks: {str(e)}")
            raise Exception(f"Failed to get lead tasks: {str(e)}")



    async def get_task_by_id(self, task_id: str, user_id: str, user_role: str) -> Optional[Dict[str, Any]]:
        """Get a specific task by ID"""
        try:
            db = get_database()
            
            task_obj_id = ObjectId(task_id)
            task = await db.lead_tasks.find_one({"_id": task_obj_id})
            
            if not task:
                return None
            
            # Convert ObjectIds and add user names
            result = {
                "id": str(task["_id"]),
                "task_title": task.get("task_title"),
                "task_description": task.get("task_description"),
                "task_type": task.get("task_type"),
                "priority": task.get("priority"),
                "lead_id": task.get("lead_id"), 
                "status": task.get("status"),
                "due_date": task.get("due_date"),
                "due_time": task.get("due_time"),
                "notes": task.get("notes"),
                "created_by": str(task.get("created_by", "")),
                "assigned_to": str(task.get("assigned_to", "")) if task.get("assigned_to") else "",  # FIXED: Convert ObjectId
                "lead_object_id": str(task.get("lead_object_id", "")) if task.get("lead_object_id") else "",  # ADD: This field
                "created_at": task.get("created_at"),
                "updated_at": task.get("updated_at"),
                "completed_at": task.get("completed_at"),
                "completion_notes": task.get("completion_notes"),
                "is_overdue": False
            }
            
            # Get creator name
            try:
                creator = await db.users.find_one({"_id": ObjectId(task["created_by"])})
                if creator:
                    first_name = creator.get('first_name', '')
                    last_name = creator.get('last_name', '')
                    if first_name and last_name:
                        result["created_by_name"] = f"{first_name} {last_name}".strip()
                    else:
                        result["created_by_name"] = creator.get('email', 'Unknown User')
                else:
                    result["created_by_name"] = "Unknown User"
            except:
                result["created_by_name"] = "Unknown User"
            
            # Get assigned user name
            if task.get("assigned_to"):
                try:
                    assigned_user = await db.users.find_one({"_id": ObjectId(task["assigned_to"])})
                    if assigned_user:
                        first_name = assigned_user.get('first_name', '')
                        last_name = assigned_user.get('last_name', '')
                        if first_name and last_name:
                            result["assigned_to_name"] = f"{first_name} {last_name}".strip()
                        else:
                            result["assigned_to_name"] = assigned_user.get('email', 'Unknown User')
                    else:
                        result["assigned_to_name"] = "Unassigned"
                except:
                    result["assigned_to_name"] = "Unassigned"
            else:
                result["assigned_to_name"] = "Unassigned"
            
            # Calculate overdue status
            if task.get("due_datetime") and task["status"] not in ["completed", "cancelled"]:
                result["is_overdue"] = task["due_datetime"] < datetime.utcnow()
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting task by ID: {str(e)}")
            raise e

    async def delete_task(self, task_id: str, user_id: str, user_role: str) -> bool:
        """Delete a task"""
        try:
            db = get_database()
            
            # Build query with access control
            query = {"_id": ObjectId(task_id)}
            if user_role != "admin":
                query["created_by"] = ObjectId(user_id)  # Only creator can delete
            
            result = await db.lead_tasks.delete_one(query)
            return result.deleted_count > 0
            
        except Exception as e:
            logger.error(f"Error deleting task: {str(e)}")
            return False
    
    async def get_user_tasks(self, user_id: str, status_filter: Optional[str] = None, page: int = 1, limit: int = 20) -> Dict[str, Any]:
        """Get all tasks assigned to a user across all leads"""
        try:
            db = get_database()
            
            query = {"assigned_to": user_id}
            
            if status_filter and status_filter != "all":
                if status_filter == "overdue":
                    query["status"] = "overdue"
                elif status_filter == "due_today":
                    today = date.today().isoformat()
                    query["due_date"] = today
                    query["status"] = {"$nin": ["completed", "cancelled"]}
                else:
                    query["status"] = status_filter
            
            skip = (page - 1) * limit
            total = await db.lead_tasks.count_documents(query)
            tasks_cursor = db.lead_tasks.find(query).sort("due_datetime", 1).skip(skip).limit(limit)
            tasks = await tasks_cursor.to_list(None)            
            
            enriched_tasks = []
            for task in tasks:
                task["id"] = str(task["_id"])
                task["created_by"] = str(task["created_by"])
                task["lead_object_id"] = str(task["lead_object_id"])
                
                # Add creator name
                try:
                    creator = await db.users.find_one({"_id": ObjectId(task["created_by"])})
                    if creator:
                        first_name = creator.get('first_name', '')
                        last_name = creator.get('last_name', '')
                        if first_name and last_name:
                            task["created_by_name"] = f"{first_name} {last_name}".strip()
                        else:
                            task["created_by_name"] = creator.get('email', 'Unknown User')
                    else:
                        task["created_by_name"] = "Unknown User"
                except Exception as e:
                    task["created_by_name"] = "Unknown User"
                
                # Add assigned user name
                if task.get("assigned_to"):
                    try:
                        assigned_user = await db.users.find_one({"_id": ObjectId(task["assigned_to"])})
                        if assigned_user:
                            first_name = assigned_user.get('first_name', '')
                            last_name = assigned_user.get('last_name', '')
                            if first_name and last_name:
                                task["assigned_to_name"] = f"{first_name} {last_name}".strip()
                            else:
                                task["assigned_to_name"] = assigned_user.get('email', 'Unknown User')
                        else:
                            task["assigned_to_name"] = "Unassigned"
                    except Exception as e:
                        task["assigned_to_name"] = "Unassigned"
                else:
                    task["assigned_to_name"] = "Unassigned"
                
                # 🔥 NEW: Add lead name by looking up the lead
                try:
                    # Get lead by lead_id (string field in task)
                    lead = await db.leads.find_one({"lead_id": task["lead_id"]})
                    if lead:
                        task["lead_name"] = lead.get("name", "Unknown Lead")
                    else:
                        task["lead_name"] = "Unknown Lead"
                except Exception as e:
                    logger.warning(f"Could not get lead name for task {task['id']}: {e}")
                    task["lead_name"] = "Unknown Lead"
                
                # Add overdue status
                if task.get("due_datetime") and task["status"] not in ["completed", "cancelled"]:
                    task["is_overdue"] = task["due_datetime"] < datetime.utcnow()
                else:
                    task["is_overdue"] = False
                
                enriched_tasks.append(task)
            
            return {
                "tasks": enriched_tasks,
                "total": total
            }
            
        except Exception as e:
            logger.error(f"Error getting user tasks: {str(e)}")
            return {"tasks": [], "total": 0}

    async def get_all_tasks(self, status_filter: Optional[str] = None, page: int = 1, limit: int = 20) -> Dict[str, Any]:
        """Get ALL tasks from ALL users - Admin only function"""
        try:
            db = get_database()
            
            # Build query for all tasks (no user filtering)
            query = {}
            
            # Status filtering
            if status_filter and status_filter != "all":
                if status_filter == "overdue":
                    query["status"] = "overdue"
                elif status_filter == "due_today":
                    today = date.today().isoformat()
                    query["due_date"] = today
                    query["status"] = {"$nin": ["completed", "cancelled"]}
                elif status_filter == "pending":
                    query["status"] = {"$in": ["pending", "in_progress"]}
                else:
                    query["status"] = status_filter
            
            logger.info(f"Admin query for all tasks: {query}")
            
            # Get ALL tasks sorted by creation date
            skip = (page - 1) * limit
            total = await db.lead_tasks.count_documents(query)
            tasks_cursor = db.lead_tasks.find(query).sort("created_at", -1).skip(skip).limit(limit)
            tasks = await tasks_cursor.to_list(None)
            
            logger.info(f"Found {len(tasks)} total tasks across all users")
            
            # Enrich tasks with user names and lead info
            enriched_tasks = []
            for task in tasks:
                task["id"] = str(task["_id"])
                task["created_by"] = str(task["created_by"])
                task["lead_object_id"] = str(task["lead_object_id"])
                
                # Get creator name
                try:
                    creator = await db.users.find_one({"_id": ObjectId(task["created_by"])})
                    if creator:
                        first_name = creator.get('first_name', '')
                        last_name = creator.get('last_name', '')
                        if first_name and last_name:
                            task["created_by_name"] = f"{first_name} {last_name}".strip()
                        else:
                            task["created_by_name"] = creator.get('email', 'Unknown User')
                    else:
                        task["created_by_name"] = "Unknown User"
                except Exception as e:
                    task["created_by_name"] = "Unknown User"
                
                # Get assigned user name
                if task.get("assigned_to"):
                    try:
                        assigned_user = await db.users.find_one({"_id": ObjectId(task["assigned_to"])})
                        if assigned_user:
                            first_name = assigned_user.get('first_name', '')
                            last_name = assigned_user.get('last_name', '')
                            if first_name and last_name:
                                task["assigned_to_name"] = f"{first_name} {last_name}".strip()
                            else:
                                task["assigned_to_name"] = assigned_user.get('email', 'Unknown User')
                        else:
                            task["assigned_to_name"] = "Unassigned"
                    except Exception as e:
                        task["assigned_to_name"] = "Unassigned"
                else:
                    task["assigned_to_name"] = "Unassigned"
                
                # 🔥 NEW: Add lead name by looking up the lead
                try:
                    # Get lead by lead_id (string field in task)
                    lead = await db.leads.find_one({"lead_id": task["lead_id"]})
                    if lead:
                        task["lead_name"] = lead.get("name", "Unknown Lead")
                    else:
                        task["lead_name"] = "Unknown Lead"
                        
                except Exception as e:
                    logger.warning(f"Could not get lead name for task {task['id']}: {e}")
                    task["lead_name"] = "Unknown Lead"
                
                # Add overdue status
                if task.get("due_datetime") and task["status"] not in ["completed", "cancelled"]:
                    task["is_overdue"] = task["due_datetime"] < datetime.utcnow()
                else:
                    task["is_overdue"] = False
                
                enriched_tasks.append(task)
            
            return {
                "tasks": enriched_tasks,
                "total": total
            }
            
        except Exception as e:
            logger.error(f"Error getting all tasks: {str(e)}")
            return {"tasks": [], "total": 0}

    async def _calculate_task_stats(self, lead_id: str, user_id: str, user_role: str) -> Dict[str, int]:
        """Calculate task statistics for a lead - FIXED ACCESS CONTROL"""
        try:
            db = get_database()
            
            # Get lead ObjectId and check access
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                return {}
            
            # 🔑 LEAD ACCESS CONTROL
            if user_role != "admin":
                # Get user info to check email
                user_info = await db.users.find_one({"_id": ObjectId(user_id)})
                if not user_info:
                    return {}
                
                user_email = user_info.get("email", "")
                lead_assigned_to = lead.get("assigned_to", "")
                lead_co_assignees = lead.get("co_assignees", [])
                
                # Check if user has access to this lead
                has_lead_access = (
                    lead_assigned_to == user_email or 
                    user_email in lead_co_assignees
                )
                
                if not has_lead_access:
                    return {}
            
            # Build base query - ALL tasks for this lead (no user filtering)
            base_query = {"lead_object_id": lead["_id"]}
            
            # Calculate various stats
            total_tasks = await db.lead_tasks.count_documents(base_query)
            
            pending_query = {**base_query, "status": {"$in": ["pending", "in_progress"]}}
            pending_tasks = await db.lead_tasks.count_documents(pending_query)
            
            overdue_query = {**base_query, "status": "overdue"}
            overdue_tasks = await db.lead_tasks.count_documents(overdue_query)
            
            today = date.today().isoformat()
            due_today_query = {
                **base_query,
                "due_date": today,
                "status": {"$nin": ["completed", "cancelled"]}
            }
            due_today = await db.lead_tasks.count_documents(due_today_query)
            
            completed_query = {**base_query, "status": "completed"}
            completed_tasks = await db.lead_tasks.count_documents(completed_query)
            
            return {
                "total_tasks": total_tasks,
                "pending_tasks": pending_tasks,
                "overdue_tasks": overdue_tasks,
                "due_today": due_today,
                "completed_tasks": completed_tasks
            }
            
        except Exception as e:
            logger.error(f"Error calculating task stats: {str(e)}")
            return {}

    async def _calculate_global_task_stats(self, user_id: str, user_role: str, status_filter: Optional[str] = None) -> Dict[str, int]:
        """Calculate task statistics globally - with user access control"""
        try:
            db = get_database()
            
            # Build base query based on user role
            if user_role == "admin":
                # Admins see ALL tasks from ALL leads
                base_query = {}
                logger.info("Admin accessing global task stats - no filtering")
            else:
                # Regular users only see tasks from leads they have access to
                user_info = await db.users.find_one({"_id": ObjectId(user_id)})
                if not user_info:
                    return {}
                
                user_email = user_info.get("email", "")
                
                # Find all leads the user has access to
                accessible_leads_cursor = db.leads.find({
                    "$or": [
                        {"assigned_to": user_email},
                        {"co_assignees": user_email}
                    ]
                })
                accessible_leads = await accessible_leads_cursor.to_list(None)
                
                if not accessible_leads:
                    return {
                        "total_tasks": 0, "pending_tasks": 0, "overdue_tasks": 0,
                        "due_today": 0, "completed_tasks": 0
                    }
                
                # Get all lead ObjectIds user has access to
                accessible_lead_object_ids = [lead["_id"] for lead in accessible_leads]
                
                # Base query: only tasks from leads user has access to
                base_query = {"lead_object_id": {"$in": accessible_lead_object_ids}}
                logger.info(f"User {user_email} has access to {len(accessible_leads)} leads")
            
            # Add status filter if provided
            if status_filter and status_filter != "all":
                if status_filter == "overdue":
                    base_query["status"] = "overdue"
                elif status_filter == "due_today":
                    today = date.today().isoformat()
                    base_query["due_date"] = today
                    base_query["status"] = {"$nin": ["completed", "cancelled"]}
                elif status_filter == "pending":
                    base_query["status"] = {"$in": ["pending", "in_progress"]}
                else:
                    base_query["status"] = status_filter
            
            # Calculate various stats
            total_tasks = await db.lead_tasks.count_documents(base_query)
            
            pending_query = {**base_query, "status": {"$in": ["pending", "in_progress"]}}
            pending_tasks = await db.lead_tasks.count_documents(pending_query)
            
            overdue_query = {**base_query, "status": "overdue"}
            overdue_tasks = await db.lead_tasks.count_documents(overdue_query)
            
            today = date.today().isoformat()
            due_today_query = {
                **base_query,
                "due_date": today,
                "status": {"$nin": ["completed", "cancelled"]}
            }
            due_today = await db.lead_tasks.count_documents(due_today_query)
            
            completed_query = {**base_query, "status": "completed"}
            completed_tasks = await db.lead_tasks.count_documents(completed_query)
            
            return {
                "total_tasks": total_tasks,
                "pending_tasks": pending_tasks,
                "overdue_tasks": overdue_tasks,
                "due_today": due_today,
                "completed_tasks": completed_tasks
            }
            
        except Exception as e:
            logger.error(f"Error calculating global task stats: {str(e)}")
            return {}

# Global service instance
task_service = TaskService()