
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException, status

from ..config.database import get_database
from ..config.settings import settings
from .rbac_service import rbac_service

logger = logging.getLogger(__name__)


class TeamService:
    """
    Service for team hierarchy management
    """
    
    def __init__(self):
        """Initialize team service"""
        self._db = None
        self._max_hierarchy_depth = getattr(settings, 'max_hierarchy_depth', 5)
    
    def _get_db(self):
        """Lazy database connection"""
        if self._db is None:
            self._db = get_database()
        return self._db
    
    # ========================================
    # MANAGER ASSIGNMENT
    # ========================================
    
    async def set_manager(
        self,
        user_email: str,
        manager_email: str,
        assigned_by: str,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Set a manager for a user
        
        Creates manager-subordinate relationship.
        
        Args:
            user_email: User email (subordinate)
            manager_email: Manager email
            assigned_by: Admin email setting the relationship
            reason: Optional reason
            
        Returns:
            dict: Operation result
        """
        try:
            db = self._get_db()
            
            # Validate users exist
            user = await db.users.find_one({"email": user_email})
            manager = await db.users.find_one({"email": manager_email})
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User {user_email} not found"
                )
            
            if not manager:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Manager {manager_email} not found"
                )
            
            # Cannot assign self as manager
            if user_email == manager_email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User cannot be their own manager"
                )
            
            # Check for circular hierarchy
            if await self._would_create_circular_hierarchy(str(user["_id"]), str(manager["_id"])):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot create circular hierarchy - this user is already a manager of the specified manager"
                )
            
            # Check hierarchy depth
            manager_level = await self._calculate_hierarchy_depth(str(manager["_id"]))
            if manager_level >= self._max_hierarchy_depth:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Maximum hierarchy depth ({self._max_hierarchy_depth}) would be exceeded"
                )
            
            # Remove from previous manager's team (if any)
            old_manager_id = user.get("reports_to")
            if old_manager_id:
                await db.users.update_one(
                    {"_id": old_manager_id},
                    {"$pull": {"team_members": user["_id"]}}
                )
            
            # Update user's manager
            manager_name = f"{manager.get('first_name', '')} {manager.get('last_name', '')}".strip() or manager_email
            user_level = manager_level + 1
            
            await db.users.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "reports_to": manager["_id"],
                        "reports_to_name": manager_name,
                        "team_level": user_level,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            # Add to manager's team
            await db.users.update_one(
                {"_id": manager["_id"]},
                {
                    "$addToSet": {"team_members": user["_id"]},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            
            # Log audit
            await self._log_audit(
                action_type="manager_assigned",
                entity_id=str(user["_id"]),
                entity_name=user_email,
                performed_by=assigned_by,
                changes={
                    "before": {
                        "reports_to": str(old_manager_id) if old_manager_id else None
                    },
                    "after": {
                        "reports_to": str(manager["_id"]),
                        "reports_to_name": manager_name,
                        "team_level": user_level
                    }
                }
            )
            
            logger.info(f"✅ Set {manager_email} as manager of {user_email} by {assigned_by}")
            
            return {
                "success": True,
                "message": f"{manager_name} is now the manager of {user.get('first_name', user_email)}",
                "user_email": user_email,
                "manager_email": manager_email,
                "team_level": user_level
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error setting manager: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    
    async def remove_manager(
        self,
        user_email: str,
        removed_by: str,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Remove a user's manager
        
        Args:
            user_email: User email
            removed_by: Admin email removing the relationship
            reason: Optional reason
            
        Returns:
            dict: Operation result
        """
        try:
            db = self._get_db()
            
            user = await db.users.find_one({"email": user_email})
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User {user_email} not found"
                )
            
            manager_id = user.get("reports_to")
            if not manager_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"User {user_email} does not have a manager"
                )
            
            manager = await db.users.find_one({"_id": manager_id})
            manager_name = None
            if manager:
                manager_name = f"{manager.get('first_name', '')} {manager.get('last_name', '')}".strip()
            
            # Remove from manager's team
            await db.users.update_one(
                {"_id": manager_id},
                {"$pull": {"team_members": user["_id"]}}
            )
            
            # Remove manager from user
            await db.users.update_one(
                {"_id": user["_id"]},
                {
                    "$unset": {
                        "reports_to": "",
                        "reports_to_name": ""
                    },
                    "$set": {
                        "team_level": 0,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            # Log audit
            await self._log_audit(
                action_type="manager_removed",
                entity_id=str(user["_id"]),
                entity_name=user_email,
                performed_by=removed_by,
                changes={
                    "before": {
                        "reports_to": str(manager_id),
                        "reports_to_name": user.get("reports_to_name")
                    },
                    "after": {}
                }
            )
            
            logger.info(f"✅ Removed manager from {user_email} by {removed_by}")
            
            return {
                "success": True,
                "message": f"Manager removed from {user.get('first_name', user_email)}",
                "user_email": user_email,
                "previous_manager": manager_name or "Unknown"
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error removing manager: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    
    # ========================================
    # TEAM QUERIES
    # ========================================
    
    async def get_team_structure(
        self,
        user_email: str,
        max_depth: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get hierarchical team structure for a user
        
        Returns tree structure showing all subordinates.
        
        Args:
            user_email: Manager email
            max_depth: Maximum depth to traverse (default: MAX_HIERARCHY_DEPTH)
            
        Returns:
            dict: Hierarchical team structure
        """
        try:
            db = self._get_db()
            
            user = await db.users.find_one({"email": user_email})
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User {user_email} not found"
                )
            
            if max_depth is None:
                max_depth = self._max_hierarchy_depth
            
            structure = await rbac_service.get_team_structure(
                str(user["_id"]),
                max_depth=max_depth
            )
            
            return {
                "success": True,
                "user_email": user_email,
                "structure": structure
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting team structure: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    
    async def get_reportees(
        self,
        user_email: str,
        include_nested: bool = False
    ) -> Dict[str, Any]:
        """
        Get direct reports (or all subordinates) for a user
        
        Args:
            user_email: Manager email
            include_nested: Include nested subordinates
            
        Returns:
            dict: List of team members
        """
        try:
            db = self._get_db()
            
            user = await db.users.find_one({"email": user_email})
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User {user_email} not found"
                )
            
            team_members = await rbac_service.get_team_members(
                str(user["_id"]),
                include_nested=include_nested
            )
            
            # Format team members
            formatted_members = [
                {
                    "id": str(m["_id"]),
                    "email": m.get("email"),
                    "name": f"{m.get('first_name', '')} {m.get('last_name', '')}".strip(),
                    "role_name": m.get("role_name"),
                    "team_level": m.get("team_level", 0),
                    "is_active": m.get("is_active", True)
                }
                for m in team_members
            ]
            
            return {
                "success": True,
                "manager_email": user_email,
                "reportees": formatted_members,
                "total": len(formatted_members),
                "include_nested": include_nested
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting reportees: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    
    async def get_my_team(self, user_email: str) -> Dict[str, Any]:
        """
        Get team information for current user
        
        Includes both manager and subordinates.
        
        Args:
            user_email: User email
            
        Returns:
            dict: Complete team information
        """
        try:
            db = self._get_db()
            
            user = await db.users.find_one({"email": user_email})
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User {user_email} not found"
                )
            
            result = {
                "success": True,
                "user_email": user_email,
                "team_level": user.get("team_level", 0),
                "manager": None,
                "reportees": [],
                "total_reportees": 0
            }
            
            # Get manager info
            manager_id = user.get("reports_to")
            if manager_id:
                manager = await db.users.find_one({"_id": manager_id})
                if manager:
                    result["manager"] = {
                        "email": manager.get("email"),
                        "name": f"{manager.get('first_name', '')} {manager.get('last_name', '')}".strip(),
                        "role_name": manager.get("role_name")
                    }
            
            # Get reportees
            team_members = await rbac_service.get_team_members(str(user["_id"]))
            result["reportees"] = [
                {
                    "email": m.get("email"),
                    "name": f"{m.get('first_name', '')} {m.get('last_name', '')}".strip(),
                    "role_name": m.get("role_name"),
                    "is_active": m.get("is_active", True)
                }
                for m in team_members
            ]
            result["total_reportees"] = len(team_members)
            
            return result
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting my team: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    
    # ========================================
    # BULK OPERATIONS
    # ========================================
    
    async def reassign_team(
        self,
        old_manager_email: str,
        new_manager_email: str,
        reassigned_by: str,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Bulk reassign all team members from one manager to another
        
        Args:
            old_manager_email: Current manager email
            new_manager_email: New manager email
            reassigned_by: Admin performing the reassignment
            reason: Optional reason
            
        Returns:
            dict: Reassignment result
        """
        try:
            db = self._get_db()
            
            # Validate managers
            old_manager = await db.users.find_one({"email": old_manager_email})
            new_manager = await db.users.find_one({"email": new_manager_email})
            
            if not old_manager:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Old manager {old_manager_email} not found"
                )
            
            if not new_manager:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"New manager {new_manager_email} not found"
                )
            
            if old_manager_email == new_manager_email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Old and new manager cannot be the same"
                )
            
            # Get all team members
            team_member_ids = old_manager.get("team_members", [])
            
            if not team_member_ids:
                return {
                    "success": True,
                    "message": f"{old_manager_email} has no team members to reassign",
                    "reassigned_count": 0
                }
            
            # Calculate new manager level
            new_manager_level = await self._calculate_hierarchy_depth(str(new_manager["_id"]))
            new_manager_name = f"{new_manager.get('first_name', '')} {new_manager.get('last_name', '')}".strip()
            
            # Reassign each team member
            reassigned_count = 0
            for member_id in team_member_ids:
                try:
                    await db.users.update_one(
                        {"_id": member_id},
                        {
                            "$set": {
                                "reports_to": new_manager["_id"],
                                "reports_to_name": new_manager_name,
                                "team_level": new_manager_level + 1,
                                "updated_at": datetime.utcnow()
                            }
                        }
                    )
                    reassigned_count += 1
                except Exception as e:
                    logger.error(f"Error reassigning member {member_id}: {e}")
            
            # Update old manager's team_members
            await db.users.update_one(
                {"_id": old_manager["_id"]},
                {"$set": {"team_members": []}}
            )
            
            # Update new manager's team_members
            await db.users.update_one(
                {"_id": new_manager["_id"]},
                {"$addToSet": {"team_members": {"$each": team_member_ids}}}
            )
            
            # Log audit
            await self._log_audit(
                action_type="team_reassigned",
                entity_id=str(old_manager["_id"]),
                entity_name=old_manager_email,
                performed_by=reassigned_by,
                changes={
                    "before": {
                        "manager": old_manager_email,
                        "team_size": len(team_member_ids)
                    },
                    "after": {
                        "manager": new_manager_email,
                        "reassigned_count": reassigned_count
                    }
                }
            )
            
            logger.info(f"✅ Reassigned {reassigned_count} team members from {old_manager_email} to {new_manager_email}")
            
            return {
                "success": True,
                "message": f"Reassigned {reassigned_count} team members",
                "old_manager": old_manager_email,
                "new_manager": new_manager_email,
                "reassigned_count": reassigned_count,
                "total_members": len(team_member_ids)
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error reassigning team: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e)
            )
    
    # ========================================
    # VALIDATION HELPERS
    # ========================================
    
    async def _would_create_circular_hierarchy(
        self,
        user_id: str,
        potential_manager_id: str
    ) -> bool:
        """
        Check if assigning a manager would create a circular hierarchy
        
        Example: If John manages Sarah, Sarah cannot manage John
        
        Args:
            user_id: User ObjectId as string
            potential_manager_id: Potential manager ObjectId as string
            
        Returns:
            bool: True if would create circular hierarchy
        """
        try:
            db = self._get_db()
            
            # Check if potential_manager reports to user (directly or indirectly)
            current_id = potential_manager_id
            max_iterations = self._max_hierarchy_depth + 1
            
            for _ in range(max_iterations):
                current_user = await db.users.find_one({"_id": ObjectId(current_id)})
                if not current_user:
                    return False
                
                reports_to = current_user.get("reports_to")
                if not reports_to:
                    return False
                
                if str(reports_to) == user_id:
                    return True
                
                current_id = str(reports_to)
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking circular hierarchy: {e}")
            return False
    
    async def _calculate_hierarchy_depth(self, user_id: str) -> int:
        """
        Calculate hierarchy depth (level) for a user
        
        0 = No manager (individual contributor)
        1 = Has 1 level of manager above
        2 = Has 2 levels of managers above
        etc.
        
        Args:
            user_id: User ObjectId as string
            
        Returns:
            int: Hierarchy depth
        """
        try:
            db = self._get_db()
            
            depth = 0
            current_id = user_id
            max_iterations = self._max_hierarchy_depth + 1
            
            for _ in range(max_iterations):
                current_user = await db.users.find_one({"_id": ObjectId(current_id)})
                if not current_user:
                    break
                
                reports_to = current_user.get("reports_to")
                if not reports_to:
                    break
                
                depth += 1
                current_id = str(reports_to)
            
            return depth
            
        except Exception as e:
            logger.error(f"Error calculating hierarchy depth: {e}")
            return 0
    
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
                "entity_type": "team",
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

team_service = TeamService()