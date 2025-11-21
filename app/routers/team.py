# app/routers/team.py
# Complete Team Hierarchy Management Router with RBAC Integration

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
from bson import ObjectId

from ..models.user import User
from ..services.team_service import TeamService
from ..services.rbac_service import RBACService
from ..utils.dependencies import get_current_active_user
from ..config.database import get_database

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/team",
    tags=["Team Hierarchy"],
    responses={404: {"description": "Not found"}},
)

team_service = TeamService()
rbac_service = RBACService()


# ============================================================================
# SET MANAGER
# ============================================================================

@router.post("/set-manager")
async def set_manager(
    user_email: str,
    manager_email: str,
    reason: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Assign a manager to a user
    
    **Required Permission:** `team.manage_hierarchy`
    
    **Business Rules:**
    - Super admins can set anyone as manager
    - Users with `team.manage_hierarchy` can set managers for their team
    - Cannot create circular hierarchies (user cannot report to someone who reports to them)
    - Cannot exceed max hierarchy depth (default: 5 levels)
    - Automatically updates team_members arrays
    - Recalculates team levels for affected users
    - Validates both users exist and are active
    
    **Args:**
    - user_email: Email of user who will get a manager
    - manager_email: Email of user who will become the manager
    - reason: Optional reason for the assignment change
    
    **Returns:** Updated user with new manager information
    
    **Example Response:**
    ```json
    {
        "success": true,
        "message": "Manager assigned successfully",
        "data": {
            "user_email": "user@test.com",
            "manager_email": "manager@test.com",
            "team_level": 1,
            "previous_manager": null,
            "updated_at": "2024-01-15T10:30:00"
        }
    }
    ```
    """
    try:
        db = get_database()
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.manage_hierarchy"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to manage team hierarchy. Required: team.manage_hierarchy"
            )
        
        logger.info(f"Setting manager: {user_email} → {manager_email} by {current_user.get('email')}")
        
        # Set manager
        result = await team_service.set_manager(
            user_email=user_email,
            manager_email=manager_email,
            changed_by=current_user.get("email"),
            reason=reason
        )
        
        logger.info(f"✅ Manager set successfully: {user_email} → {manager_email}")
        
        return {
            "success": True,
            "message": f"Manager '{manager_email}' assigned to '{user_email}'",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error setting manager: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set manager: {str(e)}"
        )


# ============================================================================
# REMOVE MANAGER
# ============================================================================

@router.post("/remove-manager")
async def remove_manager(
    user_email: str,
    reason: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Remove a user's manager (make them a top-level user)
    
    **Required Permission:** `team.manage_hierarchy`
    
    **Business Rules:**
    - Removes reports_to relationship
    - Removes user from previous manager's team_members array
    - Sets team_level back to 0
    - Does NOT affect the user's own team_members (they keep their reports)
    - User becomes a top-level employee with no manager
    
    **Args:**
    - user_email: Email of user whose manager will be removed
    - reason: Optional reason for removing the manager
    
    **Returns:** Updated user without manager
    
    **Example Response:**
    ```json
    {
        "success": true,
        "message": "Manager removed successfully",
        "data": {
            "user_email": "user@test.com",
            "previous_manager": "manager@test.com",
            "team_level": 0,
            "updated_at": "2024-01-15T10:30:00"
        }
    }
    ```
    """
    try:
        db = get_database()
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.manage_hierarchy"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to manage team hierarchy. Required: team.manage_hierarchy"
            )
        
        logger.info(f"Removing manager from: {user_email} by {current_user.get('email')}")
        
        # Remove manager
        result = await team_service.remove_manager(
            user_email=user_email,
            removed_by=current_user.get("email"),
            reason=reason
        )
        
        logger.info(f"✅ Manager removed successfully from: {user_email}")
        
        return {
            "success": True,
            "message": f"Manager removed from '{user_email}'",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error removing manager: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove manager: {str(e)}"
        )


# ============================================================================
# GET TEAM STRUCTURE
# ============================================================================

@router.get("/structure")
async def get_team_structure(
    user_email: Optional[str] = Query(None, description="User email to get structure for (defaults to current user)"),
    max_depth: int = Query(5, ge=1, le=10, description="Maximum depth of hierarchy to retrieve"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get hierarchical team structure with nested direct reports
    
    **Required Permission:** `team.view_structure`
    
    **Description:**
    Returns a tree structure showing the user and all their subordinates at all levels.
    Each node contains user information and their direct reports recursively.
    
    **Query Parameters:**
    - user_email: Target user email (defaults to current user)
    - max_depth: Maximum hierarchy depth to retrieve (1-10, default: 5)
    
    **Returns:** Hierarchical team structure
    
    **Example Response:**
    ```json
    {
        "success": true,
        "data": {
            "user": {
                "email": "manager@company.com",
                "name": "John Manager",
                "role_name": "Team Lead",
                "team_level": 2,
                "is_active": true
            },
            "direct_reports": [
                {
                    "email": "user1@company.com",
                    "name": "Alice User",
                    "role_name": "User",
                    "team_level": 1,
                    "is_active": true,
                    "direct_reports": []
                },
                {
                    "email": "user2@company.com",
                    "name": "Bob User",
                    "role_name": "User",
                    "team_level": 1,
                    "is_active": true,
                    "direct_reports": []
                }
            ],
            "total_team_size": 3,
            "max_depth_reached": 2
        }
    }
    ```
    """
    try:
        db = get_database()
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.view_structure"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view team structure. Required: team.view_structure"
            )
        
        # Default to current user if no email provided
        target_email = user_email or current_user.get("email")
        
        logger.info(f"Getting team structure for: {target_email} (max_depth: {max_depth})")
        
        # Get structure
        structure = await team_service.get_team_structure(
            manager_email=target_email,
            max_depth=max_depth
        )
        
        logger.info(f"✅ Team structure retrieved for: {target_email} (team size: {structure.get('total_team_size', 0)})")
        
        return {
            "success": True,
            "data": structure
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting team structure: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get team structure: {str(e)}"
        )


# ============================================================================
# GET REPORTEES (DIRECT REPORTS)
# ============================================================================

@router.get("/reportees")
async def get_reportees(
    user_email: Optional[str] = Query(None, description="User email to get reportees for (defaults to current user)"),
    include_nested: bool = Query(False, description="Include all nested subordinates (not just direct reports)"),
    include_inactive: bool = Query(False, description="Include inactive users in results"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get list of direct reports (or all subordinates if nested)
    
    **Required Permission:** `team.view_structure`
    
    **Description:**
    Returns a flat list of users who report to the specified manager.
    Can be filtered to show only direct reports or include all nested levels.
    
    **Query Parameters:**
    - user_email: Target user email (defaults to current user)
    - include_nested: If true, includes all subordinates at all levels (not just direct)
    - include_inactive: If true, includes inactive/disabled users
    
    **Returns:** List of reporting users
    
    **Example Response:**
    ```json
    {
        "success": true,
        "manager": {
            "email": "manager@company.com",
            "name": "John Manager",
            "team_level": 2
        },
        "reportees": [
            {
                "id": "user_id_1",
                "email": "user1@company.com",
                "name": "Alice User",
                "first_name": "Alice",
                "last_name": "User",
                "role_name": "User",
                "team_level": 1,
                "is_active": true,
                "assigned_leads_count": 10,
                "reports_to": "manager@company.com"
            },
            {
                "id": "user_id_2",
                "email": "user2@company.com",
                "name": "Bob User",
                "first_name": "Bob",
                "last_name": "User",
                "role_name": "User",
                "team_level": 1,
                "is_active": true,
                "assigned_leads_count": 15,
                "reports_to": "manager@company.com"
            }
        ],
        "total_count": 2,
        "include_nested": false,
        "include_inactive": false
    }
    ```
    """
    try:
        db = get_database()
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.view_structure"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view team members. Required: team.view_structure"
            )
        
        # Default to current user if no email provided
        target_email = user_email or current_user.get("email")
        
        logger.info(f"Getting reportees for: {target_email} (nested: {include_nested}, inactive: {include_inactive})")
        
        # Get reportees
        reportees = await team_service.get_reportees(
            manager_email=target_email,
            include_nested=include_nested,
            include_inactive=include_inactive
        )
        
        logger.info(f"✅ Reportees retrieved for: {target_email} (count: {len(reportees)})")
        
        return {
            "success": True,
            "manager": {
                "email": target_email,
                "name": f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip(),
                "team_level": current_user.get("team_level", 0)
            },
            "reportees": reportees,
            "total_count": len(reportees),
            "include_nested": include_nested,
            "include_inactive": include_inactive
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting reportees: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get reportees: {str(e)}"
        )


# ============================================================================
# GET MY TEAM (CURRENT USER'S TEAM INFO)
# ============================================================================

@router.get("/my-team")
async def get_my_team(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get complete team information for current user
    
    **No special permission required** - all users can view their own team
    
    **Description:**
    Returns comprehensive team information including:
    - Current user's info
    - Their manager (if any)
    - Their direct reports (if any)
    - Total team size under their management
    
    **Returns:** Complete team information for current user
    
    **Example Response:**
    ```json
    {
        "success": true,
        "data": {
            "user": {
                "id": "user_id",
                "email": "user@company.com",
                "name": "John Doe",
                "first_name": "John",
                "last_name": "Doe",
                "role_name": "Team Lead",
                "team_level": 1,
                "is_active": true
            },
            "manager": {
                "id": "manager_id",
                "email": "manager@company.com",
                "name": "Jane Manager",
                "role_name": "Senior Manager",
                "team_level": 2
            },
            "direct_reports": [
                {
                    "email": "report1@company.com",
                    "name": "Alice User",
                    "role_name": "User",
                    "team_level": 0
                }
            ],
            "direct_reports_count": 1,
            "total_team_size": 5,
            "has_manager": true,
            "has_reports": true
        }
    }
    ```
    """
    try:
        db = get_database()
        
        logger.info(f"Getting team info for: {current_user.get('email')}")
        
        # Get team info
        team_info = await team_service.get_my_team(
            user_email=current_user.get("email")
        )
        
        logger.info(f"✅ Team info retrieved for: {current_user.get('email')}")
        
        return {
            "success": True,
            "data": team_info
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting my team: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get team info: {str(e)}"
        )


# ============================================================================
# REASSIGN TEAM (BULK TRANSFER)
# ============================================================================

@router.post("/reassign")
async def reassign_team(
    from_manager_email: str,
    to_manager_email: str,
    reason: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Bulk transfer all team members from one manager to another
    
    **Required Permission:** `team.transfer_ownership`
    
    **Business Rules:**
    - Super admins can reassign any team
    - Managers can only reassign their own direct reports
    - ALL direct reports are transferred at once
    - Team levels are recalculated for all affected users
    - Old manager's team_members array is cleared
    - New manager's team_members array is updated
    - Validates both managers exist and are active
    
    **Use Cases:**
    - Manager leaving the company
    - Team restructuring
    - Department changes
    - Temporary manager assignment
    
    **Args:**
    - from_manager_email: Current manager's email
    - to_manager_email: New manager's email
    - reason: Optional reason for the transfer
    
    **Returns:** Summary of transferred team
    
    **Example Response:**
    ```json
    {
        "success": true,
        "message": "Team transferred successfully",
        "data": {
            "from_manager": "old_manager@company.com",
            "to_manager": "new_manager@company.com",
            "transferred_users": [
                {"email": "user1@company.com", "name": "User One"},
                {"email": "user2@company.com", "name": "User Two"}
            ],
            "transferred_count": 2,
            "reason": "Manager resignation",
            "transferred_at": "2024-01-15T10:30:00",
            "transferred_by": "admin@company.com"
        }
    }
    ```
    """
    try:
        db = get_database()
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.transfer_ownership"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to transfer team ownership. Required: team.transfer_ownership"
            )
        
        logger.info(f"Reassigning team: {from_manager_email} → {to_manager_email} by {current_user.get('email')}")
        
        # Reassign team
        result = await team_service.reassign_team(
            old_manager_email=from_manager_email,
            new_manager_email=to_manager_email,
            transferred_by=current_user.get("email"),
            reason=reason
        )
        
        logger.info(f"✅ Team reassigned successfully: {from_manager_email} → {to_manager_email} ({result.get('transferred_count', 0)} users)")
        
        return {
            "success": True,
            "message": f"Team transferred from '{from_manager_email}' to '{to_manager_email}'",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error reassigning team: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reassign team: {str(e)}"
        )


# ============================================================================
# CHECK MANAGEMENT AUTHORITY
# ============================================================================

@router.get("/can-manage/{user_email}")
async def check_management_authority(
    user_email: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Check if current user can manage the specified user
    
    **No special permission required** - just checks hierarchy relationships
    
    **Description:**
    Determines the management relationship between current user and target user.
    Used for UI to show/hide management actions based on authority.
    
    **Returns:** Management authority details
    
    **Example Response:**
    ```json
    {
        "success": true,
        "can_manage": true,
        "reason": "Direct manager",
        "relationship": "manager",
        "manager": {
            "email": "manager@company.com",
            "name": "John Manager",
            "is_super_admin": false
        },
        "user": {
            "email": "user@company.com",
            "team_level": 1
        }
    }
    ```
    
    **Possible Relationships:**
    - `super_admin`: Current user is super admin (can manage everyone)
    - `manager`: Current user is direct manager
    - `senior_manager`: Current user is manager at higher hierarchy level
    - `none`: No management relationship exists
    """
    try:
        db = get_database()
        
        logger.info(f"Checking management authority: {current_user.get('email')} vs {user_email}")
        
        # Check if can manage
        can_manage = await rbac_service.can_manage_user(
            manager_id=str(current_user.get("_id")),
            user_email=user_email
        )
        
        # Determine relationship
        if current_user.get("is_super_admin"):
            relationship = "super_admin"
            reason = "Super admin - can manage all users"
        elif can_manage:
            # Check if direct manager
            target_user = await db.users.find_one({"email": user_email})
            if target_user:
                if target_user.get("reports_to_email") == current_user.get("email"):
                    relationship = "manager"
                    reason = "Direct manager"
                else:
                    relationship = "senior_manager"
                    reason = "Senior manager in hierarchy"
            else:
                relationship = "none"
                reason = "Target user not found"
        else:
            relationship = "none"
            reason = "No management relationship"
        
        logger.info(f"✅ Management check result: {current_user.get('email')} vs {user_email} = {can_manage} ({relationship})")
        
        return {
            "success": True,
            "can_manage": can_manage,
            "reason": reason,
            "relationship": relationship,
            "manager": {
                "email": current_user.get("email"),
                "name": f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip(),
                "is_super_admin": current_user.get("is_super_admin", False),
                "role_name": current_user.get("role_name", "")
            },
            "user": {
                "email": user_email,
                "team_level": current_user.get("team_level", 0) if user_email == current_user.get("email") else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error checking management authority: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check management authority: {str(e)}"
        )


# ============================================================================
# GET MANAGER CHAIN (PATH TO TOP)
# ============================================================================

@router.get("/manager-chain")
async def get_manager_chain(
    user_email: Optional[str] = Query(None, description="User email to get chain for (defaults to current user)"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get the complete management chain from user to top level
    
    **Required Permission:** `team.view_structure`
    
    **Description:**
    Returns the path from the user up through all their managers to the top level.
    Useful for displaying org chart paths and understanding reporting structure.
    
    **Query Parameters:**
    - user_email: Target user email (defaults to current user)
    
    **Returns:** List of managers from immediate to top level
    
    **Example Response:**
    ```json
    {
        "success": true,
        "user": {
            "email": "user@company.com",
            "name": "John User",
            "team_level": 0
        },
        "manager_chain": [
            {
                "level": 1,
                "email": "manager@company.com",
                "name": "Jane Manager",
                "role_name": "Team Lead",
                "team_level": 1
            },
            {
                "level": 2,
                "email": "director@company.com",
                "name": "Bob Director",
                "role_name": "Director",
                "team_level": 2
            },
            {
                "level": 3,
                "email": "vp@company.com",
                "name": "Alice VP",
                "role_name": "VP",
                "team_level": 3
            }
        ],
        "chain_length": 3,
        "top_level_manager": {
            "email": "vp@company.com",
            "name": "Alice VP"
        }
    }
    ```
    """
    try:
        db = get_database()
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.view_structure"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view team structure. Required: team.view_structure"
            )
        
        # Default to current user if no email provided
        target_email = user_email or current_user.get("email")
        
        logger.info(f"Getting manager chain for: {target_email}")
        
        # Get user
        target_user = await db.users.find_one({"email": target_email})
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{target_email}' not found"
            )
        
        # Build manager chain
        manager_chain = []
        current_manager_id = target_user.get("reports_to")
        level = 1
        
        while current_manager_id and level <= 10:  # Max 10 levels to prevent infinite loops
            manager = await db.users.find_one({"_id": ObjectId(current_manager_id)})
            if not manager:
                break
            
            manager_chain.append({
                "level": level,
                "id": str(manager["_id"]),
                "email": manager["email"],
                "name": f"{manager.get('first_name', '')} {manager.get('last_name', '')}".strip(),
                "role_name": manager.get("role_name", ""),
                "team_level": manager.get("team_level", 0),
                "is_active": manager.get("is_active", True)
            })
            
            current_manager_id = manager.get("reports_to")
            level += 1
        
        top_level_manager = manager_chain[-1] if manager_chain else None
        
        logger.info(f"✅ Manager chain retrieved for: {target_email} (length: {len(manager_chain)})")
        
        return {
            "success": True,
            "user": {
                "email": target_email,
                "name": f"{target_user.get('first_name', '')} {target_user.get('last_name', '')}".strip(),
                "team_level": target_user.get("team_level", 0)
            },
            "manager_chain": manager_chain,
            "chain_length": len(manager_chain),
            "top_level_manager": top_level_manager
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting manager chain: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get manager chain: {str(e)}"
        )


# ============================================================================
# GET TEAM STATISTICS
# ============================================================================

@router.get("/statistics")
async def get_team_statistics(
    user_email: Optional[str] = Query(None, description="User email to get stats for (defaults to current user)"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get team statistics and analytics for a manager
    
    **Required Permission:** `team.view_structure`
    
    **Description:**
    Provides comprehensive team metrics including:
    - Total team size (all levels)
    - Direct reports count
    - Team distribution by role
    - Team distribution by level
    - Average team level
    
    **Returns:** Team statistics and analytics
    
    **Example Response:**
    ```json
    {
        "success": true,
        "manager": {
            "email": "manager@company.com",
            "name": "John Manager",
            "team_level": 2
        },
        "statistics": {
            "total_team_size": 15,
            "direct_reports_count": 3,
            "indirect_reports_count": 12,
            "max_hierarchy_depth": 3,
            "average_team_level": 1.2,
            "active_members": 14,
            "inactive_members": 1,
            "by_role": {
                "user": 10,
                "team_lead": 3,
                "manager": 2
            },
            "by_level": {
                "0": 10,
                "1": 3,
                "2": 2
            }
        }
    }
    ```
    """
    try:
        db = get_database()
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.view_structure"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view team statistics. Required: team.view_structure"
            )
        
        # Default to current user if no email provided
        target_email = user_email or current_user.get("email")
        
        logger.info(f"Getting team statistics for: {target_email}")
        
        # Get all reportees (nested)
        all_reportees = await team_service.get_reportees(
            manager_email=target_email,
            include_nested=True,
            include_inactive=True
        )
        
        # Get direct reports only
        direct_reports = await team_service.get_reportees(
            manager_email=target_email,
            include_nested=False,
            include_inactive=False
        )
        
        # Calculate statistics
        active_count = sum(1 for r in all_reportees if r.get("is_active", True))
        inactive_count = len(all_reportees) - active_count
        
        # Group by role
        by_role = {}
        for reportee in all_reportees:
            role = reportee.get("role_name", "unknown")
            by_role[role] = by_role.get(role, 0) + 1
        
        # Group by level
        by_level = {}
        for reportee in all_reportees:
            level = str(reportee.get("team_level", 0))
            by_level[level] = by_level.get(level, 0) + 1
        
        # Calculate average level
        total_levels = sum(r.get("team_level", 0) for r in all_reportees)
        avg_level = round(total_levels / len(all_reportees), 2) if all_reportees else 0
        
        # Find max depth
        max_depth = max((r.get("team_level", 0) for r in all_reportees), default=0)
        
        logger.info(f"✅ Team statistics retrieved for: {target_email} (team size: {len(all_reportees)})")
        
        return {
            "success": True,
            "manager": {
                "email": target_email,
                "name": f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip(),
                "team_level": current_user.get("team_level", 0)
            },
            "statistics": {
                "total_team_size": len(all_reportees),
                "direct_reports_count": len(direct_reports),
                "indirect_reports_count": len(all_reportees) - len(direct_reports),
                "max_hierarchy_depth": max_depth,
                "average_team_level": avg_level,
                "active_members": active_count,
                "inactive_members": inactive_count,
                "by_role": by_role,
                "by_level": by_level
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting team statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get team statistics: {str(e)}"
        )