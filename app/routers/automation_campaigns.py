# app/routers/automation_campaigns.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

from app.utils.dependencies import get_current_active_user, get_admin_user
from app.config.database import get_database
from app.models.automation_campaign import (
    CampaignCreateRequest,
    CampaignResponse,
    CampaignListItem,
    CampaignStatsResponse,
     CampaignPreviewRequest,  
    CampaignPreviewResponse  
)
from app.services.campaign_service import campaign_service
from app.services.campaign_executor import campaign_executor

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# CAMPAIGN CRUD ENDPOINTS
# ============================================================================

@router.post("/create", response_model=CampaignResponse)
async def create_campaign(
    campaign_data: CampaignCreateRequest,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Create new automation campaign (Admin only)
    
    - Creates campaign configuration
    - Enrolls matching leads immediately
    - Returns schedule preview
    """
    try:
        admin_email = current_user.get("email")
        logger.info(f"Campaign creation requested by {admin_email}")
        
        # Create campaign
        result = await campaign_service.create_campaign(
            campaign_data=campaign_data,
            created_by=admin_email
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["message"]
            )
        
        campaign_id = result["campaign_id"]
        
        # Enroll leads immediately
        enrollment_result = await campaign_executor.enroll_leads_in_campaign(campaign_id)
        
        return CampaignResponse(
            success=True,
            message=result["message"],
            campaign_id=campaign_id,
            campaign_name=result["campaign_name"],
            total_leads_enrolled=enrollment_result.get("enrolled_count", 0),
            schedule_preview=result.get("schedule_preview")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating campaign: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create campaign: {str(e)}"
        )


@router.get("/list")
async def list_campaigns(
    campaign_type: Optional[str] = Query(None, description="Filter by type (whatsapp/email)"),
    status: Optional[str] = Query(None, description="Filter by status (active/paused/deleted/completed/cancelled). Shows ALL if not specified."),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    List all campaigns with filtering (Admin only)
    
    ✅ FIXED:
    - Shows ALL campaign statuses by default (active, paused, deleted, completed, cancelled)
    - Universal pagination structure matching other endpoints
    - Includes enrollment and message statistics
    
    - Supports filtering by type and status
    - Paginated results
    - Includes enrollment counts
    """
    try:
        skip = (page - 1) * limit
        
        # Get campaigns from service
        result = await campaign_service.list_campaigns(
            campaign_type=campaign_type,
            status=status,  # ✅ Will show ALL statuses if None
            skip=skip,
            limit=limit
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to list campaigns"
            )
        
        # Enrich with enrollment stats
        db = get_database()
        campaigns = result["campaigns"]
        
        for campaign in campaigns:
            # Get enrollment count
            enrolled = await db.campaign_tracking.count_documents({
                "campaign_id": campaign["campaign_id"],
                "job_type": "enrollment"
            })
            
            # Get messages sent count
            messages_sent = await db.campaign_tracking.count_documents({
                "campaign_id": campaign["campaign_id"],
                "job_type": "message_job",
                "status": "completed"
            })
            
            # Get pending messages count
            messages_pending = await db.campaign_tracking.count_documents({
                "campaign_id": campaign["campaign_id"],
                "job_type": "message_job",
                "status": "pending"
            })
            
            campaign["enrolled_leads"] = enrolled
            campaign["messages_sent"] = messages_sent
            campaign["messages_pending"] = messages_pending
        
        # ✅ UNIVERSAL PAGINATION STRUCTURE (matches notifications, leads, notes, etc.)
        return {
            "success": True,
            "campaigns": campaigns,
            "pagination": {
                "total": result["total"],       # Total records
                "page": page,                   # Current page (1-based)
                "limit": limit,                 # Items per page
                "pages": result["pages"],       # Total pages
                "has_next": result["has_next"], # Boolean: more pages available
                "has_prev": result["has_prev"]  # Boolean: previous pages available
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing campaigns: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list campaigns: {str(e)}"
        )
    

@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """Get campaign details by ID (Admin only)"""
    try:
        campaign = await campaign_service.get_campaign(campaign_id)
        
        if not campaign:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found"
            )
        
        return {
            "success": True,
            "campaign": campaign
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting campaign {campaign_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get campaign: {str(e)}"
        )


# ============================================================================
# CAMPAIGN CONTROL ENDPOINTS
# ============================================================================

@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Pause campaign (Admin only)
    
    - Stops new enrollments
    - Pending jobs remain but won't execute
    """
    try:
        success = await campaign_service.pause_campaign(campaign_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found or already paused"
            )
        
        return {
            "success": True,
            "message": "Campaign paused successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pausing campaign: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pause campaign: {str(e)}"
        )


@router.post("/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Resume paused campaign (Admin only)
    
    - Resumes enrollments
    - Pending jobs will execute
    """
    try:
        success = await campaign_service.resume_campaign(campaign_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found or not paused"
            )
        
        return {
            "success": True,
            "message": "Campaign resumed successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resuming campaign: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resume campaign: {str(e)}"
        )


@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Delete campaign (Admin only)
    
    - Soft delete (marks as deleted)
    - Cancels all pending jobs
    """
    try:
        db = get_database()
        
        # Soft delete campaign
        success = await campaign_service.delete_campaign(campaign_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found"
            )
        
        # Cancel all pending jobs
        await db.campaign_tracking.update_many(
            {
                "campaign_id": campaign_id,
                "job_type": "message_job",
                "status": "pending"
            },
            {
                "$set": {
                    "status": "cancelled",
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return {
            "success": True,
            "message": "Campaign deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting campaign: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete campaign: {str(e)}"
        )


# ============================================================================
# CAMPAIGN STATISTICS ENDPOINTS
# ============================================================================

@router.get("/{campaign_id}/stats")
async def get_campaign_stats(
    campaign_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Get detailed campaign statistics (Admin only)
    
    - Enrollment counts by status
    - Message delivery statistics
    - Next scheduled messages
    """
    try:
        db = get_database()
        
        # Get campaign
        campaign = await campaign_service.get_campaign(campaign_id)
        if not campaign:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found"
            )
        
        # Enrollment statistics
        total_enrolled = await db.campaign_tracking.count_documents({
            "campaign_id": campaign_id,
            "job_type": "enrollment"
        })
        
        active_enrollments = await db.campaign_tracking.count_documents({
            "campaign_id": campaign_id,
            "job_type": "enrollment",
            "status": "active"
        })
        
        completed_enrollments = await db.campaign_tracking.count_documents({
            "campaign_id": campaign_id,
            "job_type": "enrollment",
            "status": "completed"
        })
        
        criteria_not_matched = await db.campaign_tracking.count_documents({
            "campaign_id": campaign_id,
            "job_type": "enrollment",
            "status": "criteria_not_matched"
        })
        
        # Message statistics
        total_sent = await db.campaign_tracking.count_documents({
            "campaign_id": campaign_id,
            "job_type": "message_job",
            "status": "completed"
        })
        
        total_pending = await db.campaign_tracking.count_documents({
            "campaign_id": campaign_id,
            "job_type": "message_job",
            "status": "pending"
        })
        
        total_failed = await db.campaign_tracking.count_documents({
            "campaign_id": campaign_id,
            "job_type": "message_job",
            "status": "failed"
        })
        
        return {
            "success": True,
            "campaign_id": campaign_id,
            "campaign_name": campaign["campaign_name"],
            "status": campaign["status"],
            "enrollments": {
                "total": total_enrolled,
                "active": active_enrollments,
                "completed": completed_enrollments,
                "criteria_not_matched": criteria_not_matched
            },
            "messages": {
                "sent": total_sent,
                "pending": total_pending,
                "failed": total_failed
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting campaign stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get campaign stats: {str(e)}"
        )


@router.get("/{campaign_id}/enrolled-leads")
async def get_enrolled_leads(
    campaign_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Get list of enrolled leads for campaign (Admin only)
    
    - Shows enrollment status
    - Messages sent/pending count
    - Lead details
    """
    try:
        db = get_database()
        skip = (page - 1) * limit
        
        # Get total count
        total = await db.campaign_tracking.count_documents({
            "campaign_id": campaign_id,
            "job_type": "enrollment"
        })
        
        # Get enrollments
        enrollments = await db.campaign_tracking.find({
            "campaign_id": campaign_id,
            "job_type": "enrollment"
        }).sort("enrolled_at", -1).skip(skip).limit(limit).to_list(length=limit)
        
        # Enrich with lead data
        enriched_enrollments = []
        for enrollment in enrollments:
            lead = await db.leads.find_one({"lead_id": enrollment["lead_id"]})
            
            if lead:
                enriched_enrollments.append({
                    "lead_id": enrollment["lead_id"],
                    "lead_name": lead.get("name", "Unknown"),
                    "email": lead.get("email", ""),
                    "enrolled_at": enrollment["enrolled_at"],
                    "enrollment_status": enrollment["status"],
                    "messages_sent": enrollment.get("messages_sent", 0),
                    "current_sequence": enrollment.get("current_sequence", 0)
                })
        
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        
        return {
            "success": True,
            "enrollments": enriched_enrollments,
            "pagination": {
                "total": total,                  
                "page": page,                     
                "limit": limit,                   
                "pages": total_pages,             
                "has_next": page < total_pages,   
                "has_prev": page > 1              
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting enrolled leads: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get enrolled leads: {str(e)}"
        )
    

# ============================================================================
# 🆕 NEW: CAMPAIGN PREVIEW ENDPOINT
# ============================================================================

@router.post("/preview", response_model=CampaignPreviewResponse)
async def preview_campaign(
    preview_data: CampaignPreviewRequest,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Preview campaign before creation (Admin only)
    
    - Shows lead count breakdown by source, category, stage
    - Campaign schedule preview
    - REQUIRES at least one filter (stage, source, or category)
    """
    try:
        from bson import ObjectId
        
        logger.info(f"Campaign preview requested by {current_user.get('email')}")
        db = get_database()
        
        # ============================================================================
        # STEP 1: Build lead filter query
        # ============================================================================
        lead_filter = {}
        
        # Track which filters are provided
        has_source_filter = bool(preview_data.source_ids)
        has_category_filter = bool(preview_data.category_ids)
        has_stage_filter = bool(preview_data.stage_ids)
        
        logger.info(f"Has filters - Source: {has_source_filter}, Category: {has_category_filter}, Stage: {has_stage_filter}")
        
        # 🔥 Source filtering - ONLY if explicitly provided
        if has_source_filter:
            try:
                source_object_ids = [ObjectId(sid) for sid in preview_data.source_ids]
                sources = await db.sources.find({"_id": {"$in": source_object_ids}}).to_list(None)
                
                if not sources:
                    logger.warning(f"No sources found for IDs: {preview_data.source_ids}")
                    return CampaignPreviewResponse(
                        summary={
                            "total_leads": 0,
                            "breakdown_by_category": {},
                            "breakdown_by_source": {},
                            "breakdown_by_stage": {}
                        },
                        campaign_schedule={
                            "duration_days": preview_data.campaign_duration_days,
                            "messages_per_lead": preview_data.message_limit,
                            "total_messages": 0,
                            "leads_targeted": 0
                        }
                    )
                
                source_names = [s["name"] for s in sources]
                logger.info(f"✅ Found sources: {source_names}")
                lead_filter["source"] = {"$in": source_names}
                
            except Exception as e:
                logger.error(f"Error processing source_ids: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid source_ids format: {str(e)}"
                )
        
        # 🔥 Category filtering - ONLY if explicitly provided
        if has_category_filter:
            try:
                category_object_ids = [ObjectId(cid) for cid in preview_data.category_ids]
                categories = await db.lead_categories.find({"_id": {"$in": category_object_ids}}).to_list(None)
                
                if not categories:
                    logger.warning(f"No categories found for IDs: {preview_data.category_ids}")
                    return CampaignPreviewResponse(
                        summary={
                            "total_leads": 0,
                            "breakdown_by_category": {},
                            "breakdown_by_source": {},
                            "breakdown_by_stage": {}
                        },
                        campaign_schedule={
                            "duration_days": preview_data.campaign_duration_days,
                            "messages_per_lead": preview_data.message_limit,
                            "total_messages": 0,
                            "leads_targeted": 0
                        }
                    )
                
                category_names = [c["name"] for c in categories]
                logger.info(f"✅ Found categories: {category_names}")
                lead_filter["category"] = {"$in": category_names}
                
            except Exception as e:
                logger.error(f"Error processing category_ids: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid category_ids format: {str(e)}"
                )
        
        # 🔥 Stage filtering - ONLY if explicitly provided
        if has_stage_filter:
            try:
                stage_object_ids = [ObjectId(sid) for sid in preview_data.stage_ids]
                stages = await db.lead_stages.find({"_id": {"$in": stage_object_ids}}).to_list(None)
                
                if not stages:
                    logger.warning(f"No stages found for IDs: {preview_data.stage_ids}")
                    return CampaignPreviewResponse(
                        summary={
                            "total_leads": 0,
                            "breakdown_by_category": {},
                            "breakdown_by_source": {},
                            "breakdown_by_stage": {}
                        },
                        campaign_schedule={
                            "duration_days": preview_data.campaign_duration_days,
                            "messages_per_lead": preview_data.message_limit,
                            "total_messages": 0,
                            "leads_targeted": 0
                        }
                    )
                
                stage_names = [s["name"] for s in stages]
                logger.info(f"✅ Found stages: {stage_names}")
                lead_filter["stage"] = {"$in": stage_names}
                
            except Exception as e:
                logger.error(f"Error processing stage_ids: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid stage_ids format: {str(e)}"
                )
        
        # 🔥 IMPORTANT: Log the final filter
        logger.info(f"📋 Final lead_filter: {lead_filter}")
        
        # ============================================================================
        # STEP 2: Get total leads count
        # ============================================================================
        total_leads = await db.leads.count_documents(lead_filter)
        logger.info(f"✅ Total leads matching filter: {total_leads}")
        
        # ============================================================================
        # STEP 3: Breakdown by category
        # ============================================================================
        category_pipeline = [
            {"$match": lead_filter},
            {"$group": {"_id": "$category", "count": {"$sum": 1}}}
        ]
        category_breakdown = {}
        async for doc in db.leads.aggregate(category_pipeline):
            if doc["_id"]:  # Skip null categories
                category_breakdown[doc["_id"]] = doc["count"]
        
        # ============================================================================
        # STEP 4: Breakdown by source
        # ============================================================================
        source_pipeline = [
            {"$match": lead_filter},
            {"$group": {"_id": "$source", "count": {"$sum": 1}}}
        ]
        source_breakdown = {}
        async for doc in db.leads.aggregate(source_pipeline):
            if doc["_id"]:  # Skip null sources
                source_breakdown[doc["_id"]] = doc["count"]
        
        # ============================================================================
        # STEP 5: Breakdown by stage
        # ============================================================================
        stage_pipeline = [
            {"$match": lead_filter},
            {"$group": {"_id": "$stage", "count": {"$sum": 1}}}
        ]
        stage_breakdown = {}
        async for doc in db.leads.aggregate(stage_pipeline):
            if doc["_id"]:  # Skip null stages
                stage_breakdown[doc["_id"]] = doc["count"]
        
        # ============================================================================
        # STEP 6: Campaign schedule calculation
        # ============================================================================
        total_messages = total_leads * preview_data.message_limit
        
        campaign_schedule = {
            "duration_days": preview_data.campaign_duration_days,
            "messages_per_lead": preview_data.message_limit,
            "total_messages": total_messages,
            "leads_targeted": total_leads
        }
        
        # ============================================================================
        # STEP 7: Build response
        # ============================================================================
        return CampaignPreviewResponse(
            summary={
                "total_leads": total_leads,
                "breakdown_by_category": category_breakdown,
                "breakdown_by_source": source_breakdown,
                "breakdown_by_stage": stage_breakdown
            },
            campaign_schedule=campaign_schedule
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error previewing campaign: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to preview campaign: {str(e)}"
        )
