# app/routers/tasks.py - RBAC-Enabled Task Management Router
# 🔄 UPDATED: Role checks replaced with RBAC permission checks (108 permissions)
# ✅ All endpoints now use permission-based access control

from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import logging
from bson import ObjectId

# Services
from app.services.task_service import task_service
from app.services.rbac_service import RBACService

# Dependencies
from app.utils.dependencies import (
    get_current_active_user,
    get_user_with_permission
)

# Decorators
from app.decorators.timezone_decorator import convert_dates_to_ist, convert_task_dates

# Models
from ..models.task import (
    TaskCreate, TaskUpdate, TaskResponse, TaskListResponse, 
    TaskStatsResponse, TaskCompleteRequest, TaskBulkAction
)

# Database
from ..config.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize RBAC service
rbac_service = RBACService()


# ============================================================================
# RBAC HELPER FUNCTIONS
# ============================================================================

def get_user_id(current_user: Dict[str, Any]) -> str:
    """Get user ID from current_user dict, handling different possible keys"""
    user_id = current_user.get("user_id") or current_user.get("_id") or current_user.get("id")
    if not user_id:
        available_keys = list(current_user.keys())
        raise ValueError(f"No user ID found in token. Available keys: {available_keys}")
    return str(user_id)


async def check_lead_access_for_task(lead_id: str, user_email: str, current_user: Dict) -> bool:
    """
    Check if user has access to a lead (for task operations)
    
    Returns True if:
    - User has task.view_all permission, OR
    - Lead is assigned to user (primary or co-assignee)
    """
    # Check if user has view_all permission
    has_view_all = await rbac_service.check_permission(current_user, "task.view_all")
    if has_view_all:
        return True
    
    # Check if user has access to the lead
    db = get_database()
    lead = await db.leads.find_one({"lead_id": lead_id})
    
    if not lead:
        return False
    
    # Check if user is assigned to the lead (primary or co-assignee)
    assigned_to = lead.get("assigned_to")
    co_assignees = lead.get("co_assignees", [])
    
    return user_email in ([assigned_to] + co_assignees)


async def check_task_access(task: Dict, user_id: str, current_user: Dict) -> bool:
    """
    Check if user has access to a specific task
    
    Returns True if:
    - User has task.view_all permission, OR
    - Task is assigned to user, OR
    - Task was created by user
    """
    # Check if user has view_all permission
    has_view_all = await rbac_service.check_permission(current_user, "task.view_all")
    if has_view_all:
        return True
    
    # Check if task is assigned to user or created by user
    assigned_to = task.get("assigned_to")
    created_by = task.get("created_by")
    
    return str(assigned_to) == str(user_id) or str(created_by) == str(user_id)


async def build_task_query_with_rbac(current_user: Dict, db, lead_id: Optional[str] = None) -> Dict:
    """
    Build MongoDB query for tasks based on user's RBAC permissions
    
    Permission hierarchy:
    - task.view_all: See ALL tasks (no restrictions)
    - task.view_team: See team members' tasks
    - task.view: See only assigned tasks (default)
    """
    user_id = get_user_id(current_user)
    
    # Check permissions in order of scope (broadest first)
    has_view_all = await rbac_service.check_permission(current_user, "task.view_all")
    if has_view_all:
        base_query = {}
    else:
        has_view_team = await rbac_service.check_permission(current_user, "task.view_team")
        if has_view_team:
            # Get team members
            team_members = await db.users.find(
                {"reports_to_email": current_user.get("email")},
                {"_id": 1}
            ).to_list(None)
            team_member_ids = [str(member["_id"]) for member in team_members]
            
            base_query = {
                "$or": [
                    {"assigned_to": user_id},
                    {"created_by": user_id},
                    {"assigned_to": {"$in": team_member_ids}}
                ]
            }
        else:
            # Default: view - only see assigned or created tasks
            base_query = {
                "$or": [
                    {"assigned_to": user_id},
                    {"created_by": user_id}
                ]
            }
    
    # Add lead_id filter if specified
    if lead_id:
        if "$and" in base_query:
            base_query["$and"].append({"lead_id": lead_id})
        elif base_query:
            base_query = {"$and": [base_query, {"lead_id": lead_id}]}
        else:
            base_query["lead_id"] = lead_id
    
    return base_query


# ============================================================================
# RBAC-ENABLED TASK CRUD OPERATIONS
# ============================================================================

@router.post("/leads/{lead_id}/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    lead_id: str,
    task_data: TaskCreate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("task.add"))
):
    """
    🔄 RBAC-ENABLED: Create a new task for a lead
    
    **Required Permission:** `task.add`
    
    Users can only create tasks for leads they have access to.
    """
    try:
        logger.info(f"Creating task for lead {lead_id} by user {current_user.get('email')}")
        
        user_id = get_user_id(current_user)
        
        # Check if user has access to this lead
        user_email = current_user.get("email")
        has_access = await check_lead_access_for_task(lead_id, user_email, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to create tasks for this lead"
            )
        
        # Create the task
        new_task = await task_service.create_task(
            lead_id=lead_id, 
            task_data=task_data, 
            created_by=user_id
        )
        
        logger.info(f"Task created with ID: {new_task.get('id')}")
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in create_task: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {str(e)}"
        )


@router.get("/leads/{lead_id}/tasks")
@convert_task_dates()
async def get_lead_tasks(
    lead_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, description="Filter by status: pending, overdue, due_today, completed, all"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("task.view"))
):
    """
    🔄 RBAC-ENABLED: Get all tasks for a specific lead
    
    **Required Permission:**
    - `task.view` - See tasks for assigned leads
    - `task.view_team` - See team members' tasks
    - `task.view_all` - See all tasks (admin)
    """
    try:
        logger.info(f"Getting tasks for lead {lead_id} by user {current_user.get('email')}")
        
        # Check if user has access to this lead
        user_email = current_user.get("email")
        has_access = await check_lead_access_for_task(lead_id, user_email, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to view tasks for this lead"
            )
        
        user_id = get_user_id(current_user)
        
        result = await task_service.get_lead_tasks(
            lead_id, 
            user_id,
            current_user.get("role", "user"), 
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
    current_user: Dict[str, Any] = Depends(get_user_with_permission("task.view"))
):
    """
    🔄 RBAC-ENABLED: Get task statistics for a lead
    
    **Required Permission:** `task.view`
    
    Returns: total_tasks, overdue_tasks, due_today, completed_tasks, etc.
    """
    try:
        logger.info(f"Getting task stats for lead {lead_id} by user {current_user.get('email')}")
        
        # Check if user has access to this lead
        user_email = current_user.get("email")
        has_access = await check_lead_access_for_task(lead_id, user_email, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to view stats for this lead"
            )
        
        user_id = get_user_id(current_user)
        
        stats = await task_service._calculate_task_stats(
            lead_id, 
            user_id,
            current_user.get("role", "user")
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
    current_user: Dict[str, Any] = Depends(get_user_with_permission("task.view"))
):
    """
    🔄 RBAC-ENABLED: Get a specific task by ID
    
    **Required Permission:** `task.view`
    
    Users can only view tasks they have access to.
    """
    try:
        logger.info(f"Getting task {task_id} by user {current_user.get('email')}")
        
        user_id = get_user_id(current_user)
        
        # Get the task first to check permissions
        db = get_database()
        task = await db.tasks.find_one({"task_id": task_id})
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Check if user has access to this task
        has_access = await check_task_access(task, user_id, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to view this task"
            )
        
        # Call task service
        task_result = await task_service.get_task_by_id(
            task_id, 
            user_id,
            current_user.get("role", "user")
        )
        
        if not task_result:
            raise HTTPException(status_code=404, detail="Task not found")
        
        logger.info("✅ Task retrieved successfully")
        return task_result
        
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


@router.put("/{task_id}")
async def update_task(
    task_id: str,
    task_data: TaskUpdate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("task.update_own"))
):
    """
    🔄 RBAC-ENABLED: Update a task
    
    **Required Permission:**
    - `task.update_own` - Update tasks assigned to you
    - `task.update_team` - Update team members' tasks
    
    Users can update tasks assigned to them or created by them.
    Admins with task.update_team can update any task.
    """
    try:
        logger.info(f"Updating task {task_id} by user {current_user.get('email')}")
        
        user_id = get_user_id(current_user)
        
        # Get the task first to check permissions
        db = get_database()
        task = await db.tasks.find_one({"task_id": task_id})
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Check if user has update_team permission (can update any task)
        has_update_team = await rbac_service.check_permission(current_user, "task.update_team")
        
        if not has_update_team:
            # Regular user - can only update their own tasks
            has_access = await check_task_access(task, user_id, current_user)
            
            if not has_access:
                raise HTTPException(
                    status_code=403,
                    detail="You don't have permission to update this task"
                )
        
        success = await task_service.update_task(
            task_id, 
            task_data, 
            user_id,
            current_user.get("role", "user")
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found or update failed"
            )
        
        # Return updated task
        updated_task = await task_service.get_task_by_id(
            task_id, 
            user_id,
            current_user.get("role", "user")
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


@router.patch("/{task_id}/complete")
async def complete_task(
    task_id: str,
    completion_data: TaskCompleteRequest,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("task.update_own"))
):
    """
    🔄 RBAC-ENABLED: Mark a task as completed
    
    **Required Permission:** `task.update_own`
    
    Users can complete tasks assigned to them or created by them.
    """
    try:
        logger.info(f"Completing task {task_id} by user {current_user.get('email')}")
        
        user_id = get_user_id(current_user)
        
        # Get the task first to check permissions
        db = get_database()
        task = await db.tasks.find_one({"task_id": task_id})
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Check if user has access to this task
        has_access = await check_task_access(task, user_id, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to complete this task"
            )
        
        success = await task_service.complete_task(
            task_id, 
            completion_data.completion_notes, 
            user_id,
            current_user.get("role", "user")
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found or completion failed"
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


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("task.delete_own"))
):
    """
    🔄 RBAC-ENABLED: Delete a task
    
    **Required Permission:**
    - `task.delete_own` - Delete tasks you created
    - `task.delete_team` - Delete team tasks
    - `task.delete_all` - Delete any task (admin)
    
    Users can delete tasks they created.
    """
    try:
        logger.info(f"Deleting task {task_id} by user {current_user.get('email')}")
        
        user_id = get_user_id(current_user)
        
        # Get the task first to check permissions
        db = get_database()
        task = await db.tasks.find_one({"task_id": task_id})
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Check permissions
        has_delete_all = await rbac_service.check_permission(current_user, "task.delete_all")
        has_delete_team = await rbac_service.check_permission(current_user, "task.delete_team")
        created_by = str(task.get("created_by", ""))
        
        if not has_delete_all:
            if has_delete_team:
                # Can delete team tasks - check if task belongs to team
                team_members = await db.users.find(
                    {"reports_to_email": current_user.get("email")},
                    {"_id": 1}
                ).to_list(None)
                team_member_ids = [str(member["_id"]) for member in team_members]
                
                if created_by not in team_member_ids and created_by != user_id:
                    raise HTTPException(
                        status_code=403,
                        detail="You can only delete tasks created by you or your team members"
                    )
            else:
                # Regular user - can only delete own tasks
                if created_by != user_id:
                    raise HTTPException(
                        status_code=403,
                        detail="You can only delete tasks you created"
                    )
        
        success = await task_service.delete_task(
            task_id, 
            user_id,
            current_user.get("role", "user")
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found or deletion failed"
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
    current_user: Dict[str, Any] = Depends(get_user_with_permission("task.view"))
):
    """
    🔄 RBAC-ENABLED: Get all tasks assigned to the current user
    
    **Required Permission:** `task.view`
    
    **Permission-based behavior:**
    - task.view_all: See ALL tasks from ALL users
    - task.view_team: See own tasks + team members' tasks
    - task.view: See only assigned/created tasks (default)
    """
    try:
        logger.info(f"Getting tasks for user {current_user.get('email')} with RBAC filtering")
        
        user_id = get_user_id(current_user)
        
        # Check permissions to determine scope
        has_view_all = await rbac_service.check_permission(current_user, "task.view_all")
        
        if has_view_all:
            # Admin - get ALL tasks
            result = await task_service.get_all_tasks(status_filter, page, limit)
            logger.info(f"User {current_user.get('email')} retrieved {result['total']} total tasks (view_all)")
        else:
            # Regular user - get only their tasks
            result = await task_service.get_user_tasks(
                user_id,
                status_filter,
                page,     
                limit 
            )
            logger.info(f"User {current_user.get('email')} retrieved {result['total']} assigned tasks (view)")
        
        # Calculate stats
        global_stats = await task_service._calculate_global_task_stats(
            user_id, 
            current_user.get("role", "user"),
            status_filter
        )
        
        return {
            "tasks": result["tasks"],
            "stats": global_stats,
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
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    🔄 RBAC-ENABLED: Get list of users assigned to a specific lead
    
    Returns primary assignee + co-assignees for the lead.
    Users can only access leads they are assigned to.
    """
    try:
        logger.info(f"Getting assignable users for lead {lead_id} by {current_user.get('email')}")
        
        db = get_database()
        
        # Find the lead
        lead = await db.leads.find_one({"lead_id": lead_id})
        if not lead:
            raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
        
        # Check permissions using RBAC
        user_email = current_user.get("email")
        has_access = await check_lead_access_for_task(lead_id, user_email, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to view assignable users for this lead"
            )
        
        # Collect all assigned user emails
        assigned_user_emails = []
        
        if lead.get("assigned_to"):
            assigned_user_emails.append(lead.get("assigned_to"))
        
        co_assignees = lead.get("co_assignees", [])
        assigned_user_emails.extend(co_assignees)
        
        # Remove duplicates
        assigned_user_emails = list(set(filter(None, assigned_user_emails)))
        
        if not assigned_user_emails:
            return {
                "success": True,
                "users": [],
                "message": "No users are currently assigned to this lead"
            }
        
        # Get user details
        users = await db.users.find(
            {
                "email": {"$in": assigned_user_emails},
                "is_active": True
            },
            {"first_name": 1, "last_name": 1, "email": 1, "role": 1, "department": 1}
        ).to_list(None)
        
        # Build response
        assignable_users = []
        for user in users:
            is_primary = user["email"] == lead.get("assigned_to")
            
            user_info = {
                "id": str(user["_id"]),
                "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() or user["email"],
                "email": user["email"],
                "role": user["role"],
                "department": user.get("department"),
                "assignment_type": "primary" if is_primary else "co-assignee"
            }
            
            assignable_users.append(user_info)
        
        # Sort: primary first
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
    🔄 RBAC-ENABLED: Perform bulk actions on multiple tasks
    
    **Required Permissions:**
    - complete: `task.update_own`
    - delete: `task.delete_own`
    - reassign: `task.update_own`
    """
    try:
        logger.info(f"Bulk action {bulk_action.action} by {current_user.get('email')} on {len(bulk_action.task_ids)} tasks")
        
        # Check permission for the requested action
        permission_map = {
            "complete": "task.update_own",
            "delete": "task.delete_own",
            "reassign": "task.update_own"
        }
        
        required_permission = permission_map.get(bulk_action.action)
        if required_permission:
            has_permission = await rbac_service.check_permission(current_user, required_permission)
            if not has_permission:
                raise HTTPException(
                    status_code=403,
                    detail=f"You don't have permission to perform bulk {bulk_action.action}. Required: {required_permission}"
                )
        
        user_id = get_user_id(current_user)
        db = get_database()
        success_count = 0
        failed_tasks = []
        
        for task_id in bulk_action.task_ids:
            try:
                # Check access to each task
                task = await db.tasks.find_one({"task_id": task_id})
                if not task:
                    failed_tasks.append(task_id)
                    continue
                
                has_access = await check_task_access(task, user_id, current_user)
                if not has_access:
                    failed_tasks.append(task_id)
                    continue
                
                # Perform the action
                if bulk_action.action == "complete":
                    success = await task_service.complete_task(
                        task_id, 
                        bulk_action.notes, 
                        user_id,
                        current_user.get("role", "user")
                    )
                elif bulk_action.action == "delete":
                    success = await task_service.delete_task(
                        task_id, 
                        user_id,
                        current_user.get("role", "user")
                    )
                elif bulk_action.action == "reassign" and bulk_action.assigned_to:
                    task_update = TaskUpdate(assigned_to=bulk_action.assigned_to)
                    success = await task_service.update_task(
                        task_id, 
                        task_update, 
                        user_id,
                        current_user.get("role", "user")
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

