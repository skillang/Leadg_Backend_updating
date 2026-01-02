# app/routers/cv_processing.py - CV Processing API Endpoints

from fastapi import APIRouter, HTTPException, status, Depends, Query, File, UploadFile, Form
from fastapi.responses import JSONResponse
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from ..models.cv_processing import (
    CVUploadResponse,
    CVExtractionUpdateRequest,
    CVToLeadRequest,
    CVToLeadResponse,
    CVExtractionListResponse,
    CVProcessingStatsResponse,
    CVProcessingStatus
)
from ..services.cv_processing_service import cv_processing_service
from ..utils.dependencies import get_current_active_user, get_user_with_permission, get_user_with_single_lead_permission, get_user_with_bulk_lead_permission

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# ============================================================================
# CV UPLOAD ENDPOINTS
# ============================================================================

@router.post("/upload", response_model=CVUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_cv(
    file: UploadFile = File(..., description="CV file (PDF or DOCX, max 10MB)"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Upload and process CV file
    
    **Permissions**: All authenticated users can upload CVs
    **File Requirements**: PDF or DOCX files, maximum 10MB
    **Processing**: Automatic text extraction and data parsing
    """
    try:
        logger.info(f"CV upload requested by: {current_user.get('email')}")
        
        # Validate file is provided
        if not file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file provided"
            )
        
        # Read file content
        file_content = await file.read()
        
        if not file_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty file provided"
            )
        
        # Process the CV
        result = await cv_processing_service.process_uploaded_cv(
            file_content=file_content,
            filename=file.filename or "unknown.pdf",
            mime_type=file.content_type or "application/pdf",
            uploaded_by=str(current_user["_id"]),
            uploaded_by_email=current_user["email"]
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["message"]
            )
        
        # Return success response
        return CVUploadResponse(
            success=True,
            message=result["message"],
            processing_id=result["processing_id"],
            status=result.get("status"),
            estimated_processing_time=30  # Approximate processing time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in CV upload: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CV upload failed: {str(e)}"
        )

# ============================================================================
# CV EXTRACTION MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/extractions", response_model=CVExtractionListResponse)
async def get_cv_extractions(
    status_filter: Optional[str] = Query(None, description="Filter by processing status"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get CV extractions list
    
    **Permissions**: 
    - Regular users: See only their own CV uploads
    - Users with lead creation permission: See all CV uploads
    """
    try:
        # Check if user has lead creation permission
        has_lead_permission = current_user.get("can_create_leads", False) or current_user.get("role") == "admin"
        
        result = await cv_processing_service.get_cv_extractions(
            user_id=str(current_user["_id"]),
            user_email=current_user["email"],
            has_lead_permission=has_lead_permission,
            status_filter=status_filter,
            page=page,
            limit=limit
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["message"]
            )
        
        return CVExtractionListResponse(
            extractions=result["extractions"],
            total_count=result["total_count"],
            page=result["page"],
            limit=result["limit"],
            total_pages=result["total_pages"],
            filters_applied=result["filters_applied"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting CV extractions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get CV extractions: {str(e)}"
        )

@router.get("/extractions/{processing_id}")
async def get_cv_extraction(
    processing_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get single CV extraction by ID
    
    **Permissions**: Own CVs or all CVs if user has lead creation permission
    """
    try:
        has_lead_permission = current_user.get("can_create_leads", False) or current_user.get("role") == "admin"
        
        result = await cv_processing_service.get_cv_extraction_by_id(
            processing_id=processing_id,
            user_id=str(current_user["_id"]),
            user_email=current_user["email"],
            has_lead_permission=has_lead_permission
        )
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="CV extraction not found or access denied"
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting CV extraction {processing_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get CV extraction: {str(e)}"
        )

@router.put("/extractions/{processing_id}")
async def update_cv_extraction(
    processing_id: str,
    update_request: CVExtractionUpdateRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Update extracted CV data
    
    **Permissions**: 
    - Regular users: Can edit only their own CV extractions
    - Users with lead creation permission: Can edit any CV extraction
    """
    try:
        has_lead_permission = current_user.get("can_create_leads", False) or current_user.get("role") == "admin"
        
        result = await cv_processing_service.update_extraction_data(
            processing_id=processing_id,
            update_request=update_request,
            user_id=str(current_user["_id"]),
            user_email=current_user["email"],
            has_lead_permission=has_lead_permission
        )
        
        if not result["success"]:
            if "not found" in result["message"].lower() or "access denied" in result["message"].lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=result["message"]
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=result["message"]
                )
        
        return {
            "success": True,
            "message": result["message"],
            "processing_id": processing_id,
            "updated_at": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating CV extraction {processing_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update CV extraction: {str(e)}"
        )

@router.delete("/extractions/{processing_id}")
async def delete_cv_extraction(
    processing_id: str,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Delete CV extraction (only if not converted to lead)
    
    **Permissions**: 
    - Regular users: Can delete only their own unconverted CV extractions
    - Users with lead creation permission: Can delete any unconverted CV extraction
    """
    try:
        has_lead_permission = current_user.get("can_create_leads", False) or current_user.get("role") == "admin"
        
        result = await cv_processing_service.delete_cv_extraction(
            processing_id=processing_id,
            user_id=str(current_user["_id"]),
            user_email=current_user["email"],
            has_lead_permission=has_lead_permission
        )
        
        if not result["success"]:
            if "not found" in result["message"].lower() or "access denied" in result["message"].lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=result["message"]
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=result["message"]
                )
        
        return {
            "success": True,
            "message": result["message"],
            "processing_id": processing_id,
            "deleted_at": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting CV extraction {processing_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete CV extraction: {str(e)}"
        )

# ============================================================================
# CV TO LEAD CONVERSION ENDPOINTS
# ============================================================================

@router.post("/convert-to-lead", response_model=CVToLeadResponse)
async def convert_cv_to_lead(
    conversion_request: CVToLeadRequest,
    current_user: Dict[str, Any] = Depends(get_user_with_single_lead_permission)
):
    """
    Convert CV extraction to lead
    
    **Permissions**: Only users with lead creation permission
    **Process**: Creates lead using existing lead creation logic, then cleans up CV data
    """
    try:
        logger.info(f"CV to lead conversion requested by: {current_user.get('email')} for {conversion_request.processing_id}")
        
        result = await cv_processing_service.convert_cv_to_lead(
            conversion_request=conversion_request,
            user_id=str(current_user["_id"]),
            user_email=current_user["email"]
        )
        
        if not result["success"]:
            # Determine appropriate error status code
            if "not found" in result["message"].lower():
                status_code = status.HTTP_404_NOT_FOUND
            elif "already converted" in result["message"].lower():
                status_code = status.HTTP_409_CONFLICT
            elif "validation" in result["message"].lower():
                status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
            else:
                status_code = status.HTTP_400_BAD_REQUEST
            
            raise HTTPException(
                status_code=status_code,
                detail=result["message"]
            )
        
        return CVToLeadResponse(
            success=True,
            message=result["message"],
            processing_id=result["processing_id"],
            lead_id=result["lead_id"],
            lead_details=result["lead_details"],
            assignment_info=result.get("assignment_info"),
            validation_errors=result.get("validation_errors", []),
            cleanup_completed=result.get("cleanup_scheduled", False)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in CV to lead conversion: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Conversion failed: {str(e)}"
        )

# ============================================================================
# BULK OPERATIONS (FOR USERS WITH BULK LEAD PERMISSION)
# ============================================================================

@router.post("/bulk-convert")
async def bulk_convert_cvs_to_leads(
    processing_ids: List[str],
    category: str = Query(..., description="Category for all leads"),
    source: str = Query(default="cv_upload", description="Source for all leads"),
    assignment_method: str = Query(default="unassigned", description="Assignment method"),
    assign_to: Optional[str] = Query(None, description="User email to assign to"),
    current_user: Dict[str, Any] = Depends(get_user_with_bulk_lead_permission)
):
    """
    Bulk convert multiple CVs to leads
    
    **Permissions**: Only users with bulk lead creation permission
    **Limit**: Maximum 10 CVs per batch to prevent performance issues
    """
    try:
        # Validate batch size
        if len(processing_ids) > 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum 10 CVs can be converted in a single batch"
            )
        
        if not processing_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No processing IDs provided"
            )
        
        logger.info(f"Bulk CV conversion requested by: {current_user.get('email')} for {len(processing_ids)} CVs")
        
        results = []
        successful_conversions = 0
        failed_conversions = 0
        
        # Process each CV conversion
        for processing_id in processing_ids:
            try:
                conversion_request = CVToLeadRequest(
                    processing_id=processing_id,
                    category=category,
                    source=source,
                    assignment_method=assignment_method,
                    assign_to=assign_to
                )
                
                result = await cv_processing_service.convert_cv_to_lead(
                    conversion_request=conversion_request,
                    user_id=str(current_user["_id"]),
                    user_email=current_user["email"]
                )
                
                if result["success"]:
                    successful_conversions += 1
                    results.append({
                        "processing_id": processing_id,
                        "success": True,
                        "lead_id": result["lead_id"],
                        "message": result["message"]
                    })
                else:
                    failed_conversions += 1
                    results.append({
                        "processing_id": processing_id,
                        "success": False,
                        "error": result["message"]
                    })
                    
            except Exception as e:
                failed_conversions += 1
                results.append({
                    "processing_id": processing_id,
                    "success": False,
                    "error": f"Conversion failed: {str(e)}"
                })
        
        return {
            "success": True,
            "message": f"Bulk conversion completed: {successful_conversions} successful, {failed_conversions} failed",
            "total_processed": len(processing_ids),
            "successful_conversions": successful_conversions,
            "failed_conversions": failed_conversions,
            "results": results,
            "processed_at": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in bulk CV conversion: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk conversion failed: {str(e)}"
        )

# ============================================================================
# STATISTICS AND MONITORING ENDPOINTS
# ============================================================================

@router.get("/stats", response_model=CVProcessingStatsResponse)
async def get_cv_processing_stats(
    current_user: Dict[str, Any] = Depends(get_user_with_permission("dashboard.view"))
):
    """
    🔄 RBAC-ENABLED: Get CV processing statistics for dashboard
    
    **Required Permission:** `dashboard.view`
    
    **Returns**: Overall system stats and user-specific stats based on permissions
    """
    try:
        has_lead_permission = current_user.get("can_create_leads", False) or current_user.get("role") == "admin"
        
        stats = await cv_processing_service.get_cv_processing_stats(
            user_id=str(current_user["_id"]),
            user_email=current_user["email"],
            has_lead_permission=has_lead_permission
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"Error getting CV processing stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get statistics: {str(e)}"
        )

@router.get("/health")
async def cv_processing_health_check():
    """
    Health check endpoint for CV processing service
    
    **Public endpoint** - no authentication required
    """
    try:
        # Basic health check
        stats = await cv_processing_service.get_cv_processing_stats(
            user_id="system",
            user_email="system@leadg.com",
            has_lead_permission=True
        )
        
        return {
            "status": "healthy",
            "service": "CV Processing",
            "timestamp": datetime.utcnow().isoformat(),
            "summary": {
                "total_uploads": stats.total_uploads,
                "processing_count": stats.processing_count,
                "success_rate": stats.success_rate
            }
        }
        
    except Exception as e:
        logger.error(f"CV processing health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "service": "CV Processing", 
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@router.get("/permissions")
async def get_user_cv_permissions(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get user's CV processing permissions
    
    **Returns**: What CV operations the current user can perform
    """
    try:
        has_lead_permission = current_user.get("can_create_leads", False) or current_user.get("role") == "admin"
        
        permissions = cv_processing_service.check_user_cv_permissions(
            user_role=current_user.get("role", "user"),
            has_lead_creation_permission=has_lead_permission
        )
        
        return {
            "user_email": current_user["email"],
            "user_role": current_user.get("role", "user"),
            "has_lead_creation_permission": has_lead_permission,
            "cv_permissions": permissions,
            "checked_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting user CV permissions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get permissions: {str(e)}"
        )