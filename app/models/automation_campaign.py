# app/models/automation_campaign.py
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum


class CampaignType(str, Enum):
    """Campaign type enum"""
    WHATSAPP = "whatsapp"
    EMAIL = "email"


class CampaignStatus(str, Enum):
    ACTIVE = "active"       
    PAUSED = "paused"        
    DELETED = "deleted"      
    COMPLETED = "completed" 
    CANCELLED = "cancelled"


class CampaignTemplate(BaseModel):
    """Template configuration for campaign"""
    template_id: str = Field(..., description="Template ID from CMS")
    template_name: str = Field(..., description="Template name")
    sequence_order: int = Field(..., ge=1, description="Order in sequence (1-based)")
    scheduled_day: Optional[int] = Field(None, ge=1, description="Day to send (for auto-schedule)")
    custom_date: Optional[str] = Field(None, description="Specific date to send (YYYY-MM-DD format)")
    
    @validator('custom_date')
    def validate_custom_date(cls, v):
        """Validate custom date format"""
        if v:
            try:
                datetime.strptime(v, '%Y-%m-%d')
            except ValueError:
                raise ValueError('custom_date must be in YYYY-MM-DD format')
        return v


class AutomationCampaign(BaseModel):
    """Main campaign configuration model"""
    campaign_name: str = Field(..., min_length=1, max_length=100, description="Campaign name")
    campaign_type: CampaignType = Field(..., description="Campaign type (whatsapp or email)")
    
    # Lead filtering
    # Lead filtering
    send_to_all: bool = Field(default=False, description="Send to all leads if true")
    stage_ids: List[str] = Field(default=[], description="Stage IDs to filter leads")
    source_ids: List[str] = Field(default=[], description="Source IDs to filter leads")
    category_ids: List[str] = Field(default=[], description="Category IDs to filter leads")  # ✅ NEW LINE
    
    # Scheduling configuration
    use_custom_dates: bool = Field(default=False, description="Use specific dates instead of auto-schedule")
    campaign_duration_days: Optional[int] = Field(None, ge=1, description="Duration in days (for auto-schedule)")
    message_limit: int = Field(..., ge=2, description="Number of messages to send per lead")
    send_time: str = Field(default="10:00", description="Time to send messages (HH:MM format)")
    send_on_weekends: bool = Field(default=True, description="Send messages on weekends")
    
    # Templates
    templates: List[CampaignTemplate] = Field(..., min_items=2, description="Templates to send")
    
    # System fields
    status: CampaignStatus = Field(default=CampaignStatus.ACTIVE)
    created_by: str = Field(..., description="Admin email who created campaign")
    
    @validator('templates')
    def validate_templates(cls, v, values):
        """Validate templates count matches message limit"""
        message_limit = values.get('message_limit')
        if message_limit and len(v) > message_limit:
            raise ValueError(f'Cannot have more than {message_limit} templates (message_limit)')
        if len(v) < 2:
            raise ValueError('Must have at least 2 templates')
        return v
    
    @validator('campaign_duration_days')
    def validate_duration(cls, v, values):
        """Validate duration is greater than or equal to message limit"""
        message_limit = values.get('message_limit')
        use_custom_dates = values.get('use_custom_dates')
        
        if not use_custom_dates and message_limit:
            if v is None:
                raise ValueError('campaign_duration_days is required when use_custom_dates is false')
            if v < message_limit:
                raise ValueError(f'campaign_duration_days ({v}) must be >= message_limit ({message_limit})')
        return v
    
    @validator('templates')
    def validate_template_dates(cls, v, values):
        """Validate templates have either scheduled_day OR custom_date based on mode"""
        use_custom_dates = values.get('use_custom_dates', False)
        
        for template in v:
            if use_custom_dates:
                if not template.custom_date:
                    raise ValueError(f'Template {template.template_name} must have custom_date when use_custom_dates is true')
            else:
                if template.custom_date:
                    raise ValueError(f'Template {template.template_name} should not have custom_date when use_custom_dates is false')
        
        return v
    
    @validator('send_time')
    def validate_send_time(cls, v):
        """Validate time format"""
        try:
            datetime.strptime(v, '%H:%M')
        except ValueError:
            raise ValueError('send_time must be in HH:MM format (e.g., 10:00)')
        return v


class CampaignCreateRequest(BaseModel):
    """Request model for creating campaign"""
    campaign_name: str = Field(..., min_length=1, max_length=100)
    campaign_type: CampaignType
    send_to_all: bool = False
    stage_ids: List[str] = []
    source_ids: List[str] = []
    category_ids: List[str] = []
    use_custom_dates: bool = False
    campaign_duration_days: Optional[int] = None
    message_limit: int = Field(..., ge=2)
    send_time: str = "10:00"
    send_on_weekends: bool = True
    templates: List[CampaignTemplate]


class CampaignResponse(BaseModel):
    """Response model for campaign operations"""
    success: bool
    message: str
    campaign_id: Optional[str] = None
    campaign_name: Optional[str] = None
    total_leads_enrolled: Optional[int] = None
    schedule_preview: Optional[List[Dict[str, Any]]] = None


class CampaignListItem(BaseModel):
    """Campaign list item for display"""
    campaign_id: str
    campaign_name: str
    campaign_type: str
    status: str
    enrolled_leads: int
    messages_sent: int
    messages_pending: int
    created_at: datetime
    created_by: str


class CampaignStatsResponse(BaseModel):
    """Campaign statistics response"""
    campaign_id: str
    campaign_name: str
    status: str
    total_enrolled: int
    active_enrollments: int
    completed_enrollments: int
    criteria_not_matched: int
    total_messages_sent: int
    total_messages_pending: int
    total_messages_failed: int