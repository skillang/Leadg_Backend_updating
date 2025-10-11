# app/routers/tasks.py
from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import logging
from bson import ObjectId

from app.decorators.timezone_decorator import convert_dates_to_ist, convert_task_dates

from ..config.database import get_database
from ..utils.dependencies import get_current_active_user, get_admin_user
from ..models.task import (
    TaskCreate, TaskUpdate, TaskResponse, TaskListResponse, 
    TaskStatsResponse, TaskCompleteRequest, TaskBulkAction
)
from ..services.task_service import task_service

logger = logging.getLogger(__name__)
router = APIRouter()

def get_user_id(current_user: Dict[str, Any]) -> str:
    """Get user ID from current_user dict, handling different possible keys"""
    user_id = current_user.get("user_id") or current_user.get("_id") or current_user.get("id")
    if not user_id:
        available_keys = list(current_user.keys())
        raise ValueError(f"No user ID found in token. Available keys: {available_keys}")
    return str(user_id)

@router.post("/leads/{lead_id}/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    lead_id: str,
    task_data: TaskCreate,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Create a new task for a lead
    - Admins can create tasks for any lead
    - Users can create tasks for their assigned leads only
    """
    try:
        logger.info(f"Creating task for lead {lead_id} by user {current_user.get('email')}")
        logger.info(f"User role: {current_user.get('role')}")
        
        # Get user_id directly without helper function
        user_id = current_user.get("user_id") or current_user.get("_id") or current_user.get("id")
        if not user_id:
            logger.error(f"No user ID found in token. Available keys: {list(current_user.keys())}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User ID not found in authentication token"
            )
        
        logger.info(f"Using user_id: {user_id}")
        
        # 🔒 PERMISSION CHECK: Users can only create tasks for leads assigned to them
        if current_user["role"] != "admin":
            logger.info(f"Non-admin user {current_user['email']} - checking lead access")
            db = get_database()  # No await!
            lead = await db.leads.find_one({
                "lead_id": lead_id,
                "assigned_to": current_user["email"]
            })
            if not lead:
                logger.warning(f"User {current_user['email']} tried to create task for unauthorized lead {lead_id}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have permission to create tasks for this lead. You can only create tasks for leads assigned to you."
                )
            logger.info(f"Lead access confirmed for {current_user['email']}")
        else:
            logger.info(f"Admin user {current_user['email']} - skipping lead access check")
        
        # Create the task
        logger.info(f"Calling task_service.create_task")
        new_task = await task_service.create_task(
            lead_id=lead_id, 
            task_data=task_data, 
            created_by=str(user_id)
        )
        
        logger.info(f"Task service returned: {type(new_task)}")
        logger.info(f"Task created with ID: {new_task.get('id')}")
        
        # Return success response
        return {
            "success": True,
            "message": "Task created successfully",
            "task_id": new_task.get('id'),
            "task_title": new_task.get('task_title'),
            "lead_id": lead_id,
            "assigned_to": task_data.assigned_to,
            "priority": task_data.priority,
            "due_date": task_data.due_date,
            "created_by": current_user.get('email')
        }
        
    except HTTPException as he:
        logger.error(f"HTTPException in create_task: {he.detail}")
        raise he
    except Exception as e:
        logger.error(f"Unexpected error in create_task: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {str(e)}"
        )

@router.get("/leads/{lead_id}/tasks",)
@convert_task_dates()
async def get_lead_tasks(
    lead_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, description="Filter by status: pending, overdue, due_today, completed, all"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get all tasks for a specific lead
    - Admins see all tasks for the lead
    - Users see tasks for leads they have access to (primary + co-assignee)
    """
    try:
        logger.info(f"Getting tasks for lead {lead_id} by user {current_user.get('email')}")
        
        # ✅ FIXED: Verify user has access to this lead (PRIMARY OR CO-ASSIGNEE)
        if current_user["role"] != "admin":
            db = get_database()
            lead = await db.leads.find_one({
                "lead_id": lead_id,
                "$or": [
                    {"assigned_to": current_user["email"]},
                    {"co_assignees": current_user["email"]}  # 🆕 ADDED
                ]
            })
            if not lead:
                logger.warning(f"User {current_user['email']} tried to access unauthorized lead {lead_id}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have permission to view tasks for this lead"
                )
        
        result = await task_service.get_lead_tasks(
            lead_id, 
            current_user.get("user_id") or current_user.get("_id") or current_user.get("id"),
            current_user["role"], 
            status_filter,
            page,      
            limit 
        )
        
        return {
            "tasks": result["tasks"],
            "stats": result.get("stats", {}),
            "pagination": {
                "page": page,
                "limit": limit,
                "total": result["total"],
                "pages": (result["total"] + limit - 1) // limit,
                "has_next": page * limit < result["total"],
                "has_prev": page > 1
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get lead tasks error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve tasks: {str(e)}"
        )
    
@router.get("/leads/{lead_id}/tasks/stats", response_model=TaskStatsResponse)
@convert_dates_to_ist()
async def get_lead_task_stats(
    lead_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get task statistics for a lead
    Returns: total_tasks, overdue_tasks, due_today, completed_tasks, etc.
    """
    try:
        logger.info(f"Getting task stats for lead {lead_id} by user {current_user.get('email')}")
        
        # ✅ FIXED: Verify user has access to this lead (PRIMARY OR CO-ASSIGNEE)
        if current_user["role"] != "admin":
            db = get_database()
            lead = await db.leads.find_one({
                "lead_id": lead_id,
                "$or": [
                    {"assigned_to": current_user["email"]},
                    {"co_assignees": current_user["email"]}  # 🆕 ADDED
                ]
            })
            if not lead:
                logger.warning(f"User {current_user['email']} tried to access unauthorized lead {lead_id}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have permission to view stats for this lead"
                )
        
        stats = await task_service._calculate_task_stats(
            lead_id, 
            current_user.get("user_id") or current_user.get("_id") or current_user.get("id"),
            current_user["role"]
        )
        
        return TaskStatsResponse(**stats)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get task stats error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve task statistics: {str(e)}"
        )
    
@router.get("/{task_id}")
@convert_task_dates()
async def get_task(
    task_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """Get a specific task by ID"""
    try:
        logger.info(f"=== GET TASK DEBUG START ===")
        logger.info(f"Task ID requested: {task_id}")
        logger.info(f"User: {current_user.get('email')}")
        
        # Get user_id
        user_id = current_user.get("user_id") or current_user.get("_id") or current_user.get("id")
        if not user_id:
            logger.error("No user ID found in token")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User ID not found in authentication token"
            )
        
        logger.info(f"User ID extracted: {user_id}")
        
        # Call task service
        logger.info("Calling task_service.get_task_by_id...")
        task = await task_service.get_task_by_id(
            task_id, 
            str(user_id),
            current_user["role"]
        )
        
        if not task:
            logger.warning("Task service returned None")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found"
            )
        
        logger.info("✅ Task retrieved successfully")
        return task
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve task: {str(e)}"
        )

# ✅ FIXED: Update task endpoint
@router.put("/{task_id}")  # ✅ Fixed route - removed duplicate "tasks"
async def update_task(
    task_id: str,
    task_data: TaskUpdate,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Update a task
    - Users can update tasks assigned to them or created by them
    - Admins can update any task
    """
    try:
        logger.info(f"Updating task {task_id} by user {current_user.get('email')}")
        
        user_id = current_user.get("user_id") or current_user.get("_id") or current_user.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User ID not found in authentication token"
            )
        
        success = await task_service.update_task(
            task_id, 
            task_data, 
            str(user_id),  # ✅ Convert to string
            current_user["role"]
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found or you don't have permission to update it"
            )
        
        # Return updated task
        updated_task = await task_service.get_task_by_id(
            task_id, 
            str(user_id),  # ✅ Convert to string
            current_user["role"]
        )
        
        return {
            "success": True,
            "message": "Task updated successfully",
            "task": updated_task
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update task error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update task: {str(e)}"
        )

# ✅ FIXED: Complete task endpoint
@router.patch("/{task_id}/complete")  # ✅ Fixed route - removed duplicate "tasks"
async def complete_task(
    task_id: str,
    completion_data: TaskCompleteRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Mark a task as completed
    - Users can complete tasks assigned to them or created by them
    - Admins can complete any task
    """
    try:
        logger.info(f"Completing task {task_id} by user {current_user.get('email')}")
        
        user_id = current_user.get("user_id") or current_user.get("_id") or current_user.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User ID not found in authentication token"
            )
        
        success = await task_service.complete_task(
            task_id, 
            completion_data.completion_notes, 
            str(user_id),  # ✅ Convert to string
            current_user["role"]
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found or you don't have permission to complete it"
            )
        
        logger.info(f"Task {task_id} completed by {current_user['email']}")
        
        return {
            "success": True,
            "message": "Task completed successfully",
            "task_id": task_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Complete task error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to complete task: {str(e)}"
        )

# ✅ FIXED: Delete task endpoint
@router.delete("/{task_id}")  # ✅ Fixed route - removed duplicate "tasks"
async def delete_task(
    task_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Delete a task
    - Users can delete tasks they created
    - Admins can delete any task
    """
    try:
        logger.info(f"Deleting task {task_id} by user {current_user.get('email')}")
        
        user_id = current_user.get("user_id") or current_user.get("_id") or current_user.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User ID not found in authentication token"
            )
        
        success = await task_service.delete_task(
            task_id, 
            str(user_id),  # ✅ Convert to string
            current_user["role"]
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found or you don't have permission to delete it"
            )
        
        logger.info(f"Task {task_id} deleted by {current_user['email']}")
        
        return {
            "success": True,
            "message": "Task deleted successfully",
            "task_id": task_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete task error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete task: {str(e)}"
        )

@router.get("/tasks/my-tasks", response_model=TaskListResponse)
@convert_task_dates()
async def get_my_tasks(
     page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, description="Filter by status: pending, overdue, due_today, completed, all"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get all tasks assigned to the current user across all leads
    For admins: Returns ALL tasks from ALL users with global stats
    For regular users: Returns only tasks assigned to them with their stats
    """
    try:
        logger.info(f"Getting tasks for user {current_user.get('email')} with role {current_user.get('role')}")
        
        user_id = current_user.get("user_id") or current_user.get("_id") or current_user.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User ID not found in authentication token"
            )
        
        # Check if user is admin
        if current_user.get("role") == "admin":
            # For admins, get ALL tasks from ALL users
            result = await task_service.get_all_tasks(status_filter, page, limit)
            logger.info(f"Admin {current_user.get('email')} retrieved {result['total']} total tasks")
        else:
            # For regular users, get only their assigned tasks
            result = await task_service.get_user_tasks(
                str(user_id),
                status_filter,
                page,     
                limit 
            )
            logger.info(f"User {current_user.get('email')} retrieved {result['total']} assigned tasks")
        
        # Use the same global stats method for both admin and users
        # The method already has access control built-in
        global_stats = await task_service._calculate_global_task_stats(
            str(user_id), 
            current_user.get("role"),
            status_filter
        )
        
        return {
                "tasks": result["tasks"],
                "stats": global_stats,
                "pagination": {
                    "page": page,
                    "limit": limit, 
                    "total": result["total"],  # ✅ Use result['total'] from service
                    "pages": (result["total"] + limit - 1) // limit,
                    "has_next": page * limit < result["total"],
                    "has_prev": page > 1
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get my tasks error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve your tasks: {str(e)}"
        )

@router.get("/tasks/assignable-users")
@convert_dates_to_ist()
async def get_assignable_users_for_tasks(
    lead_id: str = Query(..., description="Lead ID to get assigned users for"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)  # Removed admin requirement
):
    """
    Get list of users assigned to a specific lead (primary assignee + co-assignees)
    This endpoint is accessible by all authenticated users, not just admins.
    """
    try:
        logger.info(f"Getting assignable users for lead {lead_id} by {current_user.get('email')}")
        
        db = get_database()
        
        # Find the lead by lead_id
        lead = await db.leads.find_one({"lead_id": lead_id})
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lead {lead_id} not found"
            )
        
        # Check permissions - users can only access leads they are assigned to
        user_role = current_user.get("role", "user")
        user_email = current_user.get("email")
        
        if user_role != "admin":
            # Check if user is assigned to this lead (either as primary or co-assignee)
            assigned_to = lead.get("assigned_to")
            co_assignees = lead.get("co_assignees", [])
            
            if user_email not in [assigned_to] + co_assignees:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have permission to view assignable users for this lead. You can only access leads assigned to you."
                )
        
        # Collect all assigned user emails
        assigned_user_emails = []
        
        # Add primary assignee
        if lead.get("assigned_to"):
            assigned_user_emails.append(lead.get("assigned_to"))
        
        # Add co-assignees
        co_assignees = lead.get("co_assignees", [])
        assigned_user_emails.extend(co_assignees)
        
        # Remove duplicates and filter out None values
        assigned_user_emails = list(set(filter(None, assigned_user_emails)))
        
        if not assigned_user_emails:
            return {
                "success": True,
                "users": [],
                "message": "No users are currently assigned to this lead"
            }
        
        # Get user details for all assigned users
        users = await db.users.find(
            {
                "email": {"$in": assigned_user_emails},
                "is_active": True
            },
            {"first_name": 1, "last_name": 1, "email": 1, "role": 1, "department": 1}
        ).to_list(None)
        
        # Build response with user details
        assignable_users = []
        for user in users:
            # Determine if user is primary assignee or co-assignee
            is_primary = user["email"] == lead.get("assigned_to")
            
            user_info = {
                "id": str(user["_id"]),
                "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                "email": user["email"],
                "role": user["role"],
                "department": user.get("department"),
                "assignment_type": "primary" if is_primary else "co-assignee"
            }
            
            # Fallback to email if name is empty
            if not user_info["name"]:
                user_info["name"] = user["email"]
                
            assignable_users.append(user_info)
        
        # Sort users: primary assignee first, then co-assignees
        assignable_users.sort(key=lambda x: (x["assignment_type"] != "primary", x["name"]))
        
        return {
            "success": True,
            "users": assignable_users,
            "lead_id": lead_id,
            "total_assigned_users": len(assignable_users),
            "assignment_summary": {
                "primary_assignee": lead.get("assigned_to"),
                "co_assignees_count": len(co_assignees),
                "is_multi_assigned": lead.get("is_multi_assigned", False)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get assignable users error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve assignable users: {str(e)}"
        )
    
@router.post("/tasks/bulk-action")
async def bulk_task_action(
    bulk_action: TaskBulkAction,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Perform bulk actions on multiple tasks
    Actions: complete, delete, reassign
    """
    try:
        logger.info(f"Bulk action {bulk_action.action} by {current_user.get('email')} on {len(bulk_action.task_ids)} tasks")
        
        user_id = current_user.get("user_id") or current_user.get("_id") or current_user.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User ID not found in authentication token"
            )
        
        db = get_database()  # ✅ Removed await
        success_count = 0
        failed_tasks = []
        
        for task_id in bulk_action.task_ids:
            try:
                if bulk_action.action == "complete":
                    success = await task_service.complete_task(
                        task_id, 
                        bulk_action.notes, 
                        str(user_id),  # ✅ Convert to string
                        current_user["role"]
                    )
                elif bulk_action.action == "delete":
                    success = await task_service.delete_task(
                        task_id, 
                        str(user_id),  # ✅ Convert to string
                        current_user["role"]
                    )
                elif bulk_action.action == "reassign" and bulk_action.assigned_to:
                    from ..models.task import TaskUpdate
                    task_update = TaskUpdate(assigned_to=bulk_action.assigned_to)
                    success = await task_service.update_task(
                        task_id, 
                        task_update, 
                        str(user_id),  # ✅ Convert to string
                        current_user["role"]
                    )
                else:
                    failed_tasks.append(task_id)
                    continue
                
                if success:
                    success_count += 1
                else:
                    failed_tasks.append(task_id)
                    
            except Exception as e:
                logger.error(f"Bulk action failed for task {task_id}: {str(e)}")
                failed_tasks.append(task_id)
        
        logger.info(f"Bulk {bulk_action.action}: {success_count} tasks processed by {current_user['email']}")
        
        return {
            "success": True,
            "message": f"Bulk {bulk_action.action} completed",
            "processed_count": success_count,
            "failed_tasks": failed_tasks
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk task action error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to perform bulk action: {str(e)}"
        )

# Debug endpoints
@router.get("/debug/simple")
async def simple_debug():
    """Simple debug test"""
    try:
        from ..services.task_service import task_service
        from ..models.task import TaskCreate
        return {
            "success": True, 
            "message": "Task imports working",
            "task_service": str(type(task_service))
        }
    except Exception as e:
        import traceback
        return {
            "success": False, 
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@router.get("/debug/data")
async def debug_check_data(
    current_user: dict = Depends(get_current_active_user)
):
    """Check available data for task creation"""
    try:
        db = get_database()  # ✅ Removed await
        
        # Get leads
        leads = await db.leads.find({}).to_list(None)
        lead_list = []
        for lead in leads:
            lead_list.append({
                "lead_id": lead.get("lead_id"),
                "company": lead.get("company_name"),
                "assigned_to": lead.get("assigned_to"),
                "_id": str(lead.get("_id"))
            })
        
        # Get users
        users = await db.users.find({}).to_list(None)
        user_list = []
        for user in users:
            user_list.append({
                "user_id": str(user.get("_id")),
                "email": user.get("email"),
                "name": user.get("full_name")
            })
        
        return {
            "success": True,
            "leads": lead_list,
            "users": user_list,
            "current_user": {
                "email": current_user.get("email"),
                "user_id": current_user.get("user_id"),
                "role": current_user.get("role")
            }
        }
        
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@router.post("/debug/test-create/leads/{lead_id}/tasks")
async def debug_test_create(
    lead_id: str,
    task_data: TaskCreate,
    current_user: dict = Depends(get_current_active_user)
):
    """Test task creation with detailed debugging"""
    result = {"steps": []}
    
    try:
        # Step 1: Basic validation
        result["steps"].append("1. Starting debug test")
        result["lead_id"] = lead_id
        result["task_data"] = task_data.dict()
        result["user"] = current_user.get("email")
        
        # Step 2: Database connection
        result["steps"].append("2. Getting database connection")
        db = get_database()  # ✅ Removed await
        
        # Step 3: Check lead exists
        result["steps"].append("3. Checking if lead exists")
        lead = await db.leads.find_one({"lead_id": lead_id})
        if not lead:
            result["error"] = f"Lead {lead_id} not found"
            return result
        
        result["lead_found"] = True
        result["lead_company"] = lead.get("company_name")
        
        # Step 4: Check user exists
        result["steps"].append("4. Checking assigned user")
        from bson import ObjectId
        try:
            user = await db.users.find_one({"_id": ObjectId(task_data.assigned_to)})
            if not user:
                result["error"] = f"User {task_data.assigned_to} not found"
                return result
            result["user_found"] = True
            result["assigned_user"] = user.get("email")
        except Exception as e:
            result["error"] = f"Invalid user ID: {str(e)}"
            return result
        
        # Step 5: Try to call task service
        result["steps"].append("5. Calling task service")
        
        user_id = current_user.get("user_id") or current_user.get("_id") or current_user.get("id")
        if not user_id:
            result["error"] = "User ID not found in authentication token"
            return result
        
        task = await task_service.create_task(
            lead_id=lead_id,
            task_data=task_data,
            created_by=str(user_id)  # ✅ Convert to string
        )
        
        result["success"] = True
        result["task_created"] = True
        result["task_id"] = task.get('id', 'Unknown')
        return result
        
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        result["error_type"] = type(e).__name__
        import traceback
        result["traceback"] = traceback.format_exc()
        return result
    
@router.get("/debug/test-method")
async def test_get_task_method():
    """Test if get_task_by_id method exists"""
    try:
        # Check if the method exists
        method = getattr(task_service, 'get_task_by_id', None)
        if method:
            return {
                "status": "success",
                "message": "get_task_by_id method exists",
                "method_type": str(type(method))
            }
        else:
            return {
                "status": "error", 
                "message": "get_task_by_id method NOT found"
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error checking method: {str(e)}"
        }