# app/services/note_service.py
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from bson import ObjectId
import logging
from collections import Counter

from ..config.database import get_database
from ..models.note import NoteCreate, NoteUpdate, NoteType, NoteSearchRequest
# from ..models.lead import LeadStatus

logger = logging.getLogger(__name__)

class NoteService:
    def __init__(self):
        pass
    
    async def create_note(self, lead_id: str, note_data: NoteCreate, created_by: str) -> Dict[str, Any]:
        """Create a new note for a lead with auto-activity logging"""
        try:
            logger.info(f"Creating note for lead_id: {lead_id}")
            logger.info(f"Note data: {note_data.dict()}")
            
            # Direct database call (following established pattern)
            db = get_database()  # ✅ No await
            
            # Verify lead exists
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                raise ValueError(f"Lead {lead_id} not found")
            
            logger.info(f"Lead found: {lead.get('name', 'N/A')}")
            
            # Get creator name
            creator = await db.users.find_one({"_id": ObjectId(created_by)})
            created_by_name = "Unknown User"
            if creator:
                first_name = creator.get('first_name', '')
                last_name = creator.get('last_name', '')
                if first_name and last_name:
                    created_by_name = f"{first_name} {last_name}".strip()
                else:
                    created_by_name = creator.get('email', 'Unknown User')
            
            logger.info(f"Creator: {created_by_name}")
            
            # Create note document
            note_doc = {
                "lead_id": lead["lead_id"],
                "lead_object_id": lead["_id"],
                "title": note_data.title,
                "content": note_data.content,
                "note_type": note_data.note_type,
                "tags": note_data.tags or [],
                "is_important": note_data.is_important,
                "is_private": note_data.is_private,
                "created_by": ObjectId(created_by),
                "created_by_name": created_by_name,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "updated_by": None,
                "updated_by_name": None
            }
            
            logger.info(f"Note document prepared for insert")
            
            # Insert note
            result = await db.lead_notes.insert_one(note_doc)
            note_doc["id"] = str(result.inserted_id)
            note_doc["_id"] = str(result.inserted_id)
            
            logger.info(f"Note created successfully: {note_doc['id']}")
            
            # 🔥 AUTO-ACTIVITY LOGGING (following established pattern)
            try:
                # Check if activity already exists to prevent duplicates
                existing_activity = await db.lead_activities.find_one({
                    "lead_id": lead["lead_id"],
                    "activity_type": "note_added",
                    "metadata.note_id": str(result.inserted_id)
                })
                
                if not existing_activity:
                    activity_doc = {
                        "lead_id": lead["lead_id"],  # ✅ String reference
                        "activity_type": "note_added",
                        "description": f"Note '{note_data.title}' added ({note_data.note_type})",
                        "created_by": ObjectId(created_by),
                        "created_by_name": created_by_name,
                        "created_at": datetime.utcnow(),
                        "is_system_generated": True,
                        "metadata": {
                            "note_id": str(result.inserted_id),
                            "note_title": note_data.title,
                            "note_type": note_data.note_type,
                            "tags": note_data.tags,
                            "is_important": note_data.is_important
                        }
                    }
                    await db.lead_activities.insert_one(activity_doc)
                    logger.info("✅ Activity logged successfully")
                else:
                    logger.info("⚠️ Activity already exists, skipping duplicate")
            except Exception as activity_error:
                logger.warning(f"⚠️ Failed to log activity: {activity_error}")
                # Don't fail the whole note creation if activity logging fails
            
            return note_doc
            
        except Exception as e:
            logger.error(f"❌ Error creating note: {str(e)}")
            logger.error(f"Error type: {type(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise Exception(f"Failed to create note: {str(e)}")
    
    async def get_lead_notes(self, lead_id: str, user_id: str, user_role: str, 
                           page: int = 1, limit: int = 20, 
                           search: Optional[str] = None, 
                           tags: Optional[List[str]] = None,
                           note_type: Optional[NoteType] = None,
                           show_private: bool = True) -> Dict[str, Any]:
        """Get all notes for a lead with filtering"""
        try:
            logger.info(f"Getting notes for lead: {lead_id}, user: {user_id}, role: {user_role}")
            
            db = get_database()  # ✅ No await
            
            # Get lead first to get ObjectId
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                raise ValueError(f"Lead {lead_id} not found")
            
            # Build query using lead ObjectId
            query = {"lead_object_id": lead["_id"]}
            
            # Privacy filtering - non-creators can't see private notes unless admin
            if user_role != "admin" and not show_private:
                query["$or"] = [
                    {"is_private": False},
                    {"created_by": ObjectId(user_id)}
                ]
            
            # Search filtering
            if search:
                search_conditions = [
                    {"title": {"$regex": search, "$options": "i"}},
                    {"content": {"$regex": search, "$options": "i"}}
                ]
                if "$or" in query:
                    # Combine with existing OR condition
                    query = {"$and": [query, {"$or": search_conditions}]}
                else:
                    query["$or"] = search_conditions
            
            # Tags filtering
            if tags:
                query["tags"] = {"$in": tags}
            
            # Note type filtering
            if note_type:
                query["note_type"] = note_type
            
            logger.info(f"Query: {query}")
            
            # Count total documents
            total = await db.lead_notes.count_documents(query)
            
            # Calculate pagination
            skip = (page - 1) * limit
            has_next = skip + limit < total
            has_prev = page > 1
            
            # Get notes with pagination
            notes_cursor = db.lead_notes.find(query).sort("created_at", -1).skip(skip).limit(limit)
            notes = await notes_cursor.to_list(None)
            
            logger.info(f"Found {len(notes)} notes")
            
            # ✅ Enrich notes (convert ObjectIds to strings)
            enriched_notes = []
            for note in notes:
                processed_note = {
                    "id": str(note["_id"]),
                    "lead_id": note.get("lead_id", ""),
                    "title": note.get("title", ""),
                    "content": note.get("content", ""),
                    "note_type": note.get("note_type", "general"),
                    "tags": note.get("tags", []),
                    "is_important": note.get("is_important", False),
                    "is_private": note.get("is_private", False),
                    "created_by": str(note.get("created_by", "")),
                    "created_by_name": note.get("created_by_name", "Unknown"),
                    "created_at": note.get("created_at"),
                    "updated_at": note.get("updated_at"),
                    "updated_by": str(note.get("updated_by", "")) if note.get("updated_by") else None,
                    "updated_by_name": note.get("updated_by_name"),
                    "lead_object_id": str(note.get("lead_object_id", ""))
                }
                enriched_notes.append(processed_note)
            
            # Get available tags for this lead
            available_tags = await self._get_lead_available_tags(lead["_id"])
            
            return {
                "notes": enriched_notes,
                "total": total,
                "page": page,
                "limit": limit,
                 "pages": (total + limit - 1) // limit, 
                "has_next": has_next,
                "has_prev": has_prev,
                "available_tags": available_tags
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting lead notes: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise Exception(f"Failed to get lead notes: {str(e)}")

    async def get_note_by_id(self, note_id: str, user_id: str, user_role: str) -> Optional[Dict[str, Any]]:
        """Get a specific note by ID with access control - FIXED VERSION"""
        try:
            logger.info(f"=== GET_NOTE_BY_ID DEBUG START ===")
            logger.info(f"Note ID: {note_id}")
            logger.info(f"User ID: {user_id}")
            logger.info(f"User Role: {user_role}")
            
            db = get_database()
            
            # Step 1: Validate ObjectId format
            try:
                note_object_id = ObjectId(note_id)
                logger.info(f"✅ Valid ObjectId: {note_object_id}")
            except Exception as oid_error:
                logger.error(f"❌ Invalid ObjectId format: {note_id}, Error: {oid_error}")
                return None
            
            # Step 2: Get note from database
            logger.info(f"Querying database for note...")
            note = await db.lead_notes.find_one({"_id": note_object_id})
            
            if not note:
                logger.warning(f"❌ Note not found in database: {note_id}")
                return None
            
            logger.info(f"✅ Note found: {note.get('title', 'No title')}")
            
            # Step 3: Check privacy access control
            if note.get("is_private") and user_role != "admin":
                note_creator = str(note.get("created_by", ""))
                if note_creator != str(user_id):
                    logger.warning(f"❌ Private note access denied - Creator: {note_creator}, User: {user_id}")
                    return None
            
            # Step 4: Check lead access control (user can only see notes for assigned leads)

            if user_role != "admin":
                try:
                    lead = await db.leads.find_one({
                        "_id": note["lead_object_id"]
                    })
                    if lead:
                        lead_assigned_to = str(lead.get("assigned_to", ""))
                        lead_co_assignees = lead.get("co_assignees", [])  # 🆕 ADDED
                        
                        # Get user info to check email
                        user_info = await db.users.find_one({"_id": ObjectId(user_id)})
                        user_email = user_info.get("email", "") if user_info else ""
                        
                        logger.info(f"Lead assigned to: {lead_assigned_to}")
                        logger.info(f"Lead co-assignees: {lead_co_assignees}")  # 🆕 ADDED
                        logger.info(f"User email: {user_email}")
                        
                        # ✅ FIXED: Check BOTH assigned_to AND co_assignees
                        has_lead_access = (
                            lead_assigned_to == user_email or 
                            user_email in lead_co_assignees
                        )
                        
                        if not has_lead_access:
                            logger.warning(f"❌ Lead access denied - User: {user_email}, Assigned to: {lead_assigned_to}, Co-assignees: {lead_co_assignees}")
                            return None
                    else:
                        logger.warning(f"❌ Lead not found for note")
                        return None
                except Exception as lead_check_error:
                    logger.error(f"❌ Error checking lead access: {lead_check_error}")
                    # For admin fallback, allow access if lead check fails
                    if user_role != "admin":
                        return None
            
            # Step 5: Convert ObjectIds to strings for JSON response
            try:
                processed_note = {
                    "id": str(note["_id"]),
                    "lead_id": note.get("lead_id", ""),
                    "title": note.get("title", ""),
                    "content": note.get("content", ""),
                    "note_type": note.get("note_type", "general"),
                    "tags": note.get("tags", []),
                    "is_important": note.get("is_important", False),
                    "is_private": note.get("is_private", False),
                    "created_by": str(note.get("created_by", "")),
                    "created_by_name": note.get("created_by_name", "Unknown"),
                    "created_at": note.get("created_at"),
                    "updated_at": note.get("updated_at"),
                    "updated_by": str(note.get("updated_by", "")) if note.get("updated_by") else None,
                    "updated_by_name": note.get("updated_by_name"),
                    "lead_object_id": str(note.get("lead_object_id", ""))
                }
                
                logger.info(f"✅ Note processed successfully")
                return processed_note
                
            except Exception as process_error:
                logger.error(f"❌ Error processing note data: {process_error}")
                # Return basic note data even if processing fails
                return {
                    "id": str(note["_id"]),
                    "title": note.get("title", ""),
                    "content": note.get("content", ""),
                    "error": "Some fields may be missing due to processing error"
                }
            
        except Exception as e:
            logger.error(f"❌ Unexpected error in get_note_by_id: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    async def update_note(self, note_id: str, note_data: NoteUpdate, user_id: str, user_role: str) -> bool:
            """Update a note with detailed auto-activity logging - FIXED ACCESS CONTROL"""
            try:
                db = get_database()
                
                # Get current note for access control
                current_note = await db.lead_notes.find_one({"_id": ObjectId(note_id)})
                if not current_note:
                    return False
                
                # 🔑 LEAD-BASED ACCESS CONTROL (similar to tasks)
                if user_role != "admin":
                    # Get the lead for this note
                    lead = await db.leads.find_one({"lead_id": current_note["lead_id"]})
                    if not lead:
                        return False
                    
                    # Get user info to check email
                    user_info = await db.users.find_one({"_id": ObjectId(user_id)})
                    if not user_info:
                        return False
                    
                    user_email = user_info.get("email", "")
                    lead_assigned_to = lead.get("assigned_to", "")
                    lead_co_assignees = lead.get("co_assignees", [])
                    
                    # Check if user has access to this lead OR is the note creator (for private notes)
                    note_creator = str(current_note.get("created_by", ""))
                    has_lead_access = (
                        lead_assigned_to == user_email or 
                        user_email in lead_co_assignees or
                        note_creator == str(user_id)  # Allow note creator to edit their own notes
                    )
                    
                    if not has_lead_access:
                        logger.warning(f"User {user_email} has no access to note {note_id}")
                        return False
                
                # Prepare update data and track changes with detailed information
                update_data = {}
                changes = []  # Track detailed changes for timeline
                
                # Field mapping for better display names
                field_display_names = {
                    "title": "Title",
                    "content": "Content", 
                    "note_type": "Type",
                    "tags": "Tags",
                    "is_important": "Importance",
                    "is_private": "Privacy"
                }
                
                for field, value in note_data.dict(exclude_unset=True).items():
                    if value is not None:
                        old_value = current_note.get(field)
                        display_name = field_display_names.get(field, field.replace('_', ' ').title())
                        
                        # Handle different field types
                        if field == "tags":
                            # Handle tags array - show added/removed tags
                            old_tags = set(old_value or [])
                            new_tags = set(value or [])
                            
                            if old_tags != new_tags:
                                update_data[field] = value
                                added_tags = new_tags - old_tags
                                removed_tags = old_tags - new_tags
                                
                                tag_changes = []
                                if added_tags:
                                    tag_changes.append(f"added {', '.join(sorted(added_tags))}")
                                if removed_tags:
                                    tag_changes.append(f"removed {', '.join(sorted(removed_tags))}")
                                
                                if tag_changes:
                                    changes.append(f"{display_name}: {'; '.join(tag_changes)}")
                                    
                        elif field == "is_important":
                            # Handle boolean importance flag
                            if old_value != value:
                                update_data[field] = value
                                old_display = "Important" if old_value else "Normal"
                                new_display = "Important" if value else "Normal"
                                changes.append(f"{display_name}: {old_display} → {new_display}")
                                
                        elif field == "is_private":
                            # Handle boolean privacy flag
                            if old_value != value:
                                update_data[field] = value
                                old_display = "Private" if old_value else "Public"
                                new_display = "Private" if value else "Public"
                                changes.append(f"{display_name}: {old_display} → {new_display}")
                                
                        elif field == "content":
                            # Handle content changes - show truncated preview
                            if old_value != value:
                                update_data[field] = value
                                old_preview = (old_value[:50] + "...") if old_value and len(str(old_value)) > 50 else (old_value or "Empty")
                                new_preview = (value[:50] + "...") if value and len(str(value)) > 50 else value
                                changes.append(f"{display_name}: '{old_preview}' → '{new_preview}'")
                                
                        else:
                            # Handle other fields (title, note_type, etc.)
                            if old_value != value:
                                update_data[field] = value
                                old_display = str(old_value) if old_value else "Not set"
                                new_display = str(value)
                                changes.append(f"{display_name}: '{old_display}' → '{new_display}'")
                
                if not update_data:
                    return True  # No changes needed
                
                # Get updater name
                updater = await db.users.find_one({"_id": ObjectId(user_id)})
                updated_by_name = "Unknown User"
                if updater:
                    first_name = updater.get('first_name', '')
                    last_name = updater.get('last_name', '')
                    if first_name and last_name:
                        updated_by_name = f"{first_name} {last_name}".strip()
                    else:
                        updated_by_name = updater.get('email', 'Unknown User')
                
                update_data.update({
                    "updated_at": datetime.utcnow(),
                    "updated_by": ObjectId(user_id),
                    "updated_by_name": updated_by_name
                })
                
                # Update note
                result = await db.lead_notes.update_one(
                    {"_id": ObjectId(note_id)}, 
                    {"$set": update_data}
                )
                
                if result.modified_count > 0 and changes:
                    # Enhanced AUTO-ACTIVITY LOGGING with detailed changes
                    try:
                        # Check for duplicate activity
                        existing_activity = await db.lead_activities.find_one({
                            "lead_id": current_note["lead_id"],
                            "activity_type": "note_updated",
                            "metadata.note_id": note_id,
                            "created_at": {"$gte": datetime.utcnow() - timedelta(seconds=10)}
                        })
                        
                        if not existing_activity:
                            # Create detailed description with changes
                            changes_text = "; ".join(changes[:5])  # Limit to first 5 changes
                            if len(changes) > 5:
                                changes_text += f" (+{len(changes) - 5} more)"
                            
                            description = f"Note '{current_note['title']}' updated by {updated_by_name}. Changes: {changes_text}"
                            
                            activity_doc = {
                                "lead_id": current_note["lead_id"],
                                "activity_type": "note_updated",
                                "title": f"Note Updated: {current_note['title']}",
                                "description": description,  # Now includes the changes
                                "created_by": ObjectId(user_id),
                                "created_by_name": updated_by_name,
                                "created_at": datetime.utcnow(),
                                "updated_at": datetime.utcnow(),
                                "is_system_generated": True,
                                "metadata": {
                                    "note_id": note_id,
                                    "note_title": current_note['title'],
                                    "changes": changes,  # Full list of changes
                                    "changes_count": len(changes),
                                    "updated_by": updated_by_name,
                                    "updated_fields": list(update_data.keys())  # Keep for backward compatibility
                                }
                            }
                            await db.lead_activities.insert_one(activity_doc)
                            logger.info(f"✅ Note update activity logged with {len(changes)} changes")
                        else:
                            logger.info("⚠️ Recent update activity exists, skipping duplicate")
                            
                    except Exception as activity_error:
                        logger.warning(f"⚠️ Failed to log note update activity: {activity_error}")
                
                return result.modified_count > 0
                
            except Exception as e:
                logger.error(f"❌ Error updating note: {str(e)}")
                return False

    async def delete_note(self, note_id: str, user_id: str, user_role: str) -> bool:
        """Delete a note with auto-activity logging"""
        try:
            db = get_database()
            
            # Get note for access control and activity logging
            note = await db.lead_notes.find_one({"_id": ObjectId(note_id)})
            if not note:
                return False
            
            # Access control - only creator or admin can delete
            if user_role != "admin" and str(note.get("created_by")) != str(user_id):
                return False
            
            # Get deleter name
            deleter = await db.users.find_one({"_id": ObjectId(user_id)})
            deleted_by_name = "Unknown User"
            if deleter:
                first_name = deleter.get('first_name', '')
                last_name = deleter.get('last_name', '')
                if first_name and last_name:
                    deleted_by_name = f"{first_name} {last_name}".strip()
                else:
                    deleted_by_name = deleter.get('email', 'Unknown User')
            
            # Delete note
            result = await db.lead_notes.delete_one({"_id": ObjectId(note_id)})
            
            if result.deleted_count > 0:
                # 🔥 AUTO-ACTIVITY LOGGING
                try:
                    activity_doc = {
                        "lead_id": note["lead_id"],
                        "activity_type": "note_deleted",
                        "description": f"Note '{note['title']}' deleted",
                        "created_by": ObjectId(user_id),
                        "created_by_name": deleted_by_name,
                        "created_at": datetime.utcnow(),
                        "is_system_generated": True,
                        "metadata": {
                            "note_id": note_id,
                            "note_title": note['title'],
                            "note_type": note.get('note_type')
                        }
                    }
                    await db.lead_activities.insert_one(activity_doc)
                    logger.info("✅ Note deletion activity logged")
                except Exception as activity_error:
                    logger.warning(f"⚠️ Failed to log note deletion activity: {activity_error}")
            
            return result.deleted_count > 0
            
        except Exception as e:
            logger.error(f"❌ Error deleting note: {str(e)}")
            return False
    
# Fix for app/services/note_service.py - search_notes method

    async def search_notes(self, search_request: NoteSearchRequest, user_id: str, user_role: str) -> Dict[str, Any]:
        """Search notes across leads with advanced filtering - FIXED for co-assignees"""
        try:
            db = get_database()
            
            # Base query - only search in leads accessible to user
            base_query = {}
            if user_role != "admin":
                # Get user's email first
                user_info = await db.users.find_one({"_id": ObjectId(user_id)})
                user_email = user_info.get("email", "") if user_info else ""
                
                # ✅ FIX: Get user's assigned leads (PRIMARY + CO-ASSIGNEES)
                assigned_leads = await db.leads.find({
                    "$or": [
                        {"assigned_to": user_email},
                        {"co_assignees": user_email}  # 🆕 Added missing co-assignees check
                    ]
                }).to_list(None)
                
                lead_object_ids = [lead["_id"] for lead in assigned_leads]
                base_query["lead_object_id"] = {"$in": lead_object_ids}
            
            # Rest of the search logic remains the same...
            search_conditions = []
            
            # Text search
            if search_request.query:
                search_conditions.append({
                    "$or": [
                        {"title": {"$regex": search_request.query, "$options": "i"}},
                        {"content": {"$regex": search_request.query, "$options": "i"}}
                    ]
                })
            
            # Tags filter
            if search_request.tags:
                search_conditions.append({"tags": {"$in": search_request.tags}})
            
            # Note type filter
            if search_request.note_type:
                search_conditions.append({"note_type": search_request.note_type})
            
            # Author filter
            if search_request.author:
                search_conditions.append({"created_by": search_request.author})
            
            # Combine base query with search conditions
            if search_conditions:
                if base_query:
                    final_query = {"$and": [base_query, {"$or": search_conditions}]}
                else:
                    final_query = {"$or": search_conditions}
            else:
                final_query = base_query
            
            # Continue with the rest of your existing logic...
            
        except Exception as e:
            logger.error(f"❌ Error searching notes: {str(e)}")
            return {"error": str(e)}



    async def get_note_stats(self, lead_id: str, user_id: str, user_role: str) -> Dict[str, Any]:
        """Get note statistics for a lead"""
        try:
            db = get_database()
            
            # Get lead
            lead = await db.leads.find_one({"lead_id": lead_id})
            if not lead:
                return {}
            
            # Base query
            query = {"lead_object_id": lead["_id"]}
            
            # Privacy filtering for non-admins
            if user_role != "admin":
                query["$or"] = [
                    {"is_private": False},
                    {"created_by": ObjectId(user_id)}
                ]
            
            # Get all notes for stats
            notes = await db.lead_notes.find(query).to_list(None)
            
            if not notes:
                return {
                    "total_notes": 0,
                    "notes_by_type": {},
                    "notes_by_author": {},
                    "most_used_tags": [],
                    "recent_notes_count": 0
                }
            
            # Calculate statistics
            total_notes = len(notes)
            
            # Notes by type
            notes_by_type = Counter([note.get("note_type", "general") for note in notes])
            
            # Notes by author
            notes_by_author = Counter([note.get("created_by_name", "Unknown") for note in notes])
            
            # Most used tags
            all_tags = []
            for note in notes:
                all_tags.extend(note.get("tags", []))
            tag_counts = Counter(all_tags)
            most_used_tags = [{"tag": tag, "count": count} for tag, count in tag_counts.most_common(10)]
            
            # Recent notes (last 7 days)
            week_ago = datetime.utcnow() - timedelta(days=7)
            recent_notes_count = len([note for note in notes if note.get("created_at", datetime.min) > week_ago])
            
            return {
                "total_notes": total_notes,
                "notes_by_type": dict(notes_by_type),
                "notes_by_author": dict(notes_by_author),
                "most_used_tags": most_used_tags,
                "recent_notes_count": recent_notes_count
            }
            
        except Exception as e:
            logger.error(f"❌ Error calculating note stats: {str(e)}")
            return {}
    
    async def _get_lead_available_tags(self, lead_object_id: ObjectId) -> List[str]:
        """Get all tags used in notes for a lead"""
        try:
            db = get_database()
            
            # Aggregate to get all unique tags
            pipeline = [
                {"$match": {"lead_object_id": lead_object_id}},
                {"$unwind": "$tags"},
                {"$group": {"_id": "$tags"}},
                {"$sort": {"_id": 1}}
            ]
            
            result = await db.lead_notes.aggregate(pipeline).to_list(None)
            return [item["_id"] for item in result if item["_id"]]
            
        except Exception as e:
            logger.error(f"❌ Error getting available tags: {str(e)}")
            return []

# Global service instance
note_service = NoteService()