# app/routers/permissions.py
# 🔄 RBAC-ENABLED: Complete Permission Management - All 69 Permissions Across 9 Categories
# ✅ Expanded from 2 permissions to full RBAC system

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import logging
from bson import ObjectId

# Services
from ..services.permission_service import permission_service
from ..services.rbac_service import RBACService

# Dependencies
from ..utils.dependencies import (
    get_current_active_user,
    get_user_with_permission
)

# Database
from ..config.database import get_database

logger = logging.getLogger(__name__)

# 🆕 Initialize RBAC service
rbac_service = RBACService()

# Create router
router = APIRouter()


# ============================================================================
# 🆕 PERMISSION LISTING & DISCOVERY (NEW ENDPOINTS)
# ============================================================================

@router.get("/list")
async def list_all_permissions(
    category: Optional[str] = Query(None, description="Filter by category (lead_management, user_management, etc.)"),
    resource: Optional[str] = Query(None, description="Filter by resource (lead, contact, task, etc.)"),
    action: Optional[str] = Query(None, description="Filter by action (create, read, update, delete, etc.)"),
    # 🔄 UPDATED: Use RBAC permission check
    current_user: Dict[str, Any] = Depends(get_user_with_permission("permission.read"))
):
    """
    🆕 NEW: Get list of all 69 system permissions
    
    **Required Permission:** `permission.read`
    
    Returns all available permissions that can be assigned to roles.
    Can be filtered by category, resource, or action.
    """
    try:
        db = get_database()
        
        # Build query
        query = {"is_system": True}
        if category:
            query["category"] = category
        if resource:
            query["resource"] = resource
        if action:
            query["action"] = action
        
        logger.info(f"Listing permissions with filters: {query}")
        
        # Get permissions
        permissions = await db.permissions.find(query).sort("category", 1).to_list(None)
        
        # Format response
        formatted_permissions = []
        for perm in permissions:
            formatted_permissions.append({
                "id": str(perm["_id"]),
                "code": perm["code"],
                "name": perm["name"],
                "description": perm.get("description", ""),
                "category": perm.get("category", "other"),
                "resource": perm.get("resource", ""),
                "action": perm.get("action", ""),
                "scope": perm.get("scope", "own"),
                "is_system": perm.get("is_system", True)
            })
        
        # Get total count
        total_count = await db.permissions.count_documents({"is_system": True})
        
        logger.info(f"✅ Retrieved {len(formatted_permissions)} permissions (total: {total_count})")
        
        return {
            "success": True,
            "permissions": formatted_permissions,
            "total_count": total_count,
            "filtered_count": len(formatted_permissions),
            "filters_applied": {
                "category": category,
                "resource": resource,
                "action": action
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing permissions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list permissions: {str(e)}"
        )


@router.get("/categories")
async def list_permission_categories(
    # 🔄 UPDATED: Use RBAC permission check
    current_user: Dict[str, Any] = Depends(get_user_with_permission("permission.read"))
):
    """
    🆕 NEW: Get all permission categories with counts
    
    **Required Permission:** `permission.read`
    
    Returns 9 permission categories with metadata.
    """
    try:
        db = get_database()
        
        # Aggregate permissions by category
        pipeline = [
            {"$match": {"is_system": True}},
            {
                "$group": {
                    "_id": "$category",
                    "permission_count": {"$sum": 1},
                    "permissions": {"$push": "$code"}
                }
            },
            {"$sort": {"_id": 1}}
        ]
        
        results = await db.permissions.aggregate(pipeline).to_list(None)
        
        # Category display info
        category_info = {
            "lead_management": {
                "display_name": "Lead Management",
                "description": "Permissions for managing leads and lead lifecycle"
            },
            "contact_management": {
                "display_name": "Contact Management",
                "description": "Permissions for managing contacts and relationships"
            },
            "task_management": {
                "display_name": "Task Management",
                "description": "Permissions for creating and managing tasks"
            },
            "user_management": {
                "display_name": "User Management",
                "description": "Permissions for managing users and accounts"
            },
            "role_permission_management": {
                "display_name": "Role & Permission Management",
                "description": "Permissions for managing roles and permissions"
            },
            "dashboard_reporting": {
                "display_name": "Dashboard & Reporting",
                "description": "Permissions for viewing dashboards and reports"
            },
            "system_settings": {
                "display_name": "System Settings",
                "description": "Permissions for system configuration and settings"
            },
            "email_communication": {
                "display_name": "Email & Communication",
                "description": "Permissions for email and communication features"
            },
            "team_management": {
                "display_name": "Team Management",
                "description": "Permissions for managing team hierarchy and structure"
            }
        }
        
        # Format categories
        categories = []
        for result in results:
            category_name = result["_id"]
            info = category_info.get(category_name, {
                "display_name": category_name.replace("_", " ").title(),
                "description": f"Permissions for {category_name}"
            })
            
            categories.append({
                "name": category_name,
                "display_name": info["display_name"],
                "description": info["description"],
                "permission_count": result["permission_count"],
                "sample_permissions": result["permissions"][:3]
            })
        
        logger.info(f"✅ Retrieved {len(categories)} permission categories")
        
        return {
            "success": True,
            "categories": categories,
            "total_categories": len(categories)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing permission categories: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list categories: {str(e)}"
        )


@router.get("/matrix")
async def get_permission_matrix(
    # 🔄 UPDATED: Use RBAC permission check
    current_user: Dict[str, Any] = Depends(get_user_with_permission("permission.read"))
):
    """
    🆕 NEW: Get permission matrix view (for UI display)
    
    **Required Permission:** `permission.read`
    
    Returns permissions organized by category → resource → action.
    Perfect for building Strapi-style permission matrix UI.
    """
    try:
        db = get_database()
        
        # Get all permissions
        permissions = await db.permissions.find({"is_system": True}).to_list(None)
        
        # Build matrix
        matrix = {}
        
        for perm in permissions:
            category = perm.get("category", "other")
            resource = perm.get("resource", "general")
            action = perm.get("action", "unknown")
            
            if category not in matrix:
                matrix[category] = {}
            
            if resource not in matrix[category]:
                matrix[category][resource] = {}
            
            matrix[category][resource][action] = {
                "code": perm["code"],
                "name": perm["name"],
                "description": perm.get("description", ""),
                "scope": perm.get("scope", "own")
            }
        
        logger.info(f"✅ Generated permission matrix with {len(permissions)} permissions")
        
        return {
            "success": True,
            "matrix": matrix,
            "total_permissions": len(permissions)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating permission matrix: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate matrix: {str(e)}"
        )


# ============================================================================
# 🔄 USER PERMISSION MANAGEMENT (UPDATED)
# ============================================================================

@router.get("/users")
async def get_users_with_permissions(
    include_admins: bool = Query(False, description="Include admin/super admin users"),
    include_inactive: bool = Query(False, description="Include inactive users"),
    role_filter: Optional[str] = Query(None, description="Filter by role name"),
    # 🔄 UPDATED: Use RBAC permission check
    current_user: Dict[str, Any] = Depends(get_user_with_permission("permission.read"))
):
    """
    🔄 UPDATED: Get all users with their effective permissions
    
    **Required Permission:** `permission.read`
    
    Now returns users with their role-based permissions (not just lead permissions).
    """
    try:
        db = get_database()
        
        # Build query
        query = {}
        if not include_admins:
            query["is_super_admin"] = {"$ne": True}
        if not include_inactive:
            query["is_active"] = True
        if role_filter:
            query["role_name"] = role_filter
        
        logger.info(f"Getting users with permissions: {query}")
        
        # Get users
        users = await db.users.find(
            query,
            {
                "email": 1,
                "first_name": 1,
                "last_name": 1,
                "role_name": 1,
                "is_super_admin": 1,
                "is_active": 1,
                "effective_permissions": 1,
                "permission_overrides": 1,
                "permissions_last_computed": 1
            }
        ).to_list(None)
        
        # Format users
        formatted_users = []
        for user in users:
            formatted_users.append({
                "id": str(user["_id"]),
                "email": user["email"],
                "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                "role_name": user.get("role_name", "user"),
                "is_super_admin": user.get("is_super_admin", False),
                "is_active": user.get("is_active", True),
                "permissions_count": len(user.get("effective_permissions", [])),
                "has_overrides": len(user.get("permission_overrides", [])) > 0,
                "last_computed": user.get("permissions_last_computed")
            })
        
        # Get summary statistics
        total_users = await db.users.count_documents(query)
        users_with_permissions = sum(1 for u in formatted_users if u["permissions_count"] > 0)
        
        logger.info(f"✅ Retrieved {len(formatted_users)} users with permissions")
        
        return {
            "success": True,
            "users": formatted_users,
            "total_count": len(formatted_users),
            "summary": {
                "total_users": total_users,
                "users_with_permissions": users_with_permissions,
                "users_without_permissions": total_users - users_with_permissions
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting users with permissions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get users: {str(e)}"
        )


@router.get("/users/{user_email}/effective")
async def get_user_effective_permissions(
    user_email: str,
    # 🔄 UPDATED: Use RBAC permission check
    current_user: Dict[str, Any] = Depends(get_user_with_permission("permission.read"))
):
    """
    🆕 NEW: Get user's computed effective permissions
    
    **Required Permission:** `permission.read`
    
    Returns complete list of permissions from:
    1. Role-based permissions
    2. Individual overrides
    3. Super admin bypass
    """
    try:
        db = get_database()
        
        # Get user
        user = await db.users.find_one({"email": user_email})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{user_email}' not found"
            )
        
        # Get effective permissions
        effective_permissions = user.get("effective_permissions", [])
        permission_overrides = user.get("permission_overrides", [])
        
        # Group permissions by category
        permissions_by_category = {}
        for perm_code in effective_permissions:
            perm = await db.permissions.find_one({"code": perm_code})
            if perm:
                category = perm.get("category", "other")
                if category not in permissions_by_category:
                    permissions_by_category[category] = []
                permissions_by_category[category].append(perm_code)
        
        logger.info(f"✅ Retrieved effective permissions for {user_email}: {len(effective_permissions)} permissions")
        
        return {
            "success": True,
            "user": {
                "email": user["email"],
                "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                "role_name": user.get("role_name", "user"),
                "is_super_admin": user.get("is_super_admin", False),
                "is_active": user.get("is_active", True)
            },
            "effective_permissions": effective_permissions,
            "permissions_by_category": permissions_by_category,
            "permission_count": len(effective_permissions),
            "overrides": permission_overrides,
            "overrides_count": len(permission_overrides),
            "last_computed": user.get("permissions_last_computed")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user effective permissions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get permissions: {str(e)}"
        )


@router.post("/users/{user_email}/override")
async def add_permission_override(
    user_email: str,
    permission_code: str = Query(..., description="Permission code (e.g., 'lead.delete')"),
    granted: bool = Query(..., description="true to grant, false to deny"),
    reason: str = Query(..., description="Reason for override (required for audit)"),
    # 🔄 UPDATED: Use RBAC permission check
    current_user: Dict[str, Any] = Depends(get_user_with_permission("permission.manage"))
):
    """
    🆕 NEW: Add permission override for a specific user
    
    **Required Permission:** `permission.manage`
    
    Allows granting or denying specific permissions to users,
    regardless of their role. Useful for exceptions.
    """
    try:
        db = get_database()
        
        # Validate permission exists
        perm = await db.permissions.find_one({"code": permission_code})
        if not perm:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Permission '{permission_code}' not found"
            )
        
        # Get user
        user = await db.users.find_one({"email": user_email})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{user_email}' not found"
            )
        
        logger.info(f"Adding permission override for {user_email}: {permission_code} = {granted}")
        
        # Create override
        override = {
            "permission_code": permission_code,
            "granted": granted,
            "reason": reason,
            "added_by": current_user.get("email"),
            "added_at": datetime.utcnow()
        }
        
        # Remove existing override for this permission
        await db.users.update_one(
            {"email": user_email},
            {"$pull": {"permission_overrides": {"permission_code": permission_code}}}
        )
        
        # Add new override
        await db.users.update_one(
            {"email": user_email},
            {
                "$push": {"permission_overrides": override},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        
        # Recompute effective permissions
        effective_permissions = await rbac_service.get_user_permissions(str(user["_id"]))
        
        await db.users.update_one(
            {"email": user_email},
            {
                "$set": {
                    "effective_permissions": effective_permissions,
                    "permissions_last_computed": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"✅ Permission override added and permissions recomputed for {user_email}")
        
        return {
            "success": True,
            "message": f"Permission override added for {user_email}",
            "override": override,
            "new_permission_count": len(effective_permissions)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding permission override: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add override: {str(e)}"
        )


@router.delete("/users/{user_email}/override/{permission_code}")
async def remove_permission_override(
    user_email: str,
    permission_code: str,
    # 🔄 UPDATED: Use RBAC permission check
    current_user: Dict[str, Any] = Depends(get_user_with_permission("permission.manage"))
):
    """
    🆕 NEW: Remove permission override from a user
    
    **Required Permission:** `permission.manage`
    
    Returns user to role-based permissions for that specific permission.
    """
    try:
        db = get_database()
        
        logger.info(f"Removing permission override for {user_email}: {permission_code}")
        
        # Remove override
        result = await db.users.update_one(
            {"email": user_email},
            {
                "$pull": {"permission_overrides": {"permission_code": permission_code}},
                "$set": {"updated_at": datetime.utcnow()}
            }
        )
        
        if result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Override for '{permission_code}' not found for user '{user_email}'"
            )
        
        # Get user
        user = await db.users.find_one({"email": user_email})
        
        # Recompute effective permissions
        effective_permissions = await rbac_service.get_user_permissions(str(user["_id"]))
        
        await db.users.update_one(
            {"email": user_email},
            {
                "$set": {
                    "effective_permissions": effective_permissions,
                    "permissions_last_computed": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"✅ Permission override removed and permissions recomputed for {user_email}")
        
        return {
            "success": True,
            "message": f"Permission override removed for {user_email}",
            "permission_code": permission_code,
            "new_permission_count": len(effective_permissions)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing permission override: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove override: {str(e)}"
        )


@router.post("/users/{user_email}/recompute")
async def recompute_user_permissions(
    user_email: str,
    # 🔄 UPDATED: Use RBAC permission check
    current_user: Dict[str, Any] = Depends(get_user_with_permission("permission.manage"))
):
    """
    🆕 NEW: Manually recompute user's effective permissions
    
    **Required Permission:** `permission.manage`
    
    Forces recalculation from role + overrides.
    Useful after role changes or system updates.
    """
    try:
        db = get_database()
        
        # Get user
        user = await db.users.find_one({"email": user_email})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{user_email}' not found"
            )
        
        logger.info(f"Recomputing permissions for {user_email}")
        
        # Recompute
        effective_permissions = await rbac_service.get_user_permissions(str(user["_id"]))
        
        # Update user
        await db.users.update_one(
            {"email": user_email},
            {
                "$set": {
                    "effective_permissions": effective_permissions,
                    "permissions_last_computed": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        logger.info(f"✅ Permissions recomputed for {user_email}: {len(effective_permissions)} permissions")
        
        return {
            "success": True,
            "message": f"Permissions recomputed for {user_email}",
            "user_email": user_email,
            "permission_count": len(effective_permissions),
            "recomputed_at": datetime.utcnow()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error recomputing permissions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to recompute permissions: {str(e)}"
        )


# ============================================================================
# 🆕 PERMISSION STATISTICS & ANALYTICS (NEW)
# ============================================================================

@router.get("/statistics")
async def get_permission_statistics(
    # 🔄 UPDATED: Use RBAC permission check
    current_user: Dict[str, Any] = Depends(get_user_with_permission("permission.read"))
):
    """
    🆕 NEW: Get comprehensive permission system statistics
    
    **Required Permission:** `permission.read`
    
    Returns system-wide statistics about permission usage.
    """
    try:
        db = get_database()
        
        # Get statistics
        total_permissions = await db.permissions.count_documents({"is_system": True})
        total_users = await db.users.count_documents({"is_active": True})
        users_with_overrides = await db.users.count_documents({
            "permission_overrides": {"$exists": True, "$ne": []}
        })
        
        # Get users with permissions
        users = await db.users.find(
            {"is_active": True},
            {"effective_permissions": 1}
        ).to_list(None)
        
        users_with_permissions = sum(1 for u in users if u.get("effective_permissions"))
        total_perms_granted = sum(len(u.get("effective_permissions", [])) for u in users)
        avg_perms = round(total_perms_granted / len(users), 2) if users else 0
        
        # Get most common permissions
        permission_counts = {}
        for user in users:
            for perm in user.get("effective_permissions", []):
                permission_counts[perm] = permission_counts.get(perm, 0) + 1
        
        most_common = sorted(
            [{"code": k, "user_count": v} for k, v in permission_counts.items()],
            key=lambda x: x["user_count"],
            reverse=True
        )[:10]
        
        # Get category breakdown
        pipeline = [
            {"$match": {"is_system": True}},
            {"$group": {"_id": "$category", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        category_breakdown = await db.permissions.aggregate(pipeline).to_list(None)
        by_category = {item["_id"]: item["count"] for item in category_breakdown}
        
        logger.info(f"✅ Permission statistics generated")
        
        return {
            "success": True,
            "statistics": {
                "total_permissions": total_permissions,
                "total_users": total_users,
                "users_with_permissions": users_with_permissions,
                "users_without_permissions": total_users - users_with_permissions,
                "average_permissions_per_user": avg_perms,
                "most_common_permissions": most_common,
                "users_with_overrides": users_with_overrides,
                "by_category": by_category
            },
            "generated_at": datetime.utcnow()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting permission statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get statistics: {str(e)}"
        )


# ============================================================================
# 🆕 SYSTEM VALIDATION & HEALTH CHECK (NEW)
# ============================================================================

@router.post("/validate-system")
async def validate_permission_system(
    # 🔄 UPDATED: Use RBAC permission check
    current_user: Dict[str, Any] = Depends(get_user_with_permission("system.manage"))
):
    """
    🆕 NEW: Validate permission system integrity and health
    
    **Required Permission:** `system.manage`
    
    Performs comprehensive health check:
    - Users without permissions
    - Orphaned permissions
    - Invalid references
    - System inconsistencies
    """
    try:
        db = get_database()
        
        logger.info("Starting permission system validation")
        
        issues = []
        recommendations = []
        warnings = []
        
        # Check 1: Users without effective_permissions
        users_without_perms = await db.users.count_documents({
            "effective_permissions": {"$exists": False}
        })
        if users_without_perms > 0:
            issues.append(f"{users_without_perms} users don't have effective_permissions field")
            recommendations.append("Run permission migration or recompute all user permissions")
        
        # Check 2: Stale permissions (>7 days old)
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        stale_permissions = await db.users.count_documents({
            "permissions_last_computed": {"$lt": seven_days_ago}
        })
        if stale_permissions > 0:
            warnings.append(f"{stale_permissions} users have permissions computed >7 days ago")
            recommendations.append("Consider recomputing permissions for stale data")
        
        # Check 3: Inactive users with permissions
        inactive_with_perms = await db.users.count_documents({
            "is_active": False,
            "effective_permissions": {"$exists": True, "$ne": []}
        })
        if inactive_with_perms > 0:
            warnings.append(f"{inactive_with_perms} inactive users still have permissions")
        
        # Check 4: Invalid role references
        users_with_invalid_roles = 0
        all_users = await db.users.find({"role_id": {"$exists": True}}).to_list(None)
        for user in all_users:
            role_id = user.get("role_id")
            if role_id:
                role = await db.roles.find_one({"_id": role_id})
                if not role:
                    users_with_invalid_roles += 1
        
        if users_with_invalid_roles > 0:
            issues.append(f"{users_with_invalid_roles} users reference non-existent roles")
            recommendations.append("Assign valid roles to users with invalid references")
        
        # Check 5: Permission count
        perm_count = await db.permissions.count_documents({"is_system": True})
        if perm_count != 69:
            issues.append(f"Expected 69 permissions, found {perm_count}")
            recommendations.append("Run permission seeding script")
        
        # Determine status
        if issues:
            status_level = "critical"
        elif warnings:
            status_level = "warning"
        else:
            status_level = "healthy"
        
        logger.info(f"✅ Validation complete - Status: {status_level}")
        
        return {
            "success": True,
            "validation_status": status_level,
            "issues_count": len(issues),
            "warnings_count": len(warnings),
            "issues": issues,
            "warnings": warnings,
            "recommendations": recommendations,
            "checks_performed": {
                "users_without_permissions": users_without_perms,
                "users_with_stale_permissions": stale_permissions,
                "inactive_users_with_permissions": inactive_with_perms,
                "users_with_invalid_roles": users_with_invalid_roles,
                "total_permissions": perm_count
            },
            "validated_by": current_user.get("email"),
            "validated_at": datetime.utcnow()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating permission system: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate system: {str(e)}"
        )


# ============================================================================
# HEALTH CHECK (PUBLIC)
# ============================================================================

@router.get("/health")
async def permissions_health_check():
    """
    Simple health check endpoint for monitoring
    
    **No authentication required**
    """
    return {
        "status": "healthy",
        "service": "permissions_service",
        "rbac_enabled": True,
        "version": "2.0.0",
        "total_permissions": 69,
        "endpoints": {
            "list_permissions": "GET /list",
            "categories": "GET /categories",
            "matrix": "GET /matrix",
            "users": "GET /users",
            "user_effective": "GET /users/{email}/effective",
            "add_override": "POST /users/{email}/override",
            "remove_override": "DELETE /users/{email}/override/{code}",
            "recompute": "POST /users/{email}/recompute",
            "statistics": "GET /statistics",
            "validate": "POST /validate-system"
        }
    }