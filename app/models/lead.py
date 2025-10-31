# app/models/lead.py - Updated with dynamic stages, statuses, course levels, sources, new assignment features, WhatsApp integration, and Call Stats

from pydantic import BaseModel, Field, validator, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum

# ============================================================================
# DYNAMIC VALIDATION HELPERS (For stages, statuses, course levels, and sources)
# ============================================================================

async def validate_stage_exists(stage_name: str) -> bool:
    """Validate that a stage exists and is active"""
    try:
        from ..config.database import get_database
        
        db = get_database()
        stage = await db.lead_stages.find_one({
            "name": stage_name,
            "is_active": True
        })
        return stage is not None
    except:
        return True  # Fallback - if validation fails, allow the stage

async def validate_status_exists(status_name: str) -> bool:
    """Validate that a status exists and is active"""
    try:
        from ..config.database import get_database
        
        db = get_database()
        status = await db.lead_statuses.find_one({
            "name": status_name,
            "is_active": True
        })
        return status is not None
    except:
        return True  # Fallback - if validation fails, allow the status

async def get_default_stage() -> str:
    """Get the default stage for new leads"""
    try:
        from ..config.database import get_database
        
        db = get_database()
        default_stage = await db.lead_stages.find_one({
            "is_default": True,
            "is_active": True
        })
        
        if default_stage:
            return default_stage["name"]
        
        # Fallback to first active stage
        first_stage = await db.lead_stages.find_one(
            {"is_active": True},
            sort=[("sort_order", 1)]
        )
        
        return first_stage["name"] if first_stage else "Pending"
    except:
        return "Pending"

async def get_default_status() -> str:
    """Get the default status for new leads"""
    try:
        from ..config.database import get_database
        
        db = get_database()
        default_status = await db.lead_statuses.find_one({
            "is_default": True,
            "is_active": True
        })
        
        if default_status:
            return default_status["name"]
        
        # Fallback to first active status
        first_status = await db.lead_statuses.find_one(
            {"is_active": True},
            sort=[("sort_order", 1)]
        )
        
        return first_status["name"] if first_status else "New"
    except:
        return "New"

# NEW: Dynamic Course Level Functions
async def get_default_course_level() -> str:
    """Get the default course level for new leads"""
    try:
        from ..config.database import get_database
        
        db = get_database()
        default_course_level = await db.course_levels.find_one({
            "is_default": True,
            "is_active": True
        })
        
        if default_course_level:
            return default_course_level["name"]
        
        # Fallback to first active course level
        first_course_level = await db.course_levels.find_one(
            {"is_active": True},
            sort=[("sort_order", 1)]
        )
        
        return first_course_level["name"] if first_course_level else "undergraduate"
    except:
        return "undergraduate"

async def validate_course_level_exists(course_level: str) -> bool:
    """Validate if course level exists and is active"""
    try:
        from ..config.database import get_database
        
        db = get_database()
        course_level_doc = await db.course_levels.find_one({
            "name": course_level,
            "is_active": True
        })
        
        return course_level_doc is not None
    except:
        return True  # Fallback - if validation fails, allow the course level

# NEW: Dynamic Source Functions
async def get_default_source() -> str:
    """Get the default source for new leads"""
    try:
        from ..config.database import get_database
        
        db = get_database()
        default_source = await db.sources.find_one({
            "is_default": True,
            "is_active": True
        })
        
        if default_source:
            return default_source["name"]
        
        # Fallback to first active source
        first_source = await db.sources.find_one(
            {"is_active": True},
            sort=[("sort_order", 1)]
        )
        
        return first_source["name"] if first_source else "website"
    except:
        return "website"

async def validate_source_exists(source: str) -> bool:
    """Validate if source exists and is active"""
    try:
        from ..config.database import get_database
        
        db = get_database()
        source_doc = await db.sources.find_one({
            "name": source,
            "is_active": True
        })
        
        return source_doc is not None
    except:
        return True  # Fallback - if validation fails, allow the source

# ============================================================================
# ENUMERATION CLASSES (Only Experience Level remains as enum)
# ============================================================================

# Experience Level Enumeration (Keep as enum - not dynamic)
class ExperienceLevel(str, Enum):
    """Experience level enumeration"""
    FRESHER = "fresher"
    LESS_THAN_1_YEAR = "less_than_1_year"
    ONE_TO_THREE_YEARS = "1_to_3_years"
    THREE_TO_FIVE_YEARS = "3_to_5_years"
    FIVE_TO_TEN_YEARS = "5_to_10_years"
    MORE_THAN_TEN_YEARS = "more_than_10_years"

# ============================================================================
# NEW: CALL STATS MODEL
# ============================================================================


class UserCallItem(BaseModel):
    """Individual user call statistics item for list structure"""
    user_id: str = Field(..., description="User ID")
    user_name: str = Field(..., description="User display name")
    user_email: str = Field(..., description="User email address")
    total: int = Field(default=0, description="Total calls by this user")
    answered: int = Field(default=0, description="Answered calls by this user")
    missed: int = Field(default=0, description="Missed calls by this user")

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "686f894b1ca17da22b3533e7",
                "user_name": "Hariharan Hariharan",
                "user_email": "hariharan@skillang.com",
                "total": 7,
                "answered": 0,
                "missed": 7
            }
        }

class CallStatsModel(BaseModel):
    """Call statistics tracking model with list-based user calls"""
    total_calls: int = Field(default=0, description="Total calls made to this lead")
    answered_calls: int = Field(default=0, description="Number of answered calls")
    missed_calls: int = Field(default=0, description="Number of missed/unanswered calls")
    last_call_date: Optional[datetime] = Field(None, description="Date of last call")
    user_calls: List[UserCallItem] = Field(
        default_factory=list, 
        description="Call counts per user as list of user call items"
    )
    last_updated: Optional[datetime] = Field(None, description="When call stats were last refreshed")
    phone_tracked: Optional[str] = Field(None, description="Phone number being tracked")
    
    @classmethod
    def create_default(cls) -> "CallStatsModel":
        """Create a default initialized call stats object for new leads"""
        return cls(
            total_calls=0,
            answered_calls=0,
            missed_calls=0,
            last_call_date=None,
            user_calls=[],
            last_updated=datetime.utcnow()
        )
    
    class Config:
        json_schema_extra = {
            "example": {
                "total_calls": 7,
                "answered_calls": 0,
                "missed_calls": 7,
                "last_call_date": "2025-09-08T14:30:00Z",
                "user_calls": [
                    {
                        "user_id": "686f894b1ca17da22b3533e7",
                        "user_name": "Hariharan Hariharan", 
                        "user_email": "hariharan@skillang.com",
                        "total": 7,
                        "answered": 0,
                        "missed": 7
                    }
                ],
                "last_updated": "2025-09-08T14:35:00Z",
                "phone_tracked": "+919087924334"
            }
        }
# ============================================================================
# BASIC LEAD MODELS (UPDATED FOR DYNAMIC FIELDS)
# ============================================================================

# Basic Info Section (Tab 1) - UPDATED with dynamic fields
class LeadBasicInfo(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr = Field(...)
    contact_number: str = Field(..., min_length=10, max_length=20)
    source: str = Field(default="website", description="Lead source (dynamic)")
    category: str = Field(..., min_length=1, description="Lead category (required)")
    
    # Optional additional fields
    age: Optional[int] = Field(None, ge=16, le=100, description="Age of the lead (16-100)")
    experience: Optional[ExperienceLevel] = Field(None, description="Work experience level")
    nationality: Optional[str] = Field(None, max_length=100, description="Nationality of the lead")
    current_location: Optional[str] = Field(None, max_length=150, description="Current location of the lead")
    course_level: Optional[str] = Field(None, description="Course level (dynamic)")
    date_of_birth: Optional[datetime] = Field(None, description="Date of birth (YYYY-MM-DD format)")
    
    # NEW: Call stats field
    call_stats: Optional[CallStatsModel] = Field(default=None, description="Call statistics for this lead")
    @validator('age', pre=True)
    def validate_age_enhanced(cls, v):
        """Enhanced age validator that handles Facebook age formats"""
        import re
        import logging
        
        logger = logging.getLogger(__name__)
        
        if v is None or v == "":
            return None
            
        # If already an integer, validate range
        if isinstance(v, int):
            if 16 <= v <= 100:
                return v
            else:
                logger.warning(f"Age {v} outside valid range (16-100)")
                return None
        
        # Handle string values from Facebook
        if isinstance(v, str):
            age_str = v.strip().lower()
            
            # Handle empty strings and null-like values
            if not age_str or age_str in ["not specified", "n/a", "undefined", "null", "none"]:
                return None
            
            try:
                # Handle range formats like "25_-_30", "18_-_25"
                range_match = re.match(r'(\d+)_?-_?(\d+)', age_str)
                if range_match:
                    min_age = int(range_match.group(1))
                    max_age = int(range_match.group(2))
                    middle_age = (min_age + max_age) // 2
                    if 16 <= middle_age <= 100:
                        logger.info(f"Age range '{v}' converted to {middle_age}")
                        return middle_age
                
                # Handle "35+" format  
                plus_match = re.match(r'(\d+)\+', age_str)
                if plus_match:
                    base_age = int(plus_match.group(1))
                    if 16 <= base_age <= 100:
                        logger.info(f"Age '{v}' converted to {base_age}")
                        return base_age
                
                # Handle direct integer strings "25", "30"
                if age_str.isdigit():
                    age = int(age_str)
                    if 16 <= age <= 100:
                        return age
                
                # Extract first number from complex strings
                number_match = re.search(r'(\d+)', age_str)
                if number_match:
                    age = int(number_match.group(1))
                    if 16 <= age <= 100:
                        logger.info(f"Extracted age {age} from '{v}'")
                        return age
                
            except (ValueError, AttributeError) as e:
                logger.warning(f"Error parsing age '{v}': {e}")
                return None
        
        logger.warning(f"Could not parse age value: '{v}', setting to None")
        return None
    
    @validator('category')
    def validate_category(cls, v):
        if not v.strip():
            raise ValueError("Category is required")
        return v.strip()
    
    @validator('nationality')
    def validate_nationality(cls, v):
        if v and not v.strip():
            return None
        return v.strip() if v else None
    
    @validator('current_location')
    def validate_current_location(cls, v):
        """Validate current_location field - auto-default to 'Not mentioned' if not provided"""
        if v and v.strip():
            return v.strip()
        return "Not mentioned"  # Auto-default value
    
    @validator('source')
    def validate_source_string(cls, v):
        """Basic source validation - detailed validation at service level"""
        if not v or not v.strip():
            return "website"  # Default fallback
        return v.strip().lower().replace(' ', '_')
    
    @validator('course_level')
    def validate_course_level_string(cls, v):
        """Basic course level validation - detailed validation at service level"""
        if not v or not v.strip():
            return None  # Optional field
        return v.strip().lower().replace(' ', '_')
    
    # NEW: Add validator for date_of_birth
    @validator('date_of_birth', pre=True)
    def parse_date_of_birth(cls, v):
        """Parse date_of_birth from string to datetime"""
        if v is None:
            return None
            
        if isinstance(v, str):
            try:
                # Parse string date to datetime (midnight time)
                return datetime.strptime(v, "%Y-%m-%d")
            except ValueError:
                raise ValueError("Date must be in YYYY-MM-DD format")
                
        if isinstance(v, datetime):
            return v
            
        raise ValueError("Invalid date format")
    
    @validator('date_of_birth')
    def validate_date_of_birth(cls, v):
        """Validate date of birth"""
        if v:
            today = datetime.now().date()
            birth_date = v.date()  # Extract date part for validation
            
            if birth_date > today:
                raise ValueError("Date of birth cannot be in the future")
            
            # Calculate age
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            
            if age < 16 or age > 100:
                raise ValueError("Age must be between 16-100 years")
                
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Dani Sharma",
                "email": "dani.sharma@example.com",
                "contact_number": "+91-9876543210",
                "source": "website",
                "category": "Study Abroad",
                "age": 24,
                "experience": "1_to_3_years",
                "nationality": "Indian",
                "current_location": "Mumbai, India",
                "course_level": "undergraduate"
            }
        }

# Status & Tags Section (Tab 2) 
class LeadStatusAndTags(BaseModel):
    """Status and tags section with dynamic stage and status"""
    stage: str = Field(default="Pending", description="Current lead stage (dynamic)")
    status: str = Field(default="New", description="Current lead status (dynamic)")
    lead_score: int = Field(default=0, ge=0, le=100, description="Lead score (0-100)")
    tags: List[str] = Field(default_factory=list, description="Lead tags (e.g., IELTS Ready, Engineering)")
    
    @validator('stage')
    def validate_stage(cls, v):
        """Basic stage validation - more validation done at service level"""
        if not v or not v.strip():
            return "Pending"  # Default fallback
        return v.strip()
    
    @validator('status')
    def validate_status(cls, v):
        """Basic status validation - more validation done at service level"""
        if not v or not v.strip():
            return "New"  # Default fallback
        return v.strip()
    
    @validator('tags')
    def validate_tags(cls, v):
        """Ensure tags are properly formatted"""
        if v:
            # Remove empty tags and strip whitespace
            return [tag.strip() for tag in v if tag.strip()]
        return []

# Assignment Section (Tab 3)
class LeadAssignmentInfo(BaseModel):
    """Assignment information section - always auto-assign via round-robin"""
    assigned_to: Optional[str] = Field(None, description="Leave None for automatic round-robin assignment")

    class Config:
        json_schema_extra = {
            "example": {
                "assigned_to": None  # Always use None for auto-assignment
            }
        }

# Additional Info Section (Tab 4)
class LeadAdditionalInfo(BaseModel):
    """Additional information section - just custom notes"""
    notes: Optional[str] = Field(None, max_length=2000, description="Custom notes added by the admin/user")

# Complete Lead Creation Model - UPDATED
class LeadCreateComprehensive(BaseModel):
    """Comprehensive lead creation model with all sections"""
    
    # Basic Info (Required) - Now includes dynamic course level and source
    basic_info: LeadBasicInfo
    
    # Status & Tags (Optional with defaults)
    status_and_tags: Optional[LeadStatusAndTags] = Field(default_factory=LeadStatusAndTags)
    
    # Assignment (Optional - will auto-assign if not provided)
    assignment: Optional[LeadAssignmentInfo] = Field(default_factory=LeadAssignmentInfo)
    
    # Additional Info (Optional)
    additional_info: Optional[LeadAdditionalInfo] = Field(default_factory=LeadAdditionalInfo)
    
    class Config:
        json_schema_extra = {
            "example": {
                "basic_info": {
                    "name": "Dani Sharma",
                    "email": "dani.sharma@example.com",
                    "contact_number": "+91-9876543210",
                    "source": "website",
                    "category": "Study Abroad",
                    "age": 24,
                    "experience": "1_to_3_years",
                    "nationality": "Indian",
                    "current_location": "Mumbai, India",
                    "course_level": "undergraduate"
                },
                "status_and_tags": {
                    "stage": "contacted",
                    "lead_score": 45,
                    "tags": ["IELTS Ready", "Engineering", "MBA"]
                },
                "assignment": {
                    "assigned_to": None  # Always None for auto round-robin assignment
                },
                "additional_info": {
                    "notes": "Student is very interested and has IELTS score of 7.5. Currently based in Mumbai."
                }
            }
        }

# ============================================================================
# NEW: SELECTIVE ROUND ROBIN & MULTI-ASSIGNMENT MODELS
# ============================================================================

class SelectiveRoundRobinRequest(BaseModel):
    """Request model for selective round robin assignment"""
    selected_user_emails: List[str] = Field(..., description="List of user emails to include in round robin")
    
    @validator('selected_user_emails')
    def validate_selected_users(cls, v):
        if not v:
            raise ValueError("At least one user must be selected for round robin")
        
        # Remove duplicates and empty emails
        unique_emails = list(set([email.strip().lower() for email in v if email.strip()]))
        
        if not unique_emails:
            raise ValueError("No valid email addresses provided")
        
        return unique_emails
    
    class Config:
        json_schema_extra = {
            "example": {
                "selected_user_emails": [
                    "john.doe@leadg.com",
                    "jane.smith@leadg.com",
                    "mike.johnson@leadg.com"
                ]
            }
        }

class MultiUserAssignmentRequest(BaseModel):
    """Request model for assigning lead to multiple users"""
    user_emails: List[str] = Field(..., description="List of user emails to assign the lead to")
    reason: Optional[str] = Field("Multi-user assignment", description="Reason for assignment")
    
    @validator('user_emails')
    def validate_user_emails(cls, v):
        if not v:
            raise ValueError("At least one user must be provided for assignment")
        
        # Remove duplicates and empty emails
        unique_emails = list(set([email.strip().lower() for email in v if email.strip()]))
        
        if not unique_emails:
            raise ValueError("No valid email addresses provided")
        
        if len(unique_emails) > 10:  # Reasonable limit
            raise ValueError("Cannot assign to more than 10 users at once")
        
        return unique_emails
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_emails": [
                    "john.doe@leadg.com",
                    "jane.smith@leadg.com"
                ],
                "reason": "Team collaboration required"
            }
        }

class RemoveFromAssignmentRequest(BaseModel):
    """Request model for removing user from multi-assignment"""
    user_email: str = Field(..., description="Email of user to remove from assignment")
    reason: Optional[str] = Field("Removed from assignment", description="Reason for removal")
    
    @validator('user_email')
    def validate_user_email(cls, v):
        if not v or not v.strip():
            raise ValueError("User email is required")
        return v.strip().lower()
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_email": "john.doe@leadg.com",
                "reason": "User no longer available"
            }
        }

class BulkAssignmentRequest(BaseModel):
    """Request model for bulk lead assignment with selective round robin"""
    lead_ids: List[str] = Field(..., description="List of lead IDs to assign")
    assignment_method: str = Field(..., description="Assignment method: 'all_users' or 'selected_users'")
    selected_user_emails: Optional[List[str]] = Field(None, description="Required if assignment_method is 'selected_users'")
    
    @validator('assignment_method')
    def validate_assignment_method(cls, v):
        if v not in ['all_users', 'selected_users']:
            raise ValueError("Assignment method must be 'all_users' or 'selected_users'")
        return v
    
    @validator('selected_user_emails')
    def validate_selected_users_conditional(cls, v, values):
        assignment_method = values.get('assignment_method')
        
        if assignment_method == 'selected_users':
            if not v:
                raise ValueError("selected_user_emails is required when assignment_method is 'selected_users'")
            
            # Remove duplicates and empty emails
            unique_emails = list(set([email.strip().lower() for email in v if email.strip()]))
            
            if not unique_emails:
                raise ValueError("No valid email addresses provided")
            
            return unique_emails
        
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "lead_ids": ["LD-1001", "LD-1002", "LD-1003"],
                "assignment_method": "selected_users",
                "selected_user_emails": [
                    "john.doe@leadg.com",
                    "jane.smith@leadg.com"
                ]
            }
        }

# ============================================================================
# NEW: RESPONSE MODELS
# ============================================================================

class MultiUserAssignmentResponse(BaseModel):
    """Response model for multi-user assignment"""
    success: bool
    message: str
    assigned_users: List[str]
    invalid_users: List[str]
    primary_assignee: Optional[str]
    co_assignees: List[str]
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Lead assigned to 2 users successfully",
                "assigned_users": ["john.doe@leadg.com", "jane.smith@leadg.com"],
                "invalid_users": [],
                "primary_assignee": "john.doe@leadg.com",
                "co_assignees": ["jane.smith@leadg.com"]
            }
        }

class BulkAssignmentResponse(BaseModel):
    """Response model for bulk assignment with selective round robin"""
    success: bool
    message: str
    total_leads: int
    successfully_assigned: int
    failed_assignments: List[Dict[str, str]]
    assignment_method: str
    selected_users: Optional[List[str]]
    assignment_summary: List[Dict[str, Any]]
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Bulk assignment completed",
                "total_leads": 3,
                "successfully_assigned": 3,
                "failed_assignments": [],
                "assignment_method": "selected_users",
                "selected_users": ["john.doe@leadg.com", "jane.smith@leadg.com"],
                "assignment_summary": [
                    {"lead_id": "LD-1001", "assigned_to": "john.doe@leadg.com", "status": "success"},
                    {"lead_id": "LD-1002", "assigned_to": "jane.smith@leadg.com", "status": "success"},
                    {"lead_id": "LD-1003", "assigned_to": "john.doe@leadg.com", "status": "success"}
                ]
            }
        }

class SelectiveRoundRobinResponse(BaseModel):
    """Response model for selective round robin assignment"""
    success: bool
    message: str
    selected_user: Optional[str]
    available_users: List[str]
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "User selected for assignment",
                "selected_user": "john.doe@leadg.com",
                "available_users": ["john.doe@leadg.com", "jane.smith@leadg.com"]
            }
        }

# ============================================================================
# NEW: EXTENDED LEAD RESPONSE WITH MULTI-ASSIGNMENT INFO + WHATSAPP
# ============================================================================

class LeadResponseExtended(BaseModel):
    """Extended lead response with multi-assignment information and WhatsApp tracking"""
    lead_id: str
    status: str
    name: str
    email: str
    contact_number: Optional[str]
    source: Optional[str]
    category: Optional[str]
    
    # Single assignment fields (backward compatibility)
    assigned_to: Optional[str]
    assigned_to_name: Optional[str]
    
    # Multi-assignment fields
    co_assignees: List[str] = Field(default_factory=list, description="Additional users assigned to this lead")
    co_assignees_names: List[str] = Field(default_factory=list, description="Names of co-assignees")
    is_multi_assigned: bool = Field(default=False, description="Whether lead is assigned to multiple users")
    
    # Assignment metadata
    assignment_method: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    
    # All assignees (computed field)
    all_assignees: List[str] = Field(default_factory=list, description="All users assigned to this lead")
    all_assignees_names: List[str] = Field(default_factory=list, description="Names of all assignees")
    
    # NEW: WhatsApp Activity Fields
    last_whatsapp_activity: Optional[datetime] = Field(None, description="Last WhatsApp interaction timestamp")
    last_whatsapp_message: Optional[str] = Field(None, description="Preview of last WhatsApp message")
    whatsapp_message_count: int = Field(default=0, description="Total WhatsApp messages for this lead")
    unread_whatsapp_count: int = Field(default=0, description="Unread WhatsApp messages count")
    
    # NEW: Call Stats Field
    call_stats: Optional[CallStatsModel] = Field(default=None, description="Call statistics for this lead")
    
    def __init__(self, **data):
        super().__init__(**data)
        
        # Compute all_assignees and all_assignees_names
        all_assignees = []
        all_assignees_names = []
        
        if self.assigned_to:
            all_assignees.append(self.assigned_to)
            all_assignees_names.append(self.assigned_to_name or self.assigned_to)
        
        if self.co_assignees:
            all_assignees.extend(self.co_assignees)
            all_assignees_names.extend(self.co_assignees_names or self.co_assignees)
        
        self.all_assignees = all_assignees
        self.all_assignees_names = all_assignees_names
    
    class Config:
        json_schema_extra = {
            "example": {
                "lead_id": "LD-1001",
                "status": "New",
                "name": "John Smith",
                "email": "john.smith@example.com",
                "contact_number": "+1-555-0123",
                "source": "website",
                "category": "Technology",
                "assigned_to": "john.doe@leadg.com",
                "assigned_to_name": "John Doe",
                "co_assignees": ["jane.smith@leadg.com"],
                "co_assignees_names": ["Jane Smith"],
                "is_multi_assigned": True,
                "assignment_method": "multi_user_manual",
                "all_assignees": ["john.doe@leadg.com", "jane.smith@leadg.com"],
                "all_assignees_names": ["John Doe", "Jane Smith"],
                "last_whatsapp_activity": "2024-01-15T10:30:00Z",
                "last_whatsapp_message": "Thanks for the information!",
                "whatsapp_message_count": 5,
                "unread_whatsapp_count": 2
            }
        }

# ============================================================================
# NEW: USER SELECTION MODELS
# ============================================================================

class UserSelectionOption(BaseModel):
    """Model for user selection in assignment interfaces"""
    email: str
    name: str
    current_lead_count: int
    is_active: bool
    departments: List[str] = Field(default_factory=list)
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "john.doe@leadg.com",
                "name": "John Doe",
                "current_lead_count": 15,
                "is_active": True,
                "departments": ["sales"]
            }
        }

class UserSelectionResponse(BaseModel):
    """Response model for getting assignable users"""
    total_users: int
    users: List[UserSelectionOption]
    
    class Config:
        json_schema_extra = {
            "example": {
                "total_users": 3,
                "users": [
                    {
                        "email": "john.doe@leadg.com",
                        "name": "John Doe",
                        "current_lead_count": 15,
                        "is_active": True,
                        "departments": ["sales"]
                    },
                    {
                        "email": "jane.smith@leadg.com",
                        "name": "Jane Smith",
                        "current_lead_count": 12,
                        "is_active": True,
                        "departments": ["sales"]
                    }
                ]
            }
        }

# ============================================================================
# LEGACY MODELS FOR BACKWARD COMPATIBILITY (UPDATED FOR DYNAMIC FIELDS + WHATSAPP + CALL STATS)
# ============================================================================

# Lead Response Model - UPDATED
class LeadResponseComprehensive(BaseModel):
    """Comprehensive lead response model with WhatsApp tracking and Call Stats"""
    # System Info
    id: str
    lead_id: str
    status: str  # Uses dynamic status instead of enum
    created_by: str
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    last_contacted: Optional[datetime] = None
    
    # Basic Info - UPDATED with dynamic fields including current_location
    name: str
    email: str
    contact_number: str
    source: str
    category: str
    age: Optional[int] = None
    experience: Optional[ExperienceLevel] = None
    nationality: Optional[str] = None
    current_location: Optional[str] = None
    date_of_birth: Optional[str] = None
    
    # Status & Tags
    stage: str
    lead_score: int
    priority: str = "medium"
    tags: List[str] = Field(default_factory=list)
    
    # Assignment (enhanced for multi-assignment)
    assigned_to: Optional[str] = None
    assigned_to_name: Optional[str] = None
    co_assignees: List[str] = Field(default_factory=list)
    co_assignees_names: List[str] = Field(default_factory=list)
    is_multi_assigned: bool = Field(default=False)
    assignment_method: Optional[str] = None
    assignment_history: Optional[List[Dict[str, Any]]] = None
    
    # Additional Info
    notes: Optional[str] = None
    
    # Legacy fields for backward compatibility
    phone_number: Optional[str] = None
    country_of_interest: Optional[str] = None
    course_level: Optional[str] = None
    
    # NEW: WhatsApp Activity Fields
    last_whatsapp_activity: Optional[datetime] = Field(None, description="Last WhatsApp interaction timestamp")
    last_whatsapp_message: Optional[str] = Field(None, description="Preview of last WhatsApp message")
    whatsapp_message_count: int = Field(default=0, description="Total WhatsApp messages for this lead")
    unread_whatsapp_count: int = Field(default=0, description="Unread WhatsApp messages count")
    
    # NEW: Call Stats Field
    call_stats: Optional[CallStatsModel] = Field(default=None, description="Call statistics for this lead")

# Legacy models for backward compatibility - UPDATED
class LeadCreate(LeadBasicInfo):
    """Legacy lead creation model for backward compatibility"""
    assigned_to: Optional[str] = None
    country_of_interest: Optional[str] = None
    course_level: Optional[str] = None
    source: Optional[str] = "website"
    tags: Optional[List[str]] = Field(default_factory=list)
    notes: Optional[str] = None
    # Include all new fields in legacy model too
    age: Optional[int] = Field(None, ge=16, le=100)
    experience: Optional[ExperienceLevel] = None
    nationality: Optional[str] = Field(None, max_length=100)
    current_location: Optional[str] = Field(None, max_length=150)
    date_of_birth: Optional[datetime] = Field(None, description="Date of birth (YYYY-MM-DD format)")
    
    # NEW: WhatsApp fields (for completeness, but will be auto-initialized)
    last_whatsapp_activity: Optional[datetime] = None
    last_whatsapp_message: Optional[str] = None
    whatsapp_message_count: int = 0
    unread_whatsapp_count: int = 0
    
    # NEW: Call Stats Field
    call_stats: Optional[CallStatsModel] = Field(default=None, description="Call statistics for this lead")

class LeadUpdate(BaseModel):
    """Legacy lead update model - UPDATED with WhatsApp fields and Call Stats"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = Field(None, min_length=10, max_length=20)
    contact_number: Optional[str] = Field(None, min_length=10, max_length=20)
    country_of_interest: Optional[str] = Field(None, max_length=200)
    course_level: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    lead_score: Optional[int] = Field(None, ge=0, le=100)
    priority: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = Field(None, max_length=1000)
    category: Optional[str] = Field(None, min_length=1)
    # Add all new fields to update model
    age: Optional[int] = Field(None, ge=16, le=100)
    experience: Optional[ExperienceLevel] = None
    nationality: Optional[str] = Field(None, max_length=100)
    current_location: Optional[str] = Field(None, max_length=150)
    date_of_birth: Optional[datetime] = Field(None, description="Date of birth")
    
    # NEW: WhatsApp fields (usually managed by system, but can be updated manually)
    last_whatsapp_activity: Optional[datetime] = None
    last_whatsapp_message: Optional[str] = Field(None, max_length=500)
    whatsapp_message_count: Optional[int] = Field(None, ge=0)
    unread_whatsapp_count: Optional[int] = Field(None, ge=0)
    
    # NEW: Call Stats Field
    call_stats: Optional[CallStatsModel] = Field(default=None, description="Call statistics for this lead")
    co_assignees: Optional[List[str]] = Field(None, description="List of co-assignee email addresses")
    co_assignees_names: Optional[List[str]] = Field(None, description="List of co-assignee names (auto-populated)")


class LeadAssign(BaseModel):
    """Lead assignment/reassignment model"""
    assigned_to: str = Field(..., description="User email to assign the lead to")
    notes: Optional[str] = Field(None, max_length=500, description="Reason for assignment/reassignment")

class LeadResponse(BaseModel):
    """Legacy lead response model - UPDATED with WhatsApp fields and Call Stats"""
    id: str
    lead_id: str
    name: str
    email: str
    phone_number: str
    contact_number: str
    status: str
    assigned_to: Optional[str] = None
    assigned_to_name: Optional[str] = None
    created_by: str
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    source: str
    category: str
    # Add all new fields to response
    age: Optional[int] = None
    experience: Optional[ExperienceLevel] = None
    nationality: Optional[str] = None
    date_of_birth: Optional[str] = None
    current_location: Optional[str] = None
    course_level: Optional[str] = None
    
    # NEW: WhatsApp Activity Fields
    last_whatsapp_activity: Optional[datetime] = None
    last_whatsapp_message: Optional[str] = None
    whatsapp_message_count: int = 0
    unread_whatsapp_count: int = 0
    
    # NEW: Call Stats Field
    call_stats: Optional[CallStatsModel] = Field(default=None, description="Call statistics for this lead")

class LeadListResponse(BaseModel):
    """Lead list response model with timeline-compatible pagination"""
    leads: List[LeadResponseComprehensive]
    pagination: Dict[str, Any] = Field(
        ..., 
        description="Pagination information with page, limit, total, pages, has_next, has_prev"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "leads": [],
                "pagination": {
                    "page": 1,
                    "limit": 20,
                    "total": 100,
                    "pages": 5,
                    "has_next": True,
                    "has_prev": False
                }
            }
        }

class LeadsFilterRequest(BaseModel):
    """Request model for filtering leads with optional lead_ids array"""
    lead_ids: Optional[List[str]] = Field(None, description="Array of lead IDs to filter")
    stage: Optional[str] = Field(None, description="Filter by stage")
    status: Optional[str] = Field(None, description="Filter by status")
    category: Optional[str] = Field(None, description="Filter by category")
    source: Optional[str] = Field(None, description="Filter by source")
    search: Optional[str] = Field(None, description="Search in name, email, lead_id")
    assigned_to: Optional[str] = Field(None, description="Filter by assigned user (admin only)")
    created_from: Optional[str] = Field(None, description="Filter by creation date from")
    created_to: Optional[str] = Field(None, description="Filter by creation date to")
    updated_from: Optional[str] = Field(None, description="Filter by update date from")
    updated_to: Optional[str] = Field(None, description="Filter by update date to")
    last_contacted_from: Optional[str] = Field(None, description="Filter by last contact date from")
    last_contacted_to: Optional[str] = Field(None, description="Filter by last contact date to")

class LeadStatusUpdate(BaseModel):
    """Lead status update model"""
    status: str
    notes: Optional[str] = Field(None, max_length=500)

class LeadBulkCreate(BaseModel):
    """Bulk lead creation model"""
    leads: List[LeadCreateComprehensive]
    force_create: bool = False

class LeadBulkCreateResponse(BaseModel):
    """Bulk lead creation response"""
    success: bool
    message: str
    summary: Dict[str, Any]
    results: List[Dict[str, Any]]

# Lead Creation Response
class LeadCreateResponseComprehensive(BaseModel):
    """Comprehensive lead creation response"""
    success: bool
    message: str
    lead: Optional[LeadResponseComprehensive] = None
    duplicate_check: Optional[Dict[str, Any]] = None
    assignment_info: Optional[Dict[str, Any]] = None

# Duplicate Check Result
class DuplicateCheckResult(BaseModel):
    """Duplicate check result"""
    is_duplicate: bool
    checked: bool
    existing_lead_id: Optional[str] = None
    duplicate_field: Optional[str] = None
    message: Optional[str] = None

# ============================================================================
# NEW: WHATSAPP-SPECIFIC LEAD UPDATE MODELS
# ============================================================================

class LeadWhatsAppActivityUpdate(BaseModel):
    """Model for updating WhatsApp activity on a lead"""
    last_whatsapp_activity: Optional[datetime] = None
    last_whatsapp_message: Optional[str] = Field(None, max_length=500, description="Preview of last message")
    increment_message_count: bool = Field(default=False, description="Whether to increment message count by 1")
    increment_unread_count: bool = Field(default=False, description="Whether to increment unread count by 1")
    reset_unread_count: bool = Field(default=False, description="Whether to reset unread count to 0")
    
    class Config:
        json_schema_extra = {
            "example": {
                "last_whatsapp_activity": "2024-01-15T10:30:00Z",
                "last_whatsapp_message": "Thanks for the information!",
                "increment_message_count": True,
                "increment_unread_count": False,
                "reset_unread_count": False
            }
        }

class LeadWhatsAppSummary(BaseModel):
    """Summary model for lead WhatsApp activity"""
    lead_id: str
    lead_name: str
    assigned_to: Optional[str]
    last_whatsapp_activity: Optional[datetime]
    last_whatsapp_message: Optional[str]
    whatsapp_message_count: int
    unread_whatsapp_count: int
    has_whatsapp_activity: bool = Field(default=False, description="Whether lead has any WhatsApp messages")
    
    def __init__(self, **data):
        super().__init__(**data)
        # Automatically set has_whatsapp_activity based on message count
        self.has_whatsapp_activity = self.whatsapp_message_count > 0
    
    class Config:
        json_schema_extra = {
            "example": {
                "lead_id": "LD-1001",
                "lead_name": "John Smith",
                "assigned_to": "john.doe@leadg.com",
                "last_whatsapp_activity": "2024-01-15T10:30:00Z",
                "last_whatsapp_message": "Thanks for the information!",
                "whatsapp_message_count": 5,
                "unread_whatsapp_count": 2,
                "has_whatsapp_activity": True
            }
        }

# ============================================================================
# NEW: CALL COUNT REFRESH MODELS
# ============================================================================

class CallCountRefreshRequest(BaseModel):
    """Request model for manual call count refresh"""
    lead_id: str = Field(..., description="Lead ID to refresh call count for")
    force_refresh: bool = Field(default=False, description="Force refresh even if recently updated")
    
    class Config:
        json_schema_extra = {
            "example": {
                "lead_id": "LD-1000",
                "force_refresh": False
            }
        }

class CallCountRefreshResponse(BaseModel):
    """Response model for call count refresh"""
    success: bool = Field(..., description="Refresh success status")
    message: str = Field(..., description="Response message")
    lead_id: str = Field(..., description="Lead ID that was refreshed")
    call_stats: Optional[CallStatsModel] = Field(None, description="Updated call statistics")
    refresh_time: datetime = Field(default_factory=datetime.utcnow, description="When refresh was performed")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Call count refreshed successfully",
                "lead_id": "LD-1000",
                "call_stats": {
                    "total_calls": 5,
                    "answered_calls": 3,
                    "missed_calls": 2,
                    "user_calls": {
                        "user_id_1": {"total": 3, "answered": 2, "missed": 1}
                    }
                },
                "refresh_time": "2025-09-08T14:35:00Z"
            }
        }

class BulkCallCountRefreshRequest(BaseModel):
    """Request model for bulk call count refresh"""
    lead_ids: Optional[List[str]] = Field(None, description="Specific lead IDs to refresh (empty = all leads)")
    assigned_to_user: Optional[str] = Field(None, description="Refresh only leads assigned to this user")
    force_refresh: bool = Field(default=False, description="Force refresh even if recently updated")
    batch_size: int = Field(default=50, ge=1, le=200, description="Number of leads to process at once")
    
    class Config:
        json_schema_extra = {
            "example": {
                "lead_ids": ["LD-1000", "LD-1001", "LD-1002"],
                "assigned_to_user": None,
                "force_refresh": False,
                "batch_size": 50
            }
        }

class BulkCallCountRefreshResponse(BaseModel):
    """Response model for bulk call count refresh"""
    success: bool = Field(..., description="Overall success status")
    message: str = Field(..., description="Response message")
    total_leads: int = Field(..., description="Total leads processed")
    successful_refreshes: int = Field(..., description="Number of successful refreshes")
    failed_refreshes: int = Field(..., description="Number of failed refreshes")
    processing_time: float = Field(..., description="Time taken in seconds")
    failed_lead_ids: List[str] = Field(default_factory=list, description="Lead IDs that failed to refresh")
    refresh_time: datetime = Field(default_factory=datetime.utcnow, description="When bulk refresh was performed")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Bulk call count refresh completed",
                "total_leads": 100,
                "successful_refreshes": 98,
                "failed_refreshes": 2,
                "processing_time": 45.6,
                "failed_lead_ids": ["LD-1050", "LD-1051"],
                "refresh_time": "2025-09-08T14:35:00Z"
            }
        }