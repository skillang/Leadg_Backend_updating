# app/services/team_service.py - SIMPLIFIED TEAM MANAGEMENT (NO HIERARCHY)

from typing import Optional, List, Dict, Any
from datetime import datetime
from bson import ObjectId
import logging

from ..config.database import get_database

logger = logging.getLogger(__name__)

class TeamService:
    """Service for managing teams (simplified - no hierarchy)"""
    
    def __init__(self):
        self.db = None
    
    async def _get_db(self):
        """Get database instance"""
        if self.db is None:
            self.db = get_database()
        return self.db
    
    # ============================================================================
    # CREATE TEAM
    # ============================================================================
    
    async def create_team(
        self,
        name: str,
        team_lead_email: str,
        department: Optional[str] = None,
        description: Optional[str] = None,
        created_by_email: str = None
    ) -> Dict[str, Any]:
        """
        Create a new team
        
        Args:
            name: Team name (must be unique)
            team_lead_email: Email of team lead
            department: Optional department
            description: Optional description
            created_by_email: Email of creator
            
        Returns:
            Created team document
        """
        try:
            db = await self._get_db()
            
            # Check if team name already exists
            existing_team = await db.teams.find_one({"name": name})
            if existing_team:
                raise ValueError(f"Team with name '{name}' already exists")
            
            # Get team lead user
            team_lead = await db.users.find_one({"email": team_lead_email})
            if not team_lead:
                raise ValueError(f"Team lead user '{team_lead_email}' not found")
            
            # Generate team_id
            team_id = f"TEAM-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            
            # Create team document
            team_doc = {
                "team_id": team_id,
                "name": name,
                "description": description,
                "department": department,
                "team_lead_id": str(team_lead["_id"]),
                "team_lead_email": team_lead_email,
                "team_lead_name": f"{team_lead.get('first_name', '')} {team_lead.get('last_name', '')}".strip(),
                "member_ids": [team_lead["_id"]],  # ✅ Store ObjectId directly
                "member_count": 1,
                "is_active": True,
                "created_at": datetime.utcnow(),
                "created_by": created_by_email,
                "updated_at": datetime.utcnow(),
                "updated_by": created_by_email
            }
            
            # Insert team
            result = await db.teams.insert_one(team_doc)
            team_doc["_id"] = result.inserted_id
            
            # ✅ FIXED: Update team lead user with ObjectId
            await db.users.update_one(
                {"_id": team_lead["_id"]},
                {
                    "$set": {
                        "team_id": result.inserted_id,  # ✅ Store as ObjectId, NOT string!
                        "team_name": name,
                        "is_team_lead": True,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"✅ Team '{name}' created with ID: {team_id}")
            
            return {
                "id": str(result.inserted_id),
                "team_id": team_id,
                "name": name,
                "description": description,
                "department": department,
                "team_lead_email": team_lead_email,
                "team_lead_name": team_doc["team_lead_name"],
                "member_count": 1,
                "created_at": team_doc["created_at"]
            }
            
        except ValueError as e:
            logger.error(f"❌ Validation error creating team: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Error creating team: {e}")
            raise Exception(f"Failed to create team: {str(e)}")
    
    # ============================================================================
    # GET TEAM
    # ============================================================================
    
    async def get_team(self, team_id: str) -> Optional[Dict[str, Any]]:
        """
        Get team by ID (MongoDB ObjectId only - industry standard)
        
        Args:
            team_id: Team MongoDB ObjectId string (e.g., "693eaa1e4636923296c0a569")
            
        Returns:
            Team document or None
            
        Raises:
            ValueError: If team_id is not a valid ObjectId format
        """
        try:
            db = await self._get_db()
            
            # ✅ ONLY accept valid MongoDB ObjectId (industry standard)
            if not ObjectId.is_valid(team_id):
                raise ValueError(f"Invalid team ID format. Expected MongoDB ObjectId, got: {team_id}")
            
            # Query by MongoDB _id only
            team = await db.teams.find_one({"_id": ObjectId(team_id)})
            
            if not team:
                logger.warning(f"Team not found: {team_id}")
                return None
            
            # ✅ Return both 'id' and 'team_id' for backward compatibility
            return {
                "id": str(team["_id"]),                          # ✅ PRIMARY - Use in APIs
                "team_id": team.get("team_id"),                  # ✅ DISPLAY - Human-readable reference
                "name": team.get("name"),
                "description": team.get("description"),
                "department": team.get("department"),
                "team_lead_id": team.get("team_lead_id"),
                "team_lead_email": team.get("team_lead_email"),
                "team_lead_name": team.get("team_lead_name"),
                "member_ids": [str(mid) for mid in team.get("member_ids", [])],
                "member_count": team.get("member_count", 0),
                "is_active": team.get("is_active", True),
                "created_at": team.get("created_at"),
                "created_by": team.get("created_by"),
                "updated_at": team.get("updated_at"),
                "updated_by": team.get("updated_by")
            }
            
        except ValueError as e:
            # Re-raise validation errors
            logger.error(f"❌ Invalid team ID: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Error getting team: {e}")
            raise Exception(f"Failed to get team: {str(e)}")
   
    # ============================================================================
    # LIST TEAMS
    # ============================================================================
    
    async def list_teams(
        self,
        include_inactive: bool = False,
        department: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List all teams with optional filters
        
        Args:
            include_inactive: Include inactive teams
            department: Filter by department
            skip: Pagination skip
            limit: Pagination limit
            
        Returns:
            List of team documents
        """
        try:
            db = await self._get_db()
            
            # Build query
            query = {}
            if not include_inactive:
                query["is_active"] = True
            if department:
                query["department"] = department
            
            # Get teams
            teams_cursor = db.teams.find(query).sort("created_at", -1).skip(skip).limit(limit)
            teams = await teams_cursor.to_list(length=limit)
            
            result = []
            for team in teams:
                result.append({
                    "id": str(team["_id"]),
                    "team_id": team.get("team_id"),
                    "name": team.get("name"),
                    "description": team.get("description"),
                    "department": team.get("department"),
                    "team_lead_email": team.get("team_lead_email"),
                    "team_lead_name": team.get("team_lead_name"),
                    "member_count": team.get("member_count", 0),
                    "is_active": team.get("is_active", True),
                    "created_at": team.get("created_at")
                })
            
            logger.info(f"📋 Listed {len(result)} teams")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error listing teams: {e}")
            raise Exception(f"Failed to list teams: {str(e)}")
    
    # ============================================================================
    # UPDATE TEAM
    # ============================================================================
    
    async def update_team(
        self,
        team_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        department: Optional[str] = None,
        is_active: Optional[bool] = None,
        updated_by_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update team information
        
        Args:
            team_id: Team ID (ObjectId or team_id)
            name: New name
            description: New description
            department: New department
            is_active: Active status
            updated_by_email: Email of updater
            
        Returns:
            Updated team document
        """
        try:
            db = await self._get_db()
            
            # Get team
            team = await self.get_team(team_id)
            if not team:
                raise ValueError(f"Team '{team_id}' not found")
            
            # Build update
            update_doc = {"updated_at": datetime.utcnow()}
            if updated_by_email:
                update_doc["updated_by"] = updated_by_email
            if name is not None:
                # Check name uniqueness
                existing = await db.teams.find_one({"name": name, "_id": {"$ne": ObjectId(team["id"])}})
                if existing:
                    raise ValueError(f"Team name '{name}' already exists")
                update_doc["name"] = name
            if description is not None:
                update_doc["description"] = description
            if department is not None:
                update_doc["department"] = department
            if is_active is not None:
                update_doc["is_active"] = is_active
            
            # Update team
            await db.teams.update_one(
                {"_id": ObjectId(team["id"])},
                {"$set": update_doc}
            )
            
            # ✅ FIXED: If name changed, update all members with ObjectId query
            if name is not None:
                result = await db.users.update_many(
                    {"team_id": ObjectId(team["id"])},  # ✅ Query with ObjectId!
                    {"$set": {"team_name": name}}
                )
                logger.info(f"   Updated team_name for {result.modified_count} members")
            
            logger.info(f"✅ Team '{team['name']}' updated")
            
            # Return updated team
            return await self.get_team(team["id"])
            
        except ValueError as e:
            logger.error(f"❌ Validation error updating team: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Error updating team: {e}")
            raise Exception(f"Failed to update team: {str(e)}")
    
    # ============================================================================
    # DELETE TEAM
    # ============================================================================
    
    async def delete_team(self, team_id: str) -> bool:
        """
        Delete a team (soft delete - marks as inactive and removes members)
        
        Args:
            team_id: Team ID
            
        Returns:
            True if successful
        """
        try:
            db = await self._get_db()
            
            # Get team
            team = await self.get_team(team_id)
            if not team:
                raise ValueError(f"Team '{team_id}' not found")
            
            # ✅ FIXED: Convert string ID to ObjectId for query
            team_obj_id = ObjectId(team["id"])
            
            # Remove all members from team
            result = await db.users.update_many(
                {"team_id": team_obj_id},  # ✅ Query with ObjectId!
                {
                    "$set": {
                        "team_id": None,
                        "team_name": None,
                        "is_team_lead": False,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"   Unassigned {result.modified_count} users from team")
            
            # Mark team as inactive
            await db.teams.update_one(
                {"_id": team_obj_id},  # ✅ Use ObjectId
                {
                    "$set": {
                        "is_active": False,
                        "member_ids": [],
                        "member_count": 0,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"✅ Team '{team['name']}' deleted successfully")
            return True
            
        except ValueError as e:
            logger.error(f"❌ Validation error deleting team: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Error deleting team: {e}")
            raise Exception(f"Failed to delete team: {str(e)}")
    
    # ============================================================================
    # ADD MEMBER
    # ============================================================================
    
    async def add_member(
    self,
    team_id: str,
    user_email: str,
    updated_by_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Add a member to a team
        
        Args:
            team_id: Team ID
            user_email: Email of user to add
            updated_by_email: Email of updater
            
        Returns:
            Updated team document
        """
        try:
            db = await self._get_db()
            
            # Get team
            team = await self.get_team(team_id)
            if not team:
                raise ValueError(f"Team '{team_id}' not found")
            
            # Get user
            user = await db.users.find_one({"email": user_email})
            if not user:
                raise ValueError(f"User '{user_email}' not found")
            
            user_id = user["_id"]  # ✅ Keep as ObjectId
            
            # Check if already in team
            if user_id in team["member_ids"]:
                raise ValueError(f"User '{user_email}' is already in team '{team['name']}'")
            
            # Check if user is in another team
            if user.get("team_id"):
                raise ValueError(f"User '{user_email}' is already in another team. Remove them first.")
            
            # Add to team
            await db.teams.update_one(
                {"_id": ObjectId(team["id"])},
                {
                    "$push": {"member_ids": user_id},  # ✅ Store ObjectId
                    "$inc": {"member_count": 1},
                    "$set": {
                        "updated_at": datetime.utcnow(),
                        "updated_by": updated_by_email
                    }
                }
            )
            
            # ✅ FIXED: Update user with ObjectId
            await db.users.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "team_id": ObjectId(team["id"]),  # ✅ Store as ObjectId!
                        "team_name": team["name"],
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"✅ User '{user_email}' added to team '{team['name']}'")
            
            return await self.get_team(team["id"])
            
        except ValueError as e:
            logger.error(f"❌ Validation error adding member: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Error adding member: {e}")
            raise Exception(f"Failed to add member: {str(e)}")
    
    # ============================================================================
    # REMOVE MEMBER
    # ============================================================================
    
    async def remove_member(
        self,
        team_id: str,
        user_email: str,
        updated_by_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Remove a member from a team
        
        Args:
            team_id: Team ID
            user_email: Email of user to remove
            updated_by_email: Email of updater
            
        Returns:
            Updated team document
        """
        try:
            db = await self._get_db()
            
            # Get team
            team = await self.get_team(team_id)
            if not team:
                raise ValueError(f"Team '{team_id}' not found")
            
            # Get user
            user = await db.users.find_one({"email": user_email})
            if not user:
                raise ValueError(f"User '{user_email}' not found")
            
            user_id = str(user["_id"])
            
            # Check if in team
            if user_id not in team["member_ids"]:
                raise ValueError(f"User '{user_email}' is not in team '{team['name']}'")
            
            # Cannot remove team lead
            if user_id == team["team_lead_id"]:
                raise ValueError(f"Cannot remove team lead. Change team lead first.")
            
            # Remove from team
            await db.teams.update_one(
                {"_id": ObjectId(team["id"])},
                {
                    "$pull": {"member_ids": user_id},
                    "$inc": {"member_count": -1},
                    "$set": {
                        "updated_at": datetime.utcnow(),
                        "updated_by": updated_by_email
                    }
                }
            )
            
            # Update user
            await db.users.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "team_id": None,
                        "team_name": None,
                        "is_team_lead": False,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"✅ User '{user_email}' removed from team '{team['name']}'")
            
            return await self.get_team(team["id"])
            
        except ValueError as e:
            logger.error(f"❌ Validation error removing member: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Error removing member: {e}")
            raise Exception(f"Failed to remove member: {str(e)}")
    
    # ============================================================================
    # SET TEAM LEAD
    # ============================================================================
    
    async def set_team_lead(
        self,
        team_id: str,
        new_lead_email: str,
        updated_by_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Change team lead
        
        Args:
            team_id: Team ID
            new_lead_email: Email of new team lead
            updated_by_email: Email of updater
            
        Returns:
            Updated team document
        """
        try:
            db = await self._get_db()
            
            # Get team
            team = await self.get_team(team_id)
            if not team:
                raise ValueError(f"Team '{team_id}' not found")
            
            # Get new lead
            new_lead = await db.users.find_one({"email": new_lead_email})
            if not new_lead:
                raise ValueError(f"User '{new_lead_email}' not found")
            
            new_lead_id = str(new_lead["_id"])
            
            # Check if new lead is in team
            if new_lead_id not in team["member_ids"]:
                raise ValueError(f"User '{new_lead_email}' must be a team member first. Add them to the team.")
            
            old_lead_id = team["team_lead_id"]
            
            # Update team
            new_lead_name = f"{new_lead.get('first_name', '')} {new_lead.get('last_name', '')}".strip()
            await db.teams.update_one(
                {"_id": ObjectId(team["id"])},
                {
                    "$set": {
                        "team_lead_id": new_lead_id,
                        "team_lead_email": new_lead_email,
                        "team_lead_name": new_lead_name,
                        "updated_at": datetime.utcnow(),
                        "updated_by": updated_by_email
                    }
                }
            )
            
            # Remove is_team_lead from old lead
            if old_lead_id and old_lead_id != new_lead_id:
                await db.users.update_one(
                    {"_id": ObjectId(old_lead_id)},
                    {"$set": {"is_team_lead": False, "updated_at": datetime.utcnow()}}
                )
            
            # Set is_team_lead for new lead
            await db.users.update_one(
                {"_id": new_lead["_id"]},
                {"$set": {"is_team_lead": True, "updated_at": datetime.utcnow()}}
            )
            
            logger.info(f"✅ Team lead changed to '{new_lead_email}' for team '{team['name']}'")
            
            return await self.get_team(team["id"])
            
        except ValueError as e:
            logger.error(f"❌ Validation error setting team lead: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Error setting team lead: {e}")
            raise Exception(f"Failed to set team lead: {str(e)}")
    
    # ============================================================================
    # GET TEAM MEMBERS
    # ============================================================================
    
    async def get_team_members(
        self,
        team_id: str,
        include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get all members of a team
        
        Args:
            team_id: Team ID
            include_inactive: Include inactive users
            
        Returns:
            List of user documents
        """
        try:
            db = await self._get_db()
            
            # Get team
            team = await self.get_team(team_id)
            if not team:
                raise ValueError(f"Team '{team_id}' not found")
            
            # ✅ FIXED: Build query with ObjectId
            query = {"team_id": ObjectId(team["id"])}  # ✅ Query with ObjectId!
            if not include_inactive:
                query["is_active"] = True
            
            # Get members
            members_cursor = db.users.find(query).sort("first_name", 1)
            members = await members_cursor.to_list(length=None)
            
            result = []
            for user in members:
                result.append({
                    "id": str(user["_id"]),
                    "email": user.get("email"),
                    "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                    "first_name": user.get("first_name"),
                    "last_name": user.get("last_name"),
                    "is_team_lead": user.get("is_team_lead", False),
                    "is_active": user.get("is_active", True),
                    "role_name": user.get("role_name"),
                    "departments": user.get("departments", []),
                    "total_assigned_leads": user.get("total_assigned_leads", 0)
                })
            
            logger.info(f"📋 Retrieved {len(result)} members for team '{team['name']}'")
            return result
            
        except ValueError as e:
            logger.error(f"❌ Validation error getting team members: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Error getting team members: {e}")
            raise Exception(f"Failed to get team members: {str(e)}")
    
    # ============================================================================
    # GET USER'S TEAM
    # ============================================================================
    
    async def get_user_team(self, user_email: str) -> Optional[Dict[str, Any]]:
        """
        Get the team a user belongs to
        
        Args:
            user_email: User email
            
        Returns:
            Team document or None
        """
        try:
            db = await self._get_db()
            
            # Get user
            user = await db.users.find_one({"email": user_email})
            if not user:
                return None
            
            team_id = user.get("team_id")
            if not team_id:
                return None
            
            return await self.get_team(team_id)
            
        except Exception as e:
            logger.error(f"❌ Error getting user team: {e}")
            raise Exception(f"Failed to get user team: {str(e)}")


# Global instance
team_service = TeamService()