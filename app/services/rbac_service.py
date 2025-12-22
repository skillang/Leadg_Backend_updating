

import logging
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timedelta
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..config.database import get_database
from ..config.settings import settings

logger = logging.getLogger(__name__)


class RBACService:
    """
    Core RBAC service for permission checking and management
    """
    
    def __init__(self):
        """Initialize RBAC service"""
        self._db = None
        self._permission_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = getattr(settings, 'permission_cache_ttl', 3600)  # 1 hour default
    
    def _get_db(self) -> AsyncIOMotorDatabase:
        """Lazy database connection"""
        if self._db is None:
            self._db = get_database()
        return self._db
    
    # ========================================
    # CORE PERMISSION CHECKING
    # ========================================
    
    async def check_permission(
        self,
        user: Dict[str, Any],
        permission_code: str,
        resource_id: Optional[str] = None,
        check_ownership: bool = False
    ) -> bool:
        """
        Check if user has a specific permission
        
        This is the MAIN permission checking function used throughout the app.
        
        Priority order:
        1. Super Admin → Always granted
        2. Permission Overrides → Explicit grant/deny
        3. Role Permissions → From user's role
        4. Default → Deny
        
        Args:
            user: User dict with id, email, role_id, is_super_admin, etc.
            permission_code: Permission code to check (e.g., "lead.create")
            resource_id: Optional resource ID for ownership checks
            check_ownership: Whether to verify ownership for "own" scope
            
        Returns:
            bool: Whether user has the permission
        """
        try:
            # 1. SUPER ADMIN CHECK - Always grant all permissions
            if user.get("is_super_admin", False):
                logger.debug(f"✅ Super admin {user.get('email')} granted {permission_code}")
                return True
            
            # 2. PERMISSION OVERRIDES CHECK
            overrides = user.get("permission_overrides", [])
            for override in overrides:
                if override.get("permission_code") == permission_code:
                    # Check if override is expired
                    expires_at = override.get("expires_at")
                    if expires_at and datetime.utcnow() > expires_at:
                        continue
                    
                    granted = override.get("granted", False)
                    logger.debug(f"{'✅' if granted else '❌'} Override for {user.get('email')}: {permission_code} = {granted}")
                    return granted
            
            # 3. ROLE-BASED PERMISSIONS CHECK
            effective_perms = user.get("effective_permissions", [])
            
            # If effective permissions not cached, compute them
            if not effective_perms:
                user_id = user.get("_id") or user.get("id")
                if user_id:
                    effective_perms = await self.compute_effective_permissions(str(user_id))
                    user["effective_permissions"] = effective_perms
            
            has_permission = permission_code in effective_perms
            
            # 4. OWNERSHIP CHECK (if required)
            if has_permission and check_ownership and resource_id:
                # For "own" scope permissions, verify ownership
                if await self._is_own_scope(permission_code):
                    has_permission = await self._check_ownership(
                        user_id=str(user.get("_id") or user.get("id")),
                        resource_id=resource_id,
                        permission_code=permission_code
                    )
            
            logger.debug(f"{'✅' if has_permission else '❌'} Role check for {user.get('email')}: {permission_code}")
            return has_permission
            
        except Exception as e:
            logger.error(f"Error checking permission {permission_code} for user {user.get('email')}: {e}")
            return False  # Fail closed
    
    async def check_multiple_permissions(
        self,
        user: Dict[str, Any],
        permission_codes: List[str],
        require_all: bool = True
    ) -> bool:
        """
        Check if user has multiple permissions
        
        Args:
            user: User dict
            permission_codes: List of permission codes to check
            require_all: If True, requires ALL permissions. If False, requires ANY.
            
        Returns:
            bool: Whether user has required permissions
        """
        try:
            if not permission_codes:
                return True
            
            results = []
            for code in permission_codes:
                has_perm = await self.check_permission(user, code)
                results.append(has_perm)
            
            if require_all:
                return all(results)
            else:
                return any(results)
                
        except Exception as e:
            logger.error(f"Error checking multiple permissions: {e}")
            return False
    
    # ========================================
    # EFFECTIVE PERMISSIONS COMPUTATION
    # ========================================
    
    async def compute_effective_permissions(
        self,
        user_id: str,
        force_recompute: bool = False
    ) -> List[str]:
        """
        Compute effective permissions for a user
        
        Combines:
        - Role-based permissions
        - Individual permission overrides
        - Super admin status
        
        Results are cached for PERMISSION_CACHE_TTL seconds.
        
        Args:
            user_id: User ObjectId as string
            force_recompute: Force recomputation even if cached
            
        Returns:
            List of permission codes
        """
        try:
            db = self._get_db()
            
            # Check cache first
            cache_key = f"user_perms_{user_id}"
            if not force_recompute and cache_key in self._permission_cache:
                cached = self._permission_cache[cache_key]
                cached_at = cached.get("timestamp")
                if cached_at and (datetime.utcnow() - cached_at).seconds < self._cache_ttl:
                    logger.debug(f"✅ Using cached permissions for user {user_id}")
                    return cached.get("permissions", [])
            
            # Get user
            user = await db.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                logger.warning(f"User {user_id} not found")
                return []
            
            # Super admins get ALL permissions
            if user.get("is_super_admin", False):
                all_permissions = await self._get_all_permission_codes()
                self._cache_permissions(user_id, all_permissions)
                logger.info(f"✅ Super admin {user.get('email')} has all {len(all_permissions)} permissions")
                return all_permissions
            
            # Get role permissions
            role_id = user.get("role_id")
            role_permissions: Set[str] = set()
            
            if role_id:
                role = await db.roles.find_one({"_id": ObjectId(role_id)})
                if role:
                    for perm_grant in role.get("permissions", []):
                        if perm_grant.get("granted", False):
                            role_permissions.add(perm_grant["permission_code"])
            
            # Apply permission overrides
            effective_permissions = role_permissions.copy()
            overrides = user.get("permission_overrides", [])
            
            for override in overrides:
                # Check expiration
                expires_at = override.get("expires_at")
                if expires_at and datetime.utcnow() > expires_at:
                    continue
                
                permission_code = override["permission_code"]
                granted = override.get("granted", False)
                
                if granted:
                    effective_permissions.add(permission_code)
                else:
                    effective_permissions.discard(permission_code)
            
            # Convert to list
            permissions_list = list(effective_permissions)
            
            # Cache result
            self._cache_permissions(user_id, permissions_list)
            
            # Update user's effective_permissions field
            await db.users.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$set": {
                        "effective_permissions": permissions_list,
                        "permissions_last_computed": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"✅ Computed {len(permissions_list)} effective permissions for user {user.get('email')}")
            return permissions_list
            
        except Exception as e:
            logger.error(f"Error computing effective permissions for user {user_id}: {e}")
            return []
    
    async def get_user_permissions(
        self,
        user_id: str,
        include_details: bool = False
    ) -> Dict[str, Any]:
        """
        Get user's complete permission information
        
        Args:
            user_id: User ObjectId as string
            include_details: Include role details and override details
            
        Returns:
            dict with permissions, role info, and overrides
        """
        try:
            db = self._get_db()
            
            user = await db.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                return {
                    "success": False,
                    "error": "User not found"
                }
            
            # Get effective permissions
            effective_perms = await self.compute_effective_permissions(user_id)
            
            result = {
                "success": True,
                "user_id": user_id,
                "user_email": user.get("email"),
                "is_super_admin": user.get("is_super_admin", False),
                "effective_permissions": effective_perms,
                "permissions_count": len(effective_perms)
            }
            
            if include_details:
                # Add role details
                role_id = user.get("role_id")
                if role_id:
                    role = await db.roles.find_one({"_id": ObjectId(role_id)})
                    if role:
                        result["role"] = {
                            "id": str(role["_id"]),
                            "name": role.get("name"),
                            "display_name": role.get("display_name"),
                            "type": role.get("type"),
                            "permissions_count": len(role.get("permissions", []))
                        }
                
                # Add overrides
                result["permission_overrides"] = user.get("permission_overrides", [])
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting user permissions: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    # ========================================
    # TEAM HIERARCHY QUERIES
    # ========================================
    
    async def get_team_members(
        self,
        user_id: str,
        include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get team members for a user (based on team_id, not hierarchy)
        
        Args:
            user_id: User ID to get team members for
            include_inactive: Include inactive users
            
        Returns:
            List of team member dicts
        """
        try:
            db = self._get_db()
            
            # Get user to find their team
            user = await db.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                return []
            
            team_id = user.get("team_id")
            if not team_id:
                return []
            
            # Build query for team members
            query = {"team_id": team_id}
            if not include_inactive:
                query["is_active"] = True
            
            # Get all members in the same team
            team_members = await db.users.find(query).to_list(length=None)
            
            return team_members
            
        except Exception as e:
            logger.error(f"Error getting team members: {e}")
            return []
    
    
    async def can_manage_user(
        self,
        manager_id: str,
        target_user_id: str
    ) -> bool:
        """
        Check if manager can manage target user (simplified - no hierarchy)
        
        Manager can manage if:
        1. Manager is super admin, OR
        2. Manager is team lead of target user's team, OR
        3. Manager has user.update permission
        
        Args:
            manager_id: Manager's user ID
            target_user_id: Target user's ID
            
        Returns:
            bool: Whether manager can manage target user
        """
        try:
            db = self._get_db()
            
            manager = await db.users.find_one({"_id": ObjectId(manager_id)})
            target = await db.users.find_one({"_id": ObjectId(target_user_id)})
            
            if not manager or not target:
                return False
            
            # Super admin can manage anyone
            if manager.get("is_super_admin", False):
                return True
            
            # Check if manager is team lead of target's team
            manager_team_id = manager.get("team_id")
            target_team_id = target.get("team_id")
            manager_is_team_lead = manager.get("is_team_lead", False)
            
            if manager_team_id and target_team_id and manager_team_id == target_team_id and manager_is_team_lead:
                return True
            
            # Check if manager has user.update permission
            has_perm = await self.check_permission(manager, "user.update")
            return has_perm
            
        except Exception as e:
            logger.error(f"Error checking if manager can manage user: {e}")
            return False
    
    # ========================================
    # HELPER METHODS
    # ========================================
    
    def _cache_permissions(self, user_id: str, permissions: List[str]):
        """Cache computed permissions"""
        cache_key = f"user_perms_{user_id}"
        self._permission_cache[cache_key] = {
            "permissions": permissions,
            "timestamp": datetime.utcnow()
        }
    
    def clear_user_cache(self, user_id: str):
        """Clear cached permissions for a user"""
        cache_key = f"user_perms_{user_id}"
        if cache_key in self._permission_cache:
            del self._permission_cache[cache_key]
            logger.debug(f"Cleared permission cache for user {user_id}")
    
    def clear_all_cache(self):
        """Clear entire permission cache"""
        self._permission_cache.clear()
        logger.info("Cleared entire permission cache")
    
    async def _get_all_permission_codes(self) -> List[str]:
        """Get all permission codes from database"""
        try:
            db = self._get_db()
            permissions = await db.permissions.find({}, {"code": 1}).to_list(length=None)
            return [p["code"] for p in permissions]
        except Exception as e:
            logger.error(f"Error getting all permission codes: {e}")
            return []
    
    async def _is_own_scope(self, permission_code: str) -> bool:
        """Check if permission has 'own' scope"""
        try:
            db = self._get_db()
            permission = await db.permissions.find_one({"code": permission_code})
            if permission:
                return permission.get("scope") == "own"
            return False
        except Exception as e:
            logger.error(f"Error checking permission scope: {e}")
            return False
    
    async def _check_ownership(
        self,
        user_id: str,
        resource_id: str,
        permission_code: str
    ) -> bool:
        """
        Check if user owns the resource
        
        This is a simplified check - you may need to customize based on your resources.
        """
        try:
            db = self._get_db()
            
            # Extract resource type from permission code
            resource_type = permission_code.split(".")[0]  # e.g., "lead" from "lead.update"
            
            # Map to collection names
            collection_map = {
                "lead": "leads",
                "contact": "contacts",
                "task": "tasks"
            }
            
            collection_name = collection_map.get(resource_type)
            if not collection_name:
                return False
            
            # Check ownership
            resource = await db[collection_name].find_one({
                "_id": ObjectId(resource_id),
                "assigned_to": user_id  # or "created_by" depending on your schema
            })
            
            return resource is not None
            
        except Exception as e:
            logger.error(f"Error checking ownership: {e}")
            return False
    
    # ========================================
    # PERMISSION VALIDATION
    # ========================================
    
    async def validate_permission_codes(
        self,
        permission_codes: List[str]
    ) -> Dict[str, Any]:
        """
        Validate that permission codes exist
        
        Args:
            permission_codes: List of permission codes to validate
            
        Returns:
            dict with valid and invalid codes
        """
        try:
            db = self._get_db()
            
            # Get all valid permissions
            valid_perms = await db.permissions.find(
                {"code": {"$in": permission_codes}},
                {"code": 1}
            ).to_list(length=None)
            
            valid_codes = {p["code"] for p in valid_perms}
            invalid_codes = set(permission_codes) - valid_codes
            
            return {
                "valid": list(valid_codes),
                "invalid": list(invalid_codes),
                "all_valid": len(invalid_codes) == 0
            }
            
        except Exception as e:
            logger.error(f"Error validating permission codes: {e}")
            return {
                "valid": [],
                "invalid": permission_codes,
                "all_valid": False,
                "error": str(e)
            }


# ========================================
# SINGLETON INSTANCE
# ========================================

rbac_service = RBACService()