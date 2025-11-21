from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any, List
from datetime import datetime
from bson import ObjectId
from ..config.database import get_database
from ..utils.security import security
import logging

logger = logging.getLogger(__name__)

# Security scheme
security_scheme = HTTPBearer()

class AuthenticationError(HTTPException):
    def __init__(self, detail: str = "Could not validate credentials"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

# ============================================================================
# CORE AUTHENTICATION DEPENDENCIES
# ============================================================================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme)
) -> Dict[str, Any]:
    """
    🔄 UPDATED: Dependency to get current authenticated user from JWT token
    Enhanced to include RBAC fields (role_id, effective_permissions, team hierarchy)
    """
    token = credentials.credentials
    
    # Verify token
    payload = security.verify_token(token)
    if payload is None:
        raise AuthenticationError("Invalid token")
    
    # Check token type
    if payload.get("type") != "access":
        raise AuthenticationError("Invalid token type")
    
    # Check if token is blacklisted
    token_jti = payload.get("jti")
    if token_jti and await security.is_token_blacklisted(token_jti):
        raise AuthenticationError("Token has been revoked")
    
    # Get user from database
    user_id = payload.get("sub")
    if user_id is None:
        raise AuthenticationError("Invalid token payload")
    
    db = get_database()
    user_data = await db.users.find_one({"_id": ObjectId(user_id)})
    
    if user_data is None:
        raise AuthenticationError("User not found")
    
    # Check if user is active
    if not user_data.get("is_active", False):
        raise AuthenticationError("User account is disabled")
    
    # ============================================================================
    # 🆕 RBAC: ENSURE ALL RBAC FIELDS EXIST (BACKWARD COMPATIBILITY)
    # ============================================================================
    
    # Add role_id if missing (for users created before RBAC)
    if "role_id" not in user_data:
        user_data["role_id"] = None
        user_data["role_name"] = None
    
    # Add is_super_admin if missing
    if "is_super_admin" not in user_data:
        user_data["is_super_admin"] = False
    
    # Add team hierarchy fields if missing
    if "reports_to" not in user_data:
        user_data["reports_to"] = None
        user_data["reports_to_name"] = None
        user_data["team_members"] = []
        user_data["team_level"] = 0
    
    # Add permission fields if missing
    if "effective_permissions" not in user_data:
        user_data["effective_permissions"] = []
        user_data["permission_overrides"] = []
        user_data["permissions_last_computed"] = None
    
    # 🔄 BACKWARD COMPATIBILITY: Keep old permissions structure
    if "permissions" not in user_data:
        user_data["permissions"] = {
            "can_create_single_lead": False,
            "can_create_bulk_leads": False,
            "granted_by": None,
            "granted_at": None,
            "last_modified_by": None,
            "last_modified_at": None
        }
    
    # Update last activity
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"last_activity": datetime.utcnow()}}
    )
    
    # Convert ObjectId to string for JSON serialization
    user_data["_id"] = str(user_data["_id"])
    
    logger.debug(f"✅ User authenticated: {user_data.get('email')} (role: {user_data.get('role_name', 'N/A')})")
    
    return user_data


async def get_current_active_user(
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Dependency to get current active user (unchanged - still works)
    """
    if not current_user.get("is_active", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


# ============================================================================
# 🆕 RBAC: NEW PERMISSION-BASED DEPENDENCIES
# ============================================================================

async def check_permission(
    current_user: Dict[str, Any],
    required_permission: str,
    resource_context: Optional[Dict[str, Any]] = None
) -> bool:
    """
    🆕 NEW: Core permission checking function
    
    Args:
        current_user: Current user data
        required_permission: Permission code (e.g., "leads.create", "leads.update")
        resource_context: Optional context (e.g., lead_id for ownership check)
    
    Returns:
        bool: True if user has permission, False otherwise
    """
    # Super admin bypass
    if current_user.get("is_super_admin"):
        logger.debug(f"✅ Super admin bypass for {required_permission}")
        return True
    
    # Check effective permissions
    effective_permissions = current_user.get("effective_permissions", [])
    has_permission = required_permission in effective_permissions
    
    if has_permission:
        logger.debug(f"✅ Permission granted: {required_permission} for {current_user.get('email')}")
    else:
        logger.warning(f"❌ Permission denied: {required_permission} for {current_user.get('email')}")
    
    return has_permission


def get_user_with_permission(required_permission: str, error_message: Optional[str] = None):
    """
    🆕 NEW: Dependency factory for permission-based access control
    
    Creates a dependency that checks if user has specific permission.
    This replaces the old role-based checks.
    
    Usage:
        @router.post("/leads")
        async def create_lead(
            current_user: Dict = Depends(get_user_with_permission("leads.create"))
        ):
            # User is guaranteed to have leads.create permission
            ...
    
    Args:
        required_permission: Permission code required
        error_message: Custom error message (optional)
    
    Returns:
        Dependency function
    """
    async def permission_checker(
        current_user: Dict[str, Any] = Depends(get_current_active_user)
    ) -> Dict[str, Any]:
        has_permission = await check_permission(current_user, required_permission)
        
        if not has_permission:
            detail = error_message or f"Missing required permission: {required_permission}"
            logger.warning(f"⚠️ Access denied for {current_user.get('email')}: {detail}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail
            )
        
        return current_user
    
    return permission_checker


async def get_super_admin_user(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    🆕 NEW: Dependency to ensure current user is super admin
    Use this for system-level operations only
    """
    if not current_user.get("is_super_admin"):
        logger.warning(f"⚠️ Super admin access denied for {current_user.get('email')}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required for this operation"
        )
    return current_user


# ============================================================================
# 🔄 BACKWARD COMPATIBLE: OLD DEPENDENCIES (DEPRECATED BUT STILL WORK)
# ============================================================================

async def get_admin_user(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    🔄 UPDATED: Dependency to ensure current user is admin
    
    **DEPRECATED:** Use get_user_with_permission() instead
    
    This now checks BOTH:
    1. Old role field (backward compatibility)
    2. New is_super_admin flag (RBAC)
    """
    # Check new RBAC super admin flag
    if current_user.get("is_super_admin"):
        logger.debug(f"✅ Super admin access for {current_user.get('email')}")
        return current_user
    
    # Check old role field (backward compatibility)
    if current_user.get("role") == "admin":
        logger.debug(f"✅ Admin role access for {current_user.get('email')} (legacy)")
        return current_user
    
    # Neither condition met
    logger.warning(f"⚠️ Admin access denied for {current_user.get('email')}")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not enough permissions. Admin access required."
    )


async def get_user_with_single_lead_permission(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    🔄 UPDATED: Dependency to allow admins OR users with single lead creation permission
    
    **DEPRECATED:** Use get_user_with_permission("leads.create") instead
    
    Now checks BOTH old and new permission systems for backward compatibility
    """
    # Check super admin first
    if current_user.get("is_super_admin"):
        logger.info(f"✅ Super admin {current_user.get('email')} accessing single lead creation")
        return current_user
    
    # Check new RBAC permission
    if "leads.create" in current_user.get("effective_permissions", []):
        logger.info(f"✅ User {current_user.get('email')} has leads.create permission (RBAC)")
        return current_user
    
    # Check old role (backward compatibility)
    if current_user.get("role") == "admin":
        logger.info(f"✅ Admin user {current_user.get('email')} accessing single lead creation (legacy)")
        return current_user
    
    # Check old permission structure (backward compatibility)
    permissions = current_user.get("permissions", {})
    if permissions.get("can_create_single_lead", False):
        logger.info(f"✅ User {current_user.get('email')} has single lead creation permission (legacy)")
        return current_user
    
    # No permission found
    logger.warning(f"⚠️ User {current_user.get('email')} denied single lead creation - no permission")
    
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You don't have permission to create leads. Contact your administrator to request access."
    )


async def get_user_with_bulk_lead_permission(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
) -> Dict[str, Any]:
    """
    🔄 UPDATED: Dependency to allow admins OR users with bulk lead creation permission
    
    **DEPRECATED:** Use get_user_with_permission("leads.create_bulk") instead
    
    Now checks BOTH old and new permission systems for backward compatibility
    """
    # Check super admin first
    if current_user.get("is_super_admin"):
        logger.info(f"✅ Super admin {current_user.get('email')} accessing bulk lead creation")
        return current_user
    
    # Check new RBAC permission
    if "leads.create_bulk" in current_user.get("effective_permissions", []):
        logger.info(f"✅ User {current_user.get('email')} has leads.create_bulk permission (RBAC)")
        return current_user
    
    # Check old role (backward compatibility)
    if current_user.get("role") == "admin":
        logger.info(f"✅ Admin user {current_user.get('email')} accessing bulk lead creation (legacy)")
        return current_user
    
    # Check old permission structure (backward compatibility)
    permissions = current_user.get("permissions", {})
    if permissions.get("can_create_bulk_leads", False):
        logger.info(f"✅ User {current_user.get('email')} has bulk lead creation permission (legacy)")
        return current_user
    
    # No permission found
    logger.warning(f"⚠️ User {current_user.get('email')} denied bulk lead creation - no permission")
    
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You don't have permission to create bulk leads. Contact your administrator to request access."
    )


# ============================================================================
# 🆕 RBAC: NEW HELPER FUNCTIONS
# ============================================================================

async def check_user_permission_async(
    current_user: Dict[str, Any],
    permission_code: str
) -> bool:
    """
    🆕 NEW: Async helper to check if user has specific permission
    
    Args:
        current_user: Current user data
        permission_code: RBAC permission code (e.g., "leads.create")
    
    Returns:
        bool: True if user has permission
    """
    return await check_permission(current_user, permission_code)


def check_user_permission(current_user: Dict[str, Any], permission_name: str) -> bool:
    """
    🔄 UPDATED: Helper function to check if user has specific permission
    
    **UPDATED:** Now checks BOTH old and new permission systems
    
    Args:
        current_user: Current user data from JWT
        permission_name: Can be:
            - RBAC permission code (e.g., "leads.create")
            - Old permission name (e.g., "can_create_single_lead")
    
    Returns:
        bool: True if user has permission, False otherwise
    """
    # Super admin bypass
    if current_user.get("is_super_admin"):
        return True
    
    # Check old admin role (backward compatibility)
    if current_user.get("role") == "admin":
        return True
    
    # Check new RBAC permissions
    effective_permissions = current_user.get("effective_permissions", [])
    if permission_name in effective_permissions:
        return True
    
    # Check old permission structure (backward compatibility)
    permissions = current_user.get("permissions", {})
    if permissions.get(permission_name, False):
        return True
    
    return False


def get_user_permissions_summary(current_user: Dict[str, Any]) -> Dict[str, Any]:
    """
    🔄 UPDATED: Get a summary of user's permissions for UI display
    
    **UPDATED:** Now includes RBAC permissions alongside legacy permissions
    
    Returns:
        dict: Comprehensive summary of user permissions and capabilities
    """
    is_super_admin = current_user.get("is_super_admin", False)
    user_role = current_user.get("role")
    effective_permissions = current_user.get("effective_permissions", [])
    old_permissions = current_user.get("permissions", {})
    
    # Super admin has everything
    if is_super_admin:
        return {
            "is_super_admin": True,
            "is_admin": True,
            "role_name": current_user.get("role_name", "Super Admin"),
            "role_id": current_user.get("role_id"),
            
            # RBAC permissions
            "effective_permissions": effective_permissions,
            "permission_count": len(effective_permissions),
            "permission_overrides_count": len(current_user.get("permission_overrides", [])),
            
            # Legacy permissions (all true for super admin)
            "can_create_single_lead": True,
            "can_create_bulk_leads": True,
            "can_manage_permissions": True,
            "can_assign_leads": True,
            "can_view_all_leads": True,
            
            # Team hierarchy
            "team_level": current_user.get("team_level", 0),
            "has_team_members": len(current_user.get("team_members", [])) > 0,
            "reports_to": current_user.get("reports_to_name"),
            
            "permission_source": "super_admin"
        }
    
    # Legacy admin role
    if user_role == "admin":
        return {
            "is_super_admin": False,
            "is_admin": True,
            "role_name": current_user.get("role_name", "Admin"),
            "role_id": current_user.get("role_id"),
            
            # RBAC permissions
            "effective_permissions": effective_permissions,
            "permission_count": len(effective_permissions),
            
            # Legacy permissions (all true for admin)
            "can_create_single_lead": True,
            "can_create_bulk_leads": True,
            "can_manage_permissions": True,
            "can_assign_leads": True,
            "can_view_all_leads": True,
            
            # Team hierarchy
            "team_level": current_user.get("team_level", 0),
            "has_team_members": len(current_user.get("team_members", [])) > 0,
            "reports_to": current_user.get("reports_to_name"),
            
            "permission_source": "admin_role_legacy"
        }
    
    # Regular user with RBAC
    return {
        "is_super_admin": False,
        "is_admin": False,
        "role_name": current_user.get("role_name", "User"),
        "role_id": current_user.get("role_id"),
        
        # RBAC permissions
        "effective_permissions": effective_permissions,
        "permission_count": len(effective_permissions),
        "permission_overrides_count": len(current_user.get("permission_overrides", [])),
        
        # Check specific permissions
        "can_create_single_lead": (
            "leads.create" in effective_permissions or 
            old_permissions.get("can_create_single_lead", False)
        ),
        "can_create_bulk_leads": (
            "leads.create_bulk" in effective_permissions or 
            old_permissions.get("can_create_bulk_leads", False)
        ),
        "can_manage_permissions": "permissions.manage" in effective_permissions,
        "can_assign_leads": (
            "leads.assign_any" in effective_permissions or
            "leads.assign_team" in effective_permissions
        ),
        "can_view_all_leads": "leads.read_all" in effective_permissions,
        "can_view_team_leads": "leads.read_team" in effective_permissions,
        "can_view_own_leads": "leads.read_own" in effective_permissions,
        
        # Team hierarchy
        "team_level": current_user.get("team_level", 0),
        "has_team_members": len(current_user.get("team_members", [])) > 0,
        "reports_to": current_user.get("reports_to_name"),
        
        "permission_source": "rbac",
        "granted_by": old_permissions.get("granted_by"),
        "granted_at": old_permissions.get("granted_at"),
        "permissions_last_computed": current_user.get("permissions_last_computed")
    }


def has_any_permission(current_user: Dict[str, Any], permission_codes: List[str]) -> bool:
    """
    🆕 NEW: Check if user has ANY of the specified permissions
    
    Args:
        current_user: Current user data
        permission_codes: List of permission codes
    
    Returns:
        bool: True if user has at least one permission
    """
    # Super admin has all permissions
    if current_user.get("is_super_admin"):
        return True
    
    # Check if user has any of the permissions
    effective_permissions = current_user.get("effective_permissions", [])
    return any(perm in effective_permissions for perm in permission_codes)


def has_all_permissions(current_user: Dict[str, Any], permission_codes: List[str]) -> bool:
    """
    🆕 NEW: Check if user has ALL of the specified permissions
    
    Args:
        current_user: Current user data
        permission_codes: List of permission codes
    
    Returns:
        bool: True if user has all permissions
    """
    # Super admin has all permissions
    if current_user.get("is_super_admin"):
        return True
    
    # Check if user has all permissions
    effective_permissions = current_user.get("effective_permissions", [])
    return all(perm in effective_permissions for perm in permission_codes)


# ============================================================================
# 🆕 CONVENIENCE DEPENDENCIES FOR COMMON USE CASES
# ============================================================================

# Lead permissions
get_user_with_lead_create = lambda: get_user_with_permission("leads.create", "You don't have permission to create leads")
get_user_with_lead_update = lambda: get_user_with_permission("leads.update", "You don't have permission to update leads")
get_user_with_lead_delete = lambda: get_user_with_permission("leads.delete", "You don't have permission to delete leads")
get_user_with_lead_read_all = lambda: get_user_with_permission("leads.read_all", "You don't have permission to view all leads")

# Contact permissions
get_user_with_contact_create = lambda: get_user_with_permission("contacts.create", "You don't have permission to create contacts")
get_user_with_contact_update = lambda: get_user_with_permission("contacts.update", "You don't have permission to update contacts")
get_user_with_contact_delete = lambda: get_user_with_permission("contacts.delete", "You don't have permission to delete contacts")

# Task permissions
get_user_with_task_create = lambda: get_user_with_permission("tasks.create", "You don't have permission to create tasks")
get_user_with_task_update = lambda: get_user_with_permission("tasks.update", "You don't have permission to update tasks")
get_user_with_task_delete = lambda: get_user_with_permission("tasks.delete", "You don't have permission to delete tasks")

# Permission management
get_user_with_permission_manage = lambda: get_user_with_permission("permissions.manage", "You don't have permission to manage permissions")
get_user_with_role_manage = lambda: get_user_with_permission("roles.manage", "You don't have permission to manage roles")

# User management
get_user_with_user_create = lambda: get_user_with_permission("users.create", "You don't have permission to create users")
get_user_with_user_update = lambda: get_user_with_permission("users.update", "You don't have permission to update users")
get_user_with_user_delete = lambda: get_user_with_permission("users.delete", "You don't have permission to delete users")

