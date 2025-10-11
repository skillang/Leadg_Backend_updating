# app/services/document_service.py
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import HTTPException, UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket
from bson import ObjectId
import logging
from pathlib import Path

from app.config.database import get_database
from app.models.document import DocumentCreate, DocumentResponse, DocumentStatus, DocumentType

logger = logging.getLogger(__name__)

class DocumentService:
    def __init__(self):
        self.db = get_database()
        # GridFS bucket for file storage in MongoDB Atlas
        self.fs_bucket = AsyncIOMotorGridFSBucket(self.db, bucket_name="documents")
        
    async def upload_document(
        self, 
        lead_id: str, 
        file: UploadFile, 
        document_data: DocumentCreate,
        current_user: Dict[str, Any]
    ) -> DocumentResponse:
        """Upload a document for a specific lead with auto-activity logging"""
        try:
            print("=" * 50)
            print(f"DOCUMENT UPLOAD STARTED!")
            print(f"Lead ID: {lead_id}")
            print(f"File: {file.filename}")
            print(f"Document Type: {document_data.document_type}")
            print("=" * 50)
            
            # 1. Check lead access permission
            lead = await self._check_lead_access(lead_id, current_user)
            
            # 2. Validate file type and size
            await self._validate_file(file)
            
            # 3. Get user information
            user_id = str(current_user.get("user_id") or current_user.get("_id") or current_user.get("id"))
            user_name = await self._get_user_name(ObjectId(user_id))
            
            # 4. Generate secure filename
            secure_filename = self._generate_secure_filename(file.filename)
            
            # 5. Store file in GridFS (MongoDB Atlas)
            file_content = await file.read()
            await file.seek(0)  # Reset file pointer
            
            grid_file_id = await self.fs_bucket.upload_from_stream(
                secure_filename,
                file_content,
                metadata={
                    "lead_id": lead_id,
                    "document_type": document_data.document_type.value,
                    "original_filename": file.filename,
                    "uploaded_by": user_id,
                    "uploaded_at": datetime.utcnow(),
                    "mime_type": file.content_type
                }
            )
            
            # 6. Create document record in database
            document_doc = {
                "lead_id": lead_id,
                "grid_file_id": grid_file_id,  # Reference to GridFS file
                "filename": secure_filename,
                "original_filename": file.filename,
                "document_type": document_data.document_type.value,
                "file_size": len(file_content),
                "mime_type": file.content_type,
                "status": DocumentStatus.PENDING.value,  # Always starts as PENDING
                "uploaded_by": ObjectId(user_id),
                "uploaded_by_name": user_name,
                "uploaded_at": datetime.utcnow(),
                "notes": document_data.notes or "",
                "expiry_date": document_data.expiry_date,
                "is_active": True
            }
            
            # 7. Insert document record
            result = await self.db.lead_documents.insert_one(document_doc)
            document_id = str(result.inserted_id)
            
            # 8. Auto-log activity
            await self._log_document_activity(
                lead_id=lead_id,
                activity_type="document_uploaded",
                description=f"Document '{file.filename}' uploaded ({document_data.document_type.value}) - Status: Pending",
                user_id=user_id,
                user_name=user_name,
                metadata={
                    "document_id": document_id,
                    "document_type": document_data.document_type.value,
                    "file_size": len(file_content),
                    "filename": file.filename,
                    "status": "Pending"
                }
            )
            
            # 9. Return document response
            document_doc["id"] = document_id
            return self._format_document_response(document_doc)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error uploading document: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to upload document: {str(e)}")
    
    async def get_lead_documents(
        self,
        lead_id: str,
        current_user: Dict[str, Any],
        document_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 10
    ) -> Dict[str, Any]:
        """Get all documents for a specific lead with filtering"""
        try:
            # 1. Check lead access
            await self._check_lead_access(lead_id, current_user)
            
            # 2. Build query
            query = {"lead_id": lead_id, "is_active": True}
            
            if document_type:
                query["document_type"] = document_type
            if status:
                query["status"] = status
                
            # 3. Calculate pagination
            skip = (page - 1) * limit
            
            # 4. Get documents with uploader names
            documents = []
            async for doc in self.db.lead_documents.find(query).sort("uploaded_at", -1).skip(skip).limit(limit):
                documents.append(self._format_document_response(doc))
            
            # 5. Get total count
            total_count = await self.db.lead_documents.count_documents(query)
            
            return {
                "documents": documents,
                "total_count": total_count,  # Keep this for router compatibility
                "page": page,
                "limit": limit,
                "total_pages": (total_count + limit - 1) // limit,  # Keep this for router compatibility
                # Add missing timeline-style fields
                "total": total_count,
                "pages": (total_count + limit - 1) // limit,
                "has_next": page * limit < total_count,
                "has_prev": page > 1
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting lead documents: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def download_document(
        self,
        document_id: str,
        current_user: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Download document file from GridFS"""
        try:
            # 1. Get document record
            document = await self.db.lead_documents.find_one({"_id": ObjectId(document_id), "is_active": True})
            if not document:
                raise HTTPException(status_code=404, detail="Document not found")
            
            # 2. Check access permission
            await self._check_lead_access(document["lead_id"], current_user)
            
            # 3. Get file from GridFS
            try:
                grid_out = await self.fs_bucket.open_download_stream(document["grid_file_id"])
                file_content = await grid_out.read()
            except Exception as e:
                logger.error(f"Error reading file from GridFS: {e}")
                raise HTTPException(status_code=404, detail="File not found in storage")
            
            return {
                "content": file_content,
                "filename": document["original_filename"],
                "mime_type": document["mime_type"],
                "file_size": document["file_size"]
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error downloading document: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def approve_document(
        self,
        document_id: str,
        approval_notes: str,
        current_user: Dict[str, Any]
    ) -> DocumentResponse:
        """Approve a document (Admin only)"""
        try:
            # 1. Check admin permission
            if current_user.get("role") != "admin":
                raise HTTPException(status_code=403, detail="Only admins can approve documents")
            
            # 2. Get document
            document = await self.db.lead_documents.find_one({"_id": ObjectId(document_id), "is_active": True})
            if not document:
                raise HTTPException(status_code=404, detail="Document not found")
            
            # 3. Get admin info
            admin_id = str(current_user.get("user_id") or current_user.get("_id") or current_user.get("id"))
            admin_name = await self._get_user_name(ObjectId(admin_id))
            
            # 4. Update document status to APPROVED
            update_data = {
                "status": DocumentStatus.APPROVED.value,
                "approved_by": ObjectId(admin_id),
                "approved_by_name": admin_name,
                "approved_at": datetime.utcnow(),
                "approval_notes": approval_notes
            }
            
            await self.db.lead_documents.update_one(
                {"_id": ObjectId(document_id)},
                {"$set": update_data}
            )
            
            # 5. Auto-log activity
            await self._log_document_activity(
                lead_id=document["lead_id"],
                activity_type="document_approved",
                description=f"Document '{document['original_filename']}' approved by {admin_name}",
                user_id=admin_id,
                user_name=admin_name,
                metadata={
                    "document_id": document_id,
                    "approved_by": admin_name,
                    "approval_notes": approval_notes,
                    "document_type": document["document_type"]
                }
            )
            
            # 6. Return updated document
            updated_document = await self.db.lead_documents.find_one({"_id": ObjectId(document_id)})
            return self._format_document_response(updated_document)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error approving document: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def reject_document(
        self,
        document_id: str,
        rejection_notes: str,
        current_user: Dict[str, Any]
    ) -> DocumentResponse:
        """Reject a document (Admin only)"""
        try:
            # 1. Check admin permission
            if current_user.get("role") != "admin":
                raise HTTPException(status_code=403, detail="Only admins can reject documents")
            
            # 2. Get document
            document = await self.db.lead_documents.find_one({"_id": ObjectId(document_id), "is_active": True})
            if not document:
                raise HTTPException(status_code=404, detail="Document not found")
            
            # 3. Get admin info
            admin_id = str(current_user.get("user_id") or current_user.get("_id") or current_user.get("id"))
            admin_name = await self._get_user_name(ObjectId(admin_id))
            
            # 4. Update document status to REJECTED
            update_data = {
                "status": DocumentStatus.REJECTED.value,
                "approved_by": ObjectId(admin_id),
                "approved_by_name": admin_name,
                "approved_at": datetime.utcnow(),
                "approval_notes": rejection_notes
            }
            
            await self.db.lead_documents.update_one(
                {"_id": ObjectId(document_id)},
                {"$set": update_data}
            )
            
            # 5. Auto-log activity
            await self._log_document_activity(
                lead_id=document["lead_id"],
                activity_type="document_rejected",
                description=f"Document '{document['original_filename']}' rejected by {admin_name}",
                user_id=admin_id,
                user_name=admin_name,
                metadata={
                    "document_id": document_id,
                    "approved_by": admin_name,
                    "rejection_notes": rejection_notes,
                    "document_type": document["document_type"]
                }
            )
            
            # 6. Return updated document
            updated_document = await self.db.lead_documents.find_one({"_id": ObjectId(document_id)})
            return self._format_document_response(updated_document)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error rejecting document: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def delete_document(
        self,
        document_id: str,
        current_user: Dict[str, Any]
    ) -> Dict[str, str]:
        """Delete a document (Users can delete from assigned leads, Admin can delete from any lead)"""
        try:
            # 1. Get document
            document = await self.db.lead_documents.find_one({"_id": ObjectId(document_id), "is_active": True})
            if not document:
                raise HTTPException(status_code=404, detail="Document not found")
            
            # 2. Check lead access permission (this handles user vs admin automatically)
            await self._check_lead_access(document["lead_id"], current_user)
            
            # 3. Get user info for logging
            user_id = str(current_user.get("user_id") or current_user.get("_id") or current_user.get("id"))
            user_name = await self._get_user_name(ObjectId(user_id))
            
            # 4. Soft delete document record
            await self.db.lead_documents.update_one(
                {"_id": ObjectId(document_id)},
                {"$set": {"is_active": False, "deleted_at": datetime.utcnow()}}
            )
            
            # 5. Delete file from GridFS
            try:
                await self.fs_bucket.delete(document["grid_file_id"])
            except Exception as e:
                logger.warning(f"Failed to delete file from GridFS: {e}")
                # Don't fail the operation if file deletion fails
            
            # 6. Auto-log activity
            await self._log_document_activity(
                lead_id=document["lead_id"],
                activity_type="document_deleted",
                description=f"Document '{document['original_filename']}' deleted by {user_name}",
                user_id=user_id,
                user_name=user_name,
                metadata={
                    "document_id": document_id,
                    "document_type": document["document_type"],
                    "deleted_by": user_name
                }
            )
            
            return {"message": "Document deleted successfully"}
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting document: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # ========================================
    # HELPER METHODS (following established patterns)
    # ========================================
    
    async def _check_lead_access(self, lead_id: str, current_user: Dict[str, Any]) -> Dict[str, Any]:
        """Check if user has access to the lead - FIXED for co-assignees"""
        # Get lead
        lead = await self.db.leads.find_one({"lead_id": lead_id})
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        # Check permissions
        user_role = current_user.get("role", "user")
        user_email = current_user.get("email")
        
        # ✅ FIXED: Check BOTH assigned_to AND co_assignees
        if user_role != "admin":
            lead_assigned_to = str(lead.get("assigned_to", ""))
            lead_co_assignees = lead.get("co_assignees", [])  # 🆕 ADDED
            
            # Check if user has access (primary assignee or co-assignee)
            has_lead_access = (
                lead_assigned_to == user_email or 
                user_email in lead_co_assignees
            )
            
            if not has_lead_access:
                raise HTTPException(
                    status_code=403, 
                    detail="Not authorized to access documents for this lead"
                )
        
        return lead

    async def _get_user_name(self, user_id: ObjectId) -> str:
        """Get user display name (following established pattern)"""
        try:
            user_info = await self.db.users.find_one({"_id": user_id})
            if user_info:
                first_name = user_info.get('first_name', '')
                last_name = user_info.get('last_name', '')
                if first_name and last_name:
                    return f"{first_name} {last_name}".strip()
                else:
                    return user_info.get('email', 'Unknown User')
            return "Unknown User"
        except Exception as e:
            logger.warning(f"Failed to get user name for {user_id}: {e}")
            return "Unknown User"
    
    async def _log_document_activity(
        self,
        lead_id: str,
        activity_type: str,
        description: str,
        user_id: str,
        user_name: str,
        metadata: Dict[str, Any]
    ):
        """Log document activity (following established pattern from task_service.py)"""
        try:
            activity_doc = {
                "lead_id": lead_id,  # String reference (following updated pattern)
                "activity_type": activity_type,
                "description": description,
                "created_by": ObjectId(user_id),
                "created_by_name": user_name,
                "created_at": datetime.utcnow(),
                "metadata": metadata
            }
            await self.db.lead_activities.insert_one(activity_doc)
            logger.info(f"Document activity logged: {activity_type}")
        except Exception as activity_error:
            logger.warning(f"Failed to log document activity: {activity_error}")
            # Don't fail main operation if activity logging fails
    
    def _format_document_response(self, document: Dict[str, Any]) -> DocumentResponse:
        """Format document for API response with ObjectId conversion"""
        doc_data = {
            "id": str(document["_id"]),
            "lead_id": document["lead_id"],
            "filename": document["original_filename"],
            "document_type": document["document_type"],
            "file_size": document["file_size"],
            "mime_type": document["mime_type"],
            "status": document["status"],
            "uploaded_by": str(document["uploaded_by"]) if document.get("uploaded_by") else "",  # ADDED: Convert ObjectId
            "uploaded_by_name": document["uploaded_by_name"],
            "uploaded_at": document["uploaded_at"],
            "notes": document.get("notes", ""),
            "expiry_date": document.get("expiry_date"),
            "approved_by": str(document.get("approved_by", "")) if document.get("approved_by") else None,  # ADDED: Convert ObjectId
            "approved_by_name": document.get("approved_by_name"),
            "approved_at": document.get("approved_at"),
            "approval_notes": document.get("approval_notes", "")
        }
        
        return DocumentResponse(**doc_data)
    
    async def _validate_file(self, file: UploadFile):
        """Validate uploaded file type and size"""
        # File type validation
        ALLOWED_MIME_TYPES = {
            'application/pdf': ['.pdf'],
            'image/jpeg': ['.jpg', '.jpeg'], 
            'image/png': ['.png'],
            'application/msword': ['.doc'],
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
            'application/vnd.ms-excel': ['.xls'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx']
        }
        
        if file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=400, 
                detail=f"File type '{file.content_type}' not allowed. Allowed types: PDF, DOC, DOCX, JPG, PNG, XLS, XLSX"
            )
        
        # File size validation (10MB limit)
        MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
        file_content = await file.read()
        await file.seek(0)  # Reset file pointer
        
        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400, 
                detail=f"File size ({len(file_content)} bytes) exceeds maximum allowed size (10MB)"
            )
    
    def _generate_secure_filename(self, original_filename: str) -> str:
        """Generate secure filename to prevent conflicts"""
        # Get file extension
        file_ext = Path(original_filename).suffix.lower()
        
        # Generate unique filename
        unique_id = str(uuid.uuid4())[:8]
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        
        # Clean original filename (remove special characters)
        clean_name = "".join(c for c in Path(original_filename).stem if c.isalnum() or c in (' ', '-', '_')).rstrip()
        clean_name = clean_name.replace(' ', '_')
        
        return f"{timestamp}_{unique_id}_{clean_name}{file_ext}"