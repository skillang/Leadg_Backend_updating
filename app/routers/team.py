# app/routers/team.py - SIMPLIFIED TEAM MANAGEMENT (NO HIERARCHY)
# Manages named teams with team leads and members

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import Optional, List, Dict, Any
import logging
from pydantic import BaseModel, EmailStr
from ..utils.dependencies import get_current_active_user, get_admin_user
from ..services.team_service import team_service
from ..services.rbac_service import rbac_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/team", tags=["Team Management"])

class AddMemberRequest(BaseModel):
    user_email: EmailStr

class SetTeamLeadRequest(BaseModel):
    new_lead_email: EmailStr

# ============================================================================
# GET MY TEAM (SIMPLIFIED)
# ============================================================================

@router.get("/my-team")
async def get_my_team(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get current user's team information (simplified - no hierarchy)
    
    **Returns:**
    - Team details if user is in a team
    - Team members list
    - User's role in team (team_lead or member)
    
    **Example Response:**
```json
    {
        "success": true,
        "user": {
            "email": "john@company.com",
            "name": "John Doe",
            "is_team_lead": false
        },
        "team": {
            "id": "team_123",
            "name": "Sales Team Alpha",
            "department": "Sales",
            "team_lead_email": "manager@company.com",
            "team_lead_name": "Jane Manager",
            "member_count": 5
        },
        "team_members": [...]
    }
```
    """
    try:
        user_email = current_user.get("email")
        team_id = current_user.get("team_id")
        
        logger.info(f"Getting team info for: {user_email}")
        
        # Get user's team
        if not team_id:
            return {
                "success": True,
                "message": "User is not assigned to any team",
                "user": {
                    "email": user_email,
                    "name": f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip(),
                    "is_team_lead": False
                },
                "team": None,
                "team_members": []
            }
        
        # Get team details
        team = await team_service.get_team(team_id)
        
        if not team:
            return {
                "success": False,
                "message": "Team not found",
                "user": {
                    "email": user_email,
                    "name": f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip(),
                    "is_team_lead": False
                },
                "team": None,
                "team_members": []
            }
        
        # Get team members
        team_members = await team_service.get_team_members(team_id)
        
        logger.info(f"✅ Team info retrieved for: {user_email}")
        
        return {
            "success": True,
            "user": {
                "email": user_email,
                "name": f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip(),
                "is_team_lead": current_user.get("is_team_lead", False)
            },
            "team": team,
            "team_members": team_members
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting my team: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get team info: {str(e)}"
        )


# ============================================================================
# CREATE TEAM
# ============================================================================

@router.post("/create")
async def create_team(
    name: str,
    team_lead_email: str,
    department: Optional[str] = None,
    description: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Create a new team
    
    **Required Permission:** Admin only
    
    **Parameters:**
    - name: Team name (must be unique)
    - team_lead_email: Email of team lead
    - department: Optional department
    - description: Optional description
    
    **Example Request:**
```json
    {
        "name": "Sales Team Alpha",
        "team_lead_email": "john@company.com",
        "department": "Sales",
        "description": "Enterprise sales team"
    }
```
    
    **Example Response:**
```json
    {
        "success": true,
        "message": "Team created successfully",
        "team": {
            "id": "team_123",
            "team_id": "TEAM-20250101120000",
            "name": "Sales Team Alpha",
            "team_lead_email": "john@company.com",
            "member_count": 1
        }
    }
```
    """
    try:
        logger.info(f"Creating team '{name}' with lead {team_lead_email}")
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.create"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to create teams"
            )
        
        # Create team
        team = await team_service.create_team(
            name=name,
            team_lead_email=team_lead_email,
            department=department,
            description=description,
            created_by_email=current_user.get("email")
        )
        
        logger.info(f"✅ Team '{name}' created successfully")
        
        return {
            "success": True,
            "message": "Team created successfully",
            "team": team
        }
        
    except ValueError as e:
        logger.error(f"❌ Validation error creating team: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"❌ Error creating team: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create team: {str(e)}"
        )


# ============================================================================
# LIST TEAMS
# ============================================================================

@router.get("/list")
async def list_teams(
    include_inactive: bool = Query(False, description="Include inactive teams"),
    department: Optional[str] = Query(None, description="Filter by department"),
    skip: int = Query(0, ge=0, description="Pagination skip"),
    limit: int = Query(100, ge=1, le=500, description="Pagination limit"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    List all teams with optional filters
    
    **Required Permission:** `team.view_structure` or admin
    
    **Query Parameters:**
    - include_inactive: Include inactive teams (default: false)
    - department: Filter by department
    - skip: Pagination skip (default: 0)
    - limit: Pagination limit (default: 100, max: 500)
    
    **Example Response:**
```json
    {
        "success": true,
        "teams": [
            {
                "id": "team_123",
                "name": "Sales Team Alpha",
                "team_lead_email": "john@company.com",
                "member_count": 5
            }
        ],
        "total_count": 10
    }
```
    """
    try:
        logger.info(f"Listing teams (inactive: {include_inactive}, dept: {department})")
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.view_structure"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view teams"
            )
        
        # Get teams
        teams = await team_service.list_teams(
            include_inactive=include_inactive,
            department=department,
            skip=skip,
            limit=limit
        )
        
        logger.info(f"✅ Listed {len(teams)} teams")
        
        return {
            "success": True,
            "teams": teams,
            "total_count": len(teams),
            "filters": {
                "include_inactive": include_inactive,
                "department": department
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error listing teams: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list teams: {str(e)}"
        )


# ============================================================================
# GET TEAM DETAILS
# ============================================================================

@router.get("/{team_id}")
async def get_team(
    team_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get team details by ID
    
    **Required Permission:** `team.view_structure` or admin
    
    **Example Response:**
```json
    {
        "success": true,
        "team": {
            "id": "team_123",
            "name": "Sales Team Alpha",
            "description": "Enterprise sales team",
            "department": "Sales",
            "team_lead_email": "john@company.com",
            "member_count": 5
        }
    }
```
    """
    try:
        logger.info(f"Getting team details for: {team_id}")
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.view_structure"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view team details"
            )
        
        # Get team
        team = await team_service.get_team(team_id)
        
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Team '{team_id}' not found"
            )
        
        logger.info(f"✅ Team details retrieved for: {team_id}")
        
        return {
            "success": True,
            "team": team
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting team: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get team: {str(e)}"
        )


# ============================================================================
# UPDATE TEAM
# ============================================================================

@router.put("/{team_id}")
async def update_team(
    team_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    department: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Update team information
    
    **Required Permission:** Admin only
    
    **Example Request:**
```json
    {
        "name": "Sales Team Beta",
        "description": "Updated description",
        "department": "Sales"
    }
```
    """
    try:
        logger.info(f"Updating team: {team_id}")
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.update"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to update teams"
            )
        
        # Update team
        team = await team_service.update_team(
            team_id=team_id,
            name=name,
            description=description,
            department=department,
            is_active=is_active,
            updated_by_email=current_user.get("email")
        )
        
        logger.info(f"✅ Team {team_id} updated successfully")
        
        return {
            "success": True,
            "message": "Team updated successfully",
            "team": team
        }
        
    except ValueError as e:
        logger.error(f"❌ Validation error updating team: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating team: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update team: {str(e)}"
        )


# ============================================================================
# DELETE TEAM
# ============================================================================

@router.delete("/{team_id}")
async def delete_team(
    team_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Delete a team (soft delete - marks as inactive and removes members)
    
    **Required Permission:** Admin only
    
    **Warning:** This will remove all members from the team!
    """
    try:
        logger.info(f"Deleting team: {team_id}")
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.delete"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to delete teams"
            )
        
        # Delete team
        success = await team_service.delete_team(team_id)
        
        if success:
            logger.info(f"✅ Team {team_id} deleted successfully")
            return {
                "success": True,
                "message": "Team deleted successfully"
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to delete team"
            )
        
    except ValueError as e:
        logger.error(f"❌ Validation error deleting team: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting team: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete team: {str(e)}"
        )


# ============================================================================
# GET TEAM MEMBERS
# ============================================================================

@router.get("/{team_id}/members")
async def get_team_members(
    team_id: str,
    include_inactive: bool = Query(False, description="Include inactive users"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get all members of a team
    
    **Required Permission:** `team.view_structure` or admin
    
    **Example Response:**
```json
    {
        "success": true,
        "team_id": "team_123",
        "members": [
            {
                "email": "john@company.com",
                "name": "John Doe",
                "is_team_lead": true,
                "is_active": true
            }
        ],
        "total_count": 5
    }
```
    """
    try:
        logger.info(f"Getting team members for: {team_id}")
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.view_structure"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view team members"
            )
        
        # Get members
        members = await team_service.get_team_members(
            team_id=team_id,
            include_inactive=include_inactive
        )
        
        logger.info(f"✅ Retrieved {len(members)} members for team {team_id}")
        
        return {
            "success": True,
            "team_id": team_id,
            "members": members,
            "total_count": len(members)
        }
        
    except ValueError as e:
        logger.error(f"❌ Validation error getting team members: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting team members: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get team members: {str(e)}"
        )


# ============================================================================
# ADD MEMBER TO TEAM
# ============================================================================

@router.post("/{team_id}/members/add")
async def add_team_member(
    team_id: str,
    request: AddMemberRequest,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Add a member to a team
    
    **Required Permission:** Admin only
    
    **Business Rules:**
    - User must exist and be active
    - User cannot already be in another team
    - User cannot already be in this team
    
    **Example Request:**
```json
    {
        "user_email": "newmember@company.com"
    }
```
    """
    try:
        user_email = request.user_email
        logger.info(f"Adding {user_email} to team {team_id}")
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.manage_members"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to manage team members"
            )
        
        # Add member
        team = await team_service.add_member(
            team_id=team_id,
            user_email=user_email,
            updated_by_email=current_user.get("email")
        )
        
        logger.info(f"✅ User {user_email} added to team {team_id}")
        
        return {
            "success": True,
            "message": f"User {user_email} added to team successfully",
            "team": team
        }
        
    except ValueError as e:
        logger.error(f"❌ Validation error adding member: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error adding team member: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add team member: {str(e)}"
        )


# ============================================================================
# REMOVE MEMBER FROM TEAM
# ============================================================================

@router.post("/{team_id}/members/remove")
async def remove_team_member(
    team_id: str,
    request: AddMemberRequest,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Remove a member from a team
    
    **Required Permission:** Admin only
    
    **Business Rules:**
    - User must be in the team
    - Cannot remove team lead (change team lead first)
    
    **Example Request:**
```json
    {
        "user_email": "member@company.com"
    }
```
    """
    try:
        user_email = request.user_email
        logger.info(f"Removing {user_email} from team {team_id}")
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.manage_members"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to manage team members"
            )
        
        # Remove member
        team = await team_service.remove_member(
            team_id=team_id,
            user_email=user_email,
            updated_by_email=current_user.get("email")
        )
        
        logger.info(f"✅ User {user_email} removed from team {team_id}")
        
        return {
            "success": True,
            "message": f"User {user_email} removed from team successfully",
            "team": team
        }
        
    except ValueError as e:
        logger.error(f"❌ Validation error removing member: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error removing team member: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove team member: {str(e)}"
        )


# ============================================================================
# SET TEAM LEAD
# ============================================================================

@router.post("/{team_id}/lead/set")
async def set_team_lead(
    team_id: str,
    request: SetTeamLeadRequest,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Change team lead
    
    **Required Permission:** Admin only
    
    **Business Rules:**
    - New lead must be a member of the team
    - Old lead will be demoted to regular member
    
    **Example Request:**
```json
    {
        "new_lead_email": "newlead@company.com"
    }
```
    """
    try:
        logger.info(f"Setting new team lead {new_lead_email} for team {team_id}")
        
        # Check permission
        has_permission = await rbac_service.check_permission(
            user=current_user,
            permission_code="team.manage_members"
        )
        
        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to change team lead"
            )
        
        # Set team lead
        team = await team_service.set_team_lead(
            team_id=team_id,
            new_lead_email=new_lead_email,
            updated_by_email=current_user.get("email")
        )
        
        logger.info(f"✅ Team lead changed to {new_lead_email} for team {team_id}")
        
        return {
            "success": True,
            "message": f"Team lead changed to {new_lead_email} successfully",
            "team": team
        }
        
    except ValueError as e:
        logger.error(f"❌ Validation error setting team lead: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error setting team lead: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set team lead: {str(e)}"
        )