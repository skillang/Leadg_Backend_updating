# app/services/permission_service.py - UPDATED FOR RBAC SYSTEM
# Changes: Refactored to handle all 69 permissions, added permission override management

from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import HTTPException
from ..config.database import get_database
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

class PermissionService:
    """Service class for managing user permissions - UPDATED FOR RBAC"""
    
    def __init__(self):
        self.db = None
    
    def _get_db(self):
        """Lazy database connection - only connect when needed"""
        if self.db is None:
            self.db = get_database()
        return self.db
    
    # ============================================================================
    # 🆕 NEW RBAC METHODS - Generic Permission Management
    # ============================================================================
    
    async def get_all_permissions(self) -> List[Dict[str, Any]]:
        """
        Get all 69 permissions from database
        
        Returns:
            List of all permission definitions
        """
        try:
            logger.info("Fetching all permissions")
            
            db = self._get_db()
            
            # Get all permissions from database
            cursor = db.permissions.find({}).sort("category", 1)
            permissions = await cursor.to_list(None)
            
            # Convert ObjectId to string
            for perm in permissions:
                perm["_id"] = str(perm["_id"])
            
            logger.info(f"Retrieved {len(permissions)} permissions")
            
            return permissions
            
        except Exception as e:
            logger.error(f"Error fetching permissions: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch permissions: {str(e)}"
            )
    
    async def get_permissions_by_category(self, category: str) -> List[Dict[str, Any]]:
        """
        Get permissions filtered by category
        
        Args:
            category: Permission category (e.g., 'lead_management')
            
        Returns:
            List of permissions in the category
        """
        try:
            logger.info(f"Fetching permissions for category: {category}")
            
            db = self._get_db()
            
            cursor = db.permissions.find({"category": category})
            permissions = await cursor.to_list(None)
            
            # Convert ObjectId to string
            for perm in permissions:
                perm["_id"] = str(perm["_id"])
            
            logger.info(f"Retrieved {len(permissions)} permissions for {category}")
            
            return permissions
            
        except Exception as e:
            logger.error(f"Error fetching permissions by category: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch permissions: {str(e)}"
            )
    
    async def get_permission_categories(self) -> List[Dict[str, Any]]:
        """
        Get all unique permission categories with counts
        
        Returns:
            List of categories with permission counts
        """
        try:
            logger.info("Fetching permission categories")
            
            db = self._get_db()
            
            # Aggregate by category
            pipeline = [
                {
                    "$group": {
                        "_id": "$category",
                        "count": {"$sum": 1},
                        "permissions": {"$push": "$code"}
                    }
                },
                {"$sort": {"_id": 1}}
            ]
            
            cursor = db.permissions.aggregate(pipeline)
            categories = await cursor.to_list(None)
            
            # Format response
            result = []
            for cat in categories:
                result.append({
                    "category": cat["_id"],
                    "display_name": cat["_id"].replace("_", " ").title(),
                    "permission_count": cat["count"],
                    "permission_codes": cat["permissions"]
                })
            
            logger.info(f"Retrieved {len(result)} categories")
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching categories: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch categories: {str(e)}"
            )
    
    async def get_permission_by_code(self, permission_code: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific permission by its code
        
        Args:
            permission_code: Permission code (e.g., 'lead.create')
            
        Returns:
            Permission document or None
        """
        try:
            db = self._get_db()
            
            permission = await db.permissions.find_one({"code": permission_code})
            
            if permission:
                permission["_id"] = str(permission["_id"])
            
            return permission
            
        except Exception as e:
            logger.error(f"Error fetching permission {permission_code}: {str(e)}")
            return None
    
    async def add_permission_override(
        self,
        user_email: str,
        permission_code: str,
        granted: bool,
        admin_user: Dict[str, Any],
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Add or update a permission override for a user
        
        Args:
            user_email: User to grant/deny permission
            permission_code: Permission code (e.g., 'lead.delete_all')
            granted: True to grant, False to deny
            admin_user: Admin making the change
            reason: Reason for override
            
        Returns:
            Updated user with new override
        """
        try:
            logger.info(f"Adding permission override for {user_email}: {permission_code} = {granted}")
            
            db = self._get_db()
            
            # Verify user exists
            user = await db.users.find_one({"email": user_email, "is_active": True})
            if not user:
                raise HTTPException(
                    status_code=404,
                    detail=f"User {user_email} not found or inactive"
                )
            
            # Verify permission exists
            permission = await self.get_permission_by_code(permission_code)
            if not permission:
                raise HTTPException(
                    status_code=404,
                    detail=f"Permission {permission_code} not found"
                )
            
            # Prevent self-modification
            if user_email == admin_user.get("email"):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot modify your own permission overrides"
                )
            
            # Create override object
            override = {
                "permission_code": permission_code,
                "granted": granted,
                "granted_by": admin_user.get("email"),
                "granted_at": datetime.utcnow(),
                "reason": reason
            }
            
            # Check if override already exists
            existing_overrides = user.get("permission_overrides", [])
            override_exists = False
            
            for i, existing in enumerate(existing_overrides):
                if existing.get("permission_code") == permission_code:
                    existing_overrides[i] = override
                    override_exists = True
                    break
            
            if not override_exists:
                existing_overrides.append(override)
            
            # Update user
            result = await db.users.update_one(
                {"email": user_email},
                {
                    "$set": {
                        "permission_overrides": existing_overrides,
                        "permissions_last_computed": None  # Force recompute
                    }
                }
            )
            
            if result.modified_count == 0:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to add permission override"
                )
            
            # Log the change
            await self._log_permission_override(
                user_email=user_email,
                permission_code=permission_code,
                granted=granted,
                admin_user=admin_user,
                reason=reason
            )
            
            logger.info(f"✅ Permission override added for {user_email}: {permission_code}")
            
            return {
                "success": True,
                "message": f"Permission override added: {permission_code}",
                "user_email": user_email,
                "permission_code": permission_code,
                "granted": granted,
                "override": override
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error adding permission override: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to add permission override: {str(e)}"
            )
    
    async def remove_permission_override(
        self,
        user_email: str,
        permission_code: str,
        admin_user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Remove a permission override from a user
        
        Args:
            user_email: User to remove override from
            permission_code: Permission code to remove
            admin_user: Admin making the change
            
        Returns:
            Success status
        """
        try:
            logger.info(f"Removing permission override for {user_email}: {permission_code}")
            
            db = self._get_db()
            
            # Remove the override
            result = await db.users.update_one(
                {"email": user_email},
                {
                    "$pull": {
                        "permission_overrides": {"permission_code": permission_code}
                    },
                    "$set": {
                        "permissions_last_computed": None  # Force recompute
                    }
                }
            )
            
            if result.modified_count == 0:
                raise HTTPException(
                    status_code=404,
                    detail="Permission override not found or already removed"
                )
            
            logger.info(f"✅ Permission override removed for {user_email}: {permission_code}")
            
            return {
                "success": True,
                "message": f"Permission override removed: {permission_code}",
                "user_email": user_email,
                "permission_code": permission_code
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error removing permission override: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to remove permission override: {str(e)}"
            )
    
    async def get_user_effective_permissions(self, user_email: str) -> List[str]:
        """
        Get computed effective permissions for a user
        
        Args:
            user_email: User email
            
        Returns:
            List of permission codes the user has
        """
        try:
            db = self._get_db()
            
            user = await db.users.find_one({"email": user_email})
            if not user:
                raise HTTPException(
                    status_code=404,
                    detail=f"User {user_email} not found"
                )
            
            # Return effective_permissions from user document
            # (These are computed by rbac_service)
            return user.get("effective_permissions", [])
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting effective permissions: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get effective permissions: {str(e)}"
            )
    
    async def get_permission_matrix(self) -> Dict[str, Any]:
        """
        Get permission matrix for UI display (Strapi-style)
        
        Returns:
            Structured permission matrix by category
        """
        try:
            logger.info("Building permission matrix")
            
            # Get all permissions grouped by category
            all_permissions = await self.get_all_permissions()
            
            # Group by category
            matrix = {}
            for perm in all_permissions:
                category = perm["category"]
                if category not in matrix:
                    matrix[category] = {
                        "display_name": category.replace("_", " ").title(),
                        "permissions": []
                    }
                
                matrix[category]["permissions"].append({
                    "code": perm["code"],
                    "name": perm["name"],
                    "description": perm.get("description", ""),
                    "scope": perm.get("scope", "own"),
                    "resource": perm.get("resource", ""),
                    "action": perm.get("action", "")
                })
            
            logger.info(f"Built permission matrix with {len(matrix)} categories")
            
            return {
                "success": True,
                "categories": matrix,
                "total_permissions": len(all_permissions)
            }
            
        except Exception as e:
            logger.error(f"Error building permission matrix: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to build permission matrix: {str(e)}"
            )
    
    # ============================================================================
    # 🔄 OLD METHODS - Kept for backward compatibility with 2-permission system
    # ============================================================================
    
    async def update_user_permissions(
        self, 
        user_email: str, 
        permissions: Dict[str, Any],
        admin_user: Dict[str, Any],
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        DEPRECATED: Update user lead creation permissions (old 2-permission system)
        
        This method is kept for backward compatibility but should be migrated to
        use permission overrides in the new RBAC system.
        
        Args:
            user_email: Email of user to update
            permissions: Dict with permission flags
            admin_user: Admin user making the change
            reason: Optional reason for the change
            
        Returns:
            Dict with success status and details
        """
        try:
            logger.info(f"[DEPRECATED] Updating old permissions for {user_email} by {admin_user.get('email')}")
            
            db = self._get_db()
            
            # Verify target user exists and is active
            user = await db.users.find_one({"email": user_email, "is_active": True})
            if not user:
                raise HTTPException(
                    status_code=404, 
                    detail=f"User {user_email} not found or inactive"
                )
            
            # Prevent self-permission modification
            admin_email = admin_user.get("email")
            if user_email == admin_email:
                raise HTTPException(
                    status_code=400, 
                    detail="Cannot modify your own permissions"
                )
            
            # Prevent modifying super admin permissions
            if user.get("is_super_admin", False):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot modify permissions for super admin users"
                )
            
            # Get current permissions
            current_permissions = user.get("permissions", {})
            
            # Prepare update data
            update_data = {
                "permissions.can_create_single_lead": permissions.get("can_create_single_lead", False),
                "permissions.can_create_bulk_leads": permissions.get("can_create_bulk_leads", False),
                "permissions.last_modified_by": admin_email,
                "permissions.last_modified_at": datetime.utcnow()
            }
            
            # Set granted_by and granted_at only if granting new permissions for the first time
            granting_permission = (
                permissions.get("can_create_single_lead", False) or 
                permissions.get("can_create_bulk_leads", False)
            )
            
            if granting_permission and not current_permissions.get("granted_by"):
                update_data["permissions.granted_by"] = admin_email
                update_data["permissions.granted_at"] = datetime.utcnow()
            
            # Update user permissions in database
            result = await db.users.update_one(
                {"email": user_email},
                {"$set": update_data}
            )
            
            if result.modified_count == 0:
                logger.warning(f"No changes made to permissions for {user_email}")
                return {
                    "success": True,
                    "message": "No changes were needed",
                    "user_email": user_email,
                    "permissions_changed": False
                }
            
            # Get updated user data
            updated_user = await db.users.find_one({"email": user_email})
            updated_permissions = updated_user.get("permissions", {})
            
            # Log the permission change
            await self._log_permission_change(
                user_email=user_email,
                old_permissions=current_permissions,
                new_permissions=permissions,
                admin_user=admin_user,
                reason=reason
            )
            
            logger.info(f"✅ Successfully updated old permissions for {user_email}")
            
            return {
                "success": True,
                "message": "Permissions updated successfully",
                "user_email": user_email,
                "permissions_changed": True,
                "old_permissions": {
                    "can_create_single_lead": current_permissions.get("can_create_single_lead", False),
                    "can_create_bulk_leads": current_permissions.get("can_create_bulk_leads", False)
                },
                "new_permissions": {
                    "can_create_single_lead": updated_permissions.get("can_create_single_lead", False),
                    "can_create_bulk_leads": updated_permissions.get("can_create_bulk_leads", False),
                    "granted_by": updated_permissions.get("granted_by"),
                    "granted_at": updated_permissions.get("granted_at"),
                    "last_modified_by": updated_permissions.get("last_modified_by"),
                    "last_modified_at": updated_permissions.get("last_modified_at")
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating permissions for {user_email}: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to update permissions: {str(e)}"
            )
    
    async def get_users_with_permissions(self, include_admins: bool = False) -> List[Dict[str, Any]]:
        """
        Get all users with their current permissions (both old and new system)
        
        Args:
            include_admins: Whether to include admin users in results
            
        Returns:
            List of users with permission information
        """
        try:
            logger.info("Fetching users with permissions")
            
            db = self._get_db()
            
            # Build query
            query = {"is_active": True}
            
            # Get users from database
            cursor = db.users.find(
                query, 
                {
                    "email": 1, 
                    "first_name": 1, 
                    "last_name": 1, 
                    "role_id": 1,
                    "role_name": 1,
                    "is_super_admin": 1,
                    "permissions": 1,  # Old system
                    "permission_overrides": 1,  # New system
                    "effective_permissions": 1,  # New system
                    "created_at": 1,
                    "last_login": 1,
                    "departments": 1
                }
            )
            
            users = await cursor.to_list(None)
            
            # Process users and ensure permissions field exists
            processed_users = []
            for user in users:
                # Ensure old permissions field exists
                if "permissions" not in user:
                    user["permissions"] = {
                        "can_create_single_lead": False,
                        "can_create_bulk_leads": False,
                        "granted_by": None,
                        "granted_at": None,
                        "last_modified_by": None,
                        "last_modified_at": None
                    }
                
                # Add computed fields
                user["_id"] = str(user["_id"])
                user["full_name"] = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                if not user["full_name"]:
                    user["full_name"] = user.get("email", "Unknown")
                
                # Add RBAC permission info
                user["rbac_info"] = {
                    "role_name": user.get("role_name", "Unknown"),
                    "is_super_admin": user.get("is_super_admin", False),
                    "override_count": len(user.get("permission_overrides", [])),
                    "effective_permission_count": len(user.get("effective_permissions", []))
                }
                
                # Add old permission summary
                permissions = user.get("permissions", {})
                user["permission_summary"] = {
                    "has_any_permission": (
                        permissions.get("can_create_single_lead", False) or 
                        permissions.get("can_create_bulk_leads", False)
                    ),
                    "permission_level": self._get_permission_level(permissions),
                    "granted_by": permissions.get("granted_by"),
                    "granted_at": permissions.get("granted_at")
                }
                
                processed_users.append(user)
            
            # Sort by role and name
            processed_users.sort(key=lambda x: (
                not x.get("is_super_admin", False),  # Super admins first
                x.get("role_name", ""),
                x["full_name"]
            ))
            
            logger.info(f"Retrieved {len(processed_users)} users with permissions")
            
            return processed_users
            
        except Exception as e:
            logger.error(f"Error fetching users with permissions: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch users: {str(e)}"
            )
    
    async def revoke_all_permissions(
        self, 
        user_email: str, 
        admin_user: Dict[str, Any],
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        DEPRECATED: Revoke all old lead creation permissions from a user
        
        Args:
            user_email: Email of user to revoke permissions from
            admin_user: Admin user making the change
            reason: Optional reason for revocation
            
        Returns:
            Dict with success status and details
        """
        try:
            logger.info(f"[DEPRECATED] Revoking old permissions for {user_email} by {admin_user.get('email')}")
            
            # Use the update method to revoke all permissions
            result = await self.update_user_permissions(
                user_email=user_email,
                permissions={
                    "can_create_single_lead": False,
                    "can_create_bulk_leads": False
                },
                admin_user=admin_user,
                reason=reason or "All permissions revoked"
            )
            
            if result["success"]:
                result["message"] = f"All old permissions revoked for {user_email}"
                logger.info(f"✅ Successfully revoked old permissions for {user_email}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error revoking permissions for {user_email}: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to revoke permissions: {str(e)}"
            )
    
    async def get_permission_summary(self) -> Dict[str, Any]:
        """
        Get a summary of permission distribution across all users (old + new system)
        
        Returns:
            Dict with permission statistics
        """
        try:
            logger.info("Generating permission summary")
            
            db = self._get_db()
            
            # Get all active users
            users = await db.users.find(
                {"is_active": True},
                {
                    "permissions": 1,
                    "is_super_admin": 1,
                    "role_name": 1,
                    "permission_overrides": 1,
                    "effective_permissions": 1
                }
            ).to_list(None)
            
            # Calculate statistics for old system
            total_users = len(users)
            users_with_single_permission = 0
            users_with_bulk_permission = 0
            users_with_any_permission = 0
            users_with_no_permissions = 0
            
            # Calculate statistics for new RBAC system
            super_admins = 0
            users_with_overrides = 0
            total_effective_permissions = 0
            
            for user in users:
                # Old system stats
                permissions = user.get("permissions", {})
                can_single = permissions.get("can_create_single_lead", False)
                can_bulk = permissions.get("can_create_bulk_leads", False)
                
                if can_single:
                    users_with_single_permission += 1
                if can_bulk:
                    users_with_bulk_permission += 1
                if can_single or can_bulk:
                    users_with_any_permission += 1
                else:
                    users_with_no_permissions += 1
                
                # New RBAC stats
                if user.get("is_super_admin", False):
                    super_admins += 1
                
                if user.get("permission_overrides", []):
                    users_with_overrides += 1
                
                total_effective_permissions += len(user.get("effective_permissions", []))
            
            # Calculate percentages
            def calc_percentage(count: int, total: int) -> float:
                return round((count / total * 100) if total > 0 else 0, 1)
            
            summary = {
                "total_users": total_users,
                
                # Old system stats
                "old_permission_system": {
                    "users_with_single_permission": users_with_single_permission,
                    "users_with_bulk_permission": users_with_bulk_permission,
                    "users_with_any_permission": users_with_any_permission,
                    "users_with_no_permissions": users_with_no_permissions,
                    "percentages": {
                        "with_single_permission": calc_percentage(users_with_single_permission, total_users),
                        "with_bulk_permission": calc_percentage(users_with_bulk_permission, total_users),
                        "with_any_permission": calc_percentage(users_with_any_permission, total_users),
                        "with_no_permissions": calc_percentage(users_with_no_permissions, total_users)
                    }
                },
                
                # New RBAC stats
                "rbac_system": {
                    "super_admins": super_admins,
                    "users_with_overrides": users_with_overrides,
                    "average_permissions_per_user": round(total_effective_permissions / total_users if total_users > 0 else 0, 1),
                    "percentages": {
                        "super_admins": calc_percentage(super_admins, total_users),
                        "with_overrides": calc_percentage(users_with_overrides, total_users)
                    }
                }
            }
            
            logger.info(f"Permission summary generated for {total_users} users")
            
            return summary
            
        except Exception as e:
            logger.error(f"Error generating permission summary: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate permission summary: {str(e)}"
            )
    
    # ============================================================================
    # PRIVATE HELPER METHODS
    # ============================================================================
    
    async def _log_permission_change(
        self,
        user_email: str,
        old_permissions: Dict[str, Any],
        new_permissions: Dict[str, Any],
        admin_user: Dict[str, Any],
        reason: Optional[str] = None
    ) -> None:
        """
        Log OLD permission changes for audit purposes
        
        Args:
            user_email: User whose permissions changed
            old_permissions: Previous permission state
            new_permissions: New permission state
            admin_user: Admin who made the change
            reason: Optional reason for the change
        """
        try:
            # Create audit log entry
            audit_entry = {
                "action": "permission_change_old_system",
                "target_user_email": user_email,
                "admin_user_email": admin_user.get("email"),
                "admin_user_name": f"{admin_user.get('first_name', '')} {admin_user.get('last_name', '')}".strip(),
                "timestamp": datetime.utcnow(),
                "changes": {
                    "old_permissions": {
                        "can_create_single_lead": old_permissions.get("can_create_single_lead", False),
                        "can_create_bulk_leads": old_permissions.get("can_create_bulk_leads", False)
                    },
                    "new_permissions": {
                        "can_create_single_lead": new_permissions.get("can_create_single_lead", False),
                        "can_create_bulk_leads": new_permissions.get("can_create_bulk_leads", False)
                    }
                },
                "reason": reason
            }
            
            db = self._get_db()
            
            # Store in audit collection
            await db.permission_audit_log.insert_one(audit_entry)
            
            logger.info(f"Logged old permission change for {user_email}")
            
        except Exception as e:
            logger.error(f"Failed to log permission change: {str(e)}")
    
    async def _log_permission_override(
        self,
        user_email: str,
        permission_code: str,
        granted: bool,
        admin_user: Dict[str, Any],
        reason: Optional[str] = None
    ) -> None:
        """
        Log NEW RBAC permission override for audit purposes
        
        Args:
            user_email: User whose permissions changed
            permission_code: Permission that was overridden
            granted: Whether permission was granted or denied
            admin_user: Admin who made the change
            reason: Optional reason for the change
        """
        try:
            # Create audit log entry
            audit_entry = {
                "action": "permission_override",
                "entity_type": "user_permission",
                "target_user_email": user_email,
                "permission_code": permission_code,
                "granted": granted,
                "performed_by": admin_user.get("email"),
                "performed_by_name": f"{admin_user.get('first_name', '')} {admin_user.get('last_name', '')}".strip(),
                "timestamp": datetime.utcnow(),
                "reason": reason
            }
            
            db = self._get_db()
            
            # Store in audit collection
            await db.permission_audit_log.insert_one(audit_entry)
            
            logger.info(f"Logged permission override for {user_email}: {permission_code}")
            
        except Exception as e:
            logger.error(f"Failed to log permission override: {str(e)}")
    
    def _get_permission_level(self, permissions: Dict[str, Any]) -> int:
        """
        Get numeric permission level for sorting (OLD system)
        
        Args:
            permissions: User permissions dict
            
        Returns:
            int: Permission level (0=none, 1=single, 2=bulk, 3=both)
        """
        can_single = permissions.get("can_create_single_lead", False)
        can_bulk = permissions.get("can_create_bulk_leads", False)
        
        if can_single and can_bulk:
            return 3  # Both permissions
        elif can_bulk:
            return 2  # Bulk only
        elif can_single:
            return 1  # Single only
        else:
            return 0  # No permissions

# Create singleton instance
permission_service = PermissionService()