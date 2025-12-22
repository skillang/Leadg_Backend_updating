# app/routers/permissions.py
# 🔄 RBAC-ENABLED: Complete Permission Management - All 69 Permissions Across 9 Categories

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
    current_user: Dict[str, Any] = Depends(get_user_with_permission("permission.read"))
):
    """
    🆕 NEW: Get permission matrix view (for UI display)
    
    **Required Permission:** `permission.read`
    
    Returns permissions organized by category → action groups.
    Frontend-ready format with no transformation needed.
    """
    try:
        db = get_database()
        
        # Get all permissions
        permissions = await db.permissions.find({"is_system": True}).to_list(None)
        
        # Build structured matrix for frontend
        categorized_data = []
        
        # Group by category first
        category_map = {}
        for perm in permissions:
            category = perm.get("category", "other")
            if category not in category_map:
                category_map[category] = []
            category_map[category].append(perm)
        
        # Structure each category with action groups
        for category_key, category_perms in category_map.items():
            # Create category display name
            category_display = category_key.replace("_", " ").title()
            
            # Group permissions by resource + action
            action_map = {}
            for perm in category_perms:
                resource = perm.get("resource", "general")
                action = perm.get("action", "unknown")
                key = f"{resource}:{action}"
                
                if key not in action_map:
                    action_map[key] = {
                        "action": action,
                        "action_display": action.replace("_", " ").title(),
                        "resource": resource,
                        "permissions": []
                    }
                
                action_map[key]["permissions"].append({
                    "code": perm["code"],
                    "name": perm["name"],
                    "description": perm.get("description", ""),
                    "scope": perm.get("scope", "own")
                })
            
            categorized_data.append({
                "category": category_key,
                "category_display": category_display,
                "action_groups": list(action_map.values())
            })
        
        logger.info(f"✅ Generated structured permission matrix with {len(permissions)} permissions")
        
        return {
            "success": True,
            "categories": categorized_data,
            "total_permissions": len(permissions),
            "total_categories": len(categorized_data)
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
    current_user: Dict[str, Any] = Depends(get_user_with_permission("permission.read"))
):
    """
    Get all users with their effective permissions AND team info (SIMPLIFIED - NO HIERARCHY)
    
    **Required Permission:** `permission.read`
    
    Returns users with:
    - Permission data (effective_permissions, overrides, counts)
    - Team data (team_id, team_name, is_team_lead)
    - Workload data (assigned_leads_count)
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
            
        logger.info(f"Getting users with permissions and team info: {query}")
        
        # Get users with ALL fields (permissions + team)
        users = await db.users.find(
            query,
            {
                "email": 1,
                "role_name": 1,
                "role_id": 1,
                "is_super_admin": 1,
                "is_active": 1,
                "effective_permissions": 1,
                "permission_overrides": 1,
                "permissions_last_computed": 1,
                "team_name": 1,
                "is_team_lead": 1,
            }
        ).to_list(None)
        
        # Format users with both permission and team data
        formatted_users = []
        for user in users:
            # Get assigned leads count
            leads_count = await db.leads.count_documents(
                {"assigned_to": user["email"]}
            )
            
            formatted_users.append({
                # Basic info
                "id": str(user["_id"]),
                "email": user["email"],
                "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                
                # Role info
                # "role_name": user.get("role_name", "user"),
                # "role_id": str(user.get("role_id")) if user.get("role_id") else None,
                "is_super_admin": user.get("is_super_admin", False),
                "is_active": user.get("is_active", True),
                
                # Permission info
                "permissions_count": len(user.get("effective_permissions", [])),
                "has_overrides": len(user.get("permission_overrides", [])) > 0,
                
                # 🔄 UPDATED: Simplified team info (NO HIERARCHY)
                "team_id": str(user.get("team_id")) if user.get("team_id") else None,
                "team_name": user.get("team_name"),
                "is_team_lead": user.get("is_team_lead", False),
                "assigned_leads_count": leads_count,
                
                # Metadata
                # "created_at": user.get("created_at")
            })
        
        # 🔄 UPDATED: Summary statistics (NO HIERARCHY)
        total_users = await db.users.count_documents(query)
        users_with_permissions = sum(1 for u in formatted_users if u["permissions_count"] > 0)
        users_in_teams = sum(1 for u in formatted_users if u["team_id"])
        team_leads_count = sum(1 for u in formatted_users if u["is_team_lead"])
        
        logger.info(f"✅ Retrieved {len(formatted_users)} users with permissions and team info")
        
        return {
            "success": True,
            "users": formatted_users,
            "total_count": len(formatted_users),
            "summary": {
                "total_users": total_users,
                "users_with_permissions": users_with_permissions,
                "users_without_permissions": total_users - users_with_permissions,
                "users_in_teams": users_in_teams,
                "users_without_teams": total_users - users_in_teams,
                "team_leads_count": team_leads_count
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