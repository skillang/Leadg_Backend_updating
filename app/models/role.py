"""
LeadG CRM - Role-Based Access Control (RBAC) Models
====================================================

This module defines all models related to the dynamic RBAC system:
- Permission: Individual permissions (69 total)
- PermissionGrant: Permission assignment to roles
- Role: Dynamic roles with permissions
- RoleAssignment: Historical tracking of role assignments
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
from bson import ObjectId


# ========================================
# ENUMS
# ========================================
class PermissionCategory(str, Enum):
    """Categories for organizing permissions (14 categories with subcategory support)"""
    DASHBOARD = "dashboard"
    REPORTING = "reporting"
    LEAD_MANAGEMENT = "lead_management"
    CONTACT_MANAGEMENT = "contact_management"
    TASK_MANAGEMENT = "task_management"
    USER_MANAGEMENT = "user_management"
    ROLE_PERMISSION_MANAGEMENT = "role_permission_management"
    SYSTEM_CONFIGURATION = "system_configuration"
    COMMUNICATION = "communication"
    TEAM_MANAGEMENT = "team_management"
    CONTENT_ACTIVITY = "content_activity"
    FACEBOOK_LEADS = "facebook_leads"
    BATCH = "batch"
    NOTIFICATION = "notification"

class PermissionScope(str, Enum):
    """Scope levels for permissions"""
    OWN = "own"       # User's own data
    TEAM = "team"     # User's team data
    ALL = "all"       # All data in system
    NONE = "none"     # No scope (for system-wide actions)


class RoleType(str, Enum):
    """Type of role"""
    SYSTEM = "system"    # Predefined, cannot be deleted
    CUSTOM = "custom"    # Admin-created, can be deleted


class RoleAssignmentStatus(str, Enum):
    """Status of role assignment"""
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


# ========================================
# PERMISSION MODELS
# ========================================

class Permission(BaseModel):
    """
    Individual permission definition
    110 permissions total across 14 categories with subcategory support
    """
    code: str = Field(..., description="Unique permission code (e.g., 'lead.view')")
    name: str = Field(..., description="Display name")
    description: str = Field(..., description="Detailed description")
    category: PermissionCategory = Field(..., description="Permission category")
    subcategory: Optional[str] = Field(None, description="Optional subcategory (e.g., 'lead', 'lead_group', 'email')")
    resource: str = Field(..., description="Resource type (lead, contact, task, etc.)")
    action: str = Field(..., description="Action (view, add, update, delete, etc.)")
    scope: PermissionScope = Field(default=PermissionScope.OWN, description="Permission scope")
    is_system: bool = Field(default=True, description="System permission (cannot be deleted)")
    requires_permissions: List[str] = Field(default_factory=list, description="Dependencies")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "code": "lead.view",
                "name": "View Own Leads",
                "description": "Can view own assigned leads",
                "category": "lead_management",
                "subcategory": "lead",
                "resource": "lead",
                "action": "view",
                "scope": "own",
                "is_system": True,
                "requires_permissions": [],
                "metadata": {"ui_group": "Lead Operations"}
            }
        }


class PermissionSubcategory(BaseModel):
    """
    Subcategory grouping within a permission category
    Used in permission matrix UI
    """
    name: str = Field(..., description="Subcategory identifier (e.g., 'lead', 'email')")
    display_name: str = Field(..., description="Human-readable name (e.g., 'Lead', 'Email')")
    permissions: List[Dict[str, Any]] = Field(default_factory=list, description="Permissions in this subcategory")
    permission_count: int = Field(default=0, description="Number of permissions in subcategory")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "lead",
                "display_name": "Lead",
                "permission_count": 10,
                "permissions": [
                    {
                        "code": "lead.view",
                        "name": "View Own Leads",
                        "scope": "own"
                    }
                ]
            }
        }


class PermissionGrant(BaseModel):
    """
    Permission granted to a role
    """
    permission_code: str = Field(..., description="Permission code from Permission.code")
    granted: bool = Field(default=True, description="Whether permission is granted")
    scope: Optional[PermissionScope] = Field(None, description="Override scope (if different from default)")
    conditions: Dict[str, Any] = Field(default_factory=dict, description="Additional conditions")
    granted_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "permission_code": "lead.read_team",
                "granted": True,
                "scope": "team",
                "conditions": {},
                "granted_at": "2025-01-15T10:30:00Z"
            }
        }


# ========================================
# ROLE MODELS
# ========================================

class RoleBase(BaseModel):
    """Base role model with common fields"""
    name: str = Field(..., min_length=3, max_length=50, description="Unique role name (lowercase, underscore)")
    display_name: str = Field(..., min_length=3, max_length=100, description="Display name for UI")
    description: Optional[str] = Field(None, max_length=500, description="Role description")
    type: RoleType = Field(default=RoleType.CUSTOM, description="Role type")
    is_active: bool = Field(default=True, description="Whether role is active")
    
    @validator('name')
    def validate_role_name(cls, v):
        """Ensure role name is lowercase with underscores"""
        if not v.replace('_', '').isalnum():
            raise ValueError('Role name must contain only alphanumeric characters and underscores')
        if v != v.lower():
            raise ValueError('Role name must be lowercase')
        return v
    
    class Config:
        use_enum_values = True


class RoleCreate(RoleBase):
    """Model for creating a new role"""
    permissions: List[PermissionGrant] = Field(default_factory=list, description="Permissions for this role")
    can_manage_users: bool = Field(default=False, description="Can manage team members")
    can_assign_leads: bool = Field(default=False, description="Can assign leads to others")
    can_view_all_data: bool = Field(default=False, description="Can view all organization data")
    can_export_data: bool = Field(default=False, description="Can export data")
    max_team_size: Optional[int] = Field(None, description="Maximum team members (null = unlimited)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "sales_manager",
                "display_name": "Sales Manager",
                "description": "Manages sales team and processes",
                "type": "custom",
                "permissions": [
                    {"permission_code": "lead.create", "granted": True},
                    {"permission_code": "lead.read_all", "granted": True}
                ],
                "can_manage_users": True,
                "can_assign_leads": True,
                "can_view_all_data": False
            }
        }


class RoleUpdate(BaseModel):
    """Model for updating an existing role"""
    display_name: Optional[str] = Field(None, min_length=3, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    permissions: Optional[List[PermissionGrant]] = None
    can_manage_users: Optional[bool] = None
    can_assign_leads: Optional[bool] = None
    can_view_all_data: Optional[bool] = None
    can_export_data: Optional[bool] = None
    max_team_size: Optional[int] = None
    is_active: Optional[bool] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "display_name": "Senior Sales Manager",
                "description": "Updated description",
                "permissions": [
                    {"permission_code": "lead.create", "granted": True},
                    {"permission_code": "lead.delete", "granted": True}
                ],
                "can_manage_users": True
            }
        }


class RoleResponse(RoleBase):
    """Model for role API responses"""
    id: str = Field(..., description="Role ID")
    permissions: List[PermissionGrant] = Field(default_factory=list)
    can_manage_users: bool = Field(default=False)
    can_assign_leads: bool = Field(default=False)
    can_view_all_data: bool = Field(default=False)
    can_export_data: bool = Field(default=False)
    max_team_size: Optional[int] = None
    users_count: int = Field(default=0, description="Number of users with this role")
    is_deletable: bool = Field(default=True, description="Can this role be deleted")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = Field(None, description="User email who created this role")
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439011",
                "name": "sales_manager",
                "display_name": "Sales Manager",
                "description": "Manages sales team",
                "type": "custom",
                "permissions": [
                    {"permission_code": "lead.create", "granted": True},
                    {"permission_code": "lead.read_all", "granted": True}
                ],
                "can_manage_users": True,
                "can_assign_leads": True,
                "users_count": 5,
                "is_deletable": True,
                "created_at": "2025-01-15T10:30:00Z"
            }
        }


class RoleListResponse(BaseModel):
    """Response model for listing roles"""
    success: bool = True
    roles: List[RoleResponse]
    total: int
    system_roles: int
    custom_roles: int
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "roles": [],
                "total": 5,
                "system_roles": 3,
                "custom_roles": 2
            }
        }

class RoleListItemResponse(BaseModel):
    """Minimal role response for list/table views"""
    id: str = Field(..., description="Role ID")
    name: str = Field(..., description="Unique role identifier")
    display_name: str = Field(..., description="Human-readable name")
    description: Optional[str] = Field(None, description="Role description")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439011",
                "name": "admin",
                "display_name": "Admin",
                "description": "Administrative access"
            }
        }


class RoleListResponse(BaseModel):
    """Response model for listing roles with minimal fields"""
    success: bool = True
    roles: List[RoleListItemResponse] = Field(default_factory=list)
    total: int = Field(default=0)
    system_roles: int = Field(default=0)
    custom_roles: int = Field(default=0)


# ========================================
# ROLE ASSIGNMENT MODELS
# ========================================

class RoleAssignment(BaseModel):
    """
    Historical tracking of role assignments
    Stored in role_assignments collection
    """
    id: Optional[str] = Field(None, description="Assignment ID")
    user_id: str = Field(..., description="User ObjectId as string")
    user_email: str = Field(..., description="User email")
    role_id: str = Field(..., description="Role ObjectId as string")
    role_name: str = Field(..., description="Role name at time of assignment")
    assigned_by: str = Field(..., description="Admin user email who assigned")
    assigned_at: datetime = Field(default_factory=datetime.utcnow)
    status: RoleAssignmentStatus = Field(default=RoleAssignmentStatus.ACTIVE)
    revoked_by: Optional[str] = None
    revoked_at: Optional[datetime] = None
    revoke_reason: Optional[str] = None
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "user_email": "john@company.com",
                "role_id": "507f1f77bcf86cd799439012",
                "role_name": "sales_manager",
                "assigned_by": "admin@company.com",
                "assigned_at": "2025-01-15T10:30:00Z",
                "status": "active"
            }
        }


class RoleAssignRequest(BaseModel):
    """Request to assign role to user"""
    user_email: str = Field(..., description="Email of user to assign role to")
    role_id: str = Field(..., description="Role ID to assign")
    reason: Optional[str] = Field(None, max_length=500, description="Reason for assignment")
    expires_at: Optional[datetime] = Field(None, description="Optional expiration date")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_email": "john@company.com",
                "role_id": "507f1f77bcf86cd799439012",
                "reason": "Promoted to sales manager",
                "expires_at": None
            }
        }


class RoleAssignResponse(BaseModel):
    """Response for role assignment"""
    success: bool = True
    message: str
    assignment_id: str
    user_email: str
    role_name: str
    assigned_by: str
    assigned_at: datetime
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Role assigned successfully",
                "assignment_id": "507f1f77bcf86cd799439013",
                "user_email": "john@company.com",
                "role_name": "sales_manager",
                "assigned_by": "admin@company.com",
                "assigned_at": "2025-01-15T10:30:00Z"
            }
        }


# ========================================
# PERMISSION OVERRIDE MODELS
# ========================================

class PermissionOverride(BaseModel):
    """
    Individual permission override for a specific user
    Allows granting/denying specific permissions outside role
    """
    permission_code: str = Field(..., description="Permission code")
    granted: bool = Field(..., description="Whether permission is granted or denied")
    scope: Optional[PermissionScope] = Field(None, description="Override scope")
    reason: Optional[str] = Field(None, max_length=500, description="Reason for override")
    granted_by: str = Field(..., description="Admin who granted override")
    granted_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = Field(None, description="Optional expiration")
    
    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "permission_code": "lead.delete",
                "granted": True,
                "scope": "own",
                "reason": "Temporary permission for data cleanup",
                "granted_by": "admin@company.com",
                "granted_at": "2025-01-15T10:30:00Z",
                "expires_at": "2025-01-20T10:30:00Z"
            }
        }


class PermissionOverrideRequest(BaseModel):
    """Request to add permission override"""
    user_email: str = Field(..., description="User email")
    permission_code: str = Field(..., description="Permission code")
    granted: bool = Field(..., description="Grant or deny")
    scope: Optional[PermissionScope] = None
    reason: Optional[str] = Field(None, max_length=500)
    expires_at: Optional[datetime] = None
    
    class Config:
        use_enum_values = True


# ========================================
# AUDIT LOG MODELS
# ========================================

class PermissionAuditLog(BaseModel):
    """
    Audit log for permission and role changes
    Stored in permission_audit_log collection
    """
    id: Optional[str] = None
    action_type: str = Field(..., description="Type of action (role_created, permission_granted, etc.)")
    entity_type: str = Field(..., description="Type of entity (role, user, permission)")
    entity_id: str = Field(..., description="ID of affected entity")
    entity_name: str = Field(..., description="Name of affected entity")
    performed_by: str = Field(..., description="User email who performed action")
    performed_at: datetime = Field(default_factory=datetime.utcnow)
    changes: Dict[str, Any] = Field(default_factory=dict, description="Before/after changes")
    reason: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "action_type": "role_created",
                "entity_type": "role",
                "entity_id": "507f1f77bcf86cd799439012",
                "entity_name": "sales_manager",
                "performed_by": "admin@company.com",
                "performed_at": "2025-01-15T10:30:00Z",
                "changes": {
                    "before": {},
                    "after": {
                        "name": "sales_manager",
                        "permissions_count": 15
                    }
                }
            }
        }


# ========================================
# UTILITY MODELS
# ========================================

class PermissionCheck(BaseModel):
    """Model for permission check requests"""
    user_email: str = Field(..., description="User email to check")
    permission_code: str = Field(..., description="Permission code to check")
    resource_id: Optional[str] = Field(None, description="Optional resource ID for ownership checks")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_email": "john@company.com",
                "permission_code": "lead.update",
                "resource_id": "507f1f77bcf86cd799439015"
            }
        }


class PermissionCheckResponse(BaseModel):
    """Response for permission check"""
    has_permission: bool
    permission_code: str
    user_email: str
    granted_via: str = Field(..., description="How permission was granted (role/override/super_admin)")
    scope: Optional[str] = None
    checked_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_schema_extra = {
            "example": {
                "has_permission": True,
                "permission_code": "lead.update",
                "user_email": "john@company.com",
                "granted_via": "role",
                "scope": "team",
                "checked_at": "2025-01-15T10:30:00Z"
            }
        }


class RoleCloneRequest(BaseModel):
    """Request to clone an existing role"""
    source_role_id: str = Field(..., description="Role ID to clone from")
    new_role_name: str = Field(..., min_length=3, max_length=50, description="Name for new role")
    new_display_name: str = Field(..., min_length=3, max_length=100, description="Display name for new role")
    new_description: Optional[str] = Field(None, max_length=500)
    
    class Config:
        json_schema_extra = {
            "example": {
                "source_role_id": "507f1f77bcf86cd799439012",
                "new_role_name": "senior_sales_manager",
                "new_display_name": "Senior Sales Manager",
                "new_description": "Cloned from Sales Manager with additional permissions"
            }
        }


# ========================================
# PERMISSION MATRIX MODELS (FOR UI)
# ========================================

class PermissionMatrixCategory(BaseModel):
    """
    Category in permission matrix with subcategory support
    
    Structure:
    - Categories WITHOUT subcategories: Direct list of permissions
    - Categories WITH subcategories: List of subcategory objects
    """
    category: str = Field(..., description="Category identifier")
    category_display: str = Field(..., description="Category display name")
    has_subcategories: bool = Field(default=False, description="Whether this category has subcategories")
    
    # For categories WITHOUT subcategories
    permissions: Optional[List[Dict[str, Any]]] = Field(None, description="Direct permissions (if no subcategories)")
    
    # For categories WITH subcategories
    action_groups: Optional[List[Dict[str, Any]]] = Field(None, description="Action groups with subcategory info")
    
    class Config:
        json_schema_extra = {
            "examples": [
                # Category WITHOUT subcategories (e.g., Dashboard)
                {
                    "category": "dashboard",
                    "category_display": "Dashboard",
                    "has_subcategories": False,
                    "action_groups": [
                        {
                            "action": "view",
                            "action_display": "View",
                            "resource": "dashboard",
                            "subcategory": None,
                            "permissions": [
                                {"code": "dashboard.view", "name": "View Dashboard", "scope": "own"}
                            ]
                        }
                    ]
                },
                # Category WITH subcategories (e.g., Lead Management)
                {
                    "category": "lead_management",
                    "category_display": "Lead Management",
                    "has_subcategories": True,
                    "action_groups": [
                        {
                            "action": "view",
                            "action_display": "View",
                            "resource": "lead",
                            "subcategory": "lead",
                            "subcategory_display": "Lead",
                            "permissions": [
                                {"code": "lead.view", "name": "View Own Leads", "scope": "own"}
                            ]
                        },
                        {
                            "action": "view",
                            "action_display": "View",
                            "resource": "lead_group",
                            "subcategory": "lead_group",
                            "subcategory_display": "Lead Group",
                            "permissions": [
                                {"code": "lead_group.view", "name": "View Own Lead Groups", "scope": "own"}
                            ]
                        }
                    ]
                }
            ]
        }

class PermissionMatrixResponse(BaseModel):
    """
    Full permission matrix for UI with subcategory support
    
    Returns 110 permissions organized by 14 categories
    Some categories have subcategories, some don't
    """
    success: bool = True
    categories: List[PermissionMatrixCategory] = Field(default_factory=list)
    total_permissions: int = Field(default=110, description="Total permissions in system")
    total_categories: int = Field(default=14, description="Total categories")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "categories": [
                    {
                        "category": "dashboard",
                        "category_display": "Dashboard",
                        "has_subcategories": False,
                        "action_groups": [
                            {
                                "action": "view",
                                "resource": "dashboard",
                                "subcategory": None,
                                "permissions": [
                                    {"code": "dashboard.view", "name": "View Dashboard", "scope": "own"}
                                ]
                            }
                        ]
                    },
                    {
                        "category": "lead_management",
                        "category_display": "Lead Management",
                        "has_subcategories": True,
                        "action_groups": [
                            {
                                "action": "view",
                                "resource": "lead",
                                "subcategory": "lead",
                                "subcategory_display": "Lead",
                                "permissions": [
                                    {"code": "lead.view", "name": "View Own Leads", "scope": "own"}
                                ]
                            }
                        ]
                    }
                ],
                "total_permissions": 110,
                "total_categories": 14
            }
        }
    """Full permission matrix for UI"""
    success: bool = True
    categories: List[PermissionMatrixCategory]
    total_permissions: int
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "categories": [
                    {
                        "category": "lead_management",
                        "display_name": "Lead Management",
                        "permissions": [
                            {
                                "code": "lead.create",
                                "name": "Create Leads",
                                "scopes": ["own", "all"]
                            }
                        ]
                    }
                ],
                "total_permissions": 69
            }
        }