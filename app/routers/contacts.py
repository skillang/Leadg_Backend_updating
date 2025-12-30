# app/routers/contacts.py - RBAC-Enabled Contact Management Router
# 🔄 UPDATED: Role checks replaced with RBAC permission checks (108 permissions)
# ✅ All endpoints now use permission-based access control

from fastapi import APIRouter, Depends, HTTPException, status, Query  
from typing import Dict, Any, List
import logging
from datetime import datetime

# Services
from app.services.contact_service import contact_service
from app.services.rbac_service import RBACService

# Dependencies
from app.utils.dependencies import (
    get_current_active_user,
    get_user_with_permission
)

# Decorators
from app.decorators.timezone_decorator import convert_dates_to_ist

# Models
from app.models.contact import (
    ContactCreate, 
    ContactUpdate, 
    ContactResponse, 
    ContactListResponse, 
    SetPrimaryContactRequest
)

# Database
from app.config.database import get_database

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# Initialize RBAC service
rbac_service = RBACService()


# ============================================================================
# RBAC HELPER FUNCTIONS
# ============================================================================

async def check_contact_access(contact: Dict, user_email: str, current_user: Dict) -> bool:
    """
    Check if user has access to a specific contact using RBAC
    
    Returns True if:
    - User has contact.view_all permission, OR
    - Contact's lead is assigned to user (primary or co-assignee)
    """
    # Check if user has view_all permission
    has_view_all = await rbac_service.check_permission(current_user, "contact.view_all")
    if has_view_all:
        return True
    
    # Check if user has access to the contact's lead
    db = get_database()
    lead_id = contact.get("lead_id")
    
    if not lead_id:
        return False
    
    lead = await db.leads.find_one({"lead_id": lead_id})
    if not lead:
        return False
    
    # Check if user is assigned to the lead (primary or co-assignee)
    assigned_to = lead.get("assigned_to")
    co_assignees = lead.get("co_assignees", [])
    
    return user_email in ([assigned_to] + co_assignees)


async def check_lead_access_for_contact(lead_id: str, user_email: str, current_user: Dict) -> bool:
    """
    Check if user has access to a lead (for contact operations)
    """
    # Check if user has view_all permission
    has_view_all = await rbac_service.check_permission(current_user, "contact.view_all")
    if has_view_all:
        return True
    
    # Check if user has access to the lead
    db = get_database()
    lead = await db.leads.find_one({"lead_id": lead_id})
    
    if not lead:
        return False
    
    # Check if user is assigned to the lead
    assigned_to = lead.get("assigned_to")
    co_assignees = lead.get("co_assignees", [])
    
    return user_email in ([assigned_to] + co_assignees)


# ============================================================================
# RBAC-ENABLED CONTACT CRUD OPERATIONS
# ============================================================================

@router.post("/leads/{lead_id}/contacts", status_code=status.HTTP_201_CREATED)
async def create_contact(
    lead_id: str,
    contact_data: ContactCreate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("contact.add"))
):
    """
    🔄 RBAC-ENABLED: Create a new contact for a specific lead
    
    **Required Permission:** `contact.add`
    
    Features:
    - Auto-logs activity to lead_activities collection
    - Handles duplicate prevention
    - Permission checking for lead access
    """
    try:
        # Check if user has access to this lead
        user_email = current_user.get("email")
        has_access = await check_lead_access_for_contact(lead_id, user_email, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to add contacts to this lead"
            )
        
        result = await contact_service.create_contact(lead_id, contact_data, current_user)
        
        return {
            "success": True,
            "data": result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in create_contact: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/leads/{lead_id}/contacts")
@convert_dates_to_ist()
async def get_lead_contacts(
    lead_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("contact.view"))
):
    """
    🔄 RBAC-ENABLED: Get all contacts for a specific lead with pagination
    
    **Required Permission:**
    - `contact.view` - See contacts for assigned leads
    - `contact.view_all` - See all contacts (admin)
    
    Returns contacts with summary statistics and lead info.
    """
    try:
        # Check if user has access to this lead
        user_email = current_user.get("email")
        has_access = await check_lead_access_for_contact(lead_id, user_email, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to view contacts for this lead"
            )
        
        result = await contact_service.get_lead_contacts(lead_id, current_user, page, limit)
        
        # Extract data from service result
        contacts = result["contacts"]
        total_count = result["total_count"]
        
        return {
            "success": True,
            "data": {
                "lead_id": result["lead_id"],
                "lead_info": result["lead_info"],
                "contacts": contacts,
                "primary_contact": result.get("primary_contact"),
                "contact_summary": result.get("contact_summary")
            },
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": (total_count + limit - 1) // limit,
                "has_next": page * limit < total_count,
                "has_prev": page > 1
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_lead_contacts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.patch("/{contact_id}/primary")
async def set_primary_contact(
    contact_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("contact.update"))
):
    """
    🔄 RBAC-ENABLED: Set a contact as the primary contact for their lead
    
    **Required Permission:** `contact.update`
    
    Removes primary status from other contacts for the same lead.
    """
    try:
        db = get_database()
        
        # Get the contact to check permissions
        contact = await db.contacts.find_one({"contact_id": contact_id})
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        
        # Check if user has access to this contact
        user_email = current_user.get("email")
        has_access = await check_contact_access(contact, user_email, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to modify this contact"
            )
        
        result = await contact_service.set_primary_contact(contact_id, current_user)
        
        return {
            "success": True,
            "data": result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in set_primary_contact: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/{contact_id}")
@convert_dates_to_ist()
async def get_contact(
    contact_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("contact.view"))
):
    """
    🔄 RBAC-ENABLED: Get a specific contact by ID
    
    **Required Permission:**
    - `contact.view` - See contacts for assigned leads
    - `contact.view_all` - See all contacts (admin)
    
    Includes all contact details and linked leads.
    """
    try:
        db = get_database()
        
        # Get the contact to check permissions
        contact = await db.contacts.find_one({"contact_id": contact_id})
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        
        # Check if user has access to this contact
        user_email = current_user.get("email")
        has_access = await check_contact_access(contact, user_email, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to view this contact"
            )
        
        result = await contact_service.get_contact_by_id(contact_id, current_user)
        
        return {
            "success": True,
            "data": result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_contact: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.put("/{contact_id}")
async def update_contact(
    contact_id: str,
    contact_data: ContactUpdate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("contact.update"))
):
    """
    🔄 RBAC-ENABLED: Update a contact's information
    
    **Required Permission:** `contact.update`
    
    Features:
    - Handles duplicate prevention
    - Permission checking for lead access
    - Auto-logs activity to lead_activities collection
    """
    try:
        db = get_database()
        
        # Get the contact to check permissions
        contact = await db.contacts.find_one({"contact_id": contact_id})
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        
        # Check if user has access to this contact
        user_email = current_user.get("email")
        has_access = await check_contact_access(contact, user_email, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to update this contact"
            )
        
        result = await contact_service.update_contact(contact_id, contact_data, current_user)
        
        return {
            "success": True,
            "data": result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in update_contact: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.delete("/{contact_id}")
async def delete_contact(
    contact_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("contact.delete"))
):
    """
    🔄 RBAC-ENABLED: Delete a contact
    
    **Required Permission:** `contact.delete`
    
    Features:
    - Auto-logs activity to lead_activities collection
    - Returns confirmation with deleted contact info
    """
    try:
        db = get_database()
        
        # Get the contact to check permissions
        contact = await db.contacts.find_one({"contact_id": contact_id})
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        
        # Check if user has access to this contact
        user_email = current_user.get("email")
        has_access = await check_contact_access(contact, user_email, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to delete this contact"
            )
        
        result = await contact_service.delete_contact(contact_id, current_user)
        
        return {
            "success": True,
            "data": result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in delete_contact: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


# ============================================================================
# STATISTICS ENDPOINT (RBAC-ENABLED)
# ============================================================================

@router.get("/stats")
@convert_dates_to_ist()
async def get_contact_statistics(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("contact.view"))
):
    """
    🔄 RBAC-ENABLED: Get contact statistics
    
    **Required Permission:** `contact.view`
    
    Statistics are filtered based on user's permission level:
    - contact.view: See stats for own lead contacts
    - contact.view_all: See all contact stats
    """
    try:
        db = get_database()
        user_email = current_user.get("email")
        
        # Build query based on permissions
        has_view_all = await rbac_service.check_permission(current_user, "contact.view_all")
        
        if has_view_all:
            # Admin - see all contacts
            base_query = {}
        else:
            # Regular user - only see contacts for assigned leads
            user_leads = await db.leads.find({
                "$or": [
                    {"assigned_to": user_email},
                    {"co_assignees": user_email}
                ]
            }, {"lead_id": 1}).to_list(None)
            
            user_lead_ids = [lead["lead_id"] for lead in user_leads]
            base_query = {"lead_id": {"$in": user_lead_ids}}
        
        # Get statistics
        total_contacts = await db.contacts.count_documents(base_query)
        
        # Get contacts by role
        role_pipeline = [
            {"$match": base_query},
            {"$group": {"_id": "$role", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        role_result = await db.contacts.aggregate(role_pipeline).to_list(None)
        contacts_by_role = {item["_id"]: item["count"] for item in role_result if item["_id"]}
        
        # Get contacts by relationship
        relationship_pipeline = [
            {"$match": base_query},
            {"$group": {"_id": "$relationship", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        relationship_result = await db.contacts.aggregate(relationship_pipeline).to_list(None)
        contacts_by_relationship = {item["_id"]: item["count"] for item in relationship_result if item["_id"]}
        
        # Get primary contacts count
        primary_query = {**base_query, "is_primary": True}
        primary_contacts = await db.contacts.count_documents(primary_query)
        
        return {
            "success": True,
            "data": {
                "total_contacts": total_contacts,
                "primary_contacts": primary_contacts,
                "contacts_by_role": contacts_by_role,
                "contacts_by_relationship": contacts_by_relationship,
                "user": user_email,
                "scope": "all" if has_view_all else "own_leads"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting contact statistics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get statistics: {str(e)}"
        )


# ============================================================================
# DEBUG & TESTING ENDPOINTS (Keep as-is - no RBAC needed)
# ============================================================================

@router.get("/debug/test")
@convert_dates_to_ist()
async def debug_test():
    """
    Debug endpoint to test contact service availability and database connectivity.
    Tests the health of the contact service.
    
    **No authentication required** - Debug endpoint
    """
    try:
        result = await contact_service.test_service()
        return {
            "success": True,
            "data": result,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Service test failed: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/debug/test-method")
@convert_dates_to_ist()
async def test_contact_method():
    """
    Debug endpoint to test method existence.
    Verifies all required contact service methods are available.
    
    **No authentication required** - Debug endpoint
    """
    try:
        result = await contact_service.test_method_existence()
        return {
            "success": True,
            "data": result,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Method test failed: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/health")
@convert_dates_to_ist()
async def health_check():
    """
    Simple health check endpoint for monitoring.
    Returns basic service status and version info.
    
    **No authentication required** - Health check endpoint
    """
    return {
        "status": "healthy",
        "service": "contact_service",
        "rbac_enabled": True,
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0.0",
        "endpoints": {
            "create_contact": "POST /leads/{lead_id}/contacts [contact.add]",
            "get_lead_contacts": "GET /leads/{lead_id}/contacts [contact.view]", 
            "get_contact": "GET /{contact_id} [contact.view]",
            "update_contact": "PUT /{contact_id} [contact.update]",
            "delete_contact": "DELETE /{contact_id} [contact.delete]",
            "set_primary_contact": "PATCH /{contact_id}/primary [contact.update]",
            "get_statistics": "GET /stats [contact.view]",
            "debug_test": "GET /debug/test [no auth]",
            "test_methods": "GET /debug/test-method [no auth]",
            "health_check": "GET /health [no auth]"
        },
        "required_permissions": [
            "contact.add",
            "contact.view",
            "contact.view_all",
            "contact.update",
            "contact.delete"
        ]
    }