# app/models/user.py - UPDATED FOR RBAC SYSTEM
# Changes: UserRole enum removed, added RBAC fields (role_id, team_members, permissions)

from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Union, Dict, Any
from datetime import datetime
from enum import Enum
from bson import ObjectId

# ============================================================================
# RBAC: UserRole enum REMOVED - now using dynamic roles from database
# ============================================================================

class CallingStatus(str, Enum):
    """Calling status enumeration for Smartflo integration"""
    PENDING = "pending"
    ACTIVE = "active"
    FAILED = "failed"
    DISABLED = "disabled"
    RETRYING = "retrying"

# 🚀 SIMPLIFIED: Only admin is predefined, everything else is dynamic
class DepartmentType(str, Enum):
    """Only essential predefined department"""
    ADMIN = "admin"  # Only admin is predefined

class UserPermissions(BaseModel):
    """DEPRECATED: Old 2-permission system - kept for backward compatibility
    
    These will be migrated to the new RBAC permission_overrides system.
    New implementations should use the RBAC permission system instead.
    """
    can_create_single_lead: bool = False
    can_create_bulk_leads: bool = False
    granted_by: Optional[str] = None
    granted_at: Optional[datetime] = None
    last_modified_by: Optional[str] = None
    last_modified_at: Optional[datetime] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "can_create_single_lead": True,
                "can_create_bulk_leads": False,
                "granted_by": "admin@company.com",
                "granted_at": "2025-01-15T10:30:00Z",
                "last_modified_by": "admin@company.com",
                "last_modified_at": "2025-01-15T10:30:00Z"
            }
        }


# ============================================================================
# 🆕 RBAC MODELS - New Permission Override System
# ============================================================================

class PermissionOverride(BaseModel):
    """Individual permission override for a user (grant or deny)"""
    permission_code: str = Field(..., description="Permission code (e.g., 'lead.create')")
    granted: bool = Field(..., description="Whether permission is granted (True) or denied (False)")
    granted_by: Optional[str] = Field(None, description="Who granted this override")
    granted_at: Optional[datetime] = Field(None, description="When this override was granted")
    reason: Optional[str] = Field(None, max_length=500, description="Reason for override")
    
    class Config:
        json_schema_extra = {
            "example": {
                "permission_code": "lead.delete_all",
                "granted": True,
                "granted_by": "superadmin@company.com",
                "granted_at": "2025-01-15T10:30:00Z",
                "reason": "Temporary access for data cleanup project"
            }
        }

# ============================================================================
# USER BASE MODEL - UPDATED FOR RBAC
# ============================================================================

class UserBase(BaseModel):
    """Base user model with common fields - UPDATED FOR RBAC"""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    
    # ============================================================================
    # 🔥 RBAC FIELDS (NEW)
    # ============================================================================
    
    # Role Information (replaces old UserRole enum)
    role_id: Optional[str] = Field(None, description="Reference to roles collection")
    role_name: Optional[str] = Field(None, description="Cached role name for quick access")
    is_super_admin: bool = Field(default=False, description="Super admin bypass flag")
    
    # Team Assignment (Simple - No Hierarchy)
    team_id: Optional[str] = Field(None, description="Team ID (reference to teams collection)")
    team_name: Optional[str] = Field(None, description="Team name (cached)")
    is_team_lead: bool = Field(default=False, description="Whether user is the team lead")
    
    # Permission System
    permission_overrides: List[PermissionOverride] = Field(
        default_factory=list,
        description="Individual permission overrides (grant/deny)"
    )
    effective_permissions: List[str] = Field(
        default_factory=list,
        description="Computed final permissions (role + overrides)"
    )
    permissions_last_computed: Optional[datetime] = Field(
        None,
        description="When effective_permissions were last calculated"
    )
    
    # ============================================================================
    # EXISTING FIELDS
    # ============================================================================
    
    is_active: bool = True
    phone: Optional[str] = None
    
    # 🔥 DYNAMIC: Multi-department support with database validation
    departments: Union[str, List[str]] = Field(
        default_factory=list,
        description="Single department string for admin, array of departments for users"
    )

    @validator('departments')
    def validate_departments(cls, v, values):
        """Validate departments (admin is always valid, others checked at runtime)"""
        # RBAC: Role validation removed since we no longer have UserRole enum
        # Department validation is now done at runtime against database
        
        # Handle both string and list inputs
        if isinstance(v, str):
            departments_list = [v.strip()] if v and v.strip() else []
        elif isinstance(v, list):
            departments_list = [dept.strip() for dept in v if dept and dept.strip()]
        else:
            departments_list = []
        
        # Remove empty strings
        departments_list = [dept for dept in departments_list if dept]
        
        # Basic validation - detailed validation done at service layer
        if not departments_list:
            return []
        
        # Remove duplicates and return
        return list(set(departments_list))

# ============================================================================
# USER CREATE MODEL - UPDATED FOR RBAC
# ============================================================================

class UserCreate(UserBase):
    """User creation model - UPDATED FOR RBAC"""
    password: str = Field(..., min_length=8, max_length=100)
    
    # 🆕 RBAC: Accept role_id instead of role enum
    role_id: Optional[str] = Field(None, description="Role ID to assign (defaults to 'user' role)")
    
    # 🆕 OLD: Optional permissions during user creation (DEPRECATED - use RBAC)
    permissions: Optional[UserPermissions] = UserPermissions()

    @validator('password')
    def validate_password(cls, v):
        """Validate password strength"""
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "email": "john.doe@example.com",
                "username": "johndoe",
                "first_name": "John",
                "last_name": "Doe",
                "password": "SecurePass123",
                "role_id": "507f1f77bcf86cd799439011",  # Reference to roles collection
                "phone": "+1-555-123-4567",
                "departments": ["sales", "marketing"],
                "permissions": {  # DEPRECATED - will be ignored in favor of RBAC
                    "can_create_single_lead": False,
                    "can_create_bulk_leads": False
                }
            }
        }

# ============================================================================
# USER RESPONSE MODEL - UPDATED FOR RBAC
# ============================================================================

class UserResponse(BaseModel):
    """User response model (without sensitive data) - UPDATED FOR RBAC"""
    id: str
    email: str
    username: str
    first_name: str
    last_name: str
    
    # ============================================================================
    # 🔥 RBAC FIELDS (NEW) - Included in response
    # ============================================================================
    
    role_id: Optional[str] = Field(None, description="Role reference")
    role_name: Optional[str] = Field(None, description="Role display name")
    is_super_admin: bool = Field(default=False, description="Super admin flag")
    
    # Team Assignment (Simple - No Hierarchy)
    team_id: Optional[str] = Field(None, description="Team ID")
    team_name: Optional[str] = Field(None, description="Team name")
    is_team_lead: bool = Field(default=False, description="Whether user is team lead")
    
    # Permissions
    permission_overrides: List[PermissionOverride] = Field(
        default_factory=list,
        description="Individual overrides"
    )
    effective_permissions: List[str] = Field(
        default_factory=list,
        description="Final computed permissions"
    )
    permissions_last_computed: Optional[datetime] = Field(None)
    
    # ============================================================================
    # EXISTING FIELDS
    # ============================================================================
    
    is_active: bool
    phone: Optional[str] = None
    
    # 🔥 ENHANCED: Support both formats for backward compatibility
    departments: Union[str, List[str]] = Field(
        description="String for admin users, array for regular users"
    )
    
    # 🔥 NEW: Computed field for easy access
    department_list: List[str] = Field(
        description="Always returns departments as a list for consistency"
    )
    
    # 🆕 OLD: Include old permissions for backward compatibility
    permissions: Optional[UserPermissions] = UserPermissions()
    
    created_at: datetime
    last_login: Optional[datetime] = None
    
    # Existing fields
    assigned_leads: List[str] = Field(default_factory=list)
    total_assigned_leads: int = Field(default=0)
    
    # Smartflo integration fields (existing)
    extension_number: Optional[str] = Field(None)
    smartflo_agent_id: Optional[str] = Field(None)
    smartflo_user_id: Optional[str] = Field(None)
    calling_status: CallingStatus = Field(CallingStatus.PENDING)
    
    # 🆕 NEW: Additional calling fields for /auth/me endpoint
    calling_enabled: Optional[bool] = Field(default=False, description="Whether calling is enabled for user")
    tata_extension: Optional[str] = Field(None, description="TATA extension number")
    tata_agent_id: Optional[str] = Field(None, description="TATA agent ID")
    sync_status: Optional[str] = Field(default="unknown", description="TATA sync status")
    ready_to_call: Optional[bool] = Field(default=False, description="Whether user is ready to make calls")

    @validator('department_list', always=True)
    def compute_department_list(cls, v, values):
        """Compute department_list from departments field"""
        departments = values.get('departments', [])
        if isinstance(departments, str):
            return [departments]
        return departments if isinstance(departments, list) else []

    class Config:
        json_schema_extra = {
            "example": {
                "id": "60f1b2a3c4d5e6f7g8h9i0j1",
                "email": "user@example.com",
                "username": "johndoe",
                "first_name": "John",
                "last_name": "Doe",
                "role_id": "507f1f77bcf86cd799439011",
                "role_name": "Team Lead",
                "is_super_admin": False,
                "team_id": "team_507f1f77bcf86cd799439012",
                "team_name": "Sales Team Alpha",
                "is_team_lead": True,
                "permission_overrides": [],
                "effective_permissions": ["lead.create", "lead.read_team", "lead.update_own"],
                "permissions_last_computed": "2025-01-15T10:30:00Z",
                "is_active": True,
                "phone": "+1-555-123-4567",
                "departments": ["sales", "marketing"],
                "department_list": ["sales", "marketing"],
                "permissions": {
                    "can_create_single_lead": True,
                    "can_create_bulk_leads": False
                },
                "created_at": "2025-01-15T10:30:00Z",
                "last_login": "2025-01-15T15:45:00Z",
                "assigned_leads": ["LD-1001", "LD-1002"],
                "total_assigned_leads": 2,
                "extension_number": "+917965083165",
                "smartflo_agent_id": "0506197500004",
                "calling_status": "pending",
                "calling_enabled": True,
                "tata_extension": "+917965083165",
                "tata_agent_id": "0506197500004",
                "sync_status": "already_synced",
                "ready_to_call": True
            }
        }

# ============================================================================
# USER UPDATE MODEL - UPDATED FOR RBAC
# ============================================================================

class UserUpdate(BaseModel):
    """User update model - UPDATED FOR RBAC"""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    departments: Optional[Union[str, List[str]]] = None
    is_active: Optional[bool] = None
    
    # 🆕 RBAC: Allow updating role
    role_id: Optional[str] = Field(None, description="New role ID to assign")
    
    # 🆕 TEAM: Allow updating team assignment (Simple - No Hierarchy)
    team_id: Optional[str] = Field(None, description="New team ID to assign")
    
    # 🆕 OLD: Allow updating permissions through user update (DEPRECATED)
    permissions: Optional[UserPermissions] = None

    @validator('departments')
    def validate_departments_update(cls, v):
        """Validate departments during update"""
        if v is None:
            return v
            
        # Handle both string and list inputs
        if isinstance(v, str):
            departments_list = [v] if v else []
        elif isinstance(v, list):
            departments_list = v
        else:
            return v
        
        return departments_list if len(departments_list) > 1 else (departments_list[0] if departments_list else None)

# ============================================================================
# PERMISSION MANAGEMENT MODELS (DEPRECATED - kept for backward compatibility)
# ============================================================================

class PermissionUpdateRequest(BaseModel):
    """DEPRECATED: Old 2-permission update - use RBAC permission overrides instead
    
    Request model for updating user permissions
    """
    user_email: str = Field(..., description="Email of the user to update permissions for")
    can_create_single_lead: bool = Field(..., description="Allow user to create single leads")
    can_create_bulk_leads: bool = Field(..., description="Allow user to create bulk leads")
    reason: Optional[str] = Field(None, max_length=500, description="Reason for permission change")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_email": "john@company.com",
                "can_create_single_lead": True,
                "can_create_bulk_leads": False,
                "reason": "Promoted to senior sales agent"
            }
        }

class PermissionUpdateResponse(BaseModel):
    """DEPRECATED: Response model for old permission updates"""
    success: bool
    message: str
    user_email: str
    updated_permissions: UserPermissions
    updated_by: str
    updated_at: datetime
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Permissions updated successfully",
                "user_email": "john@company.com",
                "updated_permissions": {
                    "can_create_single_lead": True,
                    "can_create_bulk_leads": False,
                    "granted_by": "admin@company.com",
                    "granted_at": "2025-01-15T10:30:00Z",
                    "last_modified_by": "admin@company.com",
                    "last_modified_at": "2025-01-15T10:30:00Z"
                },
                "updated_by": "admin@company.com",
                "updated_at": "2025-01-15T10:30:00Z"
            }
        }

class UserPermissionsListResponse(BaseModel):
    """DEPRECATED: Response model for listing users with old permissions"""
    success: bool
    users: List[UserResponse]
    total: int
    summary: dict
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "users": [
                    {
                        "id": "user123",
                        "email": "john@company.com",
                        "first_name": "John",
                        "last_name": "Smith",
                        "role_name": "User",
                        "permissions": {
                            "can_create_single_lead": True,
                            "can_create_bulk_leads": False,
                            "granted_by": "admin@company.com"
                        }
                    }
                ],
                "total": 5,
                "summary": {
                    "total_users": 5,
                    "with_single_permission": 3,
                    "with_bulk_permission": 1,
                    "with_no_permissions": 1
                }
            }
        }

# ============================================================================
# 🆕 RBAC PERMISSION OVERRIDE MODELS
# ============================================================================

class PermissionOverrideRequest(BaseModel):
    """Request to add/update a permission override for a user"""
    user_email: str = Field(..., description="User to grant/deny permission")
    permission_code: str = Field(..., description="Permission code (e.g., 'lead.delete_all')")
    granted: bool = Field(..., description="True to grant, False to deny")
    reason: Optional[str] = Field(None, max_length=500, description="Reason for override")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_email": "john@company.com",
                "permission_code": "lead.delete_all",
                "granted": True,
                "reason": "Temporary access for data cleanup"
            }
        }

class PermissionOverrideResponse(BaseModel):
    """Response for permission override operation"""
    success: bool
    message: str
    user_email: str
    permission_code: str
    granted: bool
    override: PermissionOverride
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Permission override added successfully",
                "user_email": "john@company.com",
                "permission_code": "lead.delete_all",
                "granted": True,
                "override": {
                    "permission_code": "lead.delete_all",
                    "granted": True,
                    "granted_by": "superadmin@company.com",
                    "granted_at": "2025-01-15T10:30:00Z",
                    "reason": "Temporary access for data cleanup"
                }
            }
        }

# ============================================================================
# DEPARTMENT MANAGEMENT MODELS (UNCHANGED)
# ============================================================================

class DepartmentCreate(BaseModel):
    """Model for creating new departments"""
    name: str = Field(..., min_length=2, max_length=50)
    description: Optional[str] = Field(None, max_length=200)
    is_active: bool = True

    @validator('name')
    def validate_name(cls, v):
        """Validate department name"""
        # Convert to lowercase with hyphens
        cleaned = v.strip().lower().replace(' ', '-').replace('_', '-')
        
        # Remove special characters except hyphens
        import re
        cleaned = re.sub(r'[^a-z0-9-]', '', cleaned)
        
        if len(cleaned) < 2:
            raise ValueError('Department name must be at least 2 characters')
        
        predefined_list = ["admin", "sales", "pre_sales", "hr", "documents"]
        if cleaned in predefined_list:
            raise ValueError('Cannot create department named "admin" - it is reserved')
        
        return cleaned

class DepartmentResponse(BaseModel):
    """Department response model"""
    id: str
    name: str
    display_name: str
    description: Optional[str]
    is_predefined: bool
    is_active: bool
    user_count: int
    created_at: datetime
    created_by: Optional[str] = None

class DepartmentUpdate(BaseModel):
    """Model for updating departments"""
    description: Optional[str] = Field(None, max_length=200)
    is_active: Optional[bool] = None

# ============================================================================
# DEPARTMENT HELPER (UNCHANGED)
# ============================================================================

class DepartmentHelper:
    """Helper class for department operations"""
    
    @staticmethod
    async def get_all_departments():
        """Get all available departments (only admin is predefined, rest are custom)"""
        from ..config.database import get_database
        
        # Only admin is predefined now
        predefined = [
            {
                "name": "admin",
                "display_name": "Admin",
                "is_predefined": True,
                "is_active": True,
                "description": "System administration and management"
            },
            {
                "name": "sales",
                "display_name": "Sales",
                "is_predefined": True,
                "is_active": True,
                "description": "Sales and business development"
            },
            {
                "name": "pre_sales",
                "display_name": "Pre Sales",
                "is_predefined": True,
                "is_active": True,
                "description": "Pre-sales and lead qualification"
            },
            {
                "name": "hr",
                "display_name": "HR",
                "is_predefined": True,
                "is_active": True,
                "description": "Human resources management"
            },
            {
                "name": "documents",
                "display_name": "Documents",
                "is_predefined": True,
                "is_active": True,
                "description": "Document management and processing"
            }
                    
        ]
        
        # Get all custom departments from database
        db = get_database()
        custom_departments = await db.departments.find(
            {"is_active": True}
        ).to_list(None)
        
        custom = [
            {
                "id": str(dept["_id"]),
                "name": dept["name"],
                "display_name": dept.get("display_name", dept["name"].replace('-', ' ').title()),
                "description": dept.get("description"),
                "is_predefined": False,
                "is_active": dept.get("is_active", True),
                "created_at": dept.get("created_at"),
                "created_by": dept.get("created_by")
            }
            for dept in custom_departments
        ]
        
        return predefined + custom
    
    @staticmethod
    async def is_department_valid(department_name: str) -> bool:
        """Check if department name is valid (admin or exists in database)"""
        # Admin is always valid
        predefined_list = ["admin", "sales", "pre_sales", "hr", "documents"]
        if department_name in predefined_list:
            return True
        
        # Check if custom department exists
        from ..config.database import get_database
        db = get_database()
        custom_dept = await db.departments.find_one({
            "name": department_name,
            "is_active": True
        })
        
        return custom_dept is not None
    
    @staticmethod
    async def get_department_users_count(department_name: str) -> int:
        """Get count of users in a department"""
        from ..config.database import get_database
        db = get_database()
        
        # Count users with this department
        count = await db.users.count_documents({
            "$or": [
                {"departments": department_name},  # String format (admin)
                {"departments": {"$in": [department_name]}}  # Array format (users)
            ],
            "is_active": True
        })
        
        return count
    
    @staticmethod
    def normalize_departments(departments: Union[str, List[str]], role_name: str) -> Union[str, List[str]]:
        """Normalize departments based on role
        
        NOTE: In RBAC, we check role_name instead of role enum
        """
        if isinstance(departments, str):
            departments_list = [departments]
        else:
            departments_list = departments or []
        
        # Admin role gets "admin" department
        if role_name and role_name.lower() in ["admin", "super_admin"]:
            return "admin"
        else:
            return list(set(departments_list)) if departments_list else []

# ============================================================================
# DEPARTMENT SETUP HELPER (UNCHANGED)
# ============================================================================

class DepartmentSetupHelper:
    """Helper for setting up initial departments"""
    
    @staticmethod
    async def create_starter_departments():
        """Create a basic set of starter departments for new installations"""
        from ..config.database import get_database
        
        db = get_database()
        
        # Check if any custom departments exist
        existing_count = await db.departments.count_documents({})
        
        if existing_count > 0:
            return  # Already have departments, don't create defaults
        
        # Create basic starter departments
        starter_departments = [
            {
                "name": "sales",
                "display_name": "Sales",
                "description": "Sales and business development",
                "is_active": True,
                "is_predefined": False,
                "created_at": datetime.utcnow(),
                "created_by": "system_setup"
            },
            {
                "name": "support",
                "display_name": "Support", 
                "description": "Customer support and assistance",
                "is_active": True,
                "is_predefined": False,
                "created_at": datetime.utcnow(),
                "created_by": "system_setup"
            },
            {
                "name": "operations",
                "display_name": "Operations",
                "description": "Business operations and processes", 
                "is_active": True,
                "is_predefined": False,
                "created_at": datetime.utcnow(),
                "created_by": "system_setup"
            }
        ]
        
        # Insert starter departments
        await db.departments.insert_many(starter_departments)
        
        return len(starter_departments)