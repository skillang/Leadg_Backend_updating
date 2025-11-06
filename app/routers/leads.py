# app/routers/leads.py - Complete Updated with Selective Round Robin & Multi-Assignment (CORRECTED)

from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, date
import logging
from bson import ObjectId
from ..services.whatsapp_message_service import whatsapp_message_service
from ..services.tata_call_service import tata_call_service
from app.decorators.timezone_decorator import convert_lead_dates, convert_dates_to_ist
from ..services.user_lead_array_service import user_lead_array_service
from ..services.lead_assignment_service import lead_assignment_service
from app.services import lead_category_service
from ..services.lead_category_service import lead_category_service
from ..config.database import get_database
from ..utils.dependencies import get_current_active_user, get_admin_user, get_user_with_single_lead_permission, get_user_with_bulk_lead_permission

# Updated imports with new models
from ..models.lead import (
    LeadCreate, 
    LeadUpdate, 
    LeadResponse, 
    LeadListResponse, 
    LeadAssign, 
  
    LeadBulkCreate, 
    LeadBulkCreateResponse,
    LeadCreateComprehensive,
    LeadsFilterRequest,
    LeadResponseComprehensive, 
    LeadStatusUpdate,
   
    ExperienceLevel,
    # New models for selective round robin and multi-assignment
    SelectiveRoundRobinRequest,
    MultiUserAssignmentRequest,
    RemoveFromAssignmentRequest,
    BulkAssignmentRequest,
    MultiUserAssignmentResponse,
    BulkAssignmentResponse,
    SelectiveRoundRobinResponse,
    LeadResponseExtended,
    UserSelectionResponse,
    UserSelectionOption,
    CallCountRefreshRequest,
    CallCountRefreshResponse,
    BulkCallCountRefreshRequest,
    BulkCallCountRefreshResponse,
     CallStatsModel,
)

# Check if these exist - if not, comment them out
from ..schemas.lead import (
    LeadCreateResponse, 
    LeadAssignResponse, 
    LeadBulkAssign, 
    LeadBulkAssignResponse, 
    LeadStatsResponse, 
    LeadFilterParams
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ============================================================================
# OBJECTID CONVERSION UTILITY
# ============================================================================

def convert_objectid_to_str(obj):
    """Recursively convert ObjectId to string in any data structure"""
    if isinstance(obj, ObjectId):
        return str(obj)
    elif isinstance(obj, dict):
        return {key: convert_objectid_to_str(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_objectid_to_str(item) for item in obj]
    else:
        return obj

# ============================================================================
# STATUS MIGRATION UTILITIES
# ============================================================================


DEFAULT_NEW_LEAD_STATUS = "Initial"


# ============================================================================
#  SELECTIVE ROUND ROBIN ENDPOINTS
# ============================================================================

@router.post("/assignment/bulk-assign-selective", response_model=BulkAssignmentResponse)
async def bulk_assign_leads_selective(
    request: BulkAssignmentRequest,
    current_user: dict = Depends(get_admin_user)
):
    """Bulk assign leads using selective round robin or all users (Admin only)"""
    try:
        db = get_database()
        admin_email = current_user.get("email")
        
        # Validate lead IDs exist
        existing_leads = await db.leads.find(
            {"lead_id": {"$in": request.lead_ids}},
            {"lead_id": 1}
        ).to_list(None)
        
        existing_lead_ids = [lead["lead_id"] for lead in existing_leads]
        invalid_lead_ids = set(request.lead_ids) - set(existing_lead_ids)
        
        if invalid_lead_ids:
            logger.warning(f"Invalid lead IDs: {invalid_lead_ids}")
        
        assignment_summary = []
        failed_assignments = []
        successfully_assigned = 0
        
        # Process each valid lead
        for lead_id in existing_lead_ids:
            try:
                # Get next assignee based on method
                if request.assignment_method == "selected_users":
                    assignee = await lead_assignment_service.get_next_assignee_selective_round_robin(
                        request.selected_user_emails
                    )
                else:  # all_users
                    assignee = await lead_assignment_service.get_next_assignee_round_robin()
                
                if assignee:
                    # Assign the lead
                    success = await lead_assignment_service.assign_lead_to_user(
                        lead_id=lead_id,
                        user_email=assignee,
                        assigned_by=admin_email,
                        reason=f"Bulk assignment ({request.assignment_method})"
                    )
                    
                    if success:
                        assignment_summary.append({
                            "lead_id": lead_id,
                            "assigned_to": assignee,
                            "status": "success"
                        })
                        successfully_assigned += 1
                    else:
                        failed_assignments.append({
                            "lead_id": lead_id,
                            "error": "Failed to update lead assignment"
                        })
                        assignment_summary.append({
                            "lead_id": lead_id,
                            "assigned_to": None,
                            "status": "failed",
                            "error": "Assignment update failed"
                        })
                else:
                    failed_assignments.append({
                        "lead_id": lead_id,
                        "error": "No assignee available"
                    })
                    assignment_summary.append({
                        "lead_id": lead_id,
                        "assigned_to": None,
                        "status": "failed",
                        "error": "No assignee available"
                    })
            
            except Exception as e:
                logger.error(f"Error assigning lead {lead_id}: {str(e)}")
                failed_assignments.append({
                    "lead_id": lead_id,
                    "error": str(e)
                })
                assignment_summary.append({
                    "lead_id": lead_id,
                    "assigned_to": None,
                    "status": "failed",
                    "error": str(e)
                })
        
        # Add failed assignments for invalid lead IDs
        for invalid_id in invalid_lead_ids:
            failed_assignments.append({
                "lead_id": invalid_id,
                "error": "Lead ID not found"
            })
        
        return BulkAssignmentResponse(
            success=len(failed_assignments) == 0,
            message=f"Bulk assignment completed: {successfully_assigned}/{len(request.lead_ids)} successful",
            total_leads=len(request.lead_ids),
            successfully_assigned=successfully_assigned,
            failed_assignments=failed_assignments,
            assignment_method=request.assignment_method,
            selected_users=request.selected_user_emails if request.assignment_method == "selected_users" else None,
            assignment_summary=assignment_summary
        )
    
    except Exception as e:
        logger.error(f"Error in bulk selective assignment: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to perform bulk assignment: {str(e)}"
        )

@router.get("/leads/{lead_id}/assignments")
async def get_lead_assignment_details(
    lead_id: str,
    current_user: dict = Depends(get_current_active_user)
):
    """Get detailed assignment information for a lead"""
    try:
        db = get_database()
        
        # Get lead with assignment details
        lead = await db.leads.find_one({"lead_id": lead_id})
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lead {lead_id} not found"
            )
        
        # Check permissions
        user_role = current_user.get("role", "user")
        user_email = current_user.get("email")
        
        if user_role != "admin":
            # Check if user is assigned to this lead
            assigned_to = lead.get("assigned_to")
            co_assignees = lead.get("co_assignees", [])
            
            if user_email not in [assigned_to] + co_assignees:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to view this lead's assignment details"
                )
        
        # Prepare assignment details
        assignment_details = {
            "lead_id": lead_id,
            "assigned_to": lead.get("assigned_to"),
            "assigned_to_name": lead.get("assigned_to_name"),
            "co_assignees": lead.get("co_assignees", []),
            "co_assignees_names": lead.get("co_assignees_names", []),
            "is_multi_assigned": lead.get("is_multi_assigned", False),
            "assignment_method": lead.get("assignment_method"),
            "assignment_history": lead.get("assignment_history", []),
            "total_assignees": (1 if lead.get("assigned_to") else 0) + len(lead.get("co_assignees", []))
        }
        
        return convert_objectid_to_str(assignment_details)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting assignment details: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get assignment details: {str(e)}"
        )

# ============================================================================
#  USER SELECTION ENDPOINTS
# ============================================================================

@router.get("/users/assignable-with-details", response_model=UserSelectionResponse)
async def get_assignable_users_with_details(
    current_user: dict = Depends(get_admin_user)
):
    """Get all assignable users with their current lead counts and details (Admin only)"""
    try:
        db = get_database()
        
        # Get all active users with user role
        users = await db.users.find(
            {"role": "user", "is_active": True},
            {
                "email": 1,
                "first_name": 1,
                "last_name": 1,
                "total_assigned_leads": 1,
                "departments": 1,
                "is_active": 1
            }
        ).to_list(None)
        
        user_options = []
        for user in users:
            user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
            if not user_name:
                user_name = user.get('email', 'Unknown')
            
            user_options.append(UserSelectionOption(
                email=user["email"],
                name=user_name,
                current_lead_count=user.get("total_assigned_leads", 0),
                is_active=user.get("is_active", True),
                departments=user.get("departments", [])
            ))
        
        # Sort by lead count (ascending) for better load balancing
        user_options.sort(key=lambda x: x.current_lead_count)
        
        return UserSelectionResponse(
            total_users=len(user_options),
            users=user_options
        )
    
    except Exception as e:
        logger.error(f"Error getting assignable users: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get assignable users: {str(e)}"
        )

@router.get("/assignment/round-robin-preview")
async def preview_round_robin_assignment(
    selected_users: Optional[str] = Query(None, description="Comma-separated list of user emails for selective round robin"),
    current_user: dict = Depends(get_admin_user)
):
    """Preview next assignments in round robin without actually assigning (Admin only)"""
    try:
        selected_user_emails = None
        if selected_users:
            selected_user_emails = [email.strip() for email in selected_users.split(",") if email.strip()]
        
        # Get next few assignments
        preview_assignments = []
        for i in range(5):  # Preview next 5 assignments
            if selected_user_emails:
                next_user = await lead_assignment_service.get_next_assignee_selective_round_robin(
                    selected_user_emails
                )
            else:
                next_user = await lead_assignment_service.get_next_assignee_round_robin()
            
            preview_assignments.append({
                "position": i + 1,
                "would_assign_to": next_user
            })
        
        return {
            "assignment_method": "selected_users" if selected_user_emails else "all_users",
            "selected_users": selected_user_emails,
            "preview_assignments": preview_assignments,
            "note": "This is a preview - no actual assignments were made"
        }
    
    except Exception as e:
        logger.error(f"Error in round robin preview: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to preview round robin: {str(e)}"
        )

# ============================================================================
#  ENHANCED LEAD LISTING WITH MULTI-ASSIGNMENT INFO
# ============================================================================
@router.get("/leads-extended/", response_model=List[LeadResponseExtended])
async def get_leads_with_multi_assignment_info(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    include_multi_assigned: bool = Query(False, description="Filter for multi-assigned leads only"),
    assigned_to_user: Optional[str] = Query(None, description="Filter by user email (includes co-assignments)"),
    current_user: dict = Depends(get_current_active_user)
):
    """Get leads with extended multi-assignment information"""
    try:
        db = get_database()
        user_role = current_user.get("role", "user")
        user_email = current_user.get("email")
        
        # Build query filters
        query_filters = {}
        
        if user_role != "admin":
            # Regular users see leads where they are assigned (primary or co-assignee)
            query_filters["$or"] = [
                {"assigned_to": user_email},
                {"co_assignees": user_email}
            ]
        
        if include_multi_assigned:
            query_filters["is_multi_assigned"] = True
        
        if assigned_to_user:
            if user_role == "admin":  # Only admins can filter by other users
                # Fix: Handle existing query structure properly
                if "$or" in query_filters:
                    # Combine with existing conditions using $and
                    existing_or = query_filters.pop("$or")
                    query_filters = {
                        "$and": [
                            {"$or": existing_or},
                            {"$or": [
                                {"assigned_to": assigned_to_user},
                                {"co_assignees": assigned_to_user}
                            ]}
                        ]
                    }
                else:
                    query_filters["$or"] = [
                        {"assigned_to": assigned_to_user},
                        {"co_assignees": assigned_to_user}
                    ]
        
        # Get total count
        total_count = await db.leads.count_documents(query_filters)
        
        # Get leads with pagination
        skip = (page - 1) * limit
        leads = await db.leads.find(query_filters).skip(skip).limit(limit).to_list(None)
        
        # Convert to extended response format with proper processing
        extended_leads = []
        for lead in leads:
            try:
                # Process the lead through the standard processing function first
                processed_lead = await process_lead_for_response(lead, db, current_user)
                
                # Create the extended lead response
                extended_lead = LeadResponseExtended(
                    lead_id=processed_lead["lead_id"],
                    status=processed_lead.get("status", "Unknown"),
                    name=processed_lead.get("name", ""),
                    email=processed_lead.get("email", ""),
                    contact_number=processed_lead.get("contact_number"),
                    source=processed_lead.get("source"),  # This will now be correct after processing
                    category=processed_lead.get("category"),
                    assigned_to=processed_lead.get("assigned_to"),
                    assigned_to_name=processed_lead.get("assigned_to_name"),
                    co_assignees=processed_lead.get("co_assignees", []),
                    co_assignees_names=processed_lead.get("co_assignees_names", []),
                    is_multi_assigned=processed_lead.get("is_multi_assigned", False),
                    assignment_method=processed_lead.get("assignment_method"),
                    created_at=processed_lead.get("created_at", datetime.utcnow()),
                    updated_at=processed_lead.get("updated_at")
                )
                extended_leads.append(extended_lead)
            except Exception as lead_error:
                logger.error(f"Error processing lead {lead.get('lead_id', 'unknown')} in extended view: {lead_error}")
                # Create a minimal response for failed leads
                try:
                    extended_lead = LeadResponseExtended(
                        lead_id=lead.get("lead_id", "unknown"),
                        status=lead.get("status", "Unknown"),
                        name=lead.get("name", ""),
                        email=lead.get("email", ""),
                        contact_number=lead.get("contact_number", ""),
                        source=lead.get("source", "website"),  # Use default if processing failed
                        category=lead.get("category", ""),
                        assigned_to=lead.get("assigned_to"),
                        assigned_to_name=lead.get("assigned_to_name", "Unknown"),
                        co_assignees=lead.get("co_assignees", []),
                        co_assignees_names=lead.get("co_assignees_names", []),
                        is_multi_assigned=lead.get("is_multi_assigned", False),
                        assignment_method=lead.get("assignment_method"),
                        created_at=lead.get("created_at", datetime.utcnow()),
                        updated_at=lead.get("updated_at")
                    )
                    extended_leads.append(extended_lead)
                except Exception as fallback_error:
                    logger.error(f"Failed to create even minimal response for lead {lead.get('lead_id', 'unknown')}: {fallback_error}")
                    continue
        
        # Convert ObjectIds to strings for JSON serialization
        final_leads = convert_objectid_to_str(extended_leads)
        
        # Return with pagination metadata
        return {
            "leads": final_leads,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "total_pages": (total_count + limit - 1) // limit,
                "has_next": skip + limit < total_count,
                "has_prev": page > 1
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting extended leads: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get leads: {str(e)}"
        )


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

async def process_lead_for_response(lead: Dict[str, Any], db, current_user: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Process a lead document for API response with complete data transformation
    This function ensures all leads are properly formatted for Pydantic validation
    """
    try:
        # Basic field transformations
        lead["id"] = str(lead["_id"])
        lead["created_by"] = str(lead.get("created_by", ""))
        
       
        if not lead.get("status"):
            lead["status"] = DEFAULT_NEW_LEAD_STATUS
        
        
        if "lead_score" not in lead or lead["lead_score"] is None:
            lead["lead_score"] = 0
        elif not isinstance(lead["lead_score"], (int, float)):
            lead["lead_score"] = 0
        
        #  Handle new optional fields with proper defaults
        lead["age"] = lead.get("age")  # Keep None if not set
        lead["experience"] = lead.get("experience","")  # Keep None if not set
        lead["nationality"] = lead.get("nationality","")  # Keep None if not set
        lead["current_location"] = lead.get("current_location","")
        lead["date_of_birth"] = lead.get("date_of_birth","") 
        
        # Ensure all required fields have proper defaults
        required_defaults = {
            "tags": [],
            "contact_number": lead.get("phone_number", ""),
            "source": "website",
            "category": lead.get("category", ""),
        }
        
        for field, default_value in required_defaults.items():
            if field not in lead or lead[field] is None:
                lead[field] = default_value
        
        # Handle new multi-assignment fields
        lead["co_assignees"] = lead.get("co_assignees", [])
        lead["co_assignees_names"] = lead.get("co_assignees_names", [])
        lead["is_multi_assigned"] = lead.get("is_multi_assigned", False)
        
        # Fetch user info for created_by
        # FIXED CODE with ObjectId validation
        created_by = lead.get("created_by")
        user = None
        if created_by:
            if ObjectId.is_valid(created_by):
                # created_by is a valid ObjectId
                user = await db.users.find_one({"_id": ObjectId(created_by)})
            else:
                # created_by is likely an email address (legacy data)
                user = await db.users.find_one({"email": created_by})
        if user:
            full_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
            lead["created_by_name"] = full_name if full_name else user.get('email', 'Unknown User')
        else:
            lead["created_by_name"] = "Unknown User"
        
        # Fetch assigned user info
        if lead.get("assigned_to"):
            assigned_user = await db.users.find_one({"email": lead["assigned_to"]})
            if assigned_user:
                full_name = f"{assigned_user.get('first_name', '')} {assigned_user.get('last_name', '')}".strip()
                lead["assigned_to_name"] = full_name if full_name else assigned_user.get('email', 'Unknown')
            else:
                lead["assigned_to_name"] = lead["assigned_to"]
        
        # Fetch co-assignee names
        if lead.get("co_assignees"):
            co_assignee_names = []
            for email in lead["co_assignees"]:
                user = await db.users.find_one({"email": email})
                if user:
                    full_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                    co_assignee_names.append(full_name if full_name else email)
                else:
                    co_assignee_names.append(email)
            lead["co_assignees_names"] = co_assignee_names
        
        return lead
        
    except Exception as e:
        logger.error(f"Error processing lead {lead.get('lead_id', 'unknown')}: {e}")
        # Return lead with minimal processing to avoid complete failure
        lead["id"] = str(lead["_id"])
        # REMOVED: Automatic migration here too
        # lead["status"] = migrate_status_value(lead.get("status", DEFAULT_NEW_LEAD_STATUS))
        
        # Just use status as-is with default if empty
        if not lead.get("status"):
            lead["status"] = DEFAULT_NEW_LEAD_STATUS
            
        lead["lead_score"] = 0
        lead["created_by_name"] = "Unknown User"
        lead["assigned_to_name"] = "Unknown"
        lead["tags"] = []
        lead["contact_number"] = lead.get("phone_number", "")
        lead["source"] = "website"
        lead["category"] = lead.get("category", "")
        # Set defaults for new fields
        lead["age"] = lead.get("age")
        lead["experience"] = lead.get("experience","")
        lead["nationality"] = lead.get("nationality","")
        lead["date_of_birth"]=lead.get("date_of_birth")
        lead["current_location"] = lead.get("current_location","")
        # Set defaults for multi-assignment fields
        lead["co_assignees"] = lead.get("co_assignees", [])
        lead["co_assignees_names"] = lead.get("co_assignees_names", [])
        lead["is_multi_assigned"] = lead.get("is_multi_assigned", False)
        return lead
def transform_lead_to_structured_format(lead: Dict[str, Any]) -> Dict[str, Any]:
    """Transform flat lead document to structured comprehensive format"""
    # Clean ObjectIds first using our utility function
    clean_lead = convert_objectid_to_str(lead)
    
    # Transform to structured format
    structured_lead = {
        "basic_info": {
            "name": clean_lead.get("name", ""),
            "email": clean_lead.get("email", ""),
            "contact_number": clean_lead.get("contact_number", ""),
            "source": clean_lead.get("source", "website"),
            "country_of_interest": clean_lead.get("country_of_interest", ""),
            "course_level": clean_lead.get("course_level", ""),
            "category": clean_lead.get("category", ""),
            # Add new fields to structured format
            "age": clean_lead.get("age"),
            "experience": clean_lead.get("experience"),
            "nationality": clean_lead.get("nationality"),
            "date_of_birth": clean_lead.get("date_of_birth"),
            "current_location": clean_lead.get("current_location",""),
            "call_stats": clean_lead.get("call_stats"),
        },
        "status_and_tags": {
            "stage": clean_lead.get("stage", "initial"),
            "status":clean_lead.get("status"),
            "lead_score": clean_lead.get("lead_score", 0),
            "priority": clean_lead.get("priority", "medium"),
            "tags": clean_lead.get("tags", [])
        },
        "assignment": {
            "assigned_to": clean_lead.get("assigned_to"),
            "assigned_to_name": clean_lead.get("assigned_to_name"),
            "co_assignees": clean_lead.get("co_assignees", []),
            "co_assignees_names": clean_lead.get("co_assignees_names", []),
            "is_multi_assigned": clean_lead.get("is_multi_assigned", False),
            "assignment_method": clean_lead.get("assignment_method"),
            "assignment_history": clean_lead.get("assignment_history", [])
        },
        "additional_info": {
            "notes": clean_lead.get("notes", "")
        },
        "system_info": {
            "id": str(clean_lead["_id"]) if "_id" in clean_lead else clean_lead.get("id"),
            "lead_id": clean_lead.get("lead_id", ""),
            "status": clean_lead.get("status") or DEFAULT_NEW_LEAD_STATUS,
            "created_by": clean_lead.get("created_by", ""),
            "created_at": clean_lead.get("created_at"),
            "updated_at": clean_lead.get("updated_at"),
            "last_contacted": clean_lead.get("last_contacted")
        }
    }
    
    return structured_lead

def format_lead_response(lead_doc: dict) -> dict:
    """Format lead document for API response with new fields"""
    if not lead_doc:
        return None
        
    return {
        "id": str(lead_doc["_id"]),
        "lead_id": lead_doc["lead_id"],
        "name": lead_doc["name"],
        "email": lead_doc["email"],
        "phone_number": lead_doc.get("phone_number", ""),
        "contact_number": lead_doc.get("contact_number", ""),
        "country_of_interest": lead_doc.get("country_of_interest", ""),
        "course_level": lead_doc.get("course_level", ""),
        "source": lead_doc["source"],
        "category": lead_doc.get("category", ""),
        
        # Include new fields in response
        "age": lead_doc.get("age",""),
        "experience": lead_doc.get("experience",""),
        "nationality": lead_doc.get("nationality",""),
        "date_of_birth": lead_doc.get("birth_of_date"),
        "current_location": lead_doc.get("current_location",""),  #  Added current_location with default
        
        # Multi-assignment fields
        "co_assignees": lead_doc.get("co_assignees", []),
        "co_assignees_names": lead_doc.get("co_assignees_names", []),
        "is_multi_assigned": lead_doc.get("is_multi_assigned", False),
        
        "stage": lead_doc.get("stage", "initial"),
        "lead_score": lead_doc.get("lead_score", 0),
        "priority": lead_doc.get("priority", "medium"),
        "tags": lead_doc.get("tags", []),
        "status": lead_doc["status"],
        "assigned_to": lead_doc.get("assigned_to"),
        "assigned_to_name": lead_doc.get("assigned_to_name"),
        "assignment_method": lead_doc.get("assignment_method"),
        "assignment_history": lead_doc.get("assignment_history", []),
        "notes": lead_doc.get("notes"),
        "created_by": lead_doc["created_by"],
        "created_by_name": lead_doc.get("created_by_name", "Unknown"),
        "created_at": lead_doc["created_at"],
        "updated_at": lead_doc["updated_at"]
    }

def get_activity_type_for_field(field_key: str) -> str:
    """Get specific activity type based on field"""
    activity_mapping = {
        "status": "status_changed",
        "stage": "stage_changed", 
        "assigned_to": "lead_reassigned",
        "name": "contact_info_updated",
        "email": "contact_info_updated",
        "phone_number": "contact_info_updated",
        "contact_number": "contact_info_updated",
        "source": "source_updated",
        "category": "category_updated",
        "priority": "priority_updated",
        "lead_score": "lead_score_updated",
        "notes": "notes_updated",
        "country_of_interest": "preferences_updated",
        "course_level": "preferences_updated",
        # Activity types for new fields
        "age": "personal_info_updated",
        "experience": "personal_info_updated",
        "nationality": "personal_info_updated",
        "date_of_birth":"date_of_birth",
        "current_location": "personal_info_updated",
    }
    return activity_mapping.get(field_key, "field_updated")

def get_field_change_description(field_name: str, old_value: any, new_value: any) -> str:
    """Generate human-readable description for field changes"""
    # Handle None values
    old_display = old_value if old_value is not None else "None"
    new_display = new_value if new_value is not None else "None"
    
    # Special cases for different field types
    if field_name == "Assigned To":
        old_display = old_display or "Unassigned"
        new_display = new_display or "Unassigned"
        return f"Lead reassigned from '{old_display}' to '{new_display}'"
    elif field_name in ["Lead Score"]:
        return f"{field_name} updated from {old_display} to {new_display}"
    else:
        return f"{field_name} changed from '{old_display}' to '{new_display}'"

# ============================================================================
# CORE ENDPOINTS (UPDATED WITH NEW FEATURES)
# 🔄 UPDATED: MAIN LEAD CREATION ENDPOINT WITH NEW ID GENERATION
# ============================================================================

@router.post("/", status_code=status.HTTP_201_CREATED)
@convert_lead_dates()
async def create_lead(
    lead_data: dict,
    force_create: bool = Query(False, description="Create lead even if duplicates exist"),
    #  Support for selective round robin
    selected_user_emails: Optional[str] = Query(None, description="Comma-separated list of user emails for selective round robin"),
    current_user: Dict[str, Any] = Depends(get_user_with_single_lead_permission) 
):
    """
    🔄 UPDATED: Create a new lead with enhanced assignment options:
    -  Category-Source combination lead IDs (NS-WB-1, SA-SM-2, WA-RF-3, etc.)
    -  Selective round robin assignment
    -  AGE, EXPERIENCE, Nationality fields (optional)
    - Duplicate detection and prevention
    - Activity logging and user array updates
    """
    try:
        logger.info(f"Creating lead by admin: {current_user['email']}")
        
        # Parse selective round robin parameter
        selected_users = None
        if selected_user_emails:
            selected_users = [email.strip() for email in selected_user_emails.split(",") if email.strip()]
        
        # Step 1: Parse and validate incoming data
        if "basic_info" in lead_data:
            # Comprehensive format
            try:
                basic_info_data = lead_data.get("basic_info", {})
                status_and_tags_data = lead_data.get("status_and_tags", {})
                assignment_data = lead_data.get("assignment", {})
                additional_info_data = lead_data.get("additional_info", {})
                
                if not basic_info_data.get("category"):
                    raise HTTPException(
                        status_code=400,
                        detail="Category is required. Please select a valid lead category."
                    )
                
                #  Validate source is provided for new ID format
                if not basic_info_data.get("source"):
                    raise HTTPException(
                        status_code=400,
                        detail="Source is required. Please select a valid lead source."
                    )
                
                # Create structured data using the classes
                from ..models.lead import LeadCreateComprehensive, LeadBasicInfo, LeadStatusAndTags, LeadAssignmentInfo, LeadAdditionalInfo
                
                structured_lead_data = LeadCreateComprehensive(
                    basic_info=LeadBasicInfo(
                        name=basic_info_data.get("name", ""),
                        email=basic_info_data.get("email", ""),
                        contact_number=basic_info_data.get("contact_number", ""),
                        source=basic_info_data.get("source"),  # 🔄 UPDATED: Now required
                        category=basic_info_data.get("category"),
                        # Handle new optional fields
                        age=basic_info_data.get("age"),
                        experience=basic_info_data.get("experience"),
                        nationality=basic_info_data.get("nationality"),
                        current_location=basic_info_data.get("current_location"),
                        date_of_birth=basic_info_data.get("date_of_birth"),
                         call_stats=basic_info_data.get("call_stats") or CallStatsModel.create_default()
                    ),
                    status_and_tags=LeadStatusAndTags(
                        stage=status_and_tags_data.get("stage", "initial"),
                        status=status_and_tags_data.get("status", "init"),
                        lead_score=status_and_tags_data.get("lead_score", 0),
                        tags=status_and_tags_data.get("tags", [])
                    ) if status_and_tags_data else None,
                    assignment=LeadAssignmentInfo(
                        assigned_to=assignment_data.get("assigned_to")
                    ) if assignment_data else None,
                    additional_info=LeadAdditionalInfo(
                        notes=additional_info_data.get("notes")
                    ) if additional_info_data else None
                )
                
            except Exception as e:
                logger.error(f"Error parsing comprehensive lead data: {str(e)}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid lead data format: {str(e)}"
                )
        else:
            # Legacy flat format
            try:
                if not lead_data.get("category"):
                    raise HTTPException(
                        status_code=400,
                        detail="Category is required. Please select a valid lead category."
                    )
                
                #  Validate source is provided for new ID format
                if not lead_data.get("source"):
                    raise HTTPException(
                        status_code=400,
                        detail="Source is required. Please select a valid lead source."
                    )
                
                from ..models.lead import LeadCreateComprehensive, LeadBasicInfo, LeadStatusAndTags, LeadAdditionalInfo
                
                structured_lead_data = LeadCreateComprehensive(
                    basic_info=LeadBasicInfo(
                        name=lead_data.get("name", ""),
                        email=lead_data.get("email", ""),
                        contact_number=lead_data.get("contact_number", ""),
                        source=lead_data.get("source"),  # 🔄 UPDATED: Now required
                        category=lead_data.get("category"),
                        # Handle new optional fields in legacy format
                        age=lead_data.get("age"),
                        experience=lead_data.get("experience"),
                        nationality=lead_data.get("nationality"),
                        current_location=lead_data.get("current_location"),
                        date_of_birth=lead_data.get("date_of_birth"),
                        call_stats=lead_data.get("call_stats") or CallStatsModel.create_default()
                    ),
                    status_and_tags=LeadStatusAndTags(
                        stage=lead_data.get("stage", "initial"),
                        lead_score=lead_data.get("lead_score", 0),
                        status=lead_data.get("status", "init"),
                        tags=lead_data.get("tags", [])
                    ),
                    additional_info=LeadAdditionalInfo(
                        notes=lead_data.get("notes")
                    )
                )
                
            except Exception as e:
                logger.error(f"Error parsing legacy lead data: {str(e)}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid lead data format: {str(e)}"
                )
        
        # Step 2: Use the enhanced lead service with NEW ID generation
        from ..services.lead_service import lead_service
        
        # Use selective assignment if users are specified
        if selected_users and hasattr(lead_service, 'create_lead_with_selective_assignment'):
            result = await lead_service.create_lead_with_selective_assignment(
                basic_info=structured_lead_data.basic_info,
                status_and_tags=structured_lead_data.status_and_tags,
                assignment_info=structured_lead_data.assignment,
                additional_info=structured_lead_data.additional_info,
                created_by=str(current_user["_id"]),
                selected_user_emails=selected_users
            )
        else:
            # Use regular creation method with NEW ID generation
            result = await lead_service.create_lead_comprehensive(
                lead_data=structured_lead_data,
                created_by=str(current_user["_id"]),
                force_create=force_create
            )
        
        if not result["success"]:
            if result.get("duplicate_check", {}).get("is_duplicate"):
                duplicate_info = result["duplicate_check"]
                logger.warning(f"🚫 Duplicate detected: {duplicate_info.get('message', 'Duplicate found')}")
                
                # Provide detailed duplicate information
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "Duplicate lead detected",
                        "message": duplicate_info.get("message"),
                        "duplicate_field": duplicate_info.get("duplicate_field"),
                        "existing_lead_id": duplicate_info.get("existing_lead_id"),
                        "existing_lead_name": duplicate_info.get("existing_lead_name"),
                        "duplicate_value": duplicate_info.get("duplicate_value")
                    }
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=result["message"]
                )
        
        logger.info(f"✅ Lead created successfully: {result.get('lead_id', 'unknown')} with NEW format (category-source-number)")
        
        # Step 3: Return successful response with enhanced info
        return convert_objectid_to_str({
            "success": True,
            "message": result.get("message", "Lead created successfully"),
            "lead_id": result.get("lead_id"),
            "lead_id_format": "category_source_combination",  #  Track format used
            "assigned_to": result.get("assigned_to"),
            "assignment_method": result.get("assignment_method"),
            "selected_users_pool": selected_users,
            "lead_id_info": result.get("lead_id_info", {}),  #  ID generation details
            "duplicate_check": result.get("duplicate_check", {
                "is_duplicate": False,
                "checked": True
            })
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lead creation error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create lead: {str(e)}"
        )

@router.get("/")
@convert_lead_dates()  # <-- ADD THIS LINE
async def get_leads(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    lead_status: Optional[str] = Query(None),  # ✅ Changed from LeadStatus to str
    assigned_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    course_level: Optional[str] = Query(None),
    created_from: Optional[str] = Query(None),
    created_to: Optional[str] = Query(None),
    updated_from: Optional[str] = Query(None),     
    updated_to: Optional[str] = Query(None),       
    last_contacted_from: Optional[str] = Query(None),  
    last_contacted_to: Optional[str] = Query(None),    
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get leads with comprehensive filtering support

    Special values for assigned_to parameter (admin only):
    - "multi_assigned": Returns only leads with multiple assignees
    - "null": Returns only unassigned leads
    - "user@email.com": Returns leads assigned to specific user
    - Not provided or "all": Returns all leads (respects user role)
    """
    try:
        logger.info(f"Get leads requested by: {current_user.get('email')}")
        db = get_database()
        
        # Build query
        query = {}
        if current_user["role"] != "admin":
            query["$or"] = [
                {"assigned_to": current_user["email"]},
                {"co_assignees": {"$in": [current_user["email"]]}}
            ]
                
        #  Handle stage filter
        if stage:
            query["stage"] = stage
            
        #  Handle status filter (prefer new 'status' over old 'lead_status')
        if status:
            query["status"] = status
        elif lead_status:
            # Handle old parameter for backward compatibility
            possible_old_statuses = [k for k, v in OLD_TO_NEW_STATUS_MAPPING.items() if v == lead_status.value]
            status_conditions = [{"status": lead_status.value}]
            if possible_old_statuses:
                status_conditions.extend([{"status": old_status} for old_status in possible_old_statuses])
            query["$or"] = status_conditions
            
        #  Handle category filter
        if category:
            query["category"] = category
            
        #  Handle source filter
        if source:
            query["source"] = source
            
        #  Handle course_level filter
        if course_level:
            query["course_level"] = course_level
            
        #  Handle date range filter
        if created_from or created_to:
            date_query = {}
            if created_from:
                try:
                    date_query["$gte"] = datetime.fromisoformat(created_from)
                except ValueError:
                    pass  # Skip invalid date
            if created_to:
                try:
                    date_query["$lte"] = datetime.fromisoformat(created_to)
                except ValueError:
                    pass  # Skip invalid date
            if date_query:
                query["created_at"] = date_query

        # Handle assigned_to filter (admin only) - FIXED for unassigned leads
        if assigned_to and current_user["role"] == "admin":
            if assigned_to == "multi_assigned":
                # Filter for multi-assigned leads only
                query["is_multi_assigned"] = True
            elif assigned_to.lower() in ["null", "none", "unassigned"]:
                # Filter for unassigned leads
                if "$or" in query:
                    query = {"$and": [{"assigned_to": None}, {"$or": query["$or"]}]}
                else:
                    query["assigned_to"] = None
            else:
                # Filter for specific user
                if "$or" in query:
                    query = {"$and": [{"assigned_to": assigned_to}, {"$or": query["$or"]}]}
                else:
                    query["assigned_to"] = assigned_to
        
        # Handle updated_at date range
        if updated_from or updated_to:
            date_query = {}
            if updated_from:
                date_query["$gte"] = datetime.fromisoformat(updated_from)
            if updated_to:
                # Add end of day to include full day
                end_date = datetime.fromisoformat(updated_to)
                if updated_to == updated_from:  # Same day filter
                    end_date = end_date.replace(hour=23, minute=59, second=59)
                date_query["$lte"] = end_date
            if date_query:
                query["updated_at"] = date_query

        # Handle last_contacted date range  
        if last_contacted_from or last_contacted_to:
            date_query = {}
            if last_contacted_from:
                date_query["$gte"] = datetime.fromisoformat(last_contacted_from)
            if last_contacted_to:
                date_query["$lte"] = datetime.fromisoformat(last_contacted_to)
            if date_query:
                query["last_contacted"] = date_query
        
        # Handle search
        if search:
            search_condition = {
                "$or": [
                    {"name": {"$regex": search, "$options": "i"}},
                    {"email": {"$regex": search, "$options": "i"}},
                    {"lead_id": {"$regex": search, "$options": "i"}},
                    {"contact_number": {"$regex": search, "$options": "i"}},
                    {"phone_number": {"$regex": search, "$options": "i"}}
                ]
            }
            if "$and" in query:
                query["$and"].append(search_condition)
            elif "$or" in query:
                query = {"$and": [{"$or": query["$or"]}, search_condition]}
            else:
                query.update(search_condition)
        
        logger.info(f"Final query: {query}")  # 🔍 Debug log
        
        total = await db.leads.count_documents(query)
        skip = (page - 1) * limit
        
        leads = await db.leads.find(query).skip(skip).limit(limit).sort("created_at", -1).to_list(None)
        
        # Process leads with migration support
        processed_leads = []
        for lead in leads:
            try:
                processed_lead = await process_lead_for_response(lead, db, current_user)
                processed_leads.append(processed_lead)
            except Exception as e:
                logger.error(f"Failed to process lead {lead.get('lead_id', 'unknown')}: {e}")
                continue
        
        # Convert ObjectIds before response
        final_leads = convert_objectid_to_str(processed_leads)
        
        logger.info(f"Successfully processed {len(final_leads)} leads out of {len(leads)} total")
        
        return {
            "leads": final_leads,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
                "has_next": page * limit < total,
                "has_prev": page > 1
            }
        }
        
    except Exception as e:
        logger.error(f"Get leads error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve leads"
        )

@router.get("/my-leads")
@convert_lead_dates()
async def get_my_leads(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    lead_status: Optional[str] = Query(None),  # ✅ Changed from LeadStatus to str
    search: Optional[str] = Query(None),
    #  Add the missing filter parameters
    stage: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    course_level: Optional[str] = Query(None),
    created_from: Optional[str] = Query(None),
    created_to: Optional[str] = Query(None),
    updated_from: Optional[str] = Query(None),    
    updated_to: Optional[str] = Query(None),      
    last_contacted_from: Optional[str] = Query(None), 
    last_contacted_to: Optional[str] = Query(None),   
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get leads assigned to current user with filtering support
    """
    try:
        db = get_database()
        
        # Base query to include both primary assignments and co-assignments
        base_user_query = {
            "$or": [
                {"assigned_to": current_user["email"]},
                {"co_assignees": {"$in": [current_user["email"]]}}
            ]
        }
        
        # 🔧 FIXED: Build filters array instead of overwriting query
        filters = []
        
        if stage:
            filters.append({"stage": stage})
            
        if status:
            filters.append({"status": status})
        elif lead_status:
            possible_old_statuses = [k for k, v in OLD_TO_NEW_STATUS_MAPPING.items() if v == lead_status.value]
            status_conditions = [{"status": lead_status.value}]
            if possible_old_statuses:
                status_conditions.extend([{"status": old_status} for old_status in possible_old_statuses])
            filters.append({"$or": status_conditions})
            
        if category:
            filters.append({"category": category})
            
        if source:
            filters.append({"source": source})
            
        if course_level:
            filters.append({"course_level": course_level})
            
        # Handle date ranges
        if created_from or created_to:
            date_query = {}
            if created_from:
                try:
                    date_query["$gte"] = datetime.fromisoformat(created_from)
                except ValueError:
                    pass
            if created_to:
                try:
                    date_query["$lte"] = datetime.fromisoformat(created_to)
                except ValueError:
                    pass
            if date_query:
                filters.append({"created_at": date_query})
        
        if updated_from or updated_to:
            date_query = {}
            if updated_from:
                date_query["$gte"] = datetime.fromisoformat(updated_from)
            if updated_to:
                # Add end of day to include full day
                end_date = datetime.fromisoformat(updated_to)
                if updated_to == updated_from:  # Same day filter
                    end_date = end_date.replace(hour=23, minute=59, second=59)
                date_query["$lte"] = end_date
            if date_query:
                filters.append({"updated_at": date_query})

        if last_contacted_from or last_contacted_to:
            date_query = {}
            if last_contacted_from:
                date_query["$gte"] = datetime.fromisoformat(last_contacted_from)
            if last_contacted_to:
                date_query["$lte"] = datetime.fromisoformat(last_contacted_to)
            if date_query:
                filters.append({"last_contacted": date_query})

        # Handle search
        if search:
            search_condition = {
                "$or": [
                    {"name": {"$regex": search, "$options": "i"}},
                    {"email": {"$regex": search, "$options": "i"}},
                    {"lead_id": {"$regex": search, "$options": "i"}},
                    {"contact_number": {"$regex": search, "$options": "i"}},
                    {"phone_number": {"$regex": search, "$options": "i"}}
                ]
            }
            filters.append(search_condition)
        
        # 🔧 FIXED: Combine base query with filters using $and
        if filters:
            query = {"$and": [base_user_query] + filters}
        else:
            query = base_user_query
        
        total = await db.leads.count_documents(query)
        skip = (page - 1) * limit
        
        leads = await db.leads.find(query).skip(skip).limit(limit).sort("created_at", -1).to_list(None)
        
        # Process leads with migration support
        processed_leads = []
        for lead in leads:
            try:
                processed_lead = await process_lead_for_response(lead, db, current_user)
                processed_leads.append(processed_lead)
            except Exception as e:
                logger.error(f"Failed to process lead {lead.get('lead_id', 'unknown')}: {e}")
                continue
        
        # Convert ObjectIds before response
        final_leads = convert_objectid_to_str(processed_leads)
        
        return {
            "leads": final_leads,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
                "has_next": page * limit < total,
                "has_prev": page > 1
            }
        }
        
    except Exception as e:
        logger.error(f"Get my leads error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve your leads"
        )

@router.post("/filter")
@convert_lead_dates()
async def filter_leads(
    filter_request: LeadsFilterRequest,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Filter leads with optional bulk lead_ids array in request body
    
    Supports large arrays of lead IDs that won't fit in URL query parameters.
    Returns same format as /leads and /my-leads endpoints.
    """
    try:
        logger.info(f"Filter leads requested by: {current_user.get('email')}")
        db = get_database()
        
        # Build base query based on user role
        query = {}
        if current_user["role"] != "admin":
            query["$or"] = [
                {"assigned_to": current_user["email"]},
                {"co_assignees": {"$in": [current_user["email"]]}}
            ]
        
        # 🔥 Handle lead_ids filter (from request body)
        if filter_request.lead_ids:
            if "$or" in query or "$and" in query:
                # Combine with existing conditions
                existing_query = query.copy()
                query = {
                    "$and": [
                        existing_query,
                        {"lead_id": {"$in": filter_request.lead_ids}}
                    ]
                }
            else:
                query["lead_id"] = {"$in": filter_request.lead_ids}
        
        # Handle stage filter
        if filter_request.stage:
            if "$and" in query:
                query["$and"].append({"stage": filter_request.stage})
            else:
                query["stage"] = filter_request.stage
        
        # Handle status filter
        if filter_request.status:
            if "$and" in query:
                query["$and"].append({"status": filter_request.status})
            else:
                query["status"] = filter_request.status
        
        # Handle category filter
        if filter_request.category:
            if "$and" in query:
                query["$and"].append({"category": filter_request.category})
            else:
                query["category"] = filter_request.category
        
        # Handle source filter
        if filter_request.source:
            if "$and" in query:
                query["$and"].append({"source": filter_request.source})
            else:
                query["source"] = filter_request.source
        
        # Handle assigned_to filter (admin only)
        if filter_request.assigned_to and current_user["role"] == "admin":
            if "$and" in query:
                query["$and"].append({"assigned_to": filter_request.assigned_to})
            else:
                query["assigned_to"] = filter_request.assigned_to
        
        # Handle search filter
        if filter_request.search:
            search_condition = {
                "$or": [
                    {"name": {"$regex": filter_request.search, "$options": "i"}},
                    {"email": {"$regex": filter_request.search, "$options": "i"}},
                    {"lead_id": {"$regex": filter_request.search, "$options": "i"}},
                    {"contact_number": {"$regex": filter_request.search, "$options": "i"}},
                    {"phone_number": {"$regex": filter_request.search, "$options": "i"}}
                ]
            }
            if "$and" in query:
                query["$and"].append(search_condition)
            else:
                query = {"$and": [query, search_condition]} if query else search_condition
        
        # Handle date range filters
        if filter_request.created_from or filter_request.created_to:
            date_query = {}
            if filter_request.created_from:
                date_query["$gte"] = filter_request.created_from
            if filter_request.created_to:
                date_query["$lte"] = filter_request.created_to
            
            if "$and" in query:
                query["$and"].append({"created_at": date_query})
            else:
                query["created_at"] = date_query
        
        if filter_request.updated_from or filter_request.updated_to:
            date_query = {}
            if filter_request.updated_from:
                date_query["$gte"] = filter_request.updated_from
            if filter_request.updated_to:
                date_query["$lte"] = filter_request.updated_to
            
            if "$and" in query:
                query["$and"].append({"updated_at": date_query})
            else:
                query["updated_at"] = date_query
        
        if filter_request.last_contacted_from or filter_request.last_contacted_to:
            date_query = {}
            if filter_request.last_contacted_from:
                date_query["$gte"] = filter_request.last_contacted_from
            if filter_request.last_contacted_to:
                date_query["$lte"] = filter_request.last_contacted_to
            
            if "$and" in query:
                query["$and"].append({"last_contacted": date_query})
            else:
                query["last_contacted"] = date_query
        
        logger.info(f"Final filter query: {query}")
        
        # Get total count
        total = await db.leads.count_documents(query)
        skip = (page - 1) * limit
        
        # Fetch leads with pagination
        leads = await db.leads.find(query).skip(skip).limit(limit).sort("created_at", -1).to_list(None)
        
        # Process leads with migration support
        processed_leads = []
        for lead in leads:
            try:
                processed_lead = await process_lead_for_response(lead, db, current_user)
                processed_leads.append(processed_lead)
            except Exception as e:
                logger.error(f"Failed to process lead {lead.get('lead_id', 'unknown')}: {e}")
                continue
        
        # Convert ObjectIds before response
        final_leads = convert_objectid_to_str(processed_leads)
        
        logger.info(f"Successfully filtered {len(final_leads)} leads out of {len(leads)} total")
        
        # Return SAME format as /leads and /my-leads
        return {
            "leads": final_leads,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
                "has_next": page * limit < total,
                "has_prev": page > 1
            }
        }
        
    except Exception as e:
        logger.error(f"Filter leads error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to filter leads"
        )

@router.get("/stats", response_model=LeadStatsResponse)
@convert_dates_to_ist()
async def get_lead_stats(
    include_multi_assignment_stats: bool = Query(True, description="Include multi-assignment statistics"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """Get lead statistics with enhanced breakdown support"""
    try:
        db = get_database()
        user_role = current_user.get("role", "user")
        user_email = current_user.get("email")
        
        # Base query based on role
        if user_role != "admin":
            if include_multi_assignment_stats:
                base_query = {
                    "$or": [
                        {"assigned_to": user_email},
                        {"co_assignees": user_email}
                    ]
                }
            else:
                base_query = {"assigned_to": user_email}
        else:
            base_query = {}
        
        # Get total leads
        total_leads = await db.leads.count_documents(base_query)
        
        # Get status breakdown
        status_pipeline = [
            {"$match": base_query},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        status_result = await db.leads.aggregate(status_pipeline).to_list(None)
        
        # Get stage breakdown
        stage_pipeline = [
            {"$match": base_query},
            {"$group": {"_id": "$stage", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        stage_result = await db.leads.aggregate(stage_pipeline).to_list(None)
        
        # Process breakdowns into dictionaries
        status_breakdown = {item["_id"]: item["count"] for item in status_result if item["_id"]}
        stage_breakdown = {item["_id"]: item["count"] for item in stage_result if item["_id"]}
        
        # Calculate core metrics
        dnp_count = status_breakdown.get("dnp", 0)
        counseled_count = status_breakdown.get("counselled", 0)
        conversion_rate = round((counseled_count / total_leads * 100), 1) if total_leads > 0 else 0.0
        
        # Calculate my_leads and unassigned_leads
        if user_role != "admin":
            my_leads = total_leads
            unassigned_leads = 0
        else:
            if include_multi_assignment_stats:
                my_leads_count = await db.leads.count_documents({
                    "$or": [
                        {"assigned_to": user_email},
                        {"co_assignees": user_email}
                    ]
                })
            else:
                my_leads_count = await db.leads.count_documents({"assigned_to": user_email})
            
            my_leads = my_leads_count
            unassigned_leads = await db.leads.count_documents({"assigned_to": None})
        
        # Build response
        response_data = {
            "total_leads": total_leads,
            "my_leads": my_leads,
            "unassigned_leads": unassigned_leads,
            "dnp_count": dnp_count,
            "counseled_count": counseled_count,
            "conversion_rate": conversion_rate,
            "status_breakdown": status_breakdown,
            "stage_breakdown": stage_breakdown
        }
        
        # Add assignment stats for admins
        if user_role == "admin" and include_multi_assignment_stats:
            # Get workload distribution with enhanced user details
            workload_pipeline = [
                {"$match": {"assigned_to": {"$ne": None}}},
                {"$group": {"_id": "$assigned_to", "total_leads": {"$sum": 1}}},
                {"$sort": {"total_leads": -1}}
            ]
            workload_result = await db.leads.aggregate(workload_pipeline).to_list(None)
            
            # Enhanced workload distribution array
            enhanced_workload = []
            
            for item in workload_result:
                user_email = item["_id"]
                total_leads = item["total_leads"]
                
                # Get user details
                user = await db.users.find_one({"email": user_email})
                user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip() if user else user_email.split('@')[0]
                
                # Get DNP count for this user from stage breakdown
                dnp_count = await db.leads.count_documents({
                    "assigned_to": user_email,
                    "stage": "dnp"
                })
                
                # Get Counselled count for this user from stage breakdown  
                counselled_count = await db.leads.count_documents({
                    "assigned_to": user_email,
                    "stage": "counselled"
                })
                
                enhanced_workload.append({
                    "name": user_name,
                    "email": user_email,
                    "total_leads": total_leads,
                    "dnp_count": dnp_count,
                    "counselled_count": counselled_count
                })
            
            multi_assigned_count = await db.leads.count_documents({"is_multi_assigned": True})
            
            # Calculate balance score
            if workload_result:
                counts = [item["total_leads"] for item in workload_result]
                avg_leads = sum(counts) / len(counts)
                variance = sum((x - avg_leads) ** 2 for x in counts) / len(counts)
                balance_score = max(0, 100 - (variance / avg_leads * 10)) if avg_leads > 0 else 100
            else:
                avg_leads = 0
                balance_score = 100
            
            response_data["assignment_stats"] = {
                "multi_assigned_leads": multi_assigned_count,
                "workload_distribution": enhanced_workload,
                "average_leads_per_user": round(avg_leads, 1),
                "assignment_balance_score": round(balance_score, 1)
            }
        
        return LeadStatsResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Get lead stats error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve lead statistics"
        )


@router.get("/{lead_id}")
@convert_lead_dates()
async def get_lead(
    lead_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """Get a specific lead by ID with enhanced multi-assignment support"""
    try:
        db = get_database()
        
        query = {"lead_id": lead_id}
        user_role = current_user.get("role", "user")
        user_email = current_user.get("email")
        
        if user_role != "admin":
            # Check both primary and co-assignments
            query = {
                "lead_id": lead_id,
                "$or": [
                    {"assigned_to": user_email},
                    {"co_assignees": user_email}
                ]
            }
        
        lead = await db.leads.find_one(query)
        
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found or you don't have permission to view it"
            )
        
        # Transform to structured format with migration support and ObjectId conversion
        structured_lead = transform_lead_to_structured_format(lead)
        
        return {
            "success": True,
            "lead": structured_lead
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get lead error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve lead"
        )


# ============================================================================
# ASSIGNMENT ENDPOINTS
# Add all the remaining endpoints here (assign, update, delete, bulk operations, admin endpoints, etc.)
# ============================================================================

@router.post("/{lead_id}/assign", response_model=LeadAssignResponse)
async def assign_lead(
    lead_id: str,
    assignment: LeadAssign,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    🔄 UPDATED: Assign a lead to a user with unified notification
    Admin only - uses single notification for assigned user + admins
    """
    try:
        db = get_database()
        
        # Verify user exists
        assignee = await db.users.find_one({"email": assignment.assigned_to})
        if not assignee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Get current lead
        lead = await db.leads.find_one({"lead_id": lead_id})
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        current_assignee = lead.get("assigned_to")
        current_co_assignees = lead.get("co_assignees", [])
        
        # Use the assignment service for consistency (already has unified notification)
        success = await lead_assignment_service.assign_lead_to_user(
            lead_id=lead_id,
            user_email=assignment.assigned_to,
            assigned_by=current_user.get("email"),
            reason=assignment.notes or "Manual assignment"
        )
        
        if success:
            logger.info(f"Lead {lead_id} assigned to {assignee['email']} by {current_user['email']}")
            
            return LeadAssignResponse(
                success=True,
                message=f"Lead assigned to {assignee['first_name']} {assignee['last_name']}",
                lead_id=lead_id,
                assigned_to=assignment.assigned_to,
                assigned_to_name=f"{assignee['first_name']} {assignee['last_name']}"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to assign lead"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lead assignment error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assign lead"
        )
# ============================================================================
# UPDATE ENDPOINT WITH MULTI-ASSIGNMENT SUPPORT
# ============================================================================

@router.put("/update")
async def update_lead_universal(
    update_request: dict,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    🔄 UPDATED: Universal lead update endpoint with unified notification system
    Handles all lead updates including reassignment with ONE notification for assignee + admins
    """
    try:
        logger.info(f"🔄 Update by {current_user.get('email')} with data: {update_request}")
        
        db = get_database()
        
        # Get lead_id
        lead_id = update_request.get("lead_id")
        if not lead_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="lead_id is required in update request"
            )
        
        # Get current lead BEFORE updating
        lead = await db.leads.find_one({"lead_id": lead_id})
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        #  AUTOMATION LOGIC - Check if stage is changing
        new_stage = update_request.get("stage")
        current_stage = lead.get("stage")
        stage_changed = new_stage and new_stage != current_stage
        
        if stage_changed:
            logger.info(f"🔄 Stage change detected: '{current_stage}' → '{new_stage}'")
            
            # Check if target stage has automation enabled
            target_stage = await db.lead_stages.find_one({"name": new_stage})
            if target_stage and target_stage.get("automation"):
                logger.info(f"🤖 Automation enabled for stage '{new_stage}'")
                
                # Get automation config
                automation_config = target_stage.get("automation_config")
                if automation_config and automation_config.get("template_name"):
                    template_name = automation_config["template_name"]
                    
                    # Check if user confirmed automation (frontend should send this)
                    automation_approved = update_request.get("automation_approved")
                    
                    if automation_approved:
                        logger.info(f"🚀 Sending WhatsApp template '{template_name}' for lead {lead_id}")
                        
                        try:
                            # Send WhatsApp template
                            from ..services.whatsapp_message_service import whatsapp_message_service
                            
                            contact_number = lead.get("contact_number") or lead.get("phone_number")
                            if contact_number:
                                whatsapp_result = await whatsapp_message_service.send_template_message(
                                    contact=contact_number,
                                    template_name=template_name,
                                    lead_name=lead.get("name", "")
                                )
                            else:
                                whatsapp_result = {
                                    "success": False,
                                    "error": "Lead has no phone number"
                                }
                            
                            if whatsapp_result.get("success"):
                                logger.info(f"✅ WhatsApp template sent successfully for lead {lead_id}")
                                
                                # Log automation activity
                                automation_activity = {
                                    "activity_type": "automation_executed",
                                    "description": f"WhatsApp template '{template_name}' sent automatically due to stage change to '{new_stage}'",
                                    "metadata": {
                                        "template_name": template_name,
                                        "automation_trigger": "stage_change",
                                        "target_stage": new_stage,
                                        "automation_approved": True
                                    }
                                }
                            else:
                                logger.error(f"❌ WhatsApp template failed for lead {lead_id}: {whatsapp_result.get('error')}")
                                
                                # Log automation failure
                                automation_activity = {
                                    "activity_type": "automation_failed",
                                    "description": f"Failed to send WhatsApp template '{template_name}' for stage change to '{new_stage}': {whatsapp_result.get('error')}",
                                    "metadata": {
                                        "template_name": template_name,
                                        "automation_trigger": "stage_change",
                                        "target_stage": new_stage,
                                        "error": whatsapp_result.get('error')
                                    }
                                }
                            
                            # Store automation activity for later logging
                            update_request["_automation_activity"] = automation_activity
                            
                        except Exception as automation_error:
                            logger.error(f"❌ Automation error for lead {lead_id}: {str(automation_error)}")
                            
                            # Log automation error
                            automation_activity = {
                                "activity_type": "automation_error",
                                "description": f"Error executing automation for stage change to '{new_stage}': {str(automation_error)}",
                                "metadata": {
                                    "template_name": template_name,
                                    "automation_trigger": "stage_change",
                                    "target_stage": new_stage,
                                    "error": str(automation_error)
                                }
                            }
                            update_request["_automation_activity"] = automation_activity
                    
                    else:
                        logger.info(f"ℹ️ Automation declined by user for lead {lead_id}")
                        
                        # Log automation decline
                        automation_activity = {
                            "activity_type": "automation_declined",
                            "description": f"User declined to send WhatsApp template '{template_name}' for stage change to '{new_stage}'",
                            "metadata": {
                                "template_name": template_name,
                                "automation_trigger": "stage_change",
                                "target_stage": new_stage,
                                "automation_approved": False
                            }
                        }
                        update_request["_automation_activity"] = automation_activity
        
        #  Check campaign criteria when stage or source changes
        new_source = update_request.get("source")
        current_source = lead.get("source")
        source_changed = new_source and new_source != current_source

        if stage_changed or source_changed:
            try:
                from ..services.campaign_executor import campaign_executor
                
                logger.info(f"🤖 Checking campaign criteria for lead {lead_id}")
                
                # 🔥 NEW: Convert stage/source names to ObjectIds for campaign comparison
                new_stage_id = None
                new_source_id = None
                
                if new_stage:
                    # Get stage ObjectId from stage name
                    stage_doc = await db.lead_stages.find_one({"name": new_stage})
                    if stage_doc:
                        new_stage_id = str(stage_doc["_id"])
                
                if new_source:
                    # Get source ObjectId from source name
                    source_doc = await db.lead_sources.find_one({"name": new_source})
                    if source_doc:
                        new_source_id = str(source_doc["_id"])
                
                # Pass ObjectIds to campaign executor
                await campaign_executor.check_lead_criteria_change(
                    lead_id=lead_id,
                    new_stage_id=new_stage_id,
                    new_source_id=new_source_id
                )
            except Exception as campaign_error:
                logger.error(f"Campaign criteria check failed: {str(campaign_error)}")
        
        logger.info(f"📋 Found lead {lead_id}, currently assigned to: {lead.get('assigned_to')}")
        
        # Enhanced permission checking for multi-assignment
        user_role = current_user.get("role", "user")
        user_email = current_user.get("email")
        
        if user_role != "admin":
            # Check if user has access (primary or co-assignee)
            assigned_to = lead.get("assigned_to")
            co_assignees = lead.get("co_assignees", [])
            
            if user_email not in [assigned_to] + co_assignees:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only update leads assigned to you"
                )
        
        # Handle assignment change validation
        assignment_changed = False
        co_assignees_changed = False
        old_assignee = lead.get("assigned_to")
        old_co_assignees = lead.get("co_assignees", [])
        new_assignee = None
        new_co_assignees = []

        if "assigned_to" in update_request:
            new_assignee = update_request.get("assigned_to")
            assignment_changed = (old_assignee != new_assignee)

        # 🔥 NEW: Handle co-assignees from update request
        if "co_assignees" in update_request:
            new_co_assignees = update_request.get("co_assignees", [])
            if not isinstance(new_co_assignees, list):
                new_co_assignees = []
            co_assignees_changed = set(old_co_assignees) != set(new_co_assignees)
            logger.info(f"🔄 Co-assignees change detected: {old_co_assignees} → {new_co_assignees}")

        if assignment_changed and user_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can reassign leads"
            )
        
        # Validate new assignee exists (if not None)
        if new_assignee:
            assignee = await db.users.find_one({"email": new_assignee, "is_active": True})
            if not assignee:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"User {new_assignee} not found or inactive"
                )
            
            # Add assignee name for update
            update_request["assigned_to_name"] = f"{assignee.get('first_name', '')} {assignee.get('last_name', '')}".strip()
            logger.info(f"✅ New assignee validated: {new_assignee}")
        
        # 🔥 NEW: Validate co-assignees and build co_assignees_names
        if co_assignees_changed and user_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can modify co-assignees"
            )

        if new_co_assignees:
            co_assignees_names = []
            validated_co_assignees = []
            
            for co_email in new_co_assignees:
                co_user = await db.users.find_one({"email": co_email, "is_active": True})
                if not co_user:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Co-assignee {co_email} not found or inactive"
                    )
                validated_co_assignees.append(co_email)
                co_assignees_names.append(f"{co_user.get('first_name', '')} {co_user.get('last_name', '')}".strip() or co_email)
            
            update_request["co_assignees"] = validated_co_assignees
            update_request["co_assignees_names"] = co_assignees_names
            update_request["is_multi_assigned"] = len(validated_co_assignees) > 0
            logger.info(f"✅ Co-assignees validated: {validated_co_assignees}")
        elif "co_assignees" in update_request and not new_co_assignees:
            # Clearing co-assignees
            update_request["co_assignees"] = []
            update_request["co_assignees_names"] = []
            update_request["is_multi_assigned"] = False

        # Remove lead_id from update data
        update_data = {k: v for k, v in update_request.items() if k != "lead_id"}
        
        # Prepare activities list for changes
        activities_to_log = []
        
        # Track field changes for activity logging
        for field, new_value in update_data.items():
            if field in ["updated_at", "assigned_to_name"]:  # Skip system fields
                continue
                
            old_value = lead.get(field)
            
            # Only log if value actually changed
            if old_value != new_value:
                activity_type = get_activity_type_for_field(field)
                description = get_field_change_description(field.replace("_", " ").title(), old_value, new_value)
                
                activities_to_log.append({
                    "activity_type": activity_type,
                    "description": description,
                    "metadata": {
                        "field": field,
                        "old_value": str(old_value) if old_value is not None else None,
                        "new_value": str(new_value) if new_value is not None else None
                    }
                })
        
        # Add timestamp
        update_data["updated_at"] = datetime.utcnow()
        
        # Perform the actual database update
        result = await db.leads.update_one(
            {"lead_id": lead_id},
            {"$set": update_data}
        )
        
        if result.matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found for update"
            )
        
        logger.info(f"✅ Lead {lead_id} updated in database successfully")
        
        # 🔥 UPDATED: Send unified lead reassignment notification
        if assignment_changed and new_assignee:
            try:
                from ..services.realtime_service import realtime_manager
                
                # Get new assignee details
                new_user = await db.users.find_one({"email": new_assignee})
                new_user_name = f"{new_user.get('first_name', '')} {new_user.get('last_name', '')}".strip()
                if not new_user_name:
                    new_user_name = new_assignee
                
                notification_data = {
                    "lead_name": lead.get("name"),
                    "lead_email": lead.get("email"),
                    "lead_phone": lead.get("contact_number"),
                    "category": lead.get("category"),
                    "source": lead.get("source"),
                    "reassigned_from": old_assignee,
                    "reassigned": True
                }
                
                authorized_users = [{"email": new_assignee, "name": new_user_name}]
                
                # 🔥 ONE call creates notification for new assignee + admins automatically
                await realtime_manager.notify_lead_reassigned(lead_id, notification_data, authorized_users)
                
                logger.info(f"✅ Unified lead reassignment notification created for {new_assignee}")
            except Exception as notif_error:
                logger.warning(f"⚠️ Failed to send reassignment notification: {notif_error}")
        
        # 🔥 ENHANCED: User array updates for multi-assignment including co-assignees
        assignment_sync_error = None
        if assignment_changed or co_assignees_changed:
            logger.info(f"🔄 Processing enhanced user array updates")
            
            try:
                # Remove from old assignee's array (if changed)
                if assignment_changed and old_assignee and old_assignee != new_assignee:
                    logger.info(f"📤 Removing lead {lead_id} from old assignee {old_assignee}")
                    await user_lead_array_service.remove_lead_from_user_array(old_assignee, lead_id)
                    logger.info(f"✅ Removed from {old_assignee}")
                
                # Remove from old co-assignees who are no longer assigned
                removed_co_assignees = set(old_co_assignees) - set(new_co_assignees)
                for co_assignee in removed_co_assignees:
                    logger.info(f"📤 Removing lead {lead_id} from removed co-assignee {co_assignee}")
                    await user_lead_array_service.remove_lead_from_user_array(co_assignee, lead_id)
                    logger.info(f"✅ Removed from {co_assignee}")
                
                # Add to new assignee's array (if changed)
                if assignment_changed and new_assignee and old_assignee != new_assignee:
                    logger.info(f"📥 Adding lead {lead_id} to new assignee {new_assignee}")
                    await user_lead_array_service.add_lead_to_user_array(new_assignee, lead_id)
                    logger.info(f"✅ Added to {new_assignee}")
                
                # Add to new co-assignees
                added_co_assignees = set(new_co_assignees) - set(old_co_assignees)
                for co_assignee in added_co_assignees:
                    logger.info(f"📥 Adding lead {lead_id} to new co-assignee {co_assignee}")
                    await user_lead_array_service.add_lead_to_user_array(co_assignee, lead_id)
                    logger.info(f"✅ Added to {co_assignee}")
                    
            except Exception as array_error:
                logger.error(f"❌ CRITICAL: Enhanced user array update failed: {str(array_error)}")
                logger.error(f"❌ Assignment details: {old_assignee} → {new_assignee}, co-assignees: {old_co_assignees} → {new_co_assignees}")
                
                assignment_sync_error = {
                    "error": "User array sync failed",
                    "details": str(array_error),
                    "recommendation": "Run /admin/sync-user-arrays endpoint"
                }
        else:
            logger.info(f"ℹ️ No assignment or co-assignee changes, skipping user array updates")
        
        # Log all activities
        automation_activity = update_request.get("_automation_activity")
        if automation_activity:
            activities_to_log.append(automation_activity)
        
        user_id = current_user.get("_id") or current_user.get("id")
        user_name = f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip()
        if not user_name:
            user_name = current_user.get('email', 'Unknown User')
        
        for activity in activities_to_log:
            try:
                activity_doc = {
                    "lead_object_id": lead["_id"],
                    "lead_id": lead_id,
                    "activity_type": activity["activity_type"],
                    "description": activity["description"],
                    "created_by": ObjectId(user_id) if ObjectId.is_valid(str(user_id)) else user_id,
                    "created_by_name": user_name,
                    "created_at": datetime.utcnow(),
                    "is_system_generated": True,
                    "metadata": activity["metadata"]
                }
                
                await db.lead_activities.insert_one(activity_doc)
                logger.info(f"✅ Activity logged: {activity['activity_type']} for lead {lead_id}")
                
            except Exception as activity_error:
                logger.error(f"❌ Failed to log activity for lead {lead_id}: {str(activity_error)}")
        
        # Get updated lead for response
        updated_lead = await db.leads.find_one({"lead_id": lead_id})
        formatted_lead = format_lead_response(updated_lead) if updated_lead else None
        
        logger.info(f"✅ Lead {lead_id} update completed successfully with {len(activities_to_log)} activities logged")
        
        response = {
            "success": True,
            "message": "Lead updated successfully",
            "lead": formatted_lead,
            "activities_logged": len(activities_to_log),
            "assignment_changed": assignment_changed
        }
        
        # Add sync error info if it occurred
        if assignment_changed and assignment_sync_error:
            response["warning"] = assignment_sync_error
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Update lead error: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update lead"
        )

# ============================================================================
# DELETE ENDPOINT WITH MULTI-ASSIGNMENT CLEANUP
# ============================================================================

@router.delete("/{lead_id}")
async def delete_lead(
    lead_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """Delete a lead (Admin only) - Enhanced with multi-assignment cleanup"""
    try:
        db = get_database()
        
        # Get the lead first to know who it's assigned to
        lead = await db.leads.find_one({"lead_id": lead_id})
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        assigned_to = lead.get("assigned_to")
        co_assignees = lead.get("co_assignees", [])
        
        # Delete the lead
        result = await db.leads.delete_one({"lead_id": lead_id})
        
        if result.deleted_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        # Remove from all assignees' arrays
        try:
            # Remove from primary assignee's array
            if assigned_to:
                await user_lead_array_service.remove_lead_from_user_array(assigned_to, lead_id)
            
            # Remove from all co-assignees' arrays
            for co_assignee in co_assignees:
                await user_lead_array_service.remove_lead_from_user_array(co_assignee, lead_id)
                
        except Exception as array_error:
            logger.error(f"Error updating user arrays after lead deletion: {str(array_error)}")
            # Don't fail the deletion if array update fails
        
        logger.info(f"Lead {lead_id} deleted by {current_user['email']}")
        
        return {
            "success": True,
            "message": "Lead deleted successfully",
            "lead_id": lead_id,
            "removed_from_users": [assigned_to] + co_assignees if assigned_to else co_assignees
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete lead error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete lead"
        )

# ============================================================================
# BULK OPERATIONS WITH ENHANCED ASSIGNMENT SUPPORT
# ============================================================================
@router.post("/bulk-create", status_code=status.HTTP_201_CREATED)
async def bulk_create_leads(
    leads_data: List[dict],  
    force_create: bool = Query(False, description="Create leads even if duplicates exist"),
    assignment_method: str = Query("all_users", description="Assignment method: 'all_users' or 'selected_users'"),
    selected_user_emails: Optional[str] = Query(None, description="Comma-separated user emails for selective round robin"),
    current_user: Dict[str, Any] = Depends(get_user_with_bulk_lead_permission) 
):
    """
    🔧 FIXED: Bulk create leads with PROPER duplicate detection
    - Each lead is checked individually against the database in real-time
    - Uses the lead_service method that includes comprehensive duplicate checking
    """
    try:
        logger.info(f"🚀 Bulk creating {len(leads_data)} leads by {current_user['email']} (force_create={force_create})")
        
        # Parse selected user emails
        selected_users = None
        if assignment_method == "selected_users" and selected_user_emails:
            selected_users = [email.strip() for email in selected_user_emails.split(",") if email.strip()]
        
        # 🔧 CRITICAL FIX: Use the service method that includes proper duplicate detection
        from ..services.lead_service import lead_service
        
        # Call the CORRECT service method that has duplicate detection
        result = await lead_service.bulk_create_leads_with_selective_assignment(
            leads_data=leads_data,
            created_by=str(current_user["_id"]),
            assignment_method=assignment_method,
            selected_user_emails=selected_users
            # 🔧 NOTE: We don't pass force_create here because the service method
            # should handle duplicates properly according to the business logic
        )
        
        logger.info(f"✅ Bulk creation completed: {result.get('successfully_created', 0)} created, {result.get('duplicates_skipped', 0)} duplicates")
        
        return convert_objectid_to_str(result)
        
    except Exception as e:
        logger.error(f"❌ Bulk creation error: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# Add this single endpoint to your app/routers/leads.py file:

@router.post("/check-duplicates")
async def check_duplicates_batch(
    leads_data: List[Dict[str, Any]],  # [{"email": "test@test.com", "contact_number": "1234567890"}, ...]
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Check for duplicate leads during CSV parsing - minimal implementation
    Returns which leads are duplicates so frontend can categorize them
    """
    try:
        logger.info(f"Duplicate check for {len(leads_data)} leads by {current_user.get('email')}")
        
        # Import the lead service to use existing duplicate check method
        from ..services.lead_service import lead_service
        
        duplicates = []
        
        # Check each lead for duplicates using existing method
        for index, lead_info in enumerate(leads_data):
            email = lead_info.get("email", "").strip()
            contact_number = lead_info.get("contact_number", "").strip()
            
            if not email and not contact_number:
                continue  # Skip if no email or phone to check
            
            # Use your existing duplicate check method
            duplicate_check = await lead_service.check_duplicate_lead(
                email=email if email else None,
                contact_number=contact_number if contact_number else None
            )
            
            if duplicate_check.get("is_duplicate"):
                duplicates.append({
                    "index": index,
                    "email": email,
                    "contact_number": contact_number,
                    "existing_lead_id": duplicate_check.get("existing_lead_id"),
                    "existing_lead_name": duplicate_check.get("existing_lead_name", "Unknown"),
                    "duplicate_field": duplicate_check.get("duplicate_field"),
                    "duplicate_value": duplicate_check.get("duplicate_value"),
                    "message": duplicate_check.get("message")
                })
        
        logger.info(f"Found {len(duplicates)} duplicates out of {len(leads_data)} checked")
        
        return {
            "success": True,
            "total_checked": len(leads_data),
            "duplicates_found": len(duplicates),
            "duplicates": duplicates
        }
        
    except Exception as e:
        logger.error(f"Error checking duplicates: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check duplicates: {str(e)}"
        )
# ============================================================================
# ADMIN ENDPOINTS WITH MULTI-ASSIGNMENT ENHANCEMENTS
# ============================================================================

@router.get("/admin/user-lead-stats")
async def get_admin_user_lead_stats(
    #  Include multi-assignment stats
    include_multi_assignment_stats: bool = Query(True, description="Include multi-assignment statistics"),
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """SUPER FAST admin stats with enhanced multi-assignment support"""
    try:
        logger.info(f"Admin user stats requested by: {current_user.get('email')}")
        
        db = get_database()
        
        users_cursor = db.users.find(
            {"role": {"$in": ["user", "admin"]}, "is_active": True},
            {"first_name": 1, "last_name": 1, "email": 1, "role": 1, "assigned_leads": 1, "total_assigned_leads": 1}
        )
        users = await users_cursor.to_list(None)
        
        user_stats = []
        total_assigned_leads = 0
        
        for user in users:
            user_email = user["email"]
            lead_count = user.get("total_assigned_leads", len(user.get("assigned_leads", [])))
            
            # Get co-assignment count if requested
            co_assignment_count = 0
            if include_multi_assignment_stats:
                co_assignment_count = await db.leads.count_documents({"co_assignees": user_email})
            
            total_assigned_leads += lead_count
            
            user_stat = {
                "user_id": str(user["_id"]),
                "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                "email": user_email,
                "role": user["role"],
                "assigned_leads_count": lead_count,
            }
            
            if include_multi_assignment_stats:
                user_stat["co_assigned_leads_count"] = co_assignment_count
                user_stat["total_lead_access"] = lead_count + co_assignment_count
            
            user_stats.append(user_stat)
        
        user_stats.sort(key=lambda x: x.get("total_lead_access", x["assigned_leads_count"]), reverse=True)
        
        total_leads = await db.leads.count_documents({})
        unassigned_leads = await db.leads.count_documents({"assigned_to": None})
        
        summary = {
            "total_users": len(user_stats),
            "total_leads": total_leads,
            "assigned_leads": total_assigned_leads,
            "unassigned_leads": unassigned_leads
        }
        
        # Add multi-assignment summary if requested
        if include_multi_assignment_stats:
            multi_assigned_count = await db.leads.count_documents({"is_multi_assigned": True})
            summary["multi_assigned_leads"] = multi_assigned_count
        
        final_response = convert_objectid_to_str({
            "success": True,
            "user_stats": user_stats,
            "summary": summary,
            "include_multi_assignment_stats": include_multi_assignment_stats,
            "performance": "ultra_fast_array_lookup"
        })
        
        return final_response
        
    except Exception as e:
        logger.error(f"Admin stats error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get admin stats: {str(e)}"
        )

@router.post("/admin/sync-user-arrays")
async def sync_user_arrays(
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """Sync user arrays with actual lead assignments including multi-assignments"""
    try:
        logger.info(f"Enhanced array sync requested by admin: {current_user.get('email')}")
        
        db = get_database()
        sync_count = 0
        
        users = await db.users.find({}).to_list(None)
        
        for user in users:
            user_email = user["email"]
            
            # Get all leads where user is primary assignee
            primary_leads = await db.leads.find(
                {"assigned_to": user_email}, 
                {"lead_id": 1}
            ).to_list(None)
            
            # Get all leads where user is co-assignee
            co_assigned_leads = await db.leads.find(
                {"co_assignees": user_email}, 
                {"lead_id": 1}
            ).to_list(None)
            
            # Combine primary and co-assigned leads
            primary_lead_ids = [lead["lead_id"] for lead in primary_leads]
            co_assigned_ids = [lead["lead_id"] for lead in co_assigned_leads]
            
            # For user arrays, we typically track only primary assignments
            # But we can track total access in a separate field
            all_accessible_leads = list(set(primary_lead_ids + co_assigned_ids))
            
            await db.users.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "assigned_leads": primary_lead_ids,
                        "total_assigned_leads": len(primary_lead_ids),
                        "co_assigned_leads": co_assigned_ids,
                        "total_accessible_leads": len(all_accessible_leads),
                        "array_last_synced": datetime.utcnow()
                    }
                }
            )
            sync_count += 1
        
        logger.info(f"✅ Enhanced sync completed for {sync_count} users")
        
        return {
            "success": True,
            "message": f"Enhanced sync completed for {sync_count} users",
            "synced_users": sync_count,
            "includes_multi_assignment_sync": True
        }
        
    except Exception as e:
        logger.error(f"Enhanced array sync error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync arrays: {str(e)}"
        )

# ============================================================================
# ADDITIONAL UTILITY ENDPOINTS
# ============================================================================

@router.get("/users/assignable")
async def get_assignable_users(
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """Get list of users that can be assigned leads (Admin only)"""
    try:
        db = get_database()
        
        users = await db.users.find(
            {"role": "user", "is_active": True},
            {"email": 1, "first_name": 1, "last_name": 1}
        ).to_list(None)
        
        assignable_users = []
        for user in users:
            full_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
            assignable_users.append({
                "email": user["email"],
                "name": full_name if full_name else user["email"]
            })
        
        return {
            "success": True,
            "users": assignable_users,
            "total": len(assignable_users)
        }
        
    except Exception as e:
        logger.error(f"Get assignable users error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get assignable users"
        )

@router.post("/bulk-assign")
async def bulk_assign_leads(
    bulk_assign: LeadBulkAssign,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """Bulk assign multiple leads to users (Admin only)"""
    try:
        db = get_database()
        admin_email = current_user.get("email")
        
        results = []
        successful_assignments = 0
        failed_assignments = 0
        
        for lead_id in bulk_assign.lead_ids:
            try:
                # Check if lead exists
                lead = await db.leads.find_one({"lead_id": lead_id})
                if not lead:
                    results.append({
                        "lead_id": lead_id,
                        "status": "failed",
                        "error": "Lead not found"
                    })
                    failed_assignments += 1
                    continue
                
                # Get next assignee using round robin
                if bulk_assign.assignment_method == "round_robin":
                    assignee = await lead_assignment_service.get_next_assignee_round_robin()
                elif bulk_assign.assignment_method == "specific_user":
                    assignee = bulk_assign.assigned_to
                else:
                    assignee = None
                
                if assignee:
                    # Assign the lead
                    success = await lead_assignment_service.assign_lead_to_user(
                        lead_id=lead_id,
                        user_email=assignee,
                        assigned_by=admin_email,
                        reason="Bulk assignment"
                    )
                    
                    if success:
                        results.append({
                            "lead_id": lead_id,
                            "status": "success",
                            "assigned_to": assignee
                        })
                        successful_assignments += 1
                    else:
                        results.append({
                            "lead_id": lead_id,
                            "status": "failed",
                            "error": "Assignment failed"
                        })
                        failed_assignments += 1
                else:
                    results.append({
                        "lead_id": lead_id,
                        "status": "failed",
                        "error": "No assignee available"
                    })
                    failed_assignments += 1
                    
            except Exception as e:
                logger.error(f"Error assigning lead {lead_id}: {str(e)}")
                results.append({
                    "lead_id": lead_id,
                    "status": "failed",
                    "error": str(e)
                })
                failed_assignments += 1
        
        return LeadBulkAssignResponse(
            success=failed_assignments == 0,
            message=f"Bulk assignment completed: {successful_assignments} successful, {failed_assignments} failed",
            total_leads=len(bulk_assign.lead_ids),
            successful_assignments=successful_assignments,
            failed_assignments=failed_assignments,
            results=results
        )
        
    except Exception as e:
        logger.error(f"Bulk assign error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to bulk assign leads"
        )

@router.patch("/{lead_id}/status")
async def update_lead_status(
    lead_id: str,
    status_update: LeadStatusUpdate,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """Update lead status (Users can update leads assigned to them)"""
    try:
        db = get_database()
        user_role = current_user.get("role", "user")
        user_email = current_user.get("email")
        
        # Build query based on permissions
        query = {"lead_id": lead_id}
        if user_role != "admin":
            # Users can only update leads assigned to them (primary or co-assignee)
            query["$or"] = [
                {"assigned_to": user_email},
                {"co_assignees": user_email}
            ]
        
        lead = await db.leads.find_one(query)
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found or you don't have permission to update it"
            )
        
        # Migrate status value if needed
        new_status = migrate_status_value(status_update.status)
        old_status = lead.get("status")
        
        # Update the lead status
        update_data = {
            "status": new_status,
            "updated_at": datetime.utcnow()
        }
        
        result = await db.leads.update_one(
            {"lead_id": lead_id},
            {"$set": update_data}
        )
        
        if result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        # Log activity
        try:
            user_id = current_user.get("_id") or current_user.get("id")
            user_name = f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip()
            if not user_name:
                user_name = current_user.get('email', 'Unknown User')
            
            activity_doc = {
                "lead_object_id": lead["_id"],
                "lead_id": lead_id,
                "activity_type": "status_changed",
                "description": f"Status changed from '{old_status}' to '{new_status}'",
                "created_by": ObjectId(user_id) if ObjectId.is_valid(str(user_id)) else user_id,
                "created_by_name": user_name,
                "created_at": datetime.utcnow(),
                "is_system_generated": True,
                "metadata": {
                    "field": "status",
                    "old_value": old_status,
                    "new_value": new_status,
                    "notes": status_update.notes
                }
            }
            
            await db.lead_activities.insert_one(activity_doc)
            
        except Exception as activity_error:
            logger.error(f"Failed to log status change activity: {str(activity_error)}")
        
        logger.info(f"Lead {lead_id} status updated from '{old_status}' to '{new_status}' by {user_email}")
        
        return {
            "success": True,
            "message": f"Lead status updated to {new_status}",
            "lead_id": lead_id,
            "old_status": old_status,
            "new_status": new_status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update lead status error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update lead status"
        )

# ============================================================================
# HEALTH CHECK AND DEBUG ENDPOINTS
# ============================================================================

@router.get("/constants/experience-levels")
async def get_experience_levels():
    """
    Get all hardcoded experience levels from the ExperienceLevel enum
    
    Returns:
        List of experience levels with value and label
    """
    try:
        experience_levels = []
        for level in ExperienceLevel:
            # Convert enum values to readable labels
            label_map = {
                "fresher": "Fresher",
                "less_than_1_year": "Less than 1 Year", 
                "1_to_3_years": "1-3 Years",
                "3_to_5_years": "3-5 Years",
                "5_to_10_years": "5-10 Years",
                "more_than_10_years": "More than 10 Years"
            }
            
            experience_levels.append({
                "value": level.value,
                "label": label_map.get(level.value, level.value.replace("_", " ").title())
            })
        
        return {
            "success": True,
            "data": experience_levels,
            "total": len(experience_levels)
        }
    except Exception as e:
        logger.error(f"Error fetching experience levels: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch experience levels"
        )
    

@router.post("/{lead_id}/refresh-call-count", response_model=CallCountRefreshResponse)
async def refresh_lead_call_count(
    lead_id: str,
    force_refresh: bool = Query(False, description="Force refresh even if recently updated"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Refresh call count for a specific lead
    - Users can refresh leads assigned to them
    - Admins can refresh any lead
    """
    try:
        db = get_database()
        user_role = current_user.get("role", "user")
        user_email = current_user.get("email")
        
        # Check permissions
        if user_role != "admin":
            # Users can only refresh leads assigned to them (primary or co-assignee)
            lead = await db.leads.find_one({
                "lead_id": lead_id,
                "$or": [
                    {"assigned_to": user_email},
                    {"co_assignees": user_email}
                ]
            })
            if not lead:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Lead not found or you don't have permission to refresh it"
                )
        else:
            # Admin check - just verify lead exists
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Lead not found"
                )
        
        logger.info(f"Manual call count refresh requested for lead {lead_id} by {user_email}")
        
        # Use the call service to refresh
        result = await tata_call_service.refresh_lead_call_count(
            lead_id=lead_id,
            force_refresh=force_refresh
        )
        
        if result.get("success"):
            return CallCountRefreshResponse(
                success=True,
                message=result.get("message", "Call count refreshed successfully"),
                lead_id=lead_id,
                call_stats=result.get("call_stats"),
                refresh_time=datetime.utcnow()
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "Failed to refresh call count")
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing call count for lead {lead_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh call count: {str(e)}"
        )

@router.post("/bulk-refresh-call-counts", response_model=BulkCallCountRefreshResponse)
async def bulk_refresh_call_counts(
    request: BulkCallCountRefreshRequest,
    current_user: Dict[str, Any] = Depends(get_admin_user)  # Admin only for bulk operations
):
    """
    Bulk refresh call counts for multiple leads (Admin only)
    - Can refresh specific leads by ID
    - Can refresh all leads assigned to a user
    - Can refresh all leads if no filters specified
    """
    try:
        admin_email = current_user.get("email")
        logger.info(f"Bulk call count refresh requested by admin: {admin_email}")
        
        # Use the call service for bulk refresh
        result = await tata_call_service.bulk_refresh_call_counts(
            lead_ids=request.lead_ids,
            assigned_to_user=request.assigned_to_user,
            force_refresh=request.force_refresh,
            batch_size=request.batch_size
        )
        
        if result.get("success"):
            return BulkCallCountRefreshResponse(
                success=True,
                message=result.get("message", "Bulk refresh completed"),
                total_leads=result.get("total_leads", 0),
                successful_refreshes=result.get("successful_refreshes", 0),
                failed_refreshes=result.get("failed_refreshes", 0),
                processing_time=result.get("processing_time", 0),
                failed_lead_ids=result.get("failed_lead_ids", []),
                refresh_time=datetime.utcnow()
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "Bulk refresh failed")
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk call count refresh: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk refresh call counts: {str(e)}"
        )

@router.get("/{lead_id}/call-stats")
async def get_lead_call_stats(
    lead_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get call statistics for a specific lead
    - Shows total calls, answered calls, missed calls
    - Shows per-user breakdown
    - Users can view stats for leads assigned to them
    """
    try:
        db = get_database()
        user_role = current_user.get("role", "user")
        user_email = current_user.get("email")
        
        # Check permissions
        query = {"lead_id": lead_id}
        if user_role != "admin":
            query["$or"] = [
                {"assigned_to": user_email},
                {"co_assignees": user_email}
            ]
        
        lead = await db.leads.find_one(query)
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found or you don't have permission to view it"
            )
        
        call_stats = lead.get("call_stats")
        
        if not call_stats:
            return {
                "success": True,
                "lead_id": lead_id,
                "call_stats": None,
                "message": "No call statistics available. Click 'Refresh' to fetch call data.",
                "has_phone_number": bool(lead.get("contact_number") or lead.get("phone_number"))
            }
        
        # If user is not admin, filter user_calls to show only their own stats
        if user_role != "admin" and call_stats.get("user_calls"):
            current_user_id = str(current_user.get("_id") or current_user.get("user_id", ""))
            if current_user_id in call_stats["user_calls"]:
                user_specific_stats = {
                    **call_stats,
                    "user_calls": {current_user_id: call_stats["user_calls"][current_user_id]},
                    "your_calls": call_stats["user_calls"][current_user_id]
                }
            else:
                user_specific_stats = {
                    **call_stats,
                    "user_calls": {},
                    "your_calls": {"total": 0, "answered": 0, "missed": 0}
                }
            call_stats = user_specific_stats
        
        return {
            "success": True,
            "lead_id": lead_id,
            "call_stats": call_stats,
            "last_updated": call_stats.get("last_updated"),
            "phone_tracked": call_stats.get("phone_tracked")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting call stats for lead {lead_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get call statistics: {str(e)}"
        )
