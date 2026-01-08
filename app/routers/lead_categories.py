from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List, Dict, Any
import logging

from app.decorators.timezone_decorator import convert_dates_to_ist

from ..models.lead_category import LeadCategoryCreate, LeadCategoryUpdate, LeadCategoryResponse
from ..services.lead_category_service import lead_category_service
from ..utils.dependencies import get_current_active_user, get_admin_user, get_user_with_permission

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_lead_category(
    category_data: LeadCategoryCreate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("lead_category.create"))
):
    """
    🔄 RBAC-ENABLED: Create a new lead category
    
    **Required Permission:** `lead_category.create`
    
    - **name**: Category name (e.g., "Nursing", "Study Abroad")
    - **short_form**: 2-4 character code for lead IDs (e.g., "NS", "SA", "WA")
    - **description**: Optional description
    """
    try:
        result = await lead_category_service.create_category(
            category_data=category_data,
            created_by=current_user["email"]
        )
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_lead_category: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/", response_model=Dict[str, Any])
async def get_lead_categories(
    include_inactive: bool = Query(False, description="Include inactive categories"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    🔄 RBAC-ENABLED: Get all lead categories
    
    **Required Permission:** `lead_category.view`
    
    - **include_inactive**: Include inactive categories (default: False)
    """
    try:
        categories = await lead_category_service.get_all_categories(include_inactive=include_inactive)
        
        active_categories = [cat for cat in categories if cat.get("is_active", True)]
        inactive_categories = [cat for cat in categories if not cat.get("is_active", True)]
        
        return {
            "success": True,
            "categories": categories,
            "summary": {
                "total": len(categories),
                "active": len(active_categories),
                "inactive": len(inactive_categories)
            }
        }
        
    except Exception as e:
        logger.error(f"Error fetching categories: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/{category_id}")
async def update_lead_category(
    category_id: str,
    category_data: LeadCategoryUpdate,
    current_user: Dict[str, Any] = Depends(get_user_with_permission("lead_category.edit"))
):
    """
    🔄 RBAC-ENABLED: Update lead category
    
    **Required Permission:** `lead_category.edit`
    
    Note: Short form cannot be updated to maintain lead ID consistency
    """
    try:
        result = await lead_category_service.update_category(
            category_id=category_id,
            category_data=category_data
        )
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating category: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/dropdown")
@convert_dates_to_ist()
async def get_categories_for_dropdown(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get active categories for dropdown selection
    Returns simplified format for frontend dropdowns
    """
    try:
        categories = await lead_category_service.get_all_categories(include_inactive=False)
        
        dropdown_options = [
            {
                "value": cat["name"],
                "label": cat["name"],
                "short_form": cat["short_form"],
                "description": cat.get("description")
            }
            for cat in categories
        ]
        
        return {
            "success": True,
            "options": dropdown_options
        }
        
    except Exception as e:
        logger.error(f"Error fetching dropdown categories: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")