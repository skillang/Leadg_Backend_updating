"""
Batch Enrollment Models
Links leads to batches and tracks enrollment status
"""

from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
from enum import Enum

# ============================================================================
# ENUMS
# ============================================================================

class EnrollmentStatus(str, Enum):
    """Enrollment lifecycle status"""
    ENROLLED = "enrolled"
    DROPPED = "dropped"
    COMPLETED = "completed"
    WAITLISTED = "waitlisted"

# ============================================================================
# BASE ENROLLMENT MODEL
# ============================================================================

class BatchEnrollmentBase(BaseModel):
    """Base enrollment model"""
    batch_id: str = Field(..., description="Batch identifier")
    lead_id: str = Field(..., description="Lead identifier")

    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "BATCH-001",
                "lead_id": "NS-123"
            }
        }

# ============================================================================
# ENROLLMENT CREATE MODEL
# ============================================================================

class BatchEnrollmentCreate(BatchEnrollmentBase):
    """Model for enrolling a lead in a batch"""
    notes: Optional[str] = Field(None, max_length=500, description="Enrollment notes")

    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "BATCH-001",
                "lead_id": "NS-123",
                "notes": "Enrolled after counseling session"
            }
        }

# ============================================================================
# BULK ENROLLMENT MODEL
# ============================================================================

class BatchBulkEnrollmentCreate(BaseModel):
    """Model for bulk enrollment"""
    batch_id: str = Field(..., description="Batch identifier")
    lead_ids: list[str] = Field(..., min_items=1, max_items=100, description="List of lead IDs")
    notes: Optional[str] = Field(None, max_length=500)

    @validator('lead_ids')
    def validate_unique_leads(cls, v):
        """Ensure no duplicate lead IDs"""
        if len(v) != len(set(v)):
            raise ValueError('Duplicate lead IDs are not allowed')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "BATCH-001",
                "lead_ids": ["NS-123", "NS-124", "NS-125"],
                "notes": "Bulk enrollment from January intake"
            }
        }

# ============================================================================
# ENROLLMENT UPDATE MODEL
# ============================================================================

class BatchEnrollmentUpdate(BaseModel):
    """Model for updating enrollment"""
    enrollment_status: Optional[EnrollmentStatus] = None
    dropped_reason: Optional[str] = Field(None, max_length=500, description="Reason if dropped")

    class Config:
        json_schema_extra = {
            "example": {
                "enrollment_status": "dropped",
                "dropped_reason": "Personal reasons"
            }
        }

# ============================================================================
# ENROLLMENT RESPONSE MODEL
# ============================================================================

class BatchEnrollmentResponse(BaseModel):
    """Response model for enrollment data"""
    id: str = Field(..., description="MongoDB _id as string")
    enrollment_id: str = Field(..., description="Unique enrollment identifier")
    batch_id: str
    batch_name: str = Field(..., description="Name of the batch")
    lead_id: str
    lead_name: str = Field(..., description="Name of the lead")
    lead_email: str
    enrollment_date: str
    enrollment_status: str
    enrolled_by: str = Field(..., description="User ID who enrolled the lead")
    enrolled_by_name: str
    attendance_count: int = Field(default=0, description="Number of sessions attended")
    total_sessions_held: int = Field(default=0, description="Total sessions conducted so far")
    attendance_percentage: float = Field(default=0.0, description="Attendance percentage")
    dropped_reason: Optional[str] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        json_schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439011",
                "enrollment_id": "ENR-001",
                "batch_id": "BATCH-001",
                "batch_name": "January 2025 Nursing Training",
                "lead_id": "NS-123",
                "lead_name": "John Smith",
                "lead_email": "john.smith@example.com",
                "enrollment_date": "2025-01-20T10:00:00Z",
                "enrollment_status": "enrolled",
                "enrolled_by": "507f1f77bcf86cd799439012",
                "enrolled_by_name": "Admin User",
                "attendance_count": 18,
                "total_sessions_held": 20,
                "attendance_percentage": 90.0,
                "dropped_reason": None,
                "notes": "Enrolled after counseling",
                "created_at": "2025-01-20T10:00:00Z",
                "updated_at": "2025-01-20T10:00:00Z"
            }
        }

# ============================================================================
# ENROLLMENT FILTERS
# ============================================================================

class EnrollmentFilterParams(BaseModel):
    """Parameters for filtering enrollments"""
    batch_id: Optional[str] = None
    lead_id: Optional[str] = None
    enrollment_status: Optional[EnrollmentStatus] = None
    enrolled_by: Optional[str] = None
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)

    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "BATCH-001",
                "enrollment_status": "enrolled",
                "page": 1,
                "limit": 20
            }
        }