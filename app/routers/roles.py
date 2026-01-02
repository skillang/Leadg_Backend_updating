# app/routers/roles.py - RBAC-Enabled
# Complete Role Management Router with 108-Permission RBAC Integration
# 🔄 UPDATED: Manual permission checks replaced with dependency-based RBAC

import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, status, Depends, Query
from datetime import datetime
from bson import ObjectId

from ..models.role import (
    RoleCreate, RoleUpdate, RoleResponse, RoleListResponse, RoleListItemResponse,
    RoleAssignRequest, RoleAssignResponse, RoleCloneRequest
)
from ..services.role_service import role_service
from ..services.rbac_service import RBACService
from ..utils.dependencies import get_user_with_permission
from ..config.database import get_database

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize RBAC service
rbac_service = RBACService()


# =====================================
# RBAC-ENABLED CORE ROLE MANAGEMENT
# =====================================

@router.post("/", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    role_data: RoleCreate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.create"))
):
    """
    🔄 RBAC-ENABLED: Create a new custom role
    
    **Required Permission:** `role.create`
    
    Args:
        role_data: Role creation data including name, permissions, etc.
        current_user: Authenticated user with role.add permission
        
    Returns:
        RoleResponse: Created role with all details
        
    Raises:
        403: User lacks role.add permission
        400: Role name already exists
        500: Server error
    """
    try:
        logger.info(f"Creating role '{role_data.name}' by {current_user.get('email')}")
        
        # Create role
        result = await role_service.create_role(
            role_data=role_data,
            created_by=current_user.get("email")
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_role endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/", response_model=RoleListResponse)
async def list_roles(
    include_inactive: bool = Query(False, description="Include inactive roles in results"),
    role_type: Optional[str] = Query(None, description="Filter by type: 'system' or 'custom'"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.view"))
):
    """
    🔄 RBAC-ENABLED: List all roles with optional filtering
    
    **Required Permission:** `role.view`
    
    Args:
        include_inactive: If true, includes deactivated roles
        role_type: Filter by 'system' or 'custom' roles
        current_user: Authenticated user with role.view permission
        
    Returns:
        RoleListResponse: List of roles matching filters
        
    Raises:
        403: User lacks role.view permission
        500: Server error
    """
    try:
        logger.info(f"Listing roles by {current_user.get('email')} (include_inactive={include_inactive}, type={role_type})")
        
        # List roles
        result = await role_service.list_roles(
            include_inactive=include_inactive,
            role_type=role_type
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in list_roles endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.view"))
):
    """
    🔄 RBAC-ENABLED: Get detailed information about a specific role
    
    **Required Permission:** `role.view`
    
    Args:
        role_id: MongoDB ObjectId of the role as string
        current_user: Authenticated user with role.view permission
        
    Returns:
        RoleResponse: Complete role details including permissions
        
    Raises:
        403: User lacks role.view permission
        404: Role not found
        500: Server error
    """
    try:
        logger.info(f"Getting role {role_id} by {current_user.get('email')}")
        
        # Get role
        result = await role_service.get_role(role_id)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_role endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: str,
    role_data: RoleUpdate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.edit"))
):
    """
    🔄 RBAC-ENABLED: Update an existing role
    
    **Required Permission:** `role.edit`
    
    Note: Cannot modify system roles (Super Admin, Admin, User)
    
    Args:
        role_id: MongoDB ObjectId of the role as string
        role_data: Updated role data (name, permissions, etc.)
        current_user: Authenticated user with role.update permission
        
    Returns:
        RoleResponse: Updated role details
        
    Raises:
        403: User lacks role.update permission or trying to modify system role
        404: Role not found
        500: Server error
    """
    try:
        logger.info(f"Updating role {role_id} by {current_user.get('email')}")
        
        # Update role
        result = await role_service.update_role(
            role_id=role_id,
            role_data=role_data,
            updated_by=current_user.get("email")
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_role endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/{role_id}")
async def delete_role(
    role_id: str,
    force: bool = Query(False, description="Force delete even if users are assigned to this role"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.delete"))
):
    """
    🔄 RBAC-ENABLED: Delete a custom role
    
    **Required Permission:** `role.delete`
    
    Note: 
    - Cannot delete system roles
    - Cannot delete roles with assigned users unless force=true
    - If force=true, users will be assigned to default 'User' role
    
    Args:
        role_id: MongoDB ObjectId of the role as string
        force: If true, delete even if users are assigned (they'll be reassigned)
        current_user: Authenticated user with role.delete permission
        
    Returns:
        dict: Deletion result with affected users count
        
    Raises:
        403: User lacks role.delete permission or trying to delete system role
        400: Role has assigned users and force=false
        404: Role not found
        500: Server error
    """
    try:
        logger.info(f"Deleting role {role_id} by {current_user.get('email')} (force={force})")
        
        # Delete role
        result = await role_service.delete_role(
            role_id=role_id,
            deleted_by=current_user.get("email"),
            force=force
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in delete_role endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# =====================================
# RBAC-ENABLED ROLE ASSIGNMENT
# =====================================

@router.post("/assign", response_model=RoleAssignResponse)
async def assign_role_to_user(
    request: RoleAssignRequest,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.assign"))
):
    """
    🔄 RBAC-ENABLED: Assign a role to a specific user
    
    **Required Permission:** `role.assign`
    
    Args:
        request: Role assignment request with user_email, role_id, optional reason
        current_user: Authenticated user with role.assign permission
        
    Returns:
        RoleAssignResponse: Assignment result with updated user info
        
    Raises:
        403: User lacks role.assign permission
        404: User or role not found
        500: Server error
    """
    try:
        logger.info(f"Assigning role {request.role_id} to {request.user_email} by {current_user.get('email')}")
        
        # Assign role
        result = await role_service.assign_role_to_user(
            user_email=request.user_email,
            role_id=request.role_id,
            assigned_by=current_user.get("email"),
            reason=request.reason,
            expires_at=request.expires_at
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in assign_role_to_user endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/assign-bulk")
async def assign_role_to_multiple_users(
    role_id: str,
    user_emails: List[str],
    reason: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.assign"))
):
    """
    🔄 RBAC-ENABLED: Assign a role to multiple users at once (bulk operation)
    
    **Required Permission:** `role.assign`
    
    Args:
        role_id: Role to assign to all users
        user_emails: List of user email addresses
        reason: Optional reason for bulk assignment
        current_user: Authenticated user with role.assign permission
        
    Returns:
        dict: Bulk assignment results with success/failure breakdown
        
    Example Response:
        {
            "success": true,
            "message": "Assigned role to 5 users",
            "results": {
                "success": [{"email": "user1@test.com", ...}, ...],
                "failed": [{"email": "user2@test.com", "error": "..."}, ...],
                "total": 6
            }
        }
    """
    try:
        logger.info(f"Bulk assigning role {role_id} to {len(user_emails)} users by {current_user.get('email')}")
        
        results = {
            "success": [],
            "failed": [],
            "total": len(user_emails)
        }
        
        for email in user_emails:
            try:
                result = await role_service.assign_role_to_user(
                    user_email=email,
                    role_id=role_id,
                    assigned_by=current_user.get("email"),
                    reason=reason
                )
                results["success"].append({
                    "email": email,
                    "role_id": role_id,
                    "assigned_at": datetime.utcnow().isoformat()
                })
            except Exception as e:
                results["failed"].append({
                    "email": email,
                    "error": str(e)
                })
        
        logger.info(f"Bulk assignment complete: {len(results['success'])} succeeded, {len(results['failed'])} failed")
        
        return {
            "success": True,
            "message": f"Assigned role to {len(results['success'])} out of {len(user_emails)} users",
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk role assignment: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# =====================================
# RBAC-ENABLED ROLE CLONING & UTILITIES
# =====================================

@router.post("/{role_id}/clone", response_model=RoleResponse)
async def clone_role(
    role_id: str,
    request: RoleCloneRequest,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.create"))
):
    """
    🔄 RBAC-ENABLED: Clone an existing role to create a new role with same permissions
    
    **Required Permission:** `role.create`
    
    Useful for:
    - Creating variations of existing roles
    - Duplicating roles for different departments
    - Template-based role creation
    
    Args:
        role_id: Source role ObjectId as string
        request: Clone request with new role name, display name, description
        current_user: Authenticated user with role.add permission
        
    Returns:
        RoleResponse: Newly cloned role with same permissions as source
        
    Raises:
        403: User lacks role.add permission
        404: Source role not found
        400: New role name already exists
        500: Server error
    """
    try:
        logger.info(f"Cloning role {role_id} to '{request.new_role_name}' by {current_user.get('email')}")
        
        # Clone role
        result = await role_service.clone_role(
            source_role_id=role_id,
            new_role_name=request.new_role_name,
            new_display_name=request.new_display_name,
            new_description=request.new_description,
            cloned_by=current_user.get("email")
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in clone_role endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{role_id}/users")
async def get_users_with_role(
    role_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.view"))
):
    """
    🔄 RBAC-ENABLED: Get list of all users assigned to a specific role
    
    **Required Permission:** `role.view`
    
    Args:
        role_id: Role ObjectId as string
        current_user: Authenticated user with role.view permission
        
    Returns:
        dict: List of users with this role including basic user info
        
    Example Response:
        {
            "success": true,
            "role_id": "...",
            "users": [
                {
                    "id": "...",
                    "email": "user@test.com",
                    "name": "John Doe",
                    "is_active": true,
                    "assigned_at": "2024-01-15T10:30:00"
                },
                ...
            ],
            "total": 5
        }
    """
    try:
        logger.info(f"Getting users with role {role_id} by {current_user.get('email')}")
        
        # Get users
        users = await role_service.get_users_with_role(role_id)
        
        return {
            "success": True,
            "role_id": role_id,
            "users": users,
            "total": len(users)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_users_with_role endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/by-name/{role_name}", response_model=RoleResponse)
async def get_role_by_name(
    role_name: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.view"))
):
    """
    🔄 RBAC-ENABLED: Get role by its unique name (alternative to getting by ID)
    
    **Required Permission:** `role.view`
    
    Args:
        role_name: Unique role name (e.g., "admin", "user", "team_lead", "sales_manager")
        current_user: Authenticated user with role.view permission
        
    Returns:
        RoleResponse: Role details
        
    Raises:
        403: User lacks role.view permission
        404: Role with this name not found
        500: Server error
    """
    try:
        logger.info(f"Getting role by name '{role_name}' by {current_user.get('email')}")
        
        # Get role
        result = await role_service.get_role_by_name(role_name)
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Role '{role_name}' not found"
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_role_by_name endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# =====================================
# RBAC-ENABLED ACTIVATION/DEACTIVATION
# =====================================

@router.post("/{role_id}/activate")
async def activate_role(
    role_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.edit"))
):
    """
    🔄 RBAC-ENABLED: Activate a previously deactivated role
    
    **Required Permission:** `role.edit`
    
    Args:
        role_id: Role ObjectId as string
        current_user: Authenticated user with role.update permission
        
    Returns:
        dict: Activation result with updated role
        
    Raises:
        403: User lacks role.update permission
        404: Role not found
        500: Server error
    """
    try:
        logger.info(f"Activating role {role_id} by {current_user.get('email')}")
        
        # Update role
        role_data = RoleUpdate(is_active=True)
        
        result = await role_service.update_role(
            role_id=role_id,
            role_data=role_data,
            updated_by=current_user.get("email")
        )
        
        return {
            "success": True,
            "message": f"Role '{result.get('name')}' activated successfully",
            "role": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in activate_role endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/{role_id}/deactivate")
async def deactivate_role(
    role_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.edit"))
):
    """
    🔄 RBAC-ENABLED: Deactivate a role (soft delete - doesn't remove from database)
    
    **Required Permission:** `role.edit`
    
    Note: 
    - Cannot deactivate system roles (Super Admin, Admin, User)
    - Users with this role will still have it, but role won't appear in role selection
    
    Args:
        role_id: Role ObjectId as string
        current_user: Authenticated user with role.update permission
        
    Returns:
        dict: Deactivation result with updated role
        
    Raises:
        403: User lacks role.update permission or trying to deactivate system role
        404: Role not found
        500: Server error
    """
    try:
        logger.info(f"Deactivating role {role_id} by {current_user.get('email')}")
        
        # Update role
        role_data = RoleUpdate(is_active=False)
        
        result = await role_service.update_role(
            role_id=role_id,
            role_data=role_data,
            updated_by=current_user.get("email")
        )
        
        return {
            "success": True,
            "message": f"Role '{result.get('name')}' deactivated successfully",
            "role": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in deactivate_role endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# =====================================
# RBAC-ENABLED ADVANCED FEATURES
# =====================================

@router.get("/available-permissions")
async def get_available_permissions(
    category: Optional[str] = Query(None, description="Filter by permission category"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.view"))
):
    """
    🔄 RBAC-ENABLED: Get all available permissions that can be assigned to roles
    
    **Required Permission:** `role.view`
    
    Used for: Role creation/editing UI to show permission matrix
    
    Args:
        category: Optional filter by category (lead_management, user_management, etc.)
        current_user: Authenticated user with role.view permission
        
    Returns:
        dict: Permissions grouped by category with metadata
        
    Example Response:
        {
            "success": true,
            "permissions_by_category": {
                "lead_management": [
                    {
                        "code": "lead.create",
                        "name": "Create Leads",
                        "description": "Can create new leads",
                        "scope": "own",
                        "resource": "lead",
                        "action": "create"
                    },
                    ...
                ],
                "user_management": [...],
                ...
            },
            "total_permissions": 108,
            "categories": ["lead_management", "user_management", ...]
        }
    """
    try:
        db = get_database()
        
        # Build query
        query = {"is_system": True}  # Only system-defined permissions
        if category:
            query["category"] = category
        
        # Get permissions
        permissions = await db.permissions.find(query).sort("category", 1).to_list(None)
        
        # Group by category
        grouped = {}
        for perm in permissions:
            cat = perm.get("category", "other")
            if cat not in grouped:
                grouped[cat] = []
            
            grouped[cat].append({
                "code": perm["code"],
                "name": perm["name"],
                "description": perm.get("description", ""),
                "scope": perm.get("scope", "own"),
                "resource": perm.get("resource", ""),
                "action": perm.get("action", "")
            })
        
        logger.info(f"Retrieved {len(permissions)} available permissions for {current_user.get('email')}")
        
        return {
            "success": True,
            "permissions_by_category": grouped,
            "total_permissions": len(permissions),
            "categories": list(grouped.keys())
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_available_permissions endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/statistics")
async def get_role_statistics(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.view"))
):
    """
    🔄 RBAC-ENABLED: Get role statistics and analytics
    
    **Required Permission:** `role.view`
    
    Provides:
    - Total roles breakdown (active/inactive, system/custom)
    - Top 5 roles by user count
    - Usage metrics
    
    Returns:
        dict: Comprehensive role statistics
        
    Example Response:
        {
            "success": true,
            "statistics": {
                "total_roles": 10,
                "active_roles": 8,
                "inactive_roles": 2,
                "system_roles": 3,
                "custom_roles": 7
            },
            "top_roles_by_users": [
                {"name": "user", "display_name": "User", "user_count": 50},
                {"name": "admin", "display_name": "Admin", "user_count": 5},
                ...
            ]
        }
    """
    try:
        db = get_database()
        
        # Get counts
        total_roles = await db.roles.count_documents({})
        active_roles = await db.roles.count_documents({"is_active": True})
        inactive_roles = await db.roles.count_documents({"is_active": False})
        system_roles = await db.roles.count_documents({"type": "system"})
        custom_roles = await db.roles.count_documents({"type": "custom"})
        
        # Get users per role (aggregation pipeline)
        pipeline = [
            {
                "$lookup": {
                    "from": "users",
                    "localField": "_id",
                    "foreignField": "role_id",
                    "as": "users"
                }
            },
            {
                "$project": {
                    "name": 1,
                    "display_name": 1,
                    "user_count": {"$size": "$users"}
                }
            },
            {"$sort": {"user_count": -1}},
            {"$limit": 5}
        ]
        
        top_roles = await db.roles.aggregate(pipeline).to_list(None)
        
        logger.info(f"Retrieved role statistics for {current_user.get('email')}")
        
        return {
            "success": True,
            "statistics": {
                "total_roles": total_roles,
                "active_roles": active_roles,
                "inactive_roles": inactive_roles,
                "system_roles": system_roles,
                "custom_roles": custom_roles
            },
            "top_roles_by_users": [
                {
                    "id": str(role["_id"]),
                    "name": role.get("name"),
                    "display_name": role.get("display_name"),
                    "user_count": role.get("user_count", 0)
                }
                for role in top_roles
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_role_statistics endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/compare")
async def compare_roles(
    role_id_1: str = Query(..., description="First role ID to compare"),
    role_id_2: str = Query(..., description="Second role ID to compare"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("role.view"))
):
    """
    🔄 RBAC-ENABLED: Compare permissions between two roles
    
    **Required Permission:** `role.view`
    
    Useful for:
    - Understanding permission differences
    - Role migration planning
    - Permission auditing
    
    Args:
        role_id_1: First role ObjectId as string
        role_id_2: Second role ObjectId as string
        current_user: Authenticated user with role.view permission
        
    Returns:
        dict: Detailed permission comparison
        
    Example Response:
        {
            "success": true,
            "role_1": {"id": "...", "name": "admin", "total_permissions": 85},
            "role_2": {"id": "...", "name": "user", "total_permissions": 28},
            "comparison": {
                "only_in_role_1": ["lead.delete", "user.delete", ...],
                "only_in_role_2": [],
                "in_both_roles": ["lead.create", "lead.read_own", ...],
                "unique_to_role_1_count": 57,
                "unique_to_role_2_count": 0,
                "common_count": 28
            }
        }
    """
    try:
        logger.info(f"Comparing roles {role_id_1} and {role_id_2} by {current_user.get('email')}")
        
        # Get both roles
        role1 = await role_service.get_role(role_id_1)
        role2 = await role_service.get_role(role_id_2)
        
        # Extract permission codes (only granted permissions)
        perms1 = set(p["permission_code"] for p in role1.get("permissions", []) if p.get("granted"))
        perms2 = set(p["permission_code"] for p in role2.get("permissions", []) if p.get("granted"))
        
        # Calculate differences
        only_in_role1 = sorted(list(perms1 - perms2))
        only_in_role2 = sorted(list(perms2 - perms1))
        in_both = sorted(list(perms1 & perms2))
        
        return {
            "success": True,
            "role_1": {
                "id": role_id_1,
                "name": role1.get("name"),
                "display_name": role1.get("display_name"),
                "total_permissions": len(perms1)
            },
            "role_2": {
                "id": role_id_2,
                "name": role2.get("name"),
                "display_name": role2.get("display_name"),
                "total_permissions": len(perms2)
            },
            "comparison": {
                "only_in_role_1": only_in_role1,
                "only_in_role_2": only_in_role2,
                "in_both_roles": in_both,
                "unique_to_role_1_count": len(only_in_role1),
                "unique_to_role_2_count": len(only_in_role2),
                "common_count": len(in_both)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing roles: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )