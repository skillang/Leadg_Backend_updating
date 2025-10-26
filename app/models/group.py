# app/models/group.py
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime

class GroupBase(BaseModel):
    """Base group model"""
    name: str = Field(..., min_length=1, max_length=100, description="Group name")
    description: Optional[str] = Field(None, max_length=500, description="Optional group description")
    
    @validator('name')
    def validate_name(cls, v):
        """Validate and clean group name"""
        if not v.strip():
            raise ValueError("Group name cannot be empty")
        return v.strip()

class GroupCreate(GroupBase):
    """Model for creating a group"""
    lead_ids: Optional[List[str]] = Field(default_factory=list, description="Array of lead IDs to add to group")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Engineering Batch 2025",
                "description": "Students interested in Engineering programs for Fall 2025 intake",
                "lead_ids": ["NS-1", "SA-5", "WA-10"]
            }
        }

class GroupUpdate(BaseModel):
    """
    Model for updating a group
    ✅ UPDATED: Removed lead_ids - use /add or /remove endpoints instead
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="New group name")
    description: Optional[str] = Field(None, max_length=500, description="New group description")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Engineering Batch 2025 - Updated",
                "description": "Updated description for the group"
            }
        }

class GroupAddLeads(BaseModel):
    """Model for adding leads to an existing group"""
    lead_ids: List[str] = Field(..., min_items=1, description="Lead IDs to add to the group")
    
    class Config:
        json_schema_extra = {
            "example": {
                "lead_ids": ["NS-20", "SA-15", "WA-30"]
            }
        }

class GroupRemoveLeads(BaseModel):
    """Model for removing leads from a group"""
    lead_ids: List[str] = Field(..., min_items=1, description="Lead IDs to remove from the group")
    
    class Config:
        json_schema_extra = {
            "example": {
                "lead_ids": ["NS-1", "SA-5"]
            }
        }

class GroupResponse(GroupBase):
    """
    Response model for a single group
    ✅ UPDATED: Returns user names instead of user IDs
    """
    group_id: str = Field(..., description="Unique group identifier (e.g., GRP-001)")
    lead_ids: List[str] = Field(default_factory=list, description="Array of lead IDs in this group")
    lead_count: int = Field(..., description="Number of leads in the group")
    
    # ✅ CHANGED: Return names instead of IDs
    created_by_name: str = Field(..., description="Name of user who created the group")
    created_at: datetime = Field(..., description="Group creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    updated_by_name: Optional[str] = Field(None, description="Name of user who last updated the group")
    
    class Config:
        json_schema_extra = {
            "example": {
                "group_id": "GRP-001",
                "name": "Engineering Batch 2025",
                "description": "Students interested in Engineering programs",
                "lead_ids": ["NS-1", "SA-5", "WA-10"],
                "lead_count": 3,
                "created_by_name": "John Smith",  # ✅ Changed from created_by ID
                "created_at": "2025-01-15T10:30:00Z",
                "updated_at": "2025-01-15T10:30:00Z",
                "updated_by_name": "Jane Doe"  # ✅ Changed from updated_by ID
            }
        }

class GroupWithLeadsResponse(GroupResponse):
    """Response model with populated lead details"""
    leads: List[dict] = Field(default_factory=list, description="Populated lead objects with basic info")
    
    class Config:
        json_schema_extra = {
            "example": {
                "group_id": "GRP-001",
                "name": "Engineering Batch 2025",
                "description": "Students interested in Engineering programs",
                "lead_ids": ["NS-1", "SA-5"],
                "lead_count": 2,
                "created_by_name": "John Smith",  # ✅ Changed from created_by ID
                "created_at": "2025-01-15T10:30:00Z",
                "updated_at": "2025-01-15T10:30:00Z",
                "updated_by_name": "Jane Doe",  # ✅ Changed from updated_by ID
                "leads": [
                    {
                        "lead_id": "NS-1",
                        "name": "John Doe",
                        "email": "john@example.com",
                        "contact_number": "+1234567890",
                        "stage": "qualified",
                        "assigned_to_name": "Agent Smith"
                    },
                    {
                        "lead_id": "SA-5",
                        "name": "Jane Smith",
                        "email": "jane@example.com",
                        "contact_number": "+1987654321",
                        "stage": "contacted",
                        "assigned_to_name": "Agent Johnson"
                    }
                ]
            }
        }

class GroupListResponse(BaseModel):
    """
    Response for listing groups with pagination
    ✅ UPDATED: Matches leads pagination format with nested pagination object
    """
    groups: List[GroupResponse] = Field(default_factory=list)
    pagination: Dict[str, Any] = Field(
        ..., 
        description="Pagination information with page, limit, total, pages, has_next, has_prev"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "groups": [
                    {
                        "group_id": "GRP-001",
                        "name": "Engineering Batch 2025",
                        "description": "Engineering students",
                        "lead_ids": ["NS-1", "SA-5"],
                        "lead_count": 2,
                        "created_by_name": "John Smith",
                        "created_at": "2025-01-15T10:30:00Z",
                        "updated_at": "2025-01-15T10:30:00Z",
                        "updated_by_name": "Jane Doe"
                    }
                ],
                "pagination": {
                    "page": 1,
                    "limit": 20,
                    "total": 25,
                    "pages": 2,
                    "has_next": True,
                    "has_prev": False
                }
            }
        }

class GroupDeleteResponse(BaseModel):
    """Response for group deletion"""
    success: bool = Field(default=True)
    message: str = Field(..., description="Deletion confirmation message")
    group_id: str = Field(..., description="ID of the deleted group")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Group 'Engineering Batch 2025' deleted successfully",
                "group_id": "GRP-001"
            }
        }