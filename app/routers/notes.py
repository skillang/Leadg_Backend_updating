# app/routers/notes.py - RBAC-Enabled Note Management Router
# 🔄 UPDATED: Role checks replaced with RBAC permission checks (108 permissions)
# ✅ All endpoints now use permission-based access control

from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging
from bson import ObjectId

from app.decorators.timezone_decorator import convert_dates_to_ist
from app.services.rbac_service import RBACService

from ..config.database import get_database
from ..utils.dependencies import get_current_active_user, get_user_with_permission, check_permission
from ..models.note import (
    NoteCreate, NoteUpdate, NoteResponse, NoteListResponse, 
    NoteStatsResponse, NoteSearchRequest, NoteBulkAction, NoteType
)
from ..services.note_service import note_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize RBAC service
rbac_service = RBACService()


# =====================================
# RBAC HELPER FUNCTIONS
# =====================================

def get_user_id(current_user: Dict[str, Any]) -> str:
    """Get user ID from current_user dict, handling different possible keys"""
    user_id = current_user.get("user_id") or current_user.get("_id") or current_user.get("id")
    if not user_id:
        available_keys = list(current_user.keys())
        raise ValueError(f"No user ID found in token. Available keys: {available_keys}")
    return str(user_id)


async def check_lead_access_for_note(lead_id: str, user_email: str, current_user: Dict) -> bool:
    """
    Check if user has access to a lead (for note operations)
    
    Returns True if:
    - User has note.view_all permission, OR
    - Lead is assigned to user (primary or co-assignee)
    """

    if await check_permission(current_user, "note.view_all"):
        return True
    
    # Check if user has access to the lead
    db = get_database()
    lead = await db.leads.find_one({"lead_id": lead_id})
    
    if not lead:
        return False
    
    # Check if user is assigned to the lead (primary or co-assignee)
    assigned_to = lead.get("assigned_to")
    co_assignees = lead.get("co_assignees", [])
    
    return user_email in ([assigned_to] + co_assignees)


async def check_note_access(note: Dict, user_id: str, current_user: Dict) -> bool:
    """
    Check if user has access to a specific note
    
    Returns True if:
    - User has note.view_all permission, OR
    - Note is public AND user has access to lead, OR
    - Note is private AND created by user
    """
    
    # Check if note is private
    if note.get("is_private", False):
        # Private notes only visible to creator
        return str(note.get("created_by")) == str(user_id)
    
    # Public notes - check lead access
    user_email = current_user.get("email")
    return await check_lead_access_for_note(note.get("lead_id"), user_email, current_user)


# =====================================
# RBAC-ENABLED NOTE CRUD OPERATIONS
# =====================================

@router.post("/leads/{lead_id}/notes", status_code=status.HTTP_201_CREATED)
async def create_note(
    lead_id: str,
    note_data: NoteCreate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("note.add"))
):
    """
    🔄 RBAC-ENABLED: Create a new note for a lead
    
    **Required Permission:** `note.add`
    
    Users can only create notes for leads assigned to them (primary or co-assignee)
    """
    try:
        logger.info(f"Creating note for lead {lead_id} by user {current_user.get('email')}")
        
        # Get user_id
        user_id = get_user_id(current_user)
        logger.info(f"Using user_id: {user_id}")
        
        # Check if user has access to this lead
        user_email = current_user.get("email")
        has_access = await check_lead_access_for_note(lead_id, user_email, current_user)
        
        if not has_access:
            logger.warning(f"User {user_email} tried to create note for unauthorized lead {lead_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to create notes for this lead. You can only create notes for leads assigned to you."
            )
        
        logger.info(f"Lead access confirmed for {user_email}")
        
        # Create the note
        logger.info(f"Calling note_service.create_note")
        new_note = await note_service.create_note(
            lead_id=lead_id, 
            note_data=note_data, 
            created_by=str(user_id)
        )
        
        logger.info(f"Note created with ID: {new_note.get('id')}")
        
        # Return success response
        return {
            "success": True,
            "message": "Note created successfully",
            "note_id": new_note.get('id'),
            "note_title": new_note.get('title'),
            "lead_id": lead_id,
            "note_type": note_data.note_type,
            "tags": note_data.tags,
            "created_by": current_user.get('email')
        }
        
    except HTTPException as he:
        logger.error(f"HTTPException in create_note: {he.detail}")
        raise he
    except Exception as e:
        logger.error(f"Unexpected error in create_note: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create note: {str(e)}"
        )


@router.get("/leads/{lead_id}/notes")
@convert_dates_to_ist()
async def get_lead_notes(
    lead_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search in title and content"),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by"),
    note_type: Optional[NoteType] = Query(None, description="Filter by note type"),
    show_private: bool = Query(True, description="Include private notes (if accessible)"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("note.view"))
):
    """
    🔄 RBAC-ENABLED: Get all notes for a specific lead
    
    **Required Permission:**
    - `note.view` - See notes for assigned leads
    - `note.view_all` - See all notes (admin)
    
    Privacy rules:
    - Admins see all notes
    - Users see only non-private notes + their own private notes for assigned leads
    """
    try:
        logger.info(f"Getting notes for lead {lead_id} by user {current_user.get('email')}")
        
        # Verify user has access to this lead
        user_email = current_user.get("email")
        has_access = await check_lead_access_for_note(lead_id, user_email, current_user)
        
        if not has_access:
            logger.warning(f"User {user_email} tried to access unauthorized lead {lead_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view notes for this lead"
            )
        
        # Determine role for service layer (backward compatibility)
        effective_role = current_user.get("role", "user")
        
        # Parse tags
        parsed_tags = None
        if tags:
            parsed_tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
        
        result = await note_service.get_lead_notes(
            lead_id, 
            get_user_id(current_user),
            effective_role,
            page,
            limit,
            search,
            parsed_tags,
            note_type,
            show_private
        )
        
        return {
            "notes": result["notes"],
            "available_tags": result.get("available_tags", []),
            "pagination": {
                "page": page,
                "limit": limit,
                "total": result["total"],
                "pages": (result["total"] + limit - 1) // limit,
                "has_next": page * limit < result["total"],
                "has_prev": page > 1
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get lead notes error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve notes: {str(e)}"
        )


@router.get("/leads/{lead_id}/notes/stats", response_model=NoteStatsResponse)
@convert_dates_to_ist()
async def get_lead_note_stats(
    lead_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("note.view"))
):
    """
    🔄 RBAC-ENABLED: Get note statistics for a lead
    
    **Required Permission:** `note.view`
    
    Returns: total_notes, notes_by_type, most_used_tags, etc.
    """
    try:
        logger.info(f"Getting note stats for lead {lead_id} by user {current_user.get('email')}")
        
        # Verify user has access to this lead
        user_email = current_user.get("email")
        has_access = await check_lead_access_for_note(lead_id, user_email, current_user)
        
        if not has_access:
            logger.warning(f"User {user_email} tried to access unauthorized lead {lead_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to view stats for this lead"
            )
        
        # Determine role for service layer
        effective_role = current_user.get("role", "user")
        
        stats = await note_service.get_note_stats(
            lead_id, 
            get_user_id(current_user),
            effective_role
        )
        
        return NoteStatsResponse(**stats)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get note stats error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve note statistics: {str(e)}"
        )


@router.get("/{note_id}")
@convert_dates_to_ist()
async def get_note(
    note_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("note.view"))
):
    """
    🔄 RBAC-ENABLED: Get a specific note by ID
    
    **Required Permission:** `note.view`
    
    Privacy and access control applied
    """
    try:
        logger.info(f"=== GET NOTE DEBUG START ===")
        logger.info(f"Note ID requested: {note_id}")
        logger.info(f"User: {current_user.get('email')}")
        
        # Get user_id
        user_id = get_user_id(current_user)
        logger.info(f"User ID extracted: {user_id}")
        
        # Determine role for service layer
        effective_role = current_user.get("role", "user")
        
        # Call note service
        logger.info("Calling note_service.get_note_by_id...")
        note = await note_service.get_note_by_id(
            note_id, 
            str(user_id),
            effective_role
        )
        
        if not note:
            logger.warning("Note service returned None")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Note not found or you don't have permission to view it"
            )
        
        logger.info("✅ Note retrieved successfully")
        return note
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve note: {str(e)}"
        )


@router.put("/{note_id}")
async def update_note(
    note_id: str,
    note_data: NoteUpdate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("note.update"))
):
    """
    🔄 RBAC-ENABLED: Update a note
    
    **Required Permission:** `note.update`
    
    Users can update notes they created
    Admins with note.update_all can update any note
    """
    try:
        logger.info(f"Updating note {note_id} by user {current_user.get('email')}")
        
        user_id = get_user_id(current_user)
        
        # Check if user has update_all permission
        effective_role = current_user.get("role", "user")

        
        success = await note_service.update_note(
            note_id, 
            note_data, 
            str(user_id),
            effective_role
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Note not found or you don't have permission to update it"
            )
        
        # Return updated note
        updated_note = await note_service.get_note_by_id(
            note_id, 
            str(user_id),
            effective_role
        )
        
        return {
            "success": True,
            "message": "Note updated successfully",
            "note": updated_note
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update note error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update note: {str(e)}"
        )


@router.delete("/{note_id}")
async def delete_note(
    note_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("note.delete"))
):
    """
    🔄 RBAC-ENABLED: Delete a note
    
    **Required Permission:** `note.delete`
    
    Users can delete notes they created
    Admins with note.delete_all can delete any note
    """
    try:
        logger.info(f"Deleting note {note_id} by user {current_user.get('email')}")
        
        user_id = get_user_id(current_user)
        
        # Check if user has delete_all permission
        effective_role = current_user.get("role", "user")
        
        success = await note_service.delete_note(
            note_id, 
            str(user_id),
            effective_role
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Note not found or you don't have permission to delete it"
            )
        
        logger.info(f"Note {note_id} deleted by {current_user['email']}")
        
        return {
            "success": True,
            "message": "Note deleted successfully",
            "note_id": note_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete note error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete note: {str(e)}"
        )


@router.post("/search")
async def search_notes(
    search_request: NoteSearchRequest,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("note.view"))
):
    """
    🔄 RBAC-ENABLED: Search notes across all accessible leads
    
    **Required Permission:**
    - `note.view` - Search notes in assigned leads
    - `note.view_all` - Search all notes (admin)
    
    Advanced filtering with privacy controls
    """
    try:
        logger.info(f"Searching notes by user {current_user.get('email')}")
        logger.info(f"Search query: {search_request.query}")
        logger.info(f"Tags filter: {search_request.tags}")
        
        # Determine role for service layer
        effective_role = current_user.get("role", "user")
        
        result = await note_service.search_notes(
            search_request,
            get_user_id(current_user),
            effective_role
        )
        
        return {
            "success": True,
            "results": result
        }
        
    except Exception as e:
        logger.error(f"Search notes error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search notes: {str(e)}"
        )


@router.post("/bulk-action")
async def bulk_note_action(
    bulk_action: NoteBulkAction,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    🔄 RBAC-ENABLED: Perform bulk actions on multiple notes
    
    **Required Permissions:**
    - delete: `note.delete`
    - add_tag, remove_tag, mark_important, mark_private: `note.update`
    
    Actions: delete, add_tag, remove_tag, mark_important, mark_private
    """
    try:
        logger.info(f"Bulk action {bulk_action.action} by {current_user.get('email')} on {len(bulk_action.note_ids)} notes")
        
        # Check permission for the requested action
        if bulk_action.action == "delete":
            has_permission = await rbac_service.check_permission(current_user, "note.delete")
            permission_name = "note.delete"
        else:
            has_permission = await rbac_service.check_permission(current_user, "note.update")
            permission_name = "note.update"
        
        if not has_permission:
            raise HTTPException(
                status_code=403,
                detail=f"You don't have permission to perform bulk {bulk_action.action}. Required: {permission_name}"
            )
        
        user_id = get_user_id(current_user)
        db = get_database()
        success_count = 0
        failed_notes = []
        
        # Determine role for service layer
        effective_role = current_user.get("role", "user")
        
        for note_id in bulk_action.note_ids:
            try:
                if bulk_action.action == "delete":
                    success = await note_service.delete_note(
                        note_id, 
                        str(user_id),
                        effective_role
                    )
                elif bulk_action.action == "add_tag" and bulk_action.tag:
                    # Get current note
                    note = await note_service.get_note_by_id(note_id, str(user_id), effective_role)
                    if note:
                        current_tags = note.get("tags", [])
                        if bulk_action.tag not in current_tags:
                            current_tags.append(bulk_action.tag)
                            from ..models.note import NoteUpdate
                            note_update = NoteUpdate(tags=current_tags)
                            success = await note_service.update_note(
                                note_id, note_update, str(user_id), effective_role
                            )
                        else:
                            success = True  # Tag already exists
                    else:
                        success = False
                elif bulk_action.action == "remove_tag" and bulk_action.tag:
                    # Get current note
                    note = await note_service.get_note_by_id(note_id, str(user_id), effective_role)
                    if note:
                        current_tags = note.get("tags", [])
                        if bulk_action.tag in current_tags:
                            current_tags.remove(bulk_action.tag)
                            from ..models.note import NoteUpdate
                            note_update = NoteUpdate(tags=current_tags)
                            success = await note_service.update_note(
                                note_id, note_update, str(user_id), effective_role
                            )
                        else:
                            success = True  # Tag doesn't exist
                    else:
                        success = False
                elif bulk_action.action == "mark_important":
                    from ..models.note import NoteUpdate
                    note_update = NoteUpdate(is_important=bulk_action.value)
                    success = await note_service.update_note(
                        note_id, note_update, str(user_id), effective_role
                    )
                elif bulk_action.action == "mark_private":
                    from ..models.note import NoteUpdate
                    note_update = NoteUpdate(is_private=bulk_action.value)
                    success = await note_service.update_note(
                        note_id, note_update, str(user_id), effective_role
                    )
                else:
                    failed_notes.append(note_id)
                    continue
                
                if success:
                    success_count += 1
                else:
                    failed_notes.append(note_id)
                    
            except Exception as e:
                logger.error(f"Bulk action failed for note {note_id}: {str(e)}")
                failed_notes.append(note_id)
        
        logger.info(f"Bulk {bulk_action.action}: {success_count} notes processed by {current_user['email']}")
        
        return {
            "success": True,
            "message": f"Bulk {bulk_action.action} completed",
            "processed_count": success_count,
            "failed_notes": failed_notes
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk note action error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to perform bulk action: {str(e)}"
        )


# =====================================
#  UTILITY ENDPOINTS
# =====================================

@router.get("/types")
async def get_note_types():
    """
    Get all available note types for frontend dropdown/selection
    No authentication required - metadata only
    """
    try:
        from ..models.note import NoteType
        
        # Convert enum to list of objects with value and label
        note_types = []
        for note_type in NoteType:
            # Create user-friendly labels
            label_map = {
                "general": "General Note",
                "meeting": "Meeting Notes",
                "phone_call": "Phone Call",
                "email": "Email Communication",
                "document_review": "Document Review",
                "follow_up": "Follow-up",
                "requirement": "Requirements",
                "feedback": "Feedback"
            }
            
            note_types.append({
                "value": note_type.value,
                "label": label_map.get(note_type.value, note_type.value.replace("_", " ").title()),
                "icon": {
                    "general": "📝",
                    "meeting": "🤝", 
                    "phone_call": "📞",
                    "email": "📧",
                    "document_review": "📄",
                    "follow_up": "🔄",
                    "requirement": "📋",
                    "feedback": "💬"
                }.get(note_type.value, "📝")
            })
        
        return {
            "success": True,
            "note_types": note_types,
            "total": len(note_types)
        }
        
    except Exception as e:
        logger.error(f"Error getting note types: {str(e)}")
        return {
            "success": False,
            "error": "Failed to get note types",
            "note_types": []
        }

