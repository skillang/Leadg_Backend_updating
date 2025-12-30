# app/routers/facebook_leads.py - RBAC-Enabled
# API endpoints for Facebook Leads Center integration
# 🔄 UPDATED: Role checks replaced with RBAC (108 permissions)
# ✅ All endpoints now use permission-based access control

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import logging
from datetime import datetime

from ..services.facebook_leads_service import facebook_leads_service
from ..services.facebook_category_mapper import facebook_category_mapper
from ..services.rbac_service import RBACService
from ..utils.dependencies import get_current_active_user, get_user_with_permission

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Facebook Leads Integration"],
    responses={404: {"description": "Not found"}}
)

# Initialize RBAC service
rbac_service = RBACService()


# =====================================
# REQUEST/RESPONSE MODELS
# =====================================

class FacebookConfigRequest(BaseModel):
    """Request model for Facebook API configuration"""
    app_id: str = Field(..., description="Facebook App ID")
    app_secret: str = Field(..., description="Facebook App Secret")
    access_token: str = Field(..., description="Facebook Page Access Token")
    page_id: str = Field(..., description="Facebook Page ID")
    webhook_verify_token: Optional[str] = Field(None, description="Webhook verification token")


class LeadImportRequest(BaseModel):
    """Request model for importing leads from Facebook"""
    form_id: str = Field(..., description="Facebook Lead Form ID")
    category_override: Optional[str] = Field(None, description="Override auto-detected category")
    auto_assign: bool = Field(True, description="Auto-assign leads to users")
    limit: int = Field(100, ge=1, le=500, description="Number of leads to import")


class BulkImportRequest(BaseModel):
    """Request model for bulk importing from multiple forms"""
    form_ids: List[str] = Field(..., description="List of Facebook Lead Form IDs")
    category_overrides: Optional[Dict[str, str]] = Field(None, description="Form ID → Category overrides")
    auto_assign: bool = Field(True, description="Auto-assign leads to users")


# =====================================
# RBAC-ENABLED CONFIGURATION & TESTING
# =====================================

@router.get("/test-connection", summary="Test Facebook API connection")
async def test_facebook_connection(
    current_user: dict = Depends(get_user_with_permission("facebook_leads.manage"))
):
    """
    🔄 RBAC-ENABLED: Test Facebook API connection and permissions
    
    **Required Permission:** `facebook_leads.manage`
    """
    try:
        result = await facebook_leads_service.verify_facebook_access()
        
        if result["success"]:
            logger.info(f"Facebook API test successful for {current_user.get('email')}")
            return {
                "success": True,
                "message": "Facebook API connection working properly",
                "connection_details": result.get("user_info", {}),
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            logger.warning(f"Facebook API test failed for {current_user.get('email')}: {result.get('error')}")
            return {
                "success": False,
                "error": result.get("error", "Unknown connection error"),
                "timestamp": datetime.utcnow().isoformat()
            }
        
    except Exception as e:
        logger.error(f"Facebook API test error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Connection test failed: {str(e)}"
        )


# =====================================
# RBAC-ENABLED LEAD FORM MANAGEMENT
# =====================================

@router.get("/forms", summary="Get Facebook lead forms with category mapping")
async def get_lead_forms_with_mapping(
    current_user: dict = Depends(get_user_with_permission("facebook_leads.view"))
):
    """
    🔄 RBAC-ENABLED: Get all lead forms with smart category mapping preview
    
    **Required Permission:** `facebook_leads.view`
    """
    try:
        # Get forms from Facebook
        result = await facebook_leads_service.get_lead_forms()
        
        if not result["success"]:
            return result
        
        # Add category mapping to each form
        enhanced_forms = []
        form_names = []
        
        for form in result["forms"]:
            form_name = form.get("name", "")
            form_names.append(form_name)
            
            # Get category mapping
            mapping = facebook_category_mapper.map_form_to_category(form_name)
            
            enhanced_form = {
                **form,
                "category_mapping": mapping,
                "suggested_category": mapping["category"],
                "mapping_confidence": mapping["confidence"],
                "mapping_reasoning": mapping["reasoning"]
            }
            enhanced_forms.append(enhanced_form)
        
        # Get mapping statistics
        mapping_stats = facebook_category_mapper.get_mapping_statistics(form_names)
        
        logger.info(f"Retrieved {len(enhanced_forms)} forms with category mapping for {current_user.get('email')}")
        
        return {
            "success": True,
            "forms": enhanced_forms,
            "total_forms": len(enhanced_forms),
            "mapping_statistics": mapping_stats,
            "message": f"Found {len(enhanced_forms)} lead forms with smart category mapping"
        }
        
    except Exception as e:
        logger.error(f"Failed to get lead forms with mapping: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get lead forms: {str(e)}"
        )


@router.get("/forms/{form_id}/preview", summary="Preview leads from specific form")
async def preview_leads_from_form(
    form_id: str,
    limit: int = Query(10, ge=1, le=50, description="Number of leads to preview"),
    current_user: dict = Depends(get_user_with_permission("facebook_leads.view"))
):
    """
    🔄 RBAC-ENABLED: Preview leads from a specific Facebook form without importing
    
    **Required Permission:** `facebook_leads.view`
    """
    try:
        result = await facebook_leads_service.get_leads_from_form(form_id, limit)
        
        if result["success"]:
            logger.info(f"Previewed {result.get('total_leads', 0)} leads from form {form_id} for {current_user.get('email')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to preview leads from form {form_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to preview leads: {str(e)}"
        )


# =====================================
# RBAC-ENABLED LEAD IMPORT
# =====================================

@router.post("/import/single-form", summary="Import leads from single Facebook form")
async def import_leads_single_form(
    import_request: LeadImportRequest,
    current_user: dict = Depends(get_user_with_permission("facebook_leads.import"))
):
    """
    🔄 RBAC-ENABLED: Import leads from a single Facebook form with immediate stats response
    
    **Required Permission:** `facebook_leads.import`
    """
    try:
        # Get form info for category mapping
        forms_result = await facebook_leads_service.get_lead_forms()
        
        if not forms_result["success"]:
            raise HTTPException(status_code=400, detail="Failed to get form information")
        
        # Find the specific form
        target_form = None
        for form in forms_result["forms"]:
            if form["id"] == import_request.form_id:
                target_form = form
                break
        
        if not target_form:
            raise HTTPException(status_code=404, detail="Form not found")
        
        # Determine category
        if import_request.category_override:
            category = import_request.category_override
            logger.info(f"Using category override: {category}")
        else:
            mapping = facebook_category_mapper.map_form_to_category(target_form["name"])
            category = mapping["category"]
            logger.info(f"Auto-mapped form '{target_form['name']}' to category '{category}'")
        
        # Call import directly (synchronous)
        import_result = await facebook_leads_service.import_leads_to_crm(
            import_request.form_id,
            current_user.get('email'),
            category,
            import_request.limit
        )
        
        logger.info(f"Completed Facebook lead import from form {import_request.form_id} by {current_user.get('email')}")
        
        # Return the actual import results
        if import_result["success"]:
            return {
                "success": True,
                "message": f"Import completed for form '{target_form['name']}'",
                "form_info": {
                    "form_id": import_request.form_id,
                    "form_name": target_form["name"],
                    "assigned_category": category,
                },
                "import_status": "completed",
                "stats": {
                    "total_facebook_leads": import_result["summary"]["total_facebook_leads"],
                    "imported_count": import_result["summary"]["imported_count"],
                    "failed_count": import_result["summary"]["failed_count"],
                    "skipped_count": import_result["summary"]["skipped_count"]
                }
            }
        else:
            # Handle import failure
            raise HTTPException(
                status_code=500,
                detail=f"Import failed: {import_result.get('message', 'Unknown error')}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to import leads: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import leads: {str(e)}"
        )


# =====================================
# WEBHOOK ENDPOINTS (UNAUTHENTICATED)
# =====================================

@router.get("/webhook", summary="Facebook webhook verification")
async def verify_webhook(
    request: Request,
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"), 
    hub_challenge: str = Query(alias="hub.challenge")
):
    """
    ℹ️ UNAUTHENTICATED: Verify Facebook webhook during setup
    
    **No Authentication Required** - Called by Facebook's servers
    """
    try:
        from ..config.settings import settings
        
        if hub_mode == "subscribe" and hub_verify_token == settings.facebook_webhook_verify_token:
            logger.info("Facebook webhook verification successful")
            return int(hub_challenge)
        else:
            logger.warning(f"Facebook webhook verification failed: mode={hub_mode}, token_match={hub_verify_token == settings.facebook_webhook_verify_token}")
            raise HTTPException(status_code=403, detail="Verification failed")
            
    except Exception as e:
        logger.error(f"Webhook verification error: {str(e)}")
        raise HTTPException(status_code=500, detail="Verification error")


@router.post("/webhook", summary="Facebook webhook for automatic lead import")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    ℹ️ UNAUTHENTICATED: Receive Facebook webhook notifications for automatic lead import
    
    **No Authentication Required** - Called by Facebook's servers
    """
    try:
        webhook_data = await request.json()
        
        logger.info(f"Received Facebook webhook: {webhook_data}")
        
        # Process webhook in background for automatic lead import
        background_tasks.add_task(
            facebook_leads_service.process_webhook_lead,
            webhook_data
        )
        
        return {"status": "received"}
        
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return {"status": "error", "message": str(e)}


# =====================================
# RBAC-ENABLED DASHBOARD & ANALYTICS
# =====================================

@router.get("/dashboard", summary="Facebook leads dashboard data")
async def get_facebook_dashboard(
    current_user: dict = Depends(get_user_with_permission("facebook_leads.view"))
):
    """
    🔄 RBAC-ENABLED: Get dashboard data for Facebook leads management
    
    **Required Permission:** `facebook_leads.view`
    """
    try:
        # Get forms with mapping
        forms_result = await facebook_leads_service.get_lead_forms()
        
        if not forms_result["success"]:
            return {"success": False, "error": "Failed to fetch forms data"}
        
        # Process dashboard statistics
        total_forms = len(forms_result["forms"])
        form_names = [form.get("name", "") for form in forms_result["forms"]]
        
        # Category mapping statistics
        mapping_stats = facebook_category_mapper.get_mapping_statistics(form_names)
        
        dashboard_data = {
            "success": True,
            "summary": {
                "total_forms": total_forms,
                "mapping_confidence": f"{mapping_stats['high_confidence_percentage']:.1f}%",
                "category_distribution": mapping_stats["category_distribution"],
                "last_sync": datetime.utcnow().isoformat()
            },
            "forms": forms_result["forms"],
            "mapping_statistics": mapping_stats,
            "api_status": "connected"
        }
        
        logger.info(f"Generated Facebook dashboard data for {current_user.get('email')}")
        return dashboard_data
        
    except Exception as e:
        logger.error(f"Failed to generate dashboard data: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get dashboard data: {str(e)}"
        )


@router.get("/debug-config", summary="Debug Facebook configuration")
async def debug_facebook_config(
    current_user: dict = Depends(get_user_with_permission("facebook_leads.manage"))
):
    """
    🔄 RBAC-ENABLED: Debug what configuration the server is using
    
    **Required Permission:** `facebook_leads.manage`
    """
    try:
        result = await facebook_leads_service.verify_facebook_access()
        token_preview = facebook_leads_service.access_token[:30] + "..." if facebook_leads_service.access_token else "None"
        
        return {
            "server_token_preview": token_preview,
            "server_page_id": facebook_leads_service.page_id,
            "connection_test": result,
            "expected_token_start": "EAALomt4zDXoBPaMjyCJ...",
            "tokens_match": facebook_leads_service.access_token.startswith("EAALomt4zDXoBPaMjyCJ") if facebook_leads_service.access_token else False
        }
    except Exception as e:
        return {"error": str(e)}