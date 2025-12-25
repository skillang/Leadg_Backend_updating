"""
Batch Management Models
Handles training batches, demos, and recurring class sessions
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
from enum import Enum

# ============================================================================
# ENUMS
# ============================================================================

class BatchType(str, Enum):
    """Types of batches"""
    DEMO = "demo"
    TRAINING = "training"
    ORIENTATION = "orientation"
    WORKSHOP = "workshop"

class BatchStatus(str, Enum):
    """Batch lifecycle status"""
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SCHEDULED = "scheduled"  # Not yet started

class DayOfWeek(str, Enum):
    """Days of the week for scheduling"""
    MONDAY = "Monday"
    TUESDAY = "Tuesday"
    WEDNESDAY = "Wednesday"
    THURSDAY = "Thursday"
    FRIDAY = "Friday"
    SATURDAY = "Saturday"
    SUNDAY = "Sunday"

# ============================================================================
# SUB-MODELS
# ============================================================================

class BatchTrainer(BaseModel):
    """Trainer information embedded in batch"""
    user_id: str = Field(..., description="User ID of the trainer")
    name: str = Field(..., description="Full name of trainer")
    email: str = Field(..., description="Email of trainer")

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "name": "John Doe",
                "email": "john.doe@example.com"
            }
        }

# ============================================================================
# BASE BATCH MODEL
# ============================================================================

class BatchBase(BaseModel):
    """Base batch model with common fields"""
    batch_name: str = Field(..., min_length=3, max_length=200, description="Name of the batch")
    batch_type: BatchType = Field(..., description="Type of batch")
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    duration_weeks: int = Field(..., ge=1, le=52, description="Duration in weeks (1-52)")
    class_days: List[DayOfWeek] = Field(..., min_items=1, description="Days of the week for classes")
    class_time: str = Field(..., description="Time range (e.g., '10:00 AM - 12:00 PM')")
    max_capacity: int = Field(..., ge=1, le=1000, description="Maximum number of students")

    @validator('start_date')
    def validate_start_date(cls, v):
        """Validate date format"""
        try:
            datetime.strptime(v, '%Y-%m-%d')
            return v
        except ValueError:
            raise ValueError('start_date must be in YYYY-MM-DD format')
    
    @validator('class_time')
    def validate_class_time(cls, v):
        """Validate time format"""
        if not v or len(v.strip()) < 5:
            raise ValueError('class_time must be specified (e.g., "10:00 AM - 12:00 PM")')
        return v.strip()
    
    @validator('class_days')
    def validate_class_days(cls, v):
        """Ensure no duplicate days"""
        if len(v) != len(set(v)):
            raise ValueError('Duplicate days are not allowed')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "batch_name": "January 2025 Nursing Training",
                "batch_type": "training",
                "start_date": "2025-02-01",
                "duration_weeks": 8,
                "class_days": ["Monday", "Wednesday", "Friday"],
                "class_time": "10:00 AM - 12:00 PM",
                "max_capacity": 20
            }
        }

# ============================================================================
# BATCH CREATE MODEL
# ============================================================================

class BatchCreate(BatchBase):
    """Model for creating a new batch"""
    trainer_id: str = Field(..., description="User ID of the assigned trainer")
    description: Optional[str] = Field(None, max_length=1000, description="Batch description")

    class Config:
        json_schema_extra = {
            "example": {
                "batch_name": "January 2025 Nursing Training",
                "batch_type": "training",
                "start_date": "2025-02-01",
                "duration_weeks": 8,
                "class_days": ["Monday", "Wednesday", "Friday"],
                "class_time": "10:00 AM - 12:00 PM",
                "max_capacity": 20,
                "trainer_id": "507f1f77bcf86cd799439011",
                "description": "Comprehensive nursing training program"
            }
        }

# ============================================================================
# BATCH UPDATE MODEL
# ============================================================================

class BatchUpdate(BaseModel):
    """Model for updating batch details"""
    batch_name: Optional[str] = Field(None, min_length=3, max_length=200)
    batch_type: Optional[BatchType] = None
    class_time: Optional[str] = None
    max_capacity: Optional[int] = Field(None, ge=1, le=1000)
    status: Optional[BatchStatus] = None
    trainer_id: Optional[str] = None
    description: Optional[str] = Field(None, max_length=1000)

    @validator('class_time')
    def validate_class_time(cls, v):
        """Validate time format"""
        if v and len(v.strip()) < 5:
            raise ValueError('class_time must be specified (e.g., "10:00 AM - 12:00 PM")')
        return v.strip() if v else v

    class Config:
        json_schema_extra = {
            "example": {
                "batch_name": "Updated Batch Name",
                "max_capacity": 25,
                "status": "active"
            }
        }

# ============================================================================
# BATCH RESPONSE MODEL
# ============================================================================

class BatchResponse(BaseModel):
    """Response model for batch data"""
    id: str = Field(..., description="MongoDB _id as string")
    batch_id: str = Field(..., description="Unique batch identifier (e.g., BATCH-001)")
    batch_name: str
    batch_type: str
    start_date: str
    end_date: str = Field(..., description="Calculated end date")
    duration_weeks: int
    class_days: List[str]
    class_time: str
    total_sessions: int = Field(..., description="Total number of sessions")
    max_capacity: int
    current_enrollment: int = Field(default=0, description="Number of enrolled students")
    trainer: BatchTrainer
    status: str
    description: Optional[str] = None
    created_by: str
    created_by_name: str
    created_at: str
    updated_at: str

    class Config:
        json_schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439011",
                "batch_id": "BATCH-001",
                "batch_name": "January 2025 Nursing Training",
                "batch_type": "training",
                "start_date": "2025-02-01",
                "end_date": "2025-03-29",
                "duration_weeks": 8,
                "class_days": ["Monday", "Wednesday", "Friday"],
                "class_time": "10:00 AM - 12:00 PM",
                "total_sessions": 24,
                "max_capacity": 20,
                "current_enrollment": 15,
                "trainer": {
                    "user_id": "507f1f77bcf86cd799439011",
                    "name": "John Doe",
                    "email": "john.doe@example.com"
                },
                "status": "active",
                "description": "Comprehensive nursing training program",
                "created_by": "507f1f77bcf86cd799439012",
                "created_by_name": "Admin User",
                "created_at": "2025-01-15T10:00:00Z",
                "updated_at": "2025-01-15T10:00:00Z"
            }
        }

# ============================================================================
# BATCH LIST FILTERS
# ============================================================================

class BatchFilterParams(BaseModel):
    """Parameters for filtering batch lists"""
    batch_type: Optional[BatchType] = None
    status: Optional[BatchStatus] = None
    trainer_id: Optional[str] = None
    start_date_from: Optional[str] = None
    start_date_to: Optional[str] = None
    search: Optional[str] = Field(None, description="Search in batch name")
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)
    sort_by: Optional[str] = Field(default="created_at")
    sort_order: Optional[str] = Field(default="desc", pattern="^(asc|desc)$")

    class Config:
        json_schema_extra = {
            "example": {
                "status": "active",
                "trainer_id": "507f1f77bcf86cd799439011",
                "page": 1,
                "limit": 20
            }
        }