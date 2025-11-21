"""
LeadG CRM - Role Management Service
====================================

Service for managing roles and role assignments.
Handles CRUD operations, role cloning, and assignment tracking.

Author: LeadG Development Team
Date: November 2025
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException, status

from ..config.database import get_database
from ..config.settings import settings
from ..models.role import RoleCreate, RoleUpdate, RoleType, RoleAssignmentStatus
from .rbac_service import rbac_service

logger = logging.getLogger(__name__)


class RoleService:
    """
    Service for role management operations
    """
    
    def __init__(self):
        """Initialize role service"""
        self._db = None
        self._max_custom_roles = getattr(settings, 'max_custom_roles', 50)
        self._allow_role_deletion = getattr(settings, 'allow_role_deletion', True)
    
    def _get_db(self):
        """Lazy database connection"""
        if self._db is None:
            self._db = get_database()
        return self._db
    
    # ========================================
    # CREATE OPERATIONS
    # ========================================
    
    async def create_role(
        self,
        role_data: RoleCreate,
        created_by: str
    ) -> Dict[str, Any]:
        """
        Create a new role
        
        Args:
            role_data: Role creation data
            created_by: Email of admin creating the role
            
        Returns:
            dict: Created role with ID
        """
        try:
            db = self._get_db()
            
            # Check if role name already exists
            existing = await db.roles.find_one({"name": role_data.name})
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Role '{role_data.name}' already exists"
                )
            
            # Check custom role limit
            if role_data.type == RoleType.CUSTOM:
                custom_count = await db.roles.count_documents({"type": "custom"})
                if custom_count >= self._max_custom_roles:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Maximum custom roles limit ({self._max_custom_roles}) reached"
                    )
            
            # Validate permission codes
            permission_codes = [p.permission_code for p in role_data.permissions]
            validation = await rbac_service.validate_permission_codes(permission_codes)
            
            if not validation["all_valid"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid permission codes: {validation['invalid']}"
                )
            
            # Prepare role document
            role_doc = {
                "name": role_data.name,
                "display_name": role_data.display_name,
                "description": role_data.description,
                "type": role_data.type,
                "is_active": role_data.is_active,
                "permissions": [p.dict() for p in role_data.permissions],
                "can_manage_users": role_data.can_manage_users,
                "can_assign_leads": role_data.can_assign_leads,
                "can_view_all_data": role_data.can_view_all_data,
                "can_export_data": role_data.can_export_data,
                "max_team_size": role_data.max_team_size,
                "users_count": 0,
                "is_deletable": role_data.type == RoleType.CUSTOM,
                "created_at": datetime.utcnow(),
                "created_by": created_by,
                "updated_at": datetime.utcnow(),
                "updated_by": None
            }
            
            # Insert role
            result = await db.roles.insert_one(role_doc)
            role_id = str(result.inserted_id)
            
            # Log audit
            await self._log_audit(
                action_type="role_created",
                entity_id=role_id,
                entity_name=role_data.name,
                performed_by=created_by,
                changes={
                    "before": {},
                    "after": {
                        "name": role_data.name,
                        "display_name": role_data.display_name,
                        "permissions_count": len(role_data.permissions)
                    }
                }
            )
            
            logger.info(f"✅ Created role '{role_data.name}' (ID: {role_id}) by {created_by}")
            
            role_doc["_id"] = result.inserted_id
            return self._format_role_response(role_doc)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating role: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create role: {str(e)}"
            )
    
    # ========================================
    # READ OPERATIONS
    # ========================================
    
    async def get_role(self, role_id: str) -> Dict[str, Any]:
        """
        Get role by ID
        
        Args:
            role_id: Role ObjectId as string
            
        Returns:
            dict: Role data
        """
        try:
            db = self._get_db()
            
            role = await db.roles.find_one({"_id": ObjectId(role_id)})
            if not role:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Role not found"
                )
            
            return self._format_role_response(role)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting role: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    
    async def get_role_by_name(self, role_name: str) -> Optional[Dict[str, Any]]:
        """
        Get role by name
        
        Args:
            role_name: Role name
            
        Returns:
            dict or None: Role data if found
        """
        try:
            db = self._get_db()
            
            role = await db.roles.find_one({"name": role_name})
            if role:
                return self._format_role_response(role)
            return None
            
        except Exception as e:
            logger.error(f"Error getting role by name: {e}")
            return None
    
    async def list_roles(
        self,
        include_inactive: bool = False,
        role_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List all roles
        
        Args:
            include_inactive: Include inactive roles
            role_type: Filter by role type (system/custom)
            
        Returns:
            dict: List of roles with metadata
        """
        try:
            db = self._get_db()
            
            # Build query
            query = {}
            if not include_inactive:
                query["is_active"] = True
            if role_type:
                query["type"] = role_type
            
            # Get roles
            roles = await db.roles.find(query).sort("created_at", 1).to_list(length=None)
            
            # Count by type
            system_roles = sum(1 for r in roles if r.get("type") == "system")
            custom_roles = sum(1 for r in roles if r.get("type") == "custom")
            
            return {
                "success": True,
                "roles": [self._format_role_response(r) for r in roles],
                "total": len(roles),
                "system_roles": system_roles,
                "custom_roles": custom_roles
            }
            
        except Exception as e:
            logger.error(f"Error listing roles: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    
    # ========================================
    # UPDATE OPERATIONS
    # ========================================
    
    async def update_role(
        self,
        role_id: str,
        role_data: RoleUpdate,
        updated_by: str
    ) -> Dict[str, Any]:
        """
        Update an existing role
        
        Args:
            role_id: Role ObjectId as string
            role_data: Updated role data
            updated_by: Email of admin updating the role
            
        Returns:
            dict: Updated role
        """
        try:
            db = self._get_db()
            
            # Get existing role
            role = await db.roles.find_one({"_id": ObjectId(role_id)})
            if not role:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Role not found"
                )
            
            # Cannot modify system roles
            if role.get("type") == "system":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot modify system roles"
                )
            
            # Validate permission codes if provided
            if role_data.permissions is not None:
                permission_codes = [p.permission_code for p in role_data.permissions]
                validation = await rbac_service.validate_permission_codes(permission_codes)
                
                if not validation["all_valid"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid permission codes: {validation['invalid']}"
                    )
            
            # Prepare update document
            update_doc = {
                "updated_at": datetime.utcnow(),
                "updated_by": updated_by
            }
            
            # Only update provided fields
            if role_data.display_name is not None:
                update_doc["display_name"] = role_data.display_name
            if role_data.description is not None:
                update_doc["description"] = role_data.description
            if role_data.permissions is not None:
                update_doc["permissions"] = [p.dict() for p in role_data.permissions]
            if role_data.can_manage_users is not None:
                update_doc["can_manage_users"] = role_data.can_manage_users
            if role_data.can_assign_leads is not None:
                update_doc["can_assign_leads"] = role_data.can_assign_leads
            if role_data.can_view_all_data is not None:
                update_doc["can_view_all_data"] = role_data.can_view_all_data
            if role_data.can_export_data is not None:
                update_doc["can_export_data"] = role_data.can_export_data
            if role_data.max_team_size is not None:
                update_doc["max_team_size"] = role_data.max_team_size
            if role_data.is_active is not None:
                update_doc["is_active"] = role_data.is_active
            
            # Update role
            result = await db.roles.update_one(
                {"_id": ObjectId(role_id)},
                {"$set": update_doc}
            )
            
            if result.modified_count == 0:
                logger.warning(f"No changes made to role {role_id}")
            
            # If permissions changed, recompute affected users' permissions
            if role_data.permissions is not None:
                await self._recompute_users_with_role(role_id)
            
            # Log audit
            await self._log_audit(
                action_type="role_updated",
                entity_id=role_id,
                entity_name=role.get("name"),
                performed_by=updated_by,
                changes={
                    "before": {k: role.get(k) for k in update_doc.keys() if k in role},
                    "after": update_doc
                }
            )
            
            logger.info(f"✅ Updated role '{role.get('name')}' (ID: {role_id}) by {updated_by}")
            
            # Get updated role
            updated_role = await db.roles.find_one({"_id": ObjectId(role_id)})
            return self._format_role_response(updated_role)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating role: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    
    # ========================================
    # DELETE OPERATIONS
    # ========================================
    
    async def delete_role(
        self,
        role_id: str,
        deleted_by: str,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Delete a role
        
        Args:
            role_id: Role ObjectId as string
            deleted_by: Email of admin deleting the role
            force: Force delete even if users have this role
            
        Returns:
            dict: Deletion result
        """
        try:
            db = self._get_db()
            
            # Check if role deletion is allowed
            if not self._allow_role_deletion:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Role deletion is disabled"
                )
            
            # Get role
            role = await db.roles.find_one({"_id": ObjectId(role_id)})
            if not role:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Role not found"
                )
            
            # Cannot delete system roles
            if role.get("type") == "system":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot delete system roles"
                )
            
            # Check if role is deletable
            if not role.get("is_deletable", True):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This role cannot be deleted"
                )
            
            # Check if role has users
            users_count = await db.users.count_documents({"role_id": ObjectId(role_id)})
            
            if users_count > 0 and not force:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot delete role with {users_count} assigned users. Use force=true to override."
                )
            
            # If force delete, reassign users to default role
            if users_count > 0 and force:
                default_role_name = getattr(settings, 'default_new_user_role', 'user')
                default_role = await db.roles.find_one({"name": default_role_name})
                
                if default_role:
                    await db.users.update_many(
                        {"role_id": ObjectId(role_id)},
                        {
                            "$set": {
                                "role_id": default_role["_id"],
                                "role_name": default_role["name"]
                            }
                        }
                    )
                    logger.info(f"Reassigned {users_count} users to '{default_role_name}' role")
            
            # Delete role
            result = await db.roles.delete_one({"_id": ObjectId(role_id)})
            
            # Log audit
            await self._log_audit(
                action_type="role_deleted",
                entity_id=role_id,
                entity_name=role.get("name"),
                performed_by=deleted_by,
                changes={
                    "before": {
                        "name": role.get("name"),
                        "users_count": users_count
                    },
                    "after": {}
                }
            )
            
            logger.info(f"✅ Deleted role '{role.get('name')}' (ID: {role_id}) by {deleted_by}")
            
            return {
                "success": True,
                "message": f"Role '{role.get('display_name')}' deleted successfully",
                "role_id": role_id,
                "affected_users": users_count
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting role: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    
    # ========================================
    # ROLE ASSIGNMENT
    # ========================================
    
    async def assign_role_to_user(
        self,
        user_email: str,
        role_id: str,
        assigned_by: str,
        reason: Optional[str] = None,
        expires_at: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Assign role to a user
        
        Args:
            user_email: User email
            role_id: Role ObjectId as string
            assigned_by: Admin email assigning the role
            reason: Optional reason for assignment
            expires_at: Optional expiration date
            
        Returns:
            dict: Assignment result
        """
        try:
            db = self._get_db()
            
            # Get user
            user = await db.users.find_one({"email": user_email})
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User {user_email} not found"
                )
            
            # Get role
            role = await db.roles.find_one({"_id": ObjectId(role_id)})
            if not role:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Role not found"
                )
            
            if not role.get("is_active", True):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot assign inactive role"
                )
            
            # Get old role ID for decrementing count
            old_role_id = user.get("role_id")
            
            # Update user's role
            await db.users.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "role_id": ObjectId(role_id),
                        "role_name": role.get("name"),
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            # Update role users_count
            if old_role_id:
                await db.roles.update_one(
                    {"_id": old_role_id},
                    {"$inc": {"users_count": -1}}
                )
            
            await db.roles.update_one(
                {"_id": ObjectId(role_id)},
                {"$inc": {"users_count": 1}}
            )
            
            # Create role assignment record
            assignment_doc = {
                "user_id": str(user["_id"]),
                "user_email": user_email,
                "role_id": role_id,
                "role_name": role.get("name"),
                "assigned_by": assigned_by,
                "assigned_at": datetime.utcnow(),
                "status": "active",
                "expires_at": expires_at,
                "revoked_by": None,
                "revoked_at": None,
                "revoke_reason": None,
                "metadata": {"reason": reason} if reason else {}
            }
            
            result = await db.role_assignments.insert_one(assignment_doc)
            assignment_id = str(result.inserted_id)
            
            # Recompute user's effective permissions
            await rbac_service.compute_effective_permissions(
                str(user["_id"]),
                force_recompute=True
            )
            
            # Log audit
            await self._log_audit(
                action_type="role_assigned",
                entity_id=str(user["_id"]),
                entity_name=user_email,
                performed_by=assigned_by,
                changes={
                    "before": {"role_id": str(old_role_id) if old_role_id else None},
                    "after": {"role_id": role_id, "role_name": role.get("name")}
                }
            )
            
            logger.info(f"✅ Assigned role '{role.get('name')}' to {user_email} by {assigned_by}")
            
            return {
                "success": True,
                "message": f"Role '{role.get('display_name')}' assigned to {user_email}",
                "assignment_id": assignment_id,
                "user_email": user_email,
                "role_name": role.get("name"),
                "assigned_by": assigned_by,
                "assigned_at": datetime.utcnow()
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error assigning role: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    
    # ========================================
    # ROLE CLONING
    # ========================================
    
    async def clone_role(
        self,
        source_role_id: str,
        new_role_name: str,
        new_display_name: str,
        new_description: Optional[str],
        cloned_by: str
    ) -> Dict[str, Any]:
        """
        Clone an existing role
        
        Args:
            source_role_id: Role ID to clone from
            new_role_name: Name for new role
            new_display_name: Display name for new role
            new_description: Optional description
            cloned_by: Admin email cloning the role
            
        Returns:
            dict: Cloned role
        """
        try:
            db = self._get_db()
            
            # Get source role
            source_role = await db.roles.find_one({"_id": ObjectId(source_role_id)})
            if not source_role:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Source role not found"
                )
            
            # Check if new name exists
            existing = await db.roles.find_one({"name": new_role_name})
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Role '{new_role_name}' already exists"
                )
            
            # Create new role based on source
            new_role_doc = {
                "name": new_role_name,
                "display_name": new_display_name,
                "description": new_description or f"Cloned from {source_role.get('display_name')}",
                "type": "custom",  # Cloned roles are always custom
                "is_active": True,
                "permissions": source_role.get("permissions", []),
                "can_manage_users": source_role.get("can_manage_users", False),
                "can_assign_leads": source_role.get("can_assign_leads", False),
                "can_view_all_data": source_role.get("can_view_all_data", False),
                "can_export_data": source_role.get("can_export_data", False),
                "max_team_size": source_role.get("max_team_size"),
                "users_count": 0,
                "is_deletable": True,
                "created_at": datetime.utcnow(),
                "created_by": cloned_by,
                "updated_at": datetime.utcnow(),
                "metadata": {
                    "cloned_from": source_role_id,
                    "cloned_from_name": source_role.get("name")
                }
            }
            
            result = await db.roles.insert_one(new_role_doc)
            new_role_id = str(result.inserted_id)
            
            logger.info(f"✅ Cloned role '{source_role.get('name')}' to '{new_role_name}' by {cloned_by}")
            
            new_role_doc["_id"] = result.inserted_id
            return self._format_role_response(new_role_doc)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error cloning role: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    
    # ========================================
    # UTILITY METHODS
    # ========================================
    
    async def get_users_with_role(self, role_id: str) -> List[Dict[str, Any]]:
        """Get list of users with specific role"""
        try:
            db = self._get_db()
            
            users = await db.users.find(
                {"role_id": ObjectId(role_id)},
                {"email": 1, "first_name": 1, "last_name": 1, "is_active": 1}
            ).to_list(length=None)
            
            return [
                {
                    "id": str(u["_id"]),
                    "email": u.get("email"),
                    "name": f"{u.get('first_name', '')} {u.get('last_name', '')}".strip(),
                    "is_active": u.get("is_active", True)
                }
                for u in users
            ]
            
        except Exception as e:
            logger.error(f"Error getting users with role: {e}")
            return []
    
    def _format_role_response(self, role: Dict[str, Any]) -> Dict[str, Any]:
        """Format role document for API response"""
        return {
            "id": str(role["_id"]),
            "name": role.get("name"),
            "display_name": role.get("display_name"),
            "description": role.get("description"),
            "type": role.get("type"),
            "is_active": role.get("is_active", True),
            "permissions": role.get("permissions", []),
            "can_manage_users": role.get("can_manage_users", False),
            "can_assign_leads": role.get("can_assign_leads", False),
            "can_view_all_data": role.get("can_view_all_data", False),
            "can_export_data": role.get("can_export_data", False),
            "max_team_size": role.get("max_team_size"),
            "users_count": role.get("users_count", 0),
            "is_deletable": role.get("is_deletable", True),
            "created_at": role.get("created_at"),
            "created_by": role.get("created_by"),
            "updated_at": role.get("updated_at"),
            "updated_by": role.get("updated_by")
        }
    
    async def _recompute_users_with_role(self, role_id: str):
        """Recompute effective permissions for all users with this role"""
        try:
            db = self._get_db()
            
            users = await db.users.find({"role_id": ObjectId(role_id)}).to_list(length=None)
            
            for user in users:
                await rbac_service.compute_effective_permissions(
                    str(user["_id"]),
                    force_recompute=True
                )
            
            logger.info(f"✅ Recomputed permissions for {len(users)} users with role {role_id}")
            
        except Exception as e:
            logger.error(f"Error recomputing users with role: {e}")
    
    async def _log_audit(
        self,
        action_type: str,
        entity_id: str,
        entity_name: str,
        performed_by: str,
        changes: Dict[str, Any]
    ):
        """Log audit trail"""
        try:
            db = self._get_db()
            
            audit_doc = {
                "action_type": action_type,
                "entity_type": "role",
                "entity_id": entity_id,
                "entity_name": entity_name,
                "performed_by": performed_by,
                "performed_at": datetime.utcnow(),
                "changes": changes,
                "reason": None,
                "ip_address": None,
                "user_agent": None
            }
            
            await db.permission_audit_log.insert_one(audit_doc)
            
        except Exception as e:
            logger.error(f"Error logging audit: {e}")


# ========================================
# SINGLETON INSTANCE
# ========================================

role_service = RoleService()