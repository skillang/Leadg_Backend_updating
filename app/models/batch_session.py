"""
Batch Session Models
Individual class sessions within a batch
"""

from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
from enum import Enum

# ============================================================================
# ENUMS
# ============================================================================

class SessionStatus(str, Enum):
    """Session lifecycle status"""
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    IN_PROGRESS = "in_progress"

# ============================================================================
# BASE SESSION MODEL
# ============================================================================

class BatchSessionBase(BaseModel):
    """Base session model"""
    batch_id: str = Field(..., description="Parent batch identifier")
    session_number: int = Field(..., ge=1, description="Sequential session number")
    session_date: str = Field(..., description="Date of session in YYYY-MM-DD format")

    @validator('session_date')
    def validate_session_date(cls, v):
        """Validate date format"""
        try:
            datetime.strptime(v, '%Y-%m-%d')
            return v
        except ValueError:
            raise ValueError('session_date must be in YYYY-MM-DD format')

    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "BATCH-001",
                "session_number": 1,
                "session_date": "2025-02-03"
            }
        }

# ============================================================================
# SESSION CREATE MODEL
# ============================================================================

class BatchSessionCreate(BatchSessionBase):
    """Model for creating a session (usually auto-generated)"""
    session_time: Optional[str] = Field(None, description="Time (inherited from batch if not provided)")
    topic: Optional[str] = Field(None, max_length=200, description="Topic for this session")

    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "BATCH-001",
                "session_number": 1,
                "session_date": "2025-02-03",
                "session_time": "10:00 AM - 12:00 PM",
                "topic": "Introduction to Nursing Basics"
            }
        }

# ============================================================================
# SESSION UPDATE MODEL
# ============================================================================

class BatchSessionUpdate(BaseModel):
    """Model for updating session"""
    session_date: Optional[str] = None
    session_status: Optional[SessionStatus] = None
    topic: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=1000, description="Session notes")
    recording_link: Optional[str] = Field(None, description="Link to session recording")

    @validator('session_date')
    def validate_session_date(cls, v):
        """Validate date format"""
        if v:
            try:
                datetime.strptime(v, '%Y-%m-%d')
                return v
            except ValueError:
                raise ValueError('session_date must be in YYYY-MM-DD format')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "session_status": "completed",
                "topic": "Advanced Nursing Techniques",
                "notes": "Covered vital signs and patient care",
                "recording_link": "https://meet.google.com/recording/abc123"
            }
        }

# ============================================================================
# SESSION RESPONSE MODEL
# ============================================================================

class BatchSessionResponse(BaseModel):
    """Response model for session data"""
    id: str = Field(..., description="MongoDB _id as string")
    session_id: str = Field(..., description="Unique session identifier")
    batch_id: str
    batch_name: str = Field(..., description="Name of parent batch")
    session_number: int
    session_date: str
    session_time: str
    session_status: str
    topic: Optional[str] = None
    notes: Optional[str] = None
    recording_link: Optional[str] = None
    attendance_taken: bool = Field(default=False, description="Whether attendance has been marked")
    total_students: int = Field(default=0, description="Total enrolled students in batch")
    present_count: int = Field(default=0, description="Number of students present")
    absent_count: int = Field(default=0, description="Number of students absent")
    created_at: str
    updated_at: str

    class Config:
        json_schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439011",
                "session_id": "SES-001",
                "batch_id": "BATCH-001",
                "batch_name": "January 2025 Nursing Training",
                "session_number": 1,
                "session_date": "2025-02-03",
                "session_time": "10:00 AM - 12:00 PM",
                "session_status": "completed",
                "topic": "Introduction to Nursing",
                "notes": "First session went well",
                "recording_link": "https://meet.google.com/recording/abc123",
                "attendance_taken": True,
                "total_students": 20,
                "present_count": 18,
                "absent_count": 2,
                "created_at": "2025-01-15T10:00:00Z",
                "updated_at": "2025-02-03T14:00:00Z"
            }
        }

# ============================================================================
# SESSION FILTERS
# ============================================================================

class SessionFilterParams(BaseModel):
    """Parameters for filtering sessions"""
    batch_id: Optional[str] = None
    session_status: Optional[SessionStatus] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    attendance_taken: Optional[bool] = None
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=50, ge=1, le=100)

    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "BATCH-001",
                "session_status": "scheduled",
                "attendance_taken": False,
                "page": 1,
                "limit": 50
            }
        }