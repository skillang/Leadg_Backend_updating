# app/services/lead_service.py - UPDATED - LEAD SERVICE WITH CATEGORY-SOURCE COMBINATION ID GENERATION

from typing import Dict, Any, Optional, List
from datetime import datetime
from bson import ObjectId
import logging
from .rbac_service import RBACService
from .team_service import TeamService

from ..config.database import get_database
from ..models.lead import (
    LeadCreateComprehensive, ExperienceLevel,CallStatsModel
)
# 🆕 NEW: Import dynamic helpers
from ..models.course_level import CourseLevelHelper
from ..models.source import SourceHelper
from .lead_assignment_service import lead_assignment_service
from .user_lead_array_service import user_lead_array_service
from .lead_category_service import lead_category_service  # 🆕 NEW: Import for new ID generation

logger = logging.getLogger(__name__)

class LeadService:
    """Service for lead-related operations with enhanced assignment features and dynamic validation"""
    
    def __init__(self):
        self.rbac_service = RBACService()
        self.team_service = TeamService()
    
    def get_db(self):
        """Get database connection"""
        return get_database()
    
    # ============================================================================
    # 🆕 NEW: ENHANCED LEAD ID GENERATION WITH CATEGORY-SOURCE COMBINATION
    # ============================================================================
    async def build_access_filter_rbac(
    self,
    user_data: Dict[str, Any],
    db
) -> Dict[str, Any]:
        """
        Build MongoDB query filter based on user's RBAC permissions.
        
        **Permission Levels:**
        - `leads.read_all` → See all leads in system
        - `leads.read_team` → See own + team's leads (manager view)
        - `leads.read_own` → See only own assigned leads
        - Super Admin → Always see all
        
        **Returns:** MongoDB query filter
        """
        try:
            # Super admin bypass
            if user_data.get("is_super_admin"):
                logger.info("🔓 Super admin - full access")
                return {}
            
            # Get user's effective permissions
            effective_permissions = user_data.get("effective_permissions", [])
            user_email = user_data.get("email")
            
            # Check permission levels (order matters - most permissive first)
            if "leads.read_all" in effective_permissions:
                logger.info(f"✅ User {user_email} has leads.read_all - full access")
                return {}
            
            elif "leads.read_team" in effective_permissions:
                # Manager view - see own leads + team's leads
                logger.info(f"👥 User {user_email} has leads.read_team - building team filter")
                
                # Get all team member emails (including self)
                team_emails = await self._get_team_member_emails(user_data, db)
                
                logger.info(f"📋 Team members ({len(team_emails)}): {team_emails}")
                
                return {
                    "$or": [
                        {"assigned_to": {"$in": team_emails}},
                        {"co_assignees": {"$in": team_emails}},
                        {"created_by_email": user_email}  # Also see leads they created
                    ]
                }
            
            elif "leads.read_own" in effective_permissions:
                # Basic user - only see assigned leads
                logger.info(f"👤 User {user_email} has leads.read_own - own leads only")
                
                return {
                    "$or": [
                        {"assigned_to": user_email},
                        {"co_assignees": user_email}
                    ]
                }
            
            else:
                # No read permission - return impossible filter
                logger.warning(f"⚠️ User {user_email} has no lead read permissions!")
                return {"_id": ObjectId("000000000000000000000000")}  # No match
        
        except Exception as e:
            logger.error(f"❌ Error building access filter: {e}")
            # Fail-safe: restrict to user's own leads
            return {
                "$or": [
                    {"assigned_to": user_data.get("email")},
                    {"co_assignees": user_data.get("email")}
                ]
            }

    # ============================================================================
    # 🆕 NEW METHOD 2: GET TEAM MEMBER EMAILS
    # ============================================================================

    async def _get_team_member_emails(
        self,
        manager_data: Dict[str, Any],
        db
    ) -> List[str]:
        """
        Get all email addresses of team members (subordinates).
        
        **Returns:** List of team member emails (includes manager's own email)
        """
        try:
            from ..config.settings import settings
            
            manager_id = manager_data.get("_id")
            manager_email = manager_data.get("email")
            
            # Start with manager's own email
            team_emails = [manager_email]
            
            # Check if nested access is enabled
            if settings.allow_nested_team_access:
                # Get ALL subordinates at all levels
                team_emails.extend(
                    await self._get_all_subordinate_emails(manager_id, db)
                )
            else:
                # Get only direct reports
                direct_reports = await db.users.find(
                    {"reports_to": str(manager_id)},
                    {"email": 1}
                ).to_list(None)
                
                team_emails.extend([user["email"] for user in direct_reports])
            
            # Remove duplicates and return
            return list(set(team_emails))
        
        except Exception as e:
            logger.error(f"❌ Error getting team emails: {e}")
            return [manager_data.get("email")]  # Fallback to just manager

    # ============================================================================
    # 🆕 NEW METHOD 3: GET ALL SUBORDINATE EMAILS (RECURSIVE)
    # ============================================================================

    async def _get_all_subordinate_emails(
        self,
        manager_id: str,
        db,
        visited: Optional[set] = None
    ) -> List[str]:
        """
        Recursively get all subordinate emails at all levels.
        
        **Prevents Circular References:**
        - Tracks visited users to avoid infinite loops
        """
        try:
            from ..config.settings import settings
            
            if visited is None:
                visited = set()
            
            # Prevent circular references
            if str(manager_id) in visited:
                return []
            
            visited.add(str(manager_id))
            
            # Check depth limit
            if len(visited) > settings.max_hierarchy_depth * 10:  # Safety factor
                logger.warning("⚠️ Reached max subordinate depth")
                return []
            
            # Get direct reports
            direct_reports = await db.users.find(
                {"reports_to": str(manager_id)},
                {"_id": 1, "email": 1}
            ).to_list(None)
            
            subordinate_emails = []
            
            # Add direct reports and their subordinates
            for user in direct_reports:
                subordinate_emails.append(user["email"])
                
                # Recursively get their subordinates
                nested = await self._get_all_subordinate_emails(
                    str(user["_id"]),
                    db,
                    visited
                )
                subordinate_emails.extend(nested)
            
            return subordinate_emails
        
        except Exception as e:
            logger.error(f"❌ Error getting subordinates: {e}")
            return []

    # ============================================================================
    # 🆕 NEW METHOD 4: CAN USER ACCESS LEAD
    # ============================================================================

    async def can_user_access_lead(
        self,
        user_data: Dict[str, Any],
        lead_id: str,
        required_permission: str,
        db
    ) -> tuple[bool, str]:
        """
        Check if user can access a specific lead with required permission.
        
        **Args:**
        - user_data: Current user's data
        - lead_id: Lead to check access for
        - required_permission: Permission code needed (e.g., "leads.update")
        - db: Database connection
        
        **Returns:** (can_access: bool, reason: str)
        """
        try:
            # Super admin bypass
            if user_data.get("is_super_admin"):
                return True, "Super admin access"
            
            # Check if user has the required permission
            effective_permissions = user_data.get("effective_permissions", [])
            if required_permission not in effective_permissions:
                return False, f"Missing permission: {required_permission}"
            
            # Get the lead
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                return False, "Lead not found"
            
            user_email = user_data.get("email")
            
            # Check if has read_all permission
            if "leads.read_all" in effective_permissions:
                return True, "Has leads.read_all permission"
            
            # Check if assigned or co-assigned
            if lead.get("assigned_to") == user_email:
                return True, "Primary assignee"
            
            if user_email in lead.get("co_assignees", []):
                return True, "Co-assignee"
            
            # Check if lead is assigned to team member (if has read_team)
            if "leads.read_team" in effective_permissions:
                team_emails = await self._get_team_member_emails(user_data, db)
                
                if lead.get("assigned_to") in team_emails:
                    return True, "Assigned to team member"
                
                if any(co_assignee in team_emails for co_assignee in lead.get("co_assignees", [])):
                    return True, "Co-assigned to team member"
            
            # No access
            return False, "Not assigned and not in visible scope"
        
        except Exception as e:
            logger.error(f"❌ Error checking lead access: {e}")
            return False, f"Error: {str(e)}"

    # ============================================================================
    # 🆕 NEW METHOD 5: CAN USER ASSIGN LEAD
    # ============================================================================

    async def can_user_assign_lead(
        self,
        user_data: Dict[str, Any],
        target_user_email: str,
        db
    ) -> tuple[bool, str]:
        """
        Check if user can assign leads to target user.
        
        **Business Rules:**
        - Super admin: Can assign to anyone
        - Has `leads.assign_any`: Can assign to anyone
        - Has `leads.assign_team`: Can assign to team members only
        
        **Returns:** (can_assign: bool, reason: str)
        """
        try:
            # Super admin bypass
            if user_data.get("is_super_admin"):
                return True, "Super admin access"
            
            effective_permissions = user_data.get("effective_permissions", [])
            
            # Check assign_any permission
            if "leads.assign_any" in effective_permissions:
                return True, "Has leads.assign_any permission"
            
            # Check assign_team permission
            if "leads.assign_team" in effective_permissions:
                # Get team member emails
                team_emails = await self._get_team_member_emails(user_data, db)
                
                if target_user_email in team_emails:
                    return True, "Target is team member"
                else:
                    return False, "Target not in team - need leads.assign_any"
            
            # No assign permission
            return False, "Missing assignment permission (need leads.assign_team or leads.assign_any)"
        
        except Exception as e:
            logger.error(f"❌ Error checking assign permission: {e}")
            return False, f"Error: {str(e)}"

    # ============================================================================
    # 🆕 NEW METHOD 6: GET ACCESS LEVEL NAME (HELPER)
    # ============================================================================

    def _get_access_level_name(self, user_data: Dict[str, Any]) -> str:
        """Get human-readable access level name"""
        if user_data.get("is_super_admin"):
            return "super_admin"
        
        effective_permissions = user_data.get("effective_permissions", [])
        
        if "leads.read_all" in effective_permissions:
            return "read_all"
        elif "leads.read_team" in effective_permissions:
            return "read_team"
        elif "leads.read_own" in effective_permissions:
            return "read_own"
        else:
            return "no_access"

    async def generate_lead_id_by_category_and_source(self, category: str, source: str) -> str:
        """
        🆕 NEW: Generate lead ID using category-source combination
        Format: {CATEGORY_SHORT}-{SOURCE_SHORT}-{NUMBER}
        Examples: NS-WB-1, SA-SM-2, WA-RF-1
        """
        try:
            # Use the new combination-based ID generation from lead_category_service
            lead_id = await lead_category_service.generate_lead_id_by_category_and_source(
                category=category,
                source=source
            )
            
            logger.info(f"✅ Generated combination lead ID: {lead_id} for category '{category}' and source '{source}'")
            return lead_id
            
        except Exception as e:
            logger.error(f"Error generating combination lead ID: {str(e)}")
            # Fallback to old category-only format
            logger.warning("Falling back to category-only lead ID generation")
            return await self.generate_lead_id_by_category_fallback(category)
    
    async def generate_lead_id_by_category_fallback(self, category: str) -> str:
        """Fallback to old category-only format if combination fails"""
        try:
            # Use legacy method as fallback
            lead_id = await lead_category_service.generate_lead_id(category)
            logger.warning(f"Generated fallback lead ID: {lead_id} for category: {category}")
            return lead_id
            
        except Exception as e:
            logger.error(f"Error generating fallback lead ID: {str(e)}")
            # Ultimate fallback
            import time
            fallback_id = f"LD-FB-{int(time.time())}"
            logger.error(f"Using ultimate fallback ID: {fallback_id}")
            return fallback_id
    
    async def validate_category_and_source_for_lead_creation(self, category: str, source: str) -> Dict[str, Any]:
        """Validate that both category and source exist and are active before creating lead"""
        try:
            db = self.get_db()
            
            # Check category exists and is active
            category_doc = await db.lead_categories.find_one({"name": category, "is_active": True})
            category_valid = category_doc is not None
            
            # Check source exists and is active
            source_doc = await db.sources.find_one({"name": source, "is_active": True})
            source_valid = source_doc is not None
            
            validation_result = {
                "category_valid": category_valid,
                "source_valid": source_valid,
                "can_create_lead": category_valid and source_valid,
                "category_short_form": category_doc.get("short_form") if category_doc else None,
                "source_short_form": source_doc.get("short_form") if source_doc else None
            }
            
            if not validation_result["can_create_lead"]:
                missing_items = []
                if not category_valid:
                    missing_items.append(f"category '{category}'")
                if not source_valid:
                    missing_items.append(f"source '{source}'")
                
                validation_result["error_message"] = f"Cannot create lead: {' and '.join(missing_items)} not found or inactive"
            else:
                # Preview the lead ID that will be generated
                preview_id = f"{validation_result['category_short_form']}-{validation_result['source_short_form']}-X"
                validation_result["lead_id_preview"] = preview_id
            
            return validation_result
            
        except Exception as e:
            logger.error(f"Error validating category and source: {str(e)}")
            return {
                "category_valid": False,
                "source_valid": False,
                "can_create_lead": False,
                "error_message": f"Validation error: {str(e)}"
            }
    
    # ============================================================================
    # 🆕 NEW: DYNAMIC FIELD VALIDATION FUNCTIONS
    # ============================================================================
    
    async def validate_and_set_course_level(self, course_level: Optional[str]) -> Optional[str]:
        """Validate and set course level for lead creation"""
        try:
            if not course_level:
                # Get default course level if none provided
                default_course_level = await CourseLevelHelper.get_default_course_level()
                if default_course_level:
                    logger.info(f"No course level provided, using default: {default_course_level}")
                    return default_course_level
                else:
                    logger.warning("No course level provided and no default course level exists - admin must create course levels")
                    return None
            
            # Validate provided course level exists and is active
            db = self.get_db()
            
            course_level_doc = await db.course_levels.find_one({
                "name": course_level,
                "is_active": True
            })
            
            if not course_level_doc:
                logger.warning(f"Invalid course level '{course_level}', checking for default")
                default_course_level = await CourseLevelHelper.get_default_course_level()
                if default_course_level:
                    logger.info(f"Using default course level: {default_course_level}")
                    return default_course_level
                else:
                    logger.warning("No valid course level found and no default exists")
                    return None
            
            logger.info(f"Using provided course level: {course_level}")
            return course_level
            
        except Exception as e:
            logger.error(f"Error validating course level: {e}")
            # Try to get default as fallback
            try:
                default_course_level = await CourseLevelHelper.get_default_course_level()
                return default_course_level
            except:
                return None

    async def validate_and_set_source(self, source: Optional[str]) -> Optional[str]:
        """Validate and set source for lead creation"""
        try:
            if not source:
                # Get default source if none provided
                default_source = await SourceHelper.get_default_source()
                if default_source:
                    logger.info(f"No source provided, using default: {default_source}")
                    return default_source
                else:
                    logger.warning("No source provided and no default source exists - admin must create sources")
                    return None
            
            # Validate provided source exists and is active
            db = self.get_db()
            
            source_doc = await db.sources.find_one({
                "name": source,
                "is_active": True
            })
            
            if not source_doc:
                logger.warning(f"Invalid source '{source}', checking for default")
                default_source = await SourceHelper.get_default_source()
                if default_source:
                    logger.info(f"Using default source: {default_source}")
                    return default_source
                else:
                    logger.warning("No valid source found and no default exists")
                    return None
            
            logger.info(f"Using provided source: {source}")
            return source
            
        except Exception as e:
            logger.error(f"Error validating source: {e}")
            # Try to get default as fallback
            try:
                default_source = await SourceHelper.get_default_source()
                return default_source
            except:
                return None

    async def validate_required_dynamic_fields(self) -> Dict[str, Any]:
        """Check if required dynamic fields (course levels and sources) exist"""
        try:
            db = self.get_db()
            
            # Check if any active course levels exist
            course_levels_count = await db.course_levels.count_documents({"is_active": True})
            
            # Check if any active sources exist
            sources_count = await db.sources.count_documents({"is_active": True})
            
            # 🆕 NEW: Check if any active categories exist
            categories_count = await db.lead_categories.count_documents({"is_active": True})
            
            validation_result = {
                "course_levels_exist": course_levels_count > 0,
                "sources_exist": sources_count > 0,
                "categories_exist": categories_count > 0,
                "course_levels_count": course_levels_count,
                "sources_count": sources_count,
                "categories_count": categories_count,
                "can_create_leads": course_levels_count > 0 and sources_count > 0 and categories_count > 0
            }
            
            if not validation_result["can_create_leads"]:
                missing_fields = []
                if course_levels_count == 0:
                    missing_fields.append("course_levels")
                if sources_count == 0:
                    missing_fields.append("sources")
                if categories_count == 0:
                    missing_fields.append("categories")
                
                validation_result["error_message"] = f"Cannot create leads: Admin must create {' and '.join(missing_fields)} first"
            
            return validation_result
            
        except Exception as e:
            logger.error(f"Error validating dynamic fields: {e}")
            return {
                "course_levels_exist": False,
                "sources_exist": False,
                "categories_exist": False,
                "can_create_leads": False,
                "error_message": f"Error validating required fields: {str(e)}"
            }

    # ============================================================================
    # 🔄 UPDATED: ENHANCED LEAD CREATION WITH NEW ID GENERATION
    # ============================================================================
    async def create_lead_comprehensive(
    self,
    lead_data: LeadCreateComprehensive,
    created_by: str,
    force_create: bool = False
) -> Dict[str, Any]:
        """
        🔄 UPDATED: Lead creation with unified notification (ONE notification for assigned user + admins)
        """
        try:
            db = self.get_db()
            
            # 🆕 NEW: Validate dynamic fields first
            field_validation = await self.validate_required_dynamic_fields()
            if not field_validation["can_create_leads"]:
                return {
                    "success": False,
                    "message": field_validation["error_message"],
                    "validation_error": field_validation
                }
            
            # Step 1: Extract basic info including new fields
            basic_info = lead_data.basic_info
            status_and_tags = lead_data.status_and_tags or type('obj', (object,), {})()
            assignment = lead_data.assignment or type('obj', (object,), {})()
            additional_info = lead_data.additional_info or type('obj', (object,), {})()
            
            logger.info(f"Creating lead with new fields: age={basic_info.age}, experience={basic_info.experience}, nationality={basic_info.nationality}")
            
        
            # Step 2: Check for duplicates
            if not force_create:
                duplicate_check = await self.check_duplicate_lead(
                    email=basic_info.email,
                    contact_number=basic_info.contact_number
                )
                if duplicate_check["is_duplicate"]:
                    return {
                        "success": False,
                        "message": duplicate_check["message"],
                        "duplicate_check": duplicate_check
                    }
            # 🆕 NEW: Step 3: Validate and set dynamic fields
            validated_course_level = await self.validate_and_set_course_level(
                getattr(basic_info, 'course_level', None)
            )
            validated_source = await self.validate_and_set_source(
                getattr(basic_info, 'source', None)
            )
            
            # 🆕 NEW: Step 4: Validate category and source combination
            validation_result = await self.validate_category_and_source_for_lead_creation(
                basic_info.category, validated_source
            )
            
            if not validation_result["can_create_lead"]:
                return {
                    "success": False,
                    "message": validation_result["error_message"],
                    "validation_error": validation_result
                }
            
            # 🔄 UPDATED: Step 5: Generate lead ID using category-source combination
            lead_id = await self.generate_lead_id_by_category_and_source(
                category=basic_info.category,
                source=validated_source
            )
            
            logger.info(f"✅ Generated new format lead ID: {lead_id} for category '{basic_info.category}' and source '{validated_source}'")
            
            # Step 6: Handle assignment with support for explicit "unassigned"
            assigned_to = assignment.assigned_to if hasattr(assignment, 'assigned_to') else None
            assigned_to_name = None

            if assigned_to == "unassigned":
                assigned_to = None
                assigned_to_name = None
                assignment_method = "unassigned"
                logger.info("Lead explicitly set to unassigned by admin")
            elif assigned_to and assigned_to != "unassigned":
                assignment_method = "manual"
                logger.info(f"Manual assignment to: {assigned_to}")
            else:
                assigned_to = await lead_assignment_service.get_next_assignee_round_robin()
                assignment_method = "round_robin"
                logger.info(f"Auto-assigned to: {assigned_to}")
            
            # Get assignee name
            if assigned_to:
                assignee = await db.users.find_one({"email": assigned_to})
                if assignee:
                    assigned_to_name = f"{assignee.get('first_name', '')} {assignee.get('last_name', '')}".strip()
                    if not assigned_to_name:
                        assigned_to_name = assignee.get('email', 'Unknown')
            
            # Step 7: Create lead document
            lead_doc = {
                "lead_id": lead_id,
                "status": getattr(status_and_tags, 'status', 'New'),
                "name": basic_info.name,
                "email": basic_info.email.lower(),
                "contact_number": basic_info.contact_number,
                "phone_number": basic_info.contact_number,
                "source": validated_source,
                "category": basic_info.category,
                "course_level": validated_course_level,
                "date_of_birth": basic_info.date_of_birth,
                "call_stats": CallStatsModel.create_default().model_dump(),
                
                "age": basic_info.age,
                "experience": basic_info.experience,
                "nationality": basic_info.nationality,
                "current_location": basic_info.current_location,
                
                "stage": getattr(status_and_tags, 'stage', 'Pending'),
                "lead_score": getattr(status_and_tags, 'lead_score', 0),
                "priority": "medium",
                "tags": getattr(status_and_tags, 'tags', []),
                
                "assigned_to": assigned_to,
                "assigned_to_name": assigned_to_name,
                "assignment_method": assignment_method,
                
                "co_assignees": [],
                "co_assignees_names": [],
                "is_multi_assigned": False,
                
                "assignment_history": [
                    {
                        "assigned_to": assigned_to,
                        "assigned_to_name": assigned_to_name,
                        "assigned_by": created_by,
                        "assignment_method": assignment_method,
                        "assigned_at": datetime.utcnow(),
                        "reason": "Initial assignment",
                        "lead_id_format": "category_source_combination",
                        "category_short": validation_result.get("category_short_form"),
                        "source_short": validation_result.get("source_short_form")
                    }
                ],
                
                "notes": getattr(additional_info, 'notes', ''),
                "created_by": created_by,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            # Step 8: Insert lead
            result = await db.leads.insert_one(lead_doc)
            
            if result.inserted_id:
                # Step 9: Update user array if assigned
                if assigned_to:
                    await user_lead_array_service.add_lead_to_user_array(assigned_to, lead_id)
                
                # 🔥 UPDATED: Step 9.5: Send unified notification (ONE notification for user + admins)
                if assigned_to and assigned_to_name:
                    try:
                        from ..services.realtime_service import realtime_manager
                        
                        notification_data = {
                            "lead_name": basic_info.name,
                            "lead_email": basic_info.email,
                            "lead_phone": basic_info.contact_number,
                            "category": basic_info.category,
                            "source": validated_source,
                            "assignment_method": assignment_method
                        }
                        
                        authorized_users = [{"email": assigned_to, "name": assigned_to_name}]
                        
                        # This ONE call creates notification for assigned user + admins automatically
                        await realtime_manager.notify_lead_assigned(lead_id, notification_data, authorized_users)
                        
                        logger.info(f"✅ Unified lead assignment notification created for {assigned_to}")
                    except Exception as notif_error:
                        logger.warning(f"⚠️ Failed to send lead assignment notification: {notif_error}")
                
                # Step 10: Timeline Activity Logging (unchanged)
                try:
                    creator = await db.users.find_one({"_id": ObjectId(created_by)})
                    created_by_name = "Unknown User"
                    if creator:
                        first_name = creator.get('first_name', '')
                        last_name = creator.get('last_name', '')
                        if first_name and last_name:
                            created_by_name = f"{first_name} {last_name}".strip()
                        else:
                            created_by_name = creator.get('email', 'Unknown User')
                    
                    existing_activity = await db.lead_activities.find_one({
                        "lead_id": lead_id,
                        "activity_type": "lead_created"
                    })
                    
                    if not existing_activity:
                        if assigned_to and assigned_to_name:
                            description = f"Lead created by {created_by_name} and assigned to {assigned_to_name}"
                        else:
                            description = f"Lead created by {created_by_name} (unassigned)"
                        
                        activity_doc = {
                            "lead_id": lead_id,
                            "activity_type": "lead_created",
                            "description": description,
                            "created_by": ObjectId(created_by),
                            "created_by_name": created_by_name,
                            "created_at": datetime.utcnow(),
                            "updated_at": datetime.utcnow(),
                            "is_system_generated": True,
                            "metadata": {
                                "lead_id": lead_id,
                                "lead_name": basic_info.name,
                                "category": basic_info.category,
                                "source": validated_source,
                                "assigned_to": assigned_to,
                                "assigned_to_name": assigned_to_name,
                                "assignment_method": assignment_method
                            }
                        }
                        
                        await db.lead_activities.insert_one(activity_doc)
                        logger.info(f"✅ Timeline 'lead_created' logged for {lead_id} by {created_by_name}")
                        
                except Exception as activity_error:
                    logger.warning(f"⚠️ Failed to log timeline activity for {lead_id}: {activity_error}")
                
                logger.info(f"✅ Lead created successfully: {lead_id} with category-source combination format")
                
                return {
                    "success": True,
                    "message": f"Lead created successfully with ID: {lead_id}",
                    "lead": self.format_lead_response(lead_doc),
                    "assignment_info": {
                        "assigned_to": assigned_to,
                        "assigned_to_name": assigned_to_name,
                        "assignment_method": assignment_method
                    },
                    "validated_fields": {
                        "course_level": validated_course_level,
                        "source": validated_source
                    },
                    "lead_id_info": {
                        "format": "category_source_combination",
                        "category_short": validation_result.get("category_short_form"),
                        "source_short": validation_result.get("source_short_form"),
                        "lead_id": lead_id
                    },
                    "duplicate_check": {
                        "is_duplicate": False,
                        "checked": True
                    }
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to create lead"
                }
            
        except Exception as e:
            logger.error(f"Error creating lead: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to create lead: {str(e)}"
            }   
# ============================================================================
    async def create_lead_with_selective_assignment(
        self, 
        basic_info, 
        status_and_tags, 
        assignment_info, 
        additional_info,
        created_by: str,
        selected_user_emails: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        🔄 UPDATED: Create lead with selective round robin assignment using unified notification
        WITH timeline activity logging AND ONE notification for assigned user + admins
        """
        db = self.get_db()
        
        try:
            # 🆕 NEW: Validate dynamic fields first
            field_validation = await self.validate_required_dynamic_fields()
            if not field_validation["can_create_leads"]:
                return {
                    "success": False,
                    "message": field_validation["error_message"],
                    "validation_error": field_validation
                }
            
            # Step 1: Check for duplicates
            duplicate_check = await self.check_duplicate_lead(
                email=basic_info.email,
                contact_number=getattr(basic_info, 'contact_number', None)
            )
            if duplicate_check["is_duplicate"]:
                return {
                    "success": False,
                    "message": duplicate_check["message"],
                    "duplicate_check": duplicate_check
                }
            
            # Step 2: Validate and set dynamic fields
            validated_course_level = await self.validate_and_set_course_level(
                getattr(basic_info, 'course_level', None)
            )
            validated_source = await self.validate_and_set_source(
                getattr(basic_info, 'source', None)
            )
            
            # 🆕 NEW: Step 3: Validate category and source combination
            validation_result = await self.validate_category_and_source_for_lead_creation(
                basic_info.category, validated_source
            )
            
            if not validation_result["can_create_lead"]:
                return {
                    "success": False,
                    "message": validation_result["error_message"],
                    "validation_error": validation_result
                }
            
            # 🔄 UPDATED: Step 4: Generate lead ID using category-source combination
            lead_id = await self.generate_lead_id_by_category_and_source(
                category=basic_info.category,
                source=validated_source
            )
            
            # Step 5: Handle assignment with selective round robin and support for explicit "unassigned"
            assigned_to = assignment_info.assigned_to if assignment_info else None
            assigned_to_name = None

            if assigned_to == "unassigned":
                assigned_to = None
                assigned_to_name = None
                assignment_method = "unassigned"
                logger.info("Lead explicitly set to unassigned by admin")
            elif assigned_to and assigned_to != "unassigned":
                assignment_method = "manual"
                logger.info(f"Manual assignment to: {assigned_to}")
            else:
                if selected_user_emails:
                    assigned_to = await lead_assignment_service.get_next_assignee_selective_round_robin(
                        selected_user_emails
                    )
                    assignment_method = "selective_round_robin"
                    logger.info(f"Selective round robin assigned to: {assigned_to}")
                else:
                    assigned_to = await lead_assignment_service.get_next_assignee_round_robin()
                    assignment_method = "round_robin"
                    logger.info(f"Regular round robin assigned to: {assigned_to}")
            
            # Get assignee name
            if assigned_to:
                assignee = await db.users.find_one({"email": assigned_to})
                if assignee:
                    assigned_to_name = f"{assignee.get('first_name', '')} {assignee.get('last_name', '')}".strip()
                    if not assigned_to_name:
                        assigned_to_name = assignee.get('email', 'Unknown')
            
            # Step 6: Create lead document with validated dynamic fields
            lead_doc = {
                "lead_id": lead_id,
                "status": status_and_tags.status if hasattr(status_and_tags, 'status') else "New",
                "name": basic_info.name,
                "email": basic_info.email.lower(),
                "contact_number": basic_info.contact_number,
                "phone_number": basic_info.contact_number,
                "source": validated_source,
                "category": basic_info.category,
                "course_level": validated_course_level,
                
                # Optional fields
                "age": basic_info.age,
                "experience": basic_info.experience,
                "nationality": basic_info.nationality,
                "current_location": basic_info.current_location,
                "date_of_birth": basic_info.date_of_birth,
                "call_stats": CallStatsModel.create_default().model_dump(),               
                
                # Status and tags
                "stage": status_and_tags.stage if hasattr(status_and_tags, 'stage') else "Pending",
                "lead_score": status_and_tags.lead_score if hasattr(status_and_tags, 'lead_score') else 0,
                "priority": "medium",
                "tags": status_and_tags.tags if hasattr(status_and_tags, 'tags') else [],
                
                # Single assignment (backward compatibility)
                "assigned_to": assigned_to,
                "assigned_to_name": assigned_to_name,
                "assignment_method": assignment_method,
                
                # Multi-assignment fields
                "co_assignees": [],
                "co_assignees_names": [],
                "is_multi_assigned": False,
                
                # Assignment history
                "assignment_history": [
                    {
                        "assigned_to": assigned_to,
                        "assigned_to_name": assigned_to_name,
                        "assigned_by": created_by,
                        "assignment_method": assignment_method,
                        "assigned_at": datetime.utcnow(),
                        "reason": "Initial assignment",
                        "selected_users_pool": selected_user_emails,
                        "lead_id_format": "category_source_combination",
                        "category_short": validation_result.get("category_short_form"),
                        "source_short": validation_result.get("source_short_form")
                    }
                ],
                
                # Additional info
                "notes": additional_info.notes if hasattr(additional_info, 'notes') else "",
                "created_by": created_by,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            # Step 7: Insert lead
            result = await db.leads.insert_one(lead_doc)
            
            if result.inserted_id:
                # Step 8: Update user array if assigned
                if assigned_to:
                    await user_lead_array_service.add_lead_to_user_array(assigned_to, lead_id)
                
                # 🔥 UPDATED: Step 8.5: Send unified notification (ONE for assigned user + admins)
                if assigned_to and assigned_to_name:
                    try:
                        from ..services.realtime_service import realtime_manager
                        
                        notification_data = {
                            "lead_name": basic_info.name,
                            "lead_email": basic_info.email,
                            "lead_phone": basic_info.contact_number,
                            "category": basic_info.category,
                            "source": validated_source,
                            "assignment_method": assignment_method,
                            "selected_users_pool": selected_user_emails
                        }
                        
                        authorized_users = [{"email": assigned_to, "name": assigned_to_name}]
                        
                        # ONE call creates notification for assigned user + admins automatically
                        await realtime_manager.notify_lead_assigned(lead_id, notification_data, authorized_users)
                        
                        logger.info(f"✅ Unified lead assignment notification created for {assigned_to}")
                    except Exception as notif_error:
                        logger.warning(f"⚠️ Failed to send lead assignment notification: {notif_error}")
                
                # Step 9: Timeline Activity Logging
                try:
                    creator = await db.users.find_one({"_id": ObjectId(created_by)})
                    created_by_name = "Unknown User"
                    if creator:
                        first_name = creator.get('first_name', '')
                        last_name = creator.get('last_name', '')
                        if first_name and last_name:
                            created_by_name = f"{first_name} {last_name}".strip()
                        else:
                            created_by_name = creator.get('email', 'Unknown User')
                    
                    existing_activity = await db.lead_activities.find_one({
                        "lead_id": lead_id,
                        "activity_type": "lead_created"
                    })
                    
                    if not existing_activity:
                        if assigned_to and assigned_to_name:
                            description = f"Lead created by {created_by_name} and assigned to {assigned_to_name}"
                        else:
                            description = f"Lead created by {created_by_name} (unassigned)"
                        
                        activity_doc = {
                            "lead_id": lead_id,
                            "activity_type": "lead_created",
                            "description": description,
                            "created_by": ObjectId(created_by),
                            "created_by_name": created_by_name,
                            "created_at": datetime.utcnow(),
                            "updated_at": datetime.utcnow(),
                            "is_system_generated": True,
                            "metadata": {
                                "lead_id": lead_id,
                                "assigned_to": assigned_to,
                                "assigned_to_name": assigned_to_name,
                                "assignment_method": assignment_method,
                                "selected_users_pool": selected_user_emails
                            }
                        }
                        
                        await db.lead_activities.insert_one(activity_doc)
                        logger.info(f"✅ Timeline 'lead_created' logged for {lead_id} by {created_by_name}")
                    else:
                        logger.info(f"⚠️ Timeline activity already exists for lead {lead_id}")
                        
                except Exception as activity_error:
                    logger.warning(f"⚠️ Failed to log timeline activity for {lead_id}: {activity_error}")
                
                logger.info(f"Lead {lead_id} created and assigned to {assigned_to} using {assignment_method}")
                
                return {
                    "success": True,
                    "message": f"Lead created successfully with ID: {lead_id}",
                    "lead": self.format_lead_response(lead_doc),
                    "lead_id": lead_id,
                    "assigned_to": assigned_to,
                    "assignment_method": assignment_method,
                    "selected_users_pool": selected_user_emails,
                    "validated_fields": {
                        "course_level": validated_course_level,
                        "source": validated_source
                    },
                    "lead_id_info": {
                        "format": "category_source_combination",
                        "category_short": validation_result.get("category_short_form"),
                        "source_short": validation_result.get("source_short_form"),
                        "lead_id": lead_id
                    },
                    "duplicate_check": {
                        "is_duplicate": False,
                        "checked": True
                    }
                }
            else:
                return {"success": False, "error": "Failed to create lead"}
                
        except Exception as e:
            logger.error(f"Error creating lead with selective assignment: {str(e)}")
            return {"success": False, "error": str(e)}
    async def bulk_create_leads_with_selective_assignment(
    self,
    leads_data: List[Dict[str, Any]],
    created_by: str,
    assignment_method: str = "all_users",
    selected_user_emails: Optional[List[str]] = None
) -> Dict[str, Any]:
        """
        🔄 UPDATED: Bulk create leads with unified notifications
        WITH timeline activity logging AND ONE notification per lead (assigned user + admins)
        """
        db = self.get_db()
        
        try:
            # Validate dynamic fields first
            field_validation = await self.validate_required_dynamic_fields()
            if not field_validation["can_create_leads"]:
                return {
                    "success": False,
                    "message": field_validation["error_message"],
                    "validation_error": field_validation
                }
            
            created_leads = []
            failed_leads = []
            duplicates_skipped = []
            assignment_summary = []
            
            logger.info(f"🚀 Processing {len(leads_data)} leads for bulk creation...")
            
            # Get creator name once (outside loop for efficiency)
            creator = await db.users.find_one({"_id": ObjectId(created_by)})
            created_by_name = "Unknown User"
            if creator:
                first_name = creator.get('first_name', '')
                last_name = creator.get('last_name', '')
                if first_name and last_name:
                    created_by_name = f"{first_name} {last_name}".strip()
                else:
                    created_by_name = creator.get('email', 'Unknown User')
            
            for i, lead_data in enumerate(leads_data):
                try:
                    logger.info(f"📋 Processing lead {i+1}/{len(leads_data)}: {lead_data.get('email', 'no email')}")
                    
                    # Check for duplicates against LIVE database
                    duplicate_check = await self.check_duplicate_lead(
                        email=lead_data.get("email", ""),
                        contact_number=lead_data.get("contact_number", "")
                    )
                    
                    if duplicate_check["is_duplicate"]:
                        logger.warning(f"⚠️ DUPLICATE DETECTED for lead {i}: {duplicate_check['message']}")
                        duplicates_skipped.append({
                            "index": i,
                            "data": {
                                "name": lead_data.get("name", ""),
                                "email": lead_data.get("email", ""),
                                "contact_number": lead_data.get("contact_number", "")
                            },
                            "reason": duplicate_check["message"],
                            "existing_lead_id": duplicate_check.get("existing_lead_id"),
                            "duplicate_field": duplicate_check.get("duplicate_field"),
                            "duplicate_value": duplicate_check.get("duplicate_value")
                        })
                        assignment_summary.append({
                            "lead_id": None,
                            "assigned_to": None,
                            "status": "skipped_duplicate",
                            "reason": duplicate_check["message"]
                        })
                        continue
                    
                    logger.info(f"✅ No duplicate found for lead {i}, proceeding with creation...")
                    
                    # Validate and set dynamic fields
                    validated_course_level = await self.validate_and_set_course_level(
                        lead_data.get("course_level")
                    )
                    validated_source = await self.validate_and_set_source(
                        lead_data.get("source")
                    )
                    
                    # Generate lead ID using category-source combination
                    lead_id = await self.generate_lead_id_by_category_and_source(
                        category=lead_data.get("category", "General"),
                        source=validated_source
                    )
                    
                    # Handle assignment logic
                    lead_assigned_to = lead_data.get("assigned_to")
                    
                    if lead_assigned_to == "unassigned":
                        assigned_to = None
                        assigned_to_name = None
                        method = "unassigned"
                        logger.info(f"Lead {i} explicitly set to unassigned")
                    elif lead_assigned_to and lead_assigned_to != "unassigned":
                        assigned_to = lead_assigned_to
                        method = "manual"
                        logger.info(f"Lead {i} manually assigned to: {assigned_to}")
                    else:
                        if assignment_method == "selected_users" and selected_user_emails:
                            assigned_to = await lead_assignment_service.get_next_assignee_selective_round_robin(
                                selected_user_emails
                            )
                            method = "selective_round_robin"
                        else:
                            assigned_to = await lead_assignment_service.get_next_assignee_round_robin()
                            method = "round_robin"
                        logger.info(f"Lead {i} auto-assigned to: {assigned_to} using {method}")
                    
                    # Get assignee name
                    assigned_to_name = None
                    if assigned_to:
                        assignee = await db.users.find_one({"email": assigned_to})
                        if assignee:
                            assigned_to_name = f"{assignee.get('first_name', '')} {assignee.get('last_name', '')}".strip()
                            if not assigned_to_name:
                                assigned_to_name = assignee.get('email', 'Unknown')
                    
                    # Create lead document with all required fields
                    lead_doc = {
                        "lead_id": lead_id,
                        "status": lead_data.get("status", "New"),
                        "name": lead_data.get("name", ""),
                        "email": lead_data.get("email", "").lower(),
                        "contact_number": lead_data.get("contact_number", ""),
                        "phone_number": lead_data.get("contact_number", ""),
                        "source": validated_source,
                        "category": lead_data.get("category", "General"),
                        "course_level": validated_course_level,
                        
                        # Optional fields
                        "age": lead_data.get("age"),
                        "experience": lead_data.get("experience"),
                        "nationality": lead_data.get("nationality"),
                        "current_location": lead_data.get("current_location"),
                        "date_of_birth": lead_data.get("date_of_birth"),
                        "call_stats": CallStatsModel.create_default().model_dump(),
                        
                        # Status and tags
                        "stage": lead_data.get("stage", "Pending"),
                        "lead_score": lead_data.get("lead_score", 0),
                        "priority": lead_data.get("priority", "medium"),
                        "tags": lead_data.get("tags", []),
                        
                        # Assignment
                        "assigned_to": assigned_to,
                        "assigned_to_name": assigned_to_name,
                        "assignment_method": method,
                        
                        # Multi-assignment fields
                        "co_assignees": [],
                        "co_assignees_names": [],
                        "is_multi_assigned": False,
                        
                        # Assignment history
                        "assignment_history": [{
                            "assigned_to": assigned_to,
                            "assigned_to_name": assigned_to_name,
                            "assigned_by": created_by,
                            "assignment_method": method,
                            "assigned_at": datetime.utcnow(),
                            "reason": f"Bulk creation ({assignment_method})",
                            "bulk_index": i,
                            "selected_users_pool": selected_user_emails if assignment_method == "selected_users" else None,
                            "validated_course_level": validated_course_level,
                            "validated_source": validated_source,
                            "lead_id_format": "category_source_combination"
                        }],
                        
                        # Additional info
                        "notes": lead_data.get("notes", ""),
                        "created_by": created_by,
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                        
                        # WhatsApp fields
                        "last_whatsapp_activity": None,
                        "last_whatsapp_message": None,
                        "whatsapp_message_count": 0,
                        "unread_whatsapp_count": 0
                    }
                    
                    # Insert lead into database
                    result = await db.leads.insert_one(lead_doc)
                    
                    if result.inserted_id:
                        # Update user array if assigned
                        if assigned_to:
                            await user_lead_array_service.add_lead_to_user_array(assigned_to, lead_id)
                        
                        # 🔥 UPDATED: Send unified notification for bulk lead assignment
                        if assigned_to and assigned_to_name:
                            try:
                                from ..services.realtime_service import realtime_manager
                                
                                notification_data = {
                                    "lead_name": lead_data.get("name", ""),
                                    "lead_email": lead_data.get("email", ""),
                                    "lead_phone": lead_data.get("contact_number", ""),
                                    "category": lead_data.get("category", "General"),
                                    "source": validated_source,
                                    "assignment_method": method,
                                    "bulk_creation": True,
                                    "bulk_index": i
                                }
                                
                                authorized_users = [{"email": assigned_to, "name": assigned_to_name}]
                                
                                # ONE call creates notification for assigned user + admins automatically
                                await realtime_manager.notify_lead_assigned(lead_id, notification_data, authorized_users)
                                
                                logger.info(f"✅ Unified bulk lead notification created for {assigned_to} (lead {lead_id})")
                            except Exception as notif_error:
                                logger.warning(f"⚠️ Failed to send bulk lead assignment notification: {notif_error}")
                        
                        # Timeline Activity Logging
                        try:
                            existing_activity = await db.lead_activities.find_one({
                                "lead_id": lead_id,
                                "activity_type": "lead_created"
                            })
                            
                            if not existing_activity:
                                if assigned_to and assigned_to_name:
                                    description = f"Lead created by {created_by_name} and assigned to {assigned_to_name} (Bulk upload)"
                                else:
                                    description = f"Lead created by {created_by_name} (Bulk upload, unassigned)"
                                
                                activity_doc = {
                                    "lead_id": lead_id,
                                    "activity_type": "lead_created",
                                    "description": description,
                                    "created_by": ObjectId(created_by),
                                    "created_by_name": created_by_name,
                                    "created_at": datetime.utcnow(),
                                    "updated_at": datetime.utcnow(),
                                    "is_system_generated": True,
                                    "metadata": {
                                        "lead_id": lead_id,
                                        "lead_name": lead_data.get("name", ""),
                                        "assigned_to": assigned_to,
                                        "assigned_to_name": assigned_to_name,
                                        "assignment_method": method,
                                        "bulk_creation": True,
                                        "bulk_index": i,
                                        "category": lead_data.get("category", "General"),
                                        "source": validated_source
                                    }
                                }
                                
                                await db.lead_activities.insert_one(activity_doc)
                                logger.info(f"✅ Timeline 'lead_created' logged for bulk lead {lead_id} by {created_by_name}")
                            
                        except Exception as activity_error:
                            logger.warning(f"⚠️ Failed to log timeline activity for bulk lead {lead_id}: {activity_error}")
                        
                        created_leads.append(lead_id)
                        assignment_summary.append({
                            "lead_id": lead_id,
                            "assigned_to": assigned_to,
                            "validated_course_level": validated_course_level,
                            "validated_source": validated_source,
                            "lead_id_format": "category_source_combination",
                            "status": "success"
                        })
                        
                        logger.info(f"✅ Successfully created lead {lead_id} (index {i})")
                    else:
                        failed_leads.append({
                            "index": i,
                            "data": lead_data,
                            "error": "Failed to insert to database"
                        })
                        assignment_summary.append({
                            "lead_id": None,
                            "assigned_to": None,
                            "status": "failed",
                            "error": "Database insertion failed"
                        })
                        logger.error(f"❌ Failed to insert lead at index {i}")
                    
                except Exception as e:
                    logger.error(f"❌ Error creating lead at index {i}: {str(e)}")
                    failed_leads.append({
                        "index": i,
                        "data": lead_data,
                        "error": str(e)
                    })
                    assignment_summary.append({
                        "lead_id": None,
                        "assigned_to": None,
                        "status": "failed",
                        "error": str(e)
                    })
            
            # Final summary
            total_processed = len(leads_data)
            successfully_created = len(created_leads)
            duplicates_count = len(duplicates_skipped)
            failed_count = len(failed_leads)
            
            logger.info(f"🏁 Bulk creation completed:")
            logger.info(f"   📊 Total processed: {total_processed}")
            logger.info(f"   ✅ Successfully created: {successfully_created}")
            logger.info(f"   ⚠️ Duplicates skipped: {duplicates_count}")
            logger.info(f"   ❌ Failed: {failed_count}")
            
            return {
                "success": failed_count == 0,
                "message": f"Bulk creation completed: {successfully_created} created, {duplicates_count} duplicates skipped, {failed_count} failed",
                "total_processed": total_processed,
                "successfully_created": successfully_created,
                "failed_count": failed_count,
                "duplicates_skipped": duplicates_count,
                "created_lead_ids": created_leads,
                "failed_leads": failed_leads,
                "duplicate_leads": duplicates_skipped,
                "assignment_method": assignment_method,
                "selected_users": selected_user_emails if assignment_method == "selected_users" else None,
                "assignment_summary": assignment_summary,
                "lead_id_format": "category_source_combination"
            }
            
        except Exception as e:
            logger.error(f"❌ Critical error in bulk lead creation: {str(e)}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
                "total_processed": len(leads_data),
                "successfully_created": 0,
                "failed_count": len(leads_data),
                "duplicates_skipped": 0
            }
    async def get_lead_id_format_statistics(self) -> Dict[str, Any]:
        """Get statistics about lead ID formats and combinations"""
        try:
            # Get combination statistics from lead_category_service
            combination_stats = await lead_category_service.get_combination_statistics()
            
            db = self.get_db()
            
            # Get total leads count
            total_leads = await db.leads.count_documents({})
            
            # Count leads by ID format (if we track this in assignment_history)
            format_pipeline = [
                {"$unwind": "$assignment_history"},
                {
                    "$group": {
                        "_id": "$assignment_history.lead_id_format",
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            format_distribution = await db.leads.aggregate(format_pipeline).to_list(None)
            
            # Get top category-source combinations
            top_combinations_pipeline = [
                {
                    "$group": {
                        "_id": {
                            "category": "$category",
                            "source": "$source"
                        },
                        "count": {"$sum": 1},
                        "latest_lead": {"$max": "$created_at"}
                    }
                },
                {"$sort": {"count": -1}},
                {"$limit": 10}
            ]
            
            top_combinations = await db.leads.aggregate(top_combinations_pipeline).to_list(None)
            
            return {
                "total_leads": total_leads,
                "combination_statistics": combination_stats,
                "format_distribution": format_distribution,
                "top_combinations": top_combinations,
                "generated_at": datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error getting lead ID format statistics: {str(e)}")
            return {"error": str(e)}

    # ============================================================================
    # 🔄 UPDATED: LEGACY METHODS (KEEPING BACKWARD COMPATIBILITY)
    # ============================================================================
    
    async def generate_lead_id_by_category(self, category: str) -> str:
        """🔄 UPDATED: Legacy method now logs deprecation warning"""
        logger.warning(f"Using legacy lead ID generation for category: {category}. Consider using generate_lead_id_by_category_and_source() for new format.")
        try:
            db = self.get_db()
            
            # Get category short form
            category_short = await self.get_category_short_form(category)
            
            # Get the next sequence number for this category
            result = await db.lead_counters.find_one_and_update(
                {"category": category_short},
                {"$inc": {"sequence": 1}},
                upsert=True,
                return_document=True
            )
            
            sequence = result["sequence"]
            lead_id = f"{category_short}-{sequence}"
            
            logger.info(f"Generated legacy lead ID: {lead_id} for category: {category}")
            return lead_id
            
        except Exception as e:
            logger.error(f"Error generating legacy lead ID: {str(e)}")
            # Fallback to simple sequence
            return await self._generate_lead_id()
    
    async def get_category_short_form(self, category: str) -> str:
        """Get short form for category from database"""
        try:
            db = self.get_db()
            
            # Look up category in database
            category_doc = await db.lead_categories.find_one({"name": category, "is_active": True})
            
            if category_doc and "short_form" in category_doc:
                # Return short form from database
                return category_doc["short_form"]
            
            # Log warning if category not found
            logger.warning(f"Category not found in database: {category}, using fallback 'LD'")
            return "LD"  # Fallback if not found
            
        except Exception as e:
            logger.error(f"Error getting category short form from database: {str(e)}")
            return "LD"  # Fallback in case of error

    async def _generate_lead_id(self) -> str:
        """Generate simple sequential lead ID"""
        try:
            db = self.get_db()
            
            # Get the next sequence number
            result = await db.lead_counters.find_one_and_update(
                {"_id": "lead_sequence"},
                {"$inc": {"sequence": 1}},
                upsert=True,
                return_document=True
            )
            
            sequence = result["sequence"]
            lead_id = f"LD-{sequence:04d}"
            
            return lead_id
            
        except Exception as e:
            logger.error(f"Error generating lead ID: {str(e)}")
            # Ultimate fallback
            import time
            return f"LD-{int(time.time())}"

    # ============================================================================
    # EXISTING METHODS FROM ORIGINAL FILE (KEEP ALL OF THESE)
    # ============================================================================
    
    async def get_course_level_statistics(self) -> Dict[str, int]:
        """Get statistics of leads by course level"""
        try:
            db = self.get_db()
            
            # Aggregate leads by course level
            pipeline = [
                {"$group": {
                    "_id": "$course_level",
                    "count": {"$sum": 1}
                }},
                {"$sort": {"count": -1}}
            ]
            
            results = await db.leads.aggregate(pipeline).to_list(None)
            
            # Convert to dictionary
            course_level_stats = {}
            for result in results:
                course_level_name = result["_id"] or "unspecified"
                course_level_stats[course_level_name] = result["count"]
            
            return course_level_stats
            
        except Exception as e:
            logger.error(f"Error getting course level statistics: {e}")
            return {}

    async def get_source_statistics(self) -> Dict[str, int]:
        """Get statistics of leads by source"""
        try:
            db = self.get_db()
            
            # Aggregate leads by source
            pipeline = [
                {"$group": {
                    "_id": "$source",
                    "count": {"$sum": 1}
                }},
                {"$sort": {"count": -1}}
            ]
            
            results = await db.leads.aggregate(pipeline).to_list(None)
            
            # Convert to dictionary
            source_stats = {}
            for result in results:
                source_name = result["_id"] or "unspecified"
                source_stats[source_name] = result["count"]
            
            return source_stats
            
        except Exception as e:
            logger.error(f"Error getting source statistics: {e}")
            return {}

    async def bulk_update_course_level(self, old_course_level: str, new_course_level: str, updated_by: str) -> Dict[str, Any]:
        """Update all leads from old course level to new course level"""
        try:
            db = self.get_db()
            
            # Validate new course level exists and is active
            new_course_level_doc = await db.course_levels.find_one({
                "name": new_course_level,
                "is_active": True
            })
            
            if not new_course_level_doc:
                raise ValueError(f"New course level '{new_course_level}' does not exist or is not active")
            
            # Update all leads with old course level
            result = await db.leads.update_many(
                {"course_level": old_course_level},
                {
                    "$set": {
                        "course_level": new_course_level,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"Updated {result.modified_count} leads from course level '{old_course_level}' to '{new_course_level}' by {updated_by}")
            
            return {
                "success": True,
                "message": f"Successfully updated {result.modified_count} leads",
                "updated_count": result.modified_count,
                "old_course_level": old_course_level,
                "new_course_level": new_course_level
            }
            
        except Exception as e:
            logger.error(f"Error in bulk course level update: {e}")
            raise Exception(f"Failed to bulk update course level: {str(e)}")

    async def bulk_update_source(self, old_source: str, new_source: str, updated_by: str) -> Dict[str, Any]:
        """Update all leads from old source to new source"""
        try:
            db = self.get_db()
            
            # Validate new source exists and is active
            new_source_doc = await db.sources.find_one({
                "name": new_source,
                "is_active": True
            })
            
            if not new_source_doc:
                raise ValueError(f"New source '{new_source}' does not exist or is not active")
            
            # Update all leads with old source
            result = await db.leads.update_many(
                {"source": old_source},
                {
                    "$set": {
                        "source": new_source,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"Updated {result.modified_count} leads from source '{old_source}' to '{new_source}' by {updated_by}")
            
            return {
                "success": True,
                "message": f"Successfully updated {result.modified_count} leads",
                "updated_count": result.modified_count,
                "old_source": old_source,
                "new_source": new_source
            }
            
        except Exception as e:
            logger.error(f"Error in bulk source update: {e}")
            raise Exception(f"Failed to bulk update source: {str(e)}")

    async def get_leads_by_user_including_co_assignments(
        self, 
        user_email: str, 
        page: int = 1, 
        limit: int = 20,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Get all leads where user is assigned (primary or co-assignee)"""
        db = self.get_db()
        
        try:
            # Build query to include both primary and co-assignments
            base_query = {
                "$or": [
                    {"assigned_to": user_email},
                    {"co_assignees": user_email}
                ]
            }
            
            # Add additional filters if provided
            if filters:
                base_query.update(filters)
            
            # Get total count
            total_count = await db.leads.count_documents(base_query)
            
            # Get leads with pagination
            skip = (page - 1) * limit
            leads = await db.leads.find(base_query).skip(skip).limit(limit).sort("created_at", -1).to_list(None)
            
            # Convert ObjectId to string for JSON serialization
            for lead in leads:
                if "_id" in lead:
                    lead["_id"] = str(lead["_id"])
            
            return {
                "success": True,
                "leads": leads,
                "total_count": total_count,
                "page": page,
                "limit": limit,
                "total_pages": (total_count + limit - 1) // limit,
                "user_email": user_email
            }
            
        except Exception as e:
            logger.error(f"Error getting leads for user {user_email}: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "leads": [],
                "total_count": 0
            }
    
    async def get_multi_assigned_leads_stats(self) -> Dict[str, Any]:
        """Get statistics about multi-assigned leads"""
        db = self.get_db()
        
        try:
            # Count multi-assigned leads
            multi_assigned_count = await db.leads.count_documents({"is_multi_assigned": True})
            
            # Count single-assigned leads
            single_assigned_count = await db.leads.count_documents({
                "assigned_to": {"$ne": None},
                "is_multi_assigned": {"$ne": True}
            })
            
            # Count unassigned leads
            unassigned_count = await db.leads.count_documents({"assigned_to": None})
            
            # Get distribution of team sizes for multi-assigned leads
            pipeline = [
                {"$match": {"is_multi_assigned": True}},
                {
                    "$addFields": {
                        "team_size": {
                            "$add": [
                                1,  # Primary assignee
                                {"$size": {"$ifNull": ["$co_assignees", []]}}  # Co-assignees
                            ]
                        }
                    }
                },
                {
                    "$group": {
                        "_id": "$team_size",
                        "count": {"$sum": 1}
                    }
                },
                {"$sort": {"_id": 1}}
            ]
            
            team_size_distribution = await db.leads.aggregate(pipeline).to_list(None)
            
            # Get most active co-assignees
            pipeline = [
                {"$match": {"co_assignees": {"$exists": True, "$ne": []}}},
                {"$unwind": "$co_assignees"},
                {
                    "$group": {
                        "_id": "$co_assignees",
                        "co_assignment_count": {"$sum": 1}
                    }
                },
                {"$sort": {"co_assignment_count": -1}},
                {"$limit": 10}
            ]
            
            top_co_assignees = await db.leads.aggregate(pipeline).to_list(None)
            
            return {
                "total_leads": multi_assigned_count + single_assigned_count + unassigned_count,
                "multi_assigned_leads": multi_assigned_count,
                "single_assigned_leads": single_assigned_count,
                "unassigned_leads": unassigned_count,
                "multi_assignment_percentage": round((multi_assigned_count / (multi_assigned_count + single_assigned_count + unassigned_count)) * 100, 2) if (multi_assigned_count + single_assigned_count + unassigned_count) > 0 else 0,
                "team_size_distribution": team_size_distribution,
                "top_co_assignees": top_co_assignees
            }
            
        except Exception as e:
            logger.error(f"Error getting multi-assignment stats: {str(e)}")
            return {"error": str(e)}
    
    async def check_duplicate_lead(self, email: str, contact_number: str = None) -> Dict[str, Any]:
        """Check if lead with email OR phone already exists"""
        try:
            db = self.get_db()
            
            # Normalize inputs
            email_lower = email.lower().strip() if email else None
            phone_normalized = self._normalize_phone_number(contact_number) if contact_number else None
            
            # Check for email duplicate
            if email_lower:
                email_duplicate = await db.leads.find_one({"email": email_lower})
                if email_duplicate:
                    return {
                        "is_duplicate": True,
                        "checked": True,
                        "existing_lead_id": email_duplicate.get("lead_id"),
                        "duplicate_field": "email",
                        "duplicate_value": email,
                        "existing_lead_name": email_duplicate.get("name", "Unknown"),
                        "existing_lead_phone": email_duplicate.get("contact_number", ""),
                        "message": f"Lead with email '{email}' already exists (Lead ID: {email_duplicate.get('lead_id')})"
                    }
            
            # Check for phone duplicate
            if phone_normalized:
                phone_duplicate = await db.leads.find_one({
                    "$or": [
                        {"contact_number": phone_normalized},
                        {"phone_number": phone_normalized}
                    ]
                })
                if phone_duplicate:
                    return {
                        "is_duplicate": True,
                        "checked": True,
                        "existing_lead_id": phone_duplicate.get("lead_id"),
                        "duplicate_field": "phone",
                        "duplicate_value": contact_number,
                        "existing_lead_name": phone_duplicate.get("name", "Unknown"),
                        "existing_lead_email": phone_duplicate.get("email", ""),
                        "message": f"Lead with phone '{contact_number}' already exists (Lead ID: {phone_duplicate.get('lead_id')})"
                    }
            
            # No duplicates found
            return {
                "is_duplicate": False,
                "checked": True,
                "message": "No duplicates found - both email and phone are unique"
            }
            
        except Exception as e:
            logger.error(f"Error checking duplicate: {str(e)}")
            return {
                "is_duplicate": False,
                "checked": False,
                "error": True,
                "message": f"Error checking duplicate: {str(e)}"
            }
        
    def _normalize_phone_number(self, phone: str) -> str:
            """Normalize phone number for consistent duplicate checking"""
            if not phone:
                return None
                
            # Remove all non-digit characters except +
            normalized = ''.join(c for c in phone if c.isdigit() or c == '+')

            # Remove leading + for comparison
            if normalized.startswith('+'):
                normalized = normalized[1:]
            
            return normalized if len(normalized) >= 10 else None

    async def log_lead_activity(
        self,
        lead_id: str,
        activity_type: str,
        description: str,
        created_by: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log activity for a lead"""
        try:
            db = self.get_db()
            
            # Get lead document to get ObjectId
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                logger.error(f"Lead {lead_id} not found for activity logging")
                return
            
            activity_doc = {
                "lead_object_id": lead["_id"],
                "lead_id": lead_id,
                "activity_type": activity_type,
                "description": description,
                "created_by": ObjectId(created_by) if ObjectId.is_valid(created_by) else created_by,
                "created_at": datetime.utcnow(),
                "is_system_generated": True,
                "metadata": metadata or {}
            }
            
            await db.lead_activities.insert_one(activity_doc)
            logger.info(f"✅ Activity logged: {activity_type} for lead {lead_id}")
            
        except Exception as e:
            logger.error(f"Error logging activity: {str(e)}")
    
    async def get_lead_by_id(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """Get a single lead by ID"""
        try:
            db = self.get_db()
            lead = await db.leads.find_one({"lead_id": lead_id})
            
            if lead:
                # Convert ObjectId to string
                if "_id" in lead:
                    lead["_id"] = str(lead["_id"])
                return lead
            return None
            
        except Exception as e:
            logger.error(f"Error getting lead {lead_id}: {str(e)}")
            return None
    async def update_lead(
    self,
    lead_id: str,
    update_data: Dict[str, Any],
    user_data: Dict[str, Any]  # 🔄 CHANGED: was updated_by (str)
) -> Dict[str, Any]:
        """
        🔄 UPDATED: Update a lead with RBAC permission check, activity logging and dynamic field validation
        
        **Changes from original:**
        - Parameter changed from `updated_by: str` to `user_data: Dict[str, Any]`
        - Added RBAC permission check at the beginning
        - Returns access denied error if user doesn't have permission
        - All other logic remains the same
        """
        try:
            db = self.get_db()
            
            # ============================================================================
            # 🆕 RBAC: CHECK PERMISSION BEFORE UPDATE
            # ============================================================================
            can_access, reason = await self.can_user_access_lead(
                user_data=user_data,
                lead_id=lead_id,
                required_permission="leads.update",
                db=db
            )
            
            if not can_access:
                logger.warning(f"⚠️ Update denied for lead {lead_id}: {reason}")
                return {
                    "success": False,
                    "error": f"Access denied: {reason}",
                    "permission_required": "leads.update"
                }
            
            logger.info(f"✅ Permission check passed for lead {lead_id} update by {user_data.get('email')}")
            
            # ============================================================================
            # ORIGINAL LOGIC STARTS HERE (UNCHANGED)
            # ============================================================================
            
            # Validate dynamic fields if being updated
            if "course_level" in update_data:
                validated_course_level = await self.validate_and_set_course_level(update_data["course_level"])
                update_data["course_level"] = validated_course_level
            
            if "source" in update_data:
                validated_source = await self.validate_and_set_source(update_data["source"])
                update_data["source"] = validated_source
            
            # Add updated timestamp
            update_data["updated_at"] = datetime.utcnow()
            
            # Update the lead
            result = await db.leads.update_one(
                {"lead_id": lead_id},
                {"$set": update_data}
            )
            
            if result.modified_count > 0:
                # Log activity (using user_data instead of updated_by)
                await self.log_lead_activity(
                    lead_id=lead_id,
                    activity_type="lead_updated",
                    description="Lead information updated",
                    created_by=str(user_data.get("_id")),  # 🔄 CHANGED: was updated_by
                    metadata={
                        "updated_fields": list(update_data.keys()),
                        "updated_by_email": user_data.get("email")  # 🆕 NEW: added for audit
                    }
                )
                
                # Get updated lead
                updated_lead = await db.leads.find_one({"lead_id": lead_id})
                if updated_lead and "_id" in updated_lead:
                    updated_lead["_id"] = str(updated_lead["_id"])
                
                logger.info(f"✅ Lead {lead_id} updated successfully by {user_data.get('email')}")
                
                return {
                    "success": True,
                    "lead": updated_lead,
                    "message": "Lead updated successfully"
                }
            else:
                return {
                    "success": False,
                    "message": "Lead not found or no changes made"
                }
                
        except Exception as e:
            logger.error(f"❌ Error updating lead {lead_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }


    async def delete_lead(
        self,
        lead_id: str,
        user_data: Dict[str, Any]  # 🔄 CHANGED: was deleted_by (str)
    ) -> Dict[str, Any]:
        """
        🔄 UPDATED: Delete a lead with RBAC permission check and activity logging
        
        **Changes from original:**
        - Parameter changed from `deleted_by: str` to `user_data: Dict[str, Any]`
        - Added RBAC permission check at the beginning
        - Returns access denied error if user doesn't have permission
        - All other logic remains the same
        """
        try:
            db = self.get_db()
            
            # ============================================================================
            # 🆕 RBAC: CHECK PERMISSION BEFORE DELETE
            # ============================================================================
            can_access, reason = await self.can_user_access_lead(
                user_data=user_data,
                lead_id=lead_id,
                required_permission="leads.delete",
                db=db
            )
            
            if not can_access:
                logger.warning(f"⚠️ Delete denied for lead {lead_id}: {reason}")
                return {
                    "success": False,
                    "error": f"Access denied: {reason}",
                    "permission_required": "leads.delete"
                }
            
            logger.info(f"✅ Permission check passed for lead {lead_id} deletion by {user_data.get('email')}")
            
            # ============================================================================
            # ORIGINAL LOGIC STARTS HERE (UNCHANGED)
            # ============================================================================
            
            # Get lead first for logging
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                return {
                    "success": False,
                    "message": "Lead not found"
                }
            
            # Remove from user arrays if assigned
            if lead.get("assigned_to"):
                await user_lead_array_service.remove_lead_from_user_array(
                    lead.get("assigned_to"), lead_id
                )
            
            # Remove from co-assignees arrays
            for co_assignee in lead.get("co_assignees", []):
                await user_lead_array_service.remove_lead_from_user_array(
                    co_assignee, lead_id
                )
            
            # Log activity before deletion (using user_data instead of deleted_by)
            await self.log_lead_activity(
                lead_id=lead_id,
                activity_type="lead_deleted",
                description=f"Lead {lead_id} deleted",
                created_by=str(user_data.get("_id")),  # 🔄 CHANGED: was deleted_by
                metadata={
                    "lead_name": lead.get("name"),
                    "lead_email": lead.get("email"),
                    "was_assigned_to": lead.get("assigned_to"),
                    "had_co_assignees": lead.get("co_assignees", []),
                    "deleted_by_email": user_data.get("email")  # 🆕 NEW: added for audit
                }
            )
            
            # Delete the lead
            result = await db.leads.delete_one({"lead_id": lead_id})
            
            if result.deleted_count > 0:
                logger.info(f"✅ Lead {lead_id} deleted successfully by {user_data.get('email')}")
                return {
                    "success": True,
                    "message": f"Lead {lead_id} deleted successfully"
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to delete lead"
                }
                
        except Exception as e:
            logger.error(f"❌ Error deleting lead {lead_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_leads_with_filters(
        self,
        user_data: Dict[str, Any],  # 🔄 CHANGED: was user_email + user_role
        page: int = 1,
        limit: int = 20,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        🔄 UPDATED: Get leads with RBAC filtering and pagination
        """
        try:
            db = self.get_db()
            
            # 🆕 RBAC: Build access filter based on permissions
            access_filter = await self.build_access_filter_rbac(user_data, db)
            
            # Merge with additional filters
            if filters:
                base_query = {**access_filter, **filters}
            else:
                base_query = access_filter
            
            # Get total count
            total_count = await db.leads.count_documents(base_query)
            
            # Get leads with pagination
            skip = (page - 1) * limit
            leads = await db.leads.find(base_query).skip(skip).limit(limit).sort("created_at", -1).to_list(None)
            
            # Format leads for response
            formatted_leads = []
            for lead in leads:
                formatted_lead = self.format_lead_response(lead)
                formatted_leads.append(formatted_lead)
            
            return {
                "success": True,
                "leads": formatted_leads,
                "total_count": total_count,
                "page": page,
                "limit": limit,
                "total_pages": (total_count + limit - 1) // limit,
                "filters_applied": filters or {},
                "user_email": user_data.get("email"),
                "access_level": self._get_access_level_name(user_data)  # 🆕 NEW
            }
            
        except Exception as e:
            logger.error(f"Error getting leads with filters: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "leads": [],
                "total_count": 0
            }
    async def get_lead_statistics(
    self,
    user_data: Dict[str, Any]  # 🔄 CHANGED: was user_email + user_role
) -> Dict[str, Any]:
        """
        🔄 UPDATED: Get lead statistics with RBAC filtering
        """
        try:
            db = self.get_db()
            
            # 🆕 RBAC: Build access filter
            base_query = await self.build_access_filter_rbac(user_data, db)
            
            # Get total leads
            total_leads = await db.leads.count_documents(base_query)
            
            # Get status distribution
            status_pipeline = [
                {"$match": base_query},
                {
                    "$group": {
                        "_id": "$status",
                        "count": {"$sum": 1}
                    }
                }
            ]
            status_distribution = await db.leads.aggregate(status_pipeline).to_list(None)
            
            # Get course level distribution
            course_level_pipeline = [
                {"$match": base_query},
                {
                    "$group": {
                        "_id": "$course_level",
                        "count": {"$sum": 1}
                    }
                }
            ]
            course_level_distribution = await db.leads.aggregate(course_level_pipeline).to_list(None)
            
            # Get source distribution
            source_pipeline = [
                {"$match": base_query},
                {
                    "$group": {
                        "_id": "$source",
                        "count": {"$sum": 1}
                    }
                }
            ]
            source_distribution = await db.leads.aggregate(source_pipeline).to_list(None)
            
            # Get assignment statistics (if has permission)
            assignment_stats = {}
            if "leads.read_all" in user_data.get("effective_permissions", []) or user_data.get("is_super_admin"):
                multi_assigned_count = await db.leads.count_documents({**base_query, "is_multi_assigned": True})
                single_assigned_count = await db.leads.count_documents({
                    **base_query,
                    "assigned_to": {"$ne": None},
                    "is_multi_assigned": {"$ne": True}
                })
                unassigned_count = await db.leads.count_documents({**base_query, "assigned_to": None})
                
                assignment_stats = {
                    "multi_assigned": multi_assigned_count,
                    "single_assigned": single_assigned_count,
                    "unassigned": unassigned_count
                }
            
            return {
                "total_leads": total_leads,
                "status_distribution": status_distribution,
                "course_level_distribution": course_level_distribution,
                "source_distribution": source_distribution,
                "assignment_statistics": assignment_stats,
                "user_email": user_data.get("email"),
                "access_level": self._get_access_level_name(user_data)
            }
            
        except Exception as e:
            logger.error(f"Error getting lead statistics: {str(e)}")
            return {"error": str(e)}
    async def search_leads(
    self,
    search_term: str,
    user_data: Dict[str, Any],  # 🔄 CHANGED: was user_email + user_role
    page: int = 1,
    limit: int = 20
) -> Dict[str, Any]:
        """
        🔄 UPDATED: Search leads with RBAC filtering
        """
        try:
            db = self.get_db()
            
            # Build search query
            search_query = {
                "$or": [
                    {"name": {"$regex": search_term, "$options": "i"}},
                    {"email": {"$regex": search_term, "$options": "i"}},
                    {"lead_id": {"$regex": search_term, "$options": "i"}},
                    {"contact_number": {"$regex": search_term, "$options": "i"}}
                ]
            }
            
            # 🆕 RBAC: Add access filter
            access_filter = await self.build_access_filter_rbac(user_data, db)
            
            # Combine search and access filters
            combined_query = {
                "$and": [
                    search_query,
                    access_filter
                ]
            } if access_filter else search_query
            
            # Get total count
            total_count = await db.leads.count_documents(combined_query)
            
            # Get leads with pagination
            skip = (page - 1) * limit
            leads = await db.leads.find(combined_query).skip(skip).limit(limit).sort("created_at", -1).to_list(None)
            
            # Format leads for response
            formatted_leads = []
            for lead in leads:
                formatted_lead = self.format_lead_response(lead)
                formatted_leads.append(formatted_lead)
            
            return {
                "success": True,
                "leads": formatted_leads,
                "total_count": total_count,
                "page": page,
                "limit": limit,
                "total_pages": (total_count + limit - 1) // limit,
                "search_term": search_term,
                "user_email": user_data.get("email"),
                "access_level": self._get_access_level_name(user_data)
            }
            
        except Exception as e:
            logger.error(f"Error searching leads: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "leads": [],
                "total_count": 0
            }


    # ADD THESE METHODS TO YOUR EXISTING app/services/lead_service.py

# ============================================================================
# 🆕 NEW: WHATSAPP INTEGRATION METHODS (Add these to LeadService class)
# ============================================================================

    async def update_lead_whatsapp_activity(
        self,
        lead_id: str,
        last_message: str,
        increment_total: bool = False,
        increment_unread: bool = False
    ) -> Dict[str, Any]:
        """Update lead's WhatsApp activity fields"""
        try:
            db = self.get_db()
            
            update_fields = {
                "last_whatsapp_activity": datetime.utcnow(),
                "last_whatsapp_message": last_message[:200] if last_message else None  # Preview only
            }
            
            # Handle counter increments
            inc_fields = {}
            if increment_total:
                inc_fields["whatsapp_message_count"] = 1
            if increment_unread:
                inc_fields["unread_whatsapp_count"] = 1
            
            # Build update query
            update_query = {"$set": update_fields}
            if inc_fields:
                update_query["$inc"] = inc_fields
            
            # Update lead
            result = await db.leads.update_one(
                {"lead_id": lead_id},
                update_query
            )
            
            if result.modified_count > 0:
                logger.info(f"Updated WhatsApp activity for lead {lead_id}")
                return {
                    "success": True,
                    "lead_id": lead_id,
                    "updated_fields": list(update_fields.keys()) + list(inc_fields.keys())
                }
            else:
                return {
                    "success": False,
                    "message": "Lead not found or no changes made"
                }
                
        except Exception as e:
            logger.error(f"Error updating WhatsApp activity for lead {lead_id}: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    async def increment_whatsapp_message_count(self, lead_id: str, count: int = 1) -> bool:
        """Increment WhatsApp message count for a lead"""
        try:
            db = self.get_db()
            
            result = await db.leads.update_one(
                {"lead_id": lead_id},
                {
                    "$inc": {"whatsapp_message_count": count},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Error incrementing WhatsApp message count for lead {lead_id}: {str(e)}")
            return False

    async def update_unread_whatsapp_count(self, lead_id: str, new_count: int) -> bool:
        """Set unread WhatsApp message count for a lead"""
        try:
            db = self.get_db()
            
            result = await db.leads.update_one(
                {"lead_id": lead_id},
                {
                    "$set": {
                        "unread_whatsapp_count": max(0, new_count),  # Ensure non-negative
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Error updating unread WhatsApp count for lead {lead_id}: {str(e)}")
            return False

    async def reset_unread_whatsapp_count(self, lead_id: str) -> bool:
        """Reset unread WhatsApp message count to 0"""
        return await self.update_unread_whatsapp_count(lead_id, 0)

    async def get_leads_with_whatsapp_activity(
        self,
        user_email: str,
        user_role: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Get leads that have WhatsApp activity (for active chats list)"""
        try:
            db = self.get_db()
            
            # Build base query for leads with WhatsApp activity
            base_query = {"whatsapp_message_count": {"$gt": 0}}
            
            # Add role-based filtering
            if user_role != "admin":
                base_query.update({
                    "$or": [
                        {"assigned_to": user_email},
                        {"co_assignees": user_email}
                    ]
                })
            
            # Get leads sorted by last WhatsApp activity
            leads = await db.leads.find(base_query).sort(
                "last_whatsapp_activity", -1
            ).limit(limit).to_list(length=limit)
            
            # Format leads for response
            formatted_leads = []
            for lead in leads:
                formatted_lead = {
                    "lead_id": lead["lead_id"],
                    "name": lead["name"],
                    "email": lead["email"],
                    "contact_number": lead.get("contact_number", ""),
                    "assigned_to": lead.get("assigned_to"),
                    "assigned_to_name": lead.get("assigned_to_name"),
                    "last_whatsapp_activity": lead.get("last_whatsapp_activity"),
                    "last_whatsapp_message": lead.get("last_whatsapp_message"),
                    "whatsapp_message_count": lead.get("whatsapp_message_count", 0),
                    "unread_whatsapp_count": lead.get("unread_whatsapp_count", 0)
                }
                formatted_leads.append(formatted_lead)
            
            return {
                "success": True,
                "leads": formatted_leads,
                "total_count": len(formatted_leads),
                "user_role": user_role
            }
            
        except Exception as e:
            logger.error(f"Error getting leads with WhatsApp activity: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "leads": []
            }

    async def get_whatsapp_statistics(
        self,
        user_email: str,
        user_role: str
    ) -> Dict[str, Any]:
        """Get WhatsApp usage statistics for leads"""
        try:
            db = self.get_db()
            
            # Build base query based on user role
            if user_role == "admin":
                base_query = {}
            else:
                base_query = {
                    "$or": [
                        {"assigned_to": user_email},
                        {"co_assignees": user_email}
                    ]
                }
            
            # Get leads with WhatsApp activity
            leads_with_whatsapp = await db.leads.count_documents({
                **base_query,
                "whatsapp_message_count": {"$gt": 0}
            })
            
            # Get total unread messages
            pipeline = [
                {"$match": base_query},
                {
                    "$group": {
                        "_id": None,
                        "total_unread": {"$sum": "$unread_whatsapp_count"},
                        "total_messages": {"$sum": "$whatsapp_message_count"}
                    }
                }
            ]
            
            stats_result = await db.leads.aggregate(pipeline).to_list(None)
            
            if stats_result:
                total_unread = stats_result[0].get("total_unread", 0)
                total_messages = stats_result[0].get("total_messages", 0)
            else:
                total_unread = 0
                total_messages = 0
            
            return {
                "leads_with_whatsapp": leads_with_whatsapp,
                "total_unread_messages": total_unread,
                "total_whatsapp_messages": total_messages,
                "user_role": user_role
            }
            
        except Exception as e:
            logger.error(f"Error getting WhatsApp statistics: {str(e)}")
            return {"error": str(e)}

    # ============================================================================
    # 🔄 UPDATE EXISTING METHOD: format_lead_response (Add WhatsApp fields)
    # ============================================================================

    # REPLACE your existing format_lead_response method with this updated version:
    def format_lead_response(self, lead_doc: Dict[str, Any]) -> Dict[str, Any]:
        """Format lead document for response with new fields, multi-assignment support, and WhatsApp tracking"""
        if not lead_doc:
            return None
            
        return {
            "id": str(lead_doc.get("_id", "")),
            "lead_id": lead_doc.get("lead_id", ""),
            "name": lead_doc.get("name", ""),
            "email": lead_doc.get("email", ""),
            "contact_number": lead_doc.get("contact_number", ""),
            "phone_number": lead_doc.get("phone_number", ""),
            "source": lead_doc.get("source"),  # Can be None if no sources exist
            "category": lead_doc.get("category", ""),
            
            # Include new optional fields in response
            "age": lead_doc.get("age"),
            "experience": lead_doc.get("experience"),
            "nationality": lead_doc.get("nationality"),
            "course_level": lead_doc.get("course_level"),  # Can be None if no course levels exist
            "date_of_birth": lead_doc.get("date_of_birth"),
            
            "status": lead_doc.get("status", "Initial"),
            "stage": lead_doc.get("stage", "Initial"),
            "lead_score": lead_doc.get("lead_score", 0),
            "priority": lead_doc.get("priority", "medium"),
            "tags": lead_doc.get("tags", []),
            
            # Assignment fields (single and multi)
            "assigned_to": lead_doc.get("assigned_to"),
            "assigned_to_name": lead_doc.get("assigned_to_name"),
            "assignment_method": lead_doc.get("assignment_method"),
            
            # Multi-assignment fields
            "co_assignees": lead_doc.get("co_assignees", []),
            "co_assignees_names": lead_doc.get("co_assignees_names", []),
            "is_multi_assigned": lead_doc.get("is_multi_assigned", False),
            
            "assignment_history": lead_doc.get("assignment_history", []),
            "notes": lead_doc.get("notes", ""),
            "created_by": lead_doc.get("created_by", ""),
            "created_at": lead_doc.get("created_at"),
            "updated_at": lead_doc.get("updated_at"),
            "last_contacted": lead_doc.get("last_contacted"),
            
            # Legacy fields for backward compatibility
            "country_of_interest": lead_doc.get("country_of_interest", ""),
            
            # 🆕 NEW: WhatsApp Activity Fields
            "last_whatsapp_activity": lead_doc.get("last_whatsapp_activity"),
            "last_whatsapp_message": lead_doc.get("last_whatsapp_message"),
            "whatsapp_message_count": lead_doc.get("whatsapp_message_count", 0),
            "unread_whatsapp_count": lead_doc.get("unread_whatsapp_count", 0)
        }


lead_service = LeadService()