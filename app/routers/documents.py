# app/routers/documents.py - RBAC-Enabled Document Management Router
# 🔄 UPDATED: Role checks replaced with RBAC permission checks (108 permissions)
# ✅ All endpoints now use permission-based access control

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from bson import ObjectId
import io
import logging

from app.decorators.timezone_decorator import convert_dates_to_ist
from app.services.document_service import DocumentService
from app.services.rbac_service import RBACService
from app.models.document import (
    DocumentCreate, DocumentResponse, DocumentListResponse, 
    DocumentApproval, DocumentType, DocumentStatus
)
from app.utils.dependencies import get_current_active_user, get_user_with_permission

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Documents"])

# Initialize RBAC service
rbac_service = RBACService()

# Service will be initialized when needed (lazy initialization)
def get_document_service() -> DocumentService:
    """Get document service instance"""
    return DocumentService()


# =====================================
# RBAC HELPER FUNCTIONS
# =====================================

async def check_document_access(document: Dict, user_email: str, current_user: Dict) -> bool:
    """
    Check if user has access to a specific document using RBAC
    
    Returns True if:
    - User has document.view_all permission, OR
    - Document's lead is assigned to user (primary or co-assignee)
    """
    # Check if user has view_all permission
    has_view_all = await rbac_service.check_permission(current_user, "document.view_all")
    if has_view_all:
        return True
    
    # Check if user has access to the document's lead
    document_service = get_document_service()
    lead_id = document.get("lead_id")
    
    if not lead_id:
        return False
    
    lead = await document_service.db.leads.find_one({"lead_id": lead_id})
    if not lead:
        return False
    
    # Check if user is assigned to the lead (primary or co-assignee)
    assigned_to = lead.get("assigned_to")
    co_assignees = lead.get("co_assignees", [])
    
    return user_email in ([assigned_to] + co_assignees)


# =====================================
# SPECIFIC ROUTES FIRST (VERY IMPORTANT!)
# =====================================

@router.get("/types/list")
@convert_dates_to_ist()
async def get_document_types():
    """Get list of available document types for frontend dropdowns - No auth required"""
    return {"document_types": [{"value": dt.value, "label": dt.value} for dt in DocumentType]}


@router.get("/status/list") 
@convert_dates_to_ist()
async def get_document_statuses():
    """Get list of available document statuses for frontend filters - No auth required"""
    return {"statuses": [{"value": ds.value, "label": ds.value} for ds in DocumentStatus]}


@router.get("/debug/test")
@convert_dates_to_ist()
async def debug_test():
    """Test endpoint to verify router is working - No auth required"""
    return {"message": "Document router is working!", "timestamp": datetime.utcnow(), "rbac_enabled": True}


@router.get("/debug/gridfs-test")
async def debug_gridfs():
    """Test GridFS connection - No auth required"""
    try:
        bucket = get_document_service().fs_bucket
        files_count = await bucket._collection.count_documents({})
        return {"gridfs_connected": True, "files_count": files_count}
    except Exception as e:
        return {"gridfs_connected": False, "error": str(e)}


@router.get("/admin/dashboard")
async def get_admin_document_dashboard(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.view_all"))
):
    """
    🔄 RBAC-ENABLED: Get document statistics dashboard for admin
    
    **Required Permission:** `document.view_all`
    
    Returns:
    - Total documents by status
    - Recent activity
    - Documents requiring attention
    """
    try:
        document_service = get_document_service()
        
        # Get status counts
        status_pipeline = [
            {"$match": {"is_active": True}},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        
        status_counts = {}
        async for result in document_service.db.lead_documents.aggregate(status_pipeline):
            status_counts[result["_id"]] = result["count"]
        
        # Get recent uploads (last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_count = await document_service.db.lead_documents.count_documents({
            "uploaded_at": {"$gte": week_ago},
            "is_active": True
        })
        
        # Get oldest pending document
        oldest_pending = await document_service.db.lead_documents.find_one(
            {"status": "Pending", "is_active": True},
            sort=[("uploaded_at", 1)]
        )
        
        days_oldest_pending = None
        if oldest_pending:
            days_oldest_pending = (datetime.utcnow() - oldest_pending["uploaded_at"]).days
        
        return {
            "status_summary": {
                "pending": status_counts.get("Pending", 0),
                "approved": status_counts.get("Approved", 0),
                "rejected": status_counts.get("Rejected", 0),
                "total": sum(status_counts.values())
            },
            "recent_activity": {
                "uploads_last_7_days": recent_count
            },
            "attention_required": {
                "pending_documents": status_counts.get("Pending", 0),
                "oldest_pending_days": days_oldest_pending
            },
            "quick_actions": {
                "approve_pending_url": "/api/v1/documents/admin/pending",
                "bulk_approve_url": "/api/v1/documents/bulk-approve"
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting admin dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/pending")
async def get_pending_documents_for_approval(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.update"))
):
    """
    🔄 RBAC-ENABLED: Get all pending documents across all leads for admin approval
    
      **Required Permission:** `document.update`
    
    Features:
    - Shows documents with 'Pending' status from all leads
    - Includes lead information for context
    - Oldest first (FIFO)
    """
    try:
        document_service = get_document_service()
        
        # Build query for pending documents
        query = {"status": "Pending", "is_active": True}
        
        # Calculate pagination
        skip = (page - 1) * limit
        
        # Get pending documents with lead and user info
        pipeline = [
            {"$match": query},
            {"$sort": {"uploaded_at": 1}},  # Oldest first (FIFO)
            {"$skip": skip},
            {"$limit": limit},
            {
                "$lookup": {
                    "from": "leads",
                    "localField": "lead_id",
                    "foreignField": "lead_id",
                    "as": "lead_info"
                }
            },
            {
                "$lookup": {
                    "from": "users",
                    "localField": "uploaded_by",
                    "foreignField": "_id",
                    "as": "uploader_info"
                }
            }
        ]
        
        documents = []
        async for doc in document_service.db.lead_documents.aggregate(pipeline):
            # Create base document response
            doc_data = {
                "id": str(doc["_id"]),
                "lead_id": doc["lead_id"],
                "filename": doc["original_filename"],
                "document_type": doc["document_type"],
                "file_size": doc["file_size"],
                "mime_type": doc["mime_type"],
                "status": doc["status"],
                "uploaded_by_name": doc["uploaded_by_name"],
                "uploaded_at": doc["uploaded_at"],
                "notes": doc.get("notes", ""),
                "expiry_date": doc.get("expiry_date"),
                "approved_by_name": doc.get("approved_by_name"),
                "approved_at": doc.get("approved_at"),
                "approval_notes": doc.get("approval_notes", "")
            }
            
            # Add lead context for admin
            if doc.get("lead_info"):
                lead = doc["lead_info"][0]
                doc_data["lead_context"] = {
                    "lead_name": lead.get("name"),
                    "lead_email": lead.get("email"),
                    "assigned_to": lead.get("assigned_to"),
                    "assigned_to_name": lead.get("assigned_to_name")
                }
            
            documents.append(DocumentResponse(**doc_data))
        
        # Get total count
        total_count = await document_service.db.lead_documents.count_documents(query)
        
        return {
            "documents": documents,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": (total_count + limit - 1) // limit,
                "has_next": page * limit < total_count,
                "has_prev": page > 1
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pending documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/my-documents")
async def get_my_documents(
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.view"))
):
    """
    🔄 RBAC-ENABLED: Get all documents uploaded by current user across all their assigned leads
    
    **Required Permission:**
    - `document.view` - See documents for assigned leads
    - `document.view_all` - See all documents (admin)
    
    Returns documents from all leads assigned to user (primary + co-assignees)
    """
    try:
        document_service = get_document_service()
        user_email = current_user.get("email")
        
        # Build query based on RBAC permissions
        has_view_all = await rbac_service.check_permission(current_user, "document.view_all")
        
        query = {"is_active": True}
        
        if has_view_all:
            # Admin sees all documents
            pass
        else:
            # Regular users see documents from leads they have access to (primary + co-assignee)
            user_leads = []
            async for lead in document_service.db.leads.find({
                "$or": [
                    {"assigned_to": user_email},
                    {"co_assignees": user_email}
                ]
            }):
                user_leads.append(lead["lead_id"])
            
            if not user_leads:
                # User has no assigned leads
                return {
                    "documents": [],
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": 0,
                        "pages": 0,
                        "has_next": False,
                        "has_prev": False
                    }
                }
            
            query["lead_id"] = {"$in": user_leads}
        
        if status:
            query["status"] = status
        
        # Calculate pagination
        skip = (page - 1) * limit
        
        # Get documents with lead context
        pipeline = [
            {"$match": query},
            {"$sort": {"uploaded_at": -1}},  # Most recent first
            {"$skip": skip},
            {"$limit": limit},
            {
                "$lookup": {
                    "from": "leads",
                    "localField": "lead_id",
                    "foreignField": "lead_id",
                    "as": "lead_info"
                }
            }
        ]
        
        documents = []
        async for doc in document_service.db.lead_documents.aggregate(pipeline):
            # Create base document response
            doc_data = {
                "id": str(doc["_id"]),
                "lead_id": doc["lead_id"],
                "filename": doc["original_filename"],
                "document_type": doc["document_type"],
                "file_size": doc["file_size"],
                "mime_type": doc["mime_type"],
                "status": doc["status"],
                "uploaded_by_name": doc["uploaded_by_name"],
                "uploaded_at": doc["uploaded_at"],
                "notes": doc.get("notes", ""),
                "expiry_date": doc.get("expiry_date"),
                "approved_by_name": doc.get("approved_by_name"),
                "approved_at": doc.get("approved_at"),
                "approval_notes": doc.get("approval_notes", "")
            }
            
            # Add lead context
            if doc.get("lead_info"):
                lead = doc["lead_info"][0]
                doc_data["lead_context"] = {
                    "lead_name": lead.get("name"),
                    "lead_id": lead.get("lead_id")
                }
            
            documents.append(DocumentResponse(**doc_data))
        
        # Get total count
        total_count = await document_service.db.lead_documents.count_documents(query)
        
        return {
            "documents": documents,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": (total_count + limit - 1) // limit,
                "has_next": page * limit < total_count,
                "has_prev": page > 1
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/my-notifications")
async def get_my_document_notifications(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.view"))
):
    """
    🔄 RBAC-ENABLED: Get document-related notifications for current user
    
    **Required Permission:** `document.view`
    
    Returns:
    - Recent approvals/rejections
    - Documents needing attention
    """
    try:
        document_service = get_document_service()
        user_email = current_user.get("email")
        
        # Get user's leads (including co-assignments)
        user_leads = []
        async for lead in document_service.db.leads.find({
            "$or": [
                {"assigned_to": user_email},
                {"co_assignees": user_email}
            ]
        }):
            user_leads.append(lead["lead_id"])
        
        if not user_leads:
            return {"notifications": [], "summary": {"total": 0}}
        
        # Get recent status changes (last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        
        # Recent approvals/rejections
        recent_decisions = []
        async for doc in document_service.db.lead_documents.find({
            "lead_id": {"$in": user_leads},
            "status": {"$in": ["Approved", "Rejected"]},
            "approved_at": {"$gte": week_ago},
            "is_active": True
        }).sort("approved_at", -1).limit(10):
            
            recent_decisions.append({
                "document_id": str(doc["_id"]),
                "filename": doc["original_filename"],
                "lead_id": doc["lead_id"],
                "status": doc["status"],
                "approved_by_name": doc.get("approved_by_name"),
                "approved_at": doc.get("approved_at"),
                "approval_notes": doc.get("approval_notes", ""),
                "notification_type": "status_change"
            })
        
        # Count pending documents
        pending_count = await document_service.db.lead_documents.count_documents({
            "lead_id": {"$in": user_leads},
            "status": "Pending",
            "is_active": True
        })
        
        return {
            "notifications": recent_decisions,
            "summary": {
                "total": len(recent_decisions),
                "pending_documents": pending_count,
                "recent_decisions": len(recent_decisions)
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting user notifications: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bulk-approve")
async def bulk_approve_documents(
    bulk_action: dict,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.update"))
):
    """
    🔄 RBAC-ENABLED: Bulk approve multiple documents
    
      **Required Permission:** `document.update`
    
    Features:
    - Approve multiple documents at once
    - Auto-logs activity for each document
    """
    try:
        results = []
        document_ids = bulk_action.get("document_ids", [])
        notes = bulk_action.get("notes", "Bulk approval")
        
        for document_id in document_ids:
            try:
                result = await get_document_service().approve_document(
                    document_id=document_id,
                    approval_notes=notes,
                    current_user=current_user
                )
                results.append({"document_id": document_id, "status": "approved", "result": result})
            except Exception as e:
                results.append({"document_id": document_id, "status": "error", "error": str(e)})
        
        return {"results": results, "total_processed": len(document_ids)}
        
    except Exception as e:
        logger.error(f"Error in bulk approve: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================
# GENERIC ROUTES LAST (VERY IMPORTANT!)
# =====================================

@router.post("/leads/{lead_id}/upload", response_model=DocumentResponse)
async def upload_document(
    lead_id: str,
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    notes: Optional[str] = Form(None),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.add"))
):
    """
    🔄 RBAC-ENABLED: Upload a document for a specific lead
    
    **Required Permission:** `document.add`
    
    Features:
    - Users can upload to their assigned leads only
    - Admins can upload to any lead
    - Files are stored in MongoDB GridFS
    - Status automatically set to "Pending" for admin approval
    """
    try:
        document_data = DocumentCreate(
            document_type=document_type,
            notes=notes
        )
        
        result = await get_document_service().upload_document(
            lead_id=lead_id,
            file=file,
            document_data=document_data,
            current_user=current_user
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in upload endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/leads/{lead_id}/documents")
async def get_lead_documents(
    lead_id: str,
    document_type: Optional[str] = Query(None, description="Filter by document type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.view"))
):
    """
    🔄 RBAC-ENABLED: Get all documents for a specific lead with filtering
    
    **Required Permission:**
    - `document.view` - See documents for assigned leads
    - `document.view_all` - See all documents (admin)
    
    Supports filtering by type, status, and pagination
    """
    try:
        result = await get_document_service().get_lead_documents(
            lead_id=lead_id,
            current_user=current_user,
            document_type=document_type,
            status=status,
            page=page,
            limit=limit
        )
        
        # Extract data from the service result
        documents = result["documents"]
        total_count = result["total_count"]
        
        return {
            "documents": documents,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": (total_count + limit - 1) // limit,
                "has_next": page * limit < total_count,
                "has_prev": page > 1
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting lead documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.view"))
):
    """
    🔄 RBAC-ENABLED: Get specific document information
    
    **Required Permission:** `document.view`
    
    Access based on lead assignment for users, full access for admins
    """
    try:
        # Get document from database
        document_service = get_document_service()
        document = await document_service.db.lead_documents.find_one(
            {"_id": ObjectId(document_id), "is_active": True}
        )
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Check if user has access to this document
        user_email = current_user.get("email")
        has_access = await check_document_access(document, user_email, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to view this document"
            )
        
        return document_service._format_document_response(document)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.view"))
):
    """
    🔄 RBAC-ENABLED: Download document file from GridFS
    
    **Required Permission:** `document.view`
    
    Users can download from their assigned leads only, admins can download from any lead
    """
    try:
        file_data = await get_document_service().download_document(document_id, current_user)
        
        # Create streaming response
        return StreamingResponse(
            io.BytesIO(file_data["content"]),
            media_type=file_data["mime_type"],
            headers={
                "Content-Disposition": f"attachment; filename=\"{file_data['filename']}\"",
                "Content-Length": str(file_data["file_size"])
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: str,
    document_update: dict,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.update"))
):
    """
    🔄 RBAC-ENABLED: Update document information (notes, type, expiry date)
    
    **Required Permission:** `document.update`
    
    Features:
    - Users can update documents from their assigned leads
    - Admins can update documents from any lead
    - Auto-logs activity if significant changes made
    """
    try:
        # Get document
        document_service = get_document_service()
        document = await document_service.db.lead_documents.find_one(
            {"_id": ObjectId(document_id), "is_active": True}
        )
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Check if user has access to this document
        user_email = current_user.get("email")
        has_access = await check_document_access(document, user_email, current_user)
        
        if not has_access:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to update this document"
            )
        
        # Build update data
        update_data = {}
        if "document_type" in document_update:
            update_data["document_type"] = document_update["document_type"]
        if "notes" in document_update:
            update_data["notes"] = document_update["notes"]
        if "expiry_date" in document_update:
            update_data["expiry_date"] = document_update["expiry_date"]
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No valid fields to update")
        
        # Update document
        update_data["updated_at"] = datetime.utcnow()
        await document_service.db.lead_documents.update_one(
            {"_id": ObjectId(document_id)},
            {"$set": update_data}
        )
        
        # Get updated document
        updated_document = await document_service.db.lead_documents.find_one(
            {"_id": ObjectId(document_id)}
        )
        
        # Auto-log activity if significant changes
        if "document_type" in document_update or "notes" in document_update:
            user_id = str(current_user.get("user_id") or current_user.get("_id") or current_user.get("id"))
            user_name = await document_service._get_user_name(ObjectId(user_id))
            
            await document_service._log_document_activity(
                lead_id=document["lead_id"],
                activity_type="document_updated",
                description=f"Document '{document['original_filename']}' updated",
                user_id=user_id,
                user_name=user_name,
                metadata={
                    "document_id": document_id,
                    "changes": update_data,
                    "updated_by": user_name
                }
            )
        
        return document_service._format_document_response(updated_document)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.delete"))
):
    """
    🔄 RBAC-ENABLED: Delete a document
    
    **Required Permission:** `document.delete`
    
    Features:
    - Users can delete documents from their assigned leads
    - Admins can delete documents from any lead
    - Soft delete with GridFS file removal
    """
    try:
        result = await get_document_service().delete_document(document_id, current_user)
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{document_id}/approve", response_model=DocumentResponse)
async def approve_document(
    document_id: str,
    approval_data: DocumentApproval,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.update"))
):
    """
    🔄 RBAC-ENABLED: Approve a document
    
      **Required Permission:** `document.update`
    
    Features:
    - Changes status from "Pending" to "Approved"
    - Records approval timestamp and admin name
    - Auto-logs activity: "Document approved"
    """
    try:
        result = await get_document_service().approve_document(
            document_id=document_id,
            approval_notes=approval_data.approval_notes,
            current_user=current_user
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{document_id}/reject", response_model=DocumentResponse)
async def reject_document(
    document_id: str,
    rejection_data: DocumentApproval,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("document.update"))
):
    """
    🔄 RBAC-ENABLED: Reject a document
    
      **Required Permission:** `document.update`
    
    Features:
    - Changes status from "Pending" to "Rejected"
    - Records rejection timestamp and admin name
    - Auto-logs activity: "Document rejected"
    """
    try:
        result = await get_document_service().reject_document(
            document_id=document_id,
            rejection_notes=rejection_data.approval_notes,
            current_user=current_user
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rejecting document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))