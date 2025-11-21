# app/routers/auth.py
# Updated with Tata Tele Auto-Sync Integration - LOGGER FIXED

from fastapi import APIRouter, HTTPException, status, Request, Depends, Query # type: ignore
from datetime import datetime, timedelta
from typing import Dict, Any, List, Union
import logging
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase as Database

from app.decorators.timezone_decorator import convert_user_dates

# 🔧 FIX: Setup logging FIRST before using logger anywhere
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from ..config.database import get_database
from ..utils.security import security, verify_password, get_password_hash
from ..utils.dependencies import get_current_active_user, get_admin_user
from ..schemas.auth import (
    LoginRequest, LoginResponse, RegisterResponse,
    RefreshTokenRequest, RefreshTokenResponse,
    LogoutRequest, AuthResponse
)

# 🔥 FIXED: Import only the classes that exist in user models
from ..models.user import (
    UserCreate, UserResponse, UserUpdate, DepartmentHelper, 
    DepartmentCreate, DepartmentType
)
from ..config.settings import settings  # For token expiry settings

# 🆕 NEW: Import Tata services for auto-sync (NOW logger is available)
try:
    from ..services.tata_user_service import tata_user_service
    TATA_INTEGRATION_AVAILABLE = True
    logger.info("✅ Tata integration services imported successfully")
except ImportError as e:
    TATA_INTEGRATION_AVAILABLE = False
    logger.warning(f"⚠️ Tata integration not available: {e}")

router = APIRouter()

# =============================================================================
# EXISTING USER REGISTRATION - UNCHANGED
# =============================================================================

@router.post("/register", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def register_user(
    user_data: UserCreate,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    Register a new user with RBAC role assignment
    Admin only endpoint with TATA Call Routing integration
    
    🆕 RBAC CHANGES:
    - Assigns default "User" role if no role_id provided
    - Computes effective_permissions based on role
    - Initializes team hierarchy fields
    - Sets is_super_admin flag
    """
    try:
        db = get_database()
        rbac_service = RBACService()
        role_service = RoleService()
        
        logger.info(f"Admin {current_user.get('email')} registering new user: {user_data.email}")
        
        # Check if user already exists
        existing_user = await db.users.find_one({"email": user_data.email})
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists"
            )
        
        # Hash password
        hashed_password = get_password_hash(user_data.password)
        
        # 🆕 RBAC: Get or assign role
        role_id = getattr(user_data, 'role_id', None)
        
        if not role_id:
            # Get default "User" role
            default_role = await db.roles.find_one({"name": "user", "is_active": True})
            if not default_role:
                # Fallback: Create basic user role if it doesn't exist
                logger.warning("Default 'user' role not found - user will have no role assigned")
                role_id = None
                role_name = "user"  # Legacy role
                effective_permissions = []
                is_super_admin = False
            else:
                role_id = str(default_role["_id"])
                role_name = default_role["name"]
                effective_permissions = [p["permission_code"] for p in default_role.get("permissions", []) if p.get("granted", False)]
                is_super_admin = False
        else:
            # Validate provided role exists
            role = await db.roles.find_one({"_id": ObjectId(role_id), "is_active": True})
            if not role:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Role with ID {role_id} not found or inactive"
                )
            
            role_name = role["name"]
            effective_permissions = [p["permission_code"] for p in role.get("permissions", []) if p.get("granted", False)]
            is_super_admin = role.get("type") == "system" and role.get("name") == "super_admin"
        
        # Prepare user document with RBAC fields
        user_doc = {
            "email": user_data.email,
            "username": user_data.username,
            "first_name": user_data.first_name,
            "last_name": user_data.last_name,
            "full_name": f"{user_data.first_name} {user_data.last_name}",
            "hashed_password": hashed_password,
            
            # 🔄 LEGACY: Keep for backward compatibility during migration
            "role": user_data.role if hasattr(user_data, 'role') else "user",
            
            # 🆕 RBAC: New role fields
            "role_id": ObjectId(role_id) if role_id else None,
            "role_name": role_name,
            "is_super_admin": is_super_admin,
            
            # 🆕 RBAC: Permission fields
            "effective_permissions": effective_permissions,
            "permission_overrides": [],  # Individual permission overrides
            "permissions_last_computed": datetime.utcnow(),
            
            # 🆕 RBAC: Team hierarchy fields
            "reports_to": None,  # Manager's ObjectId
            "reports_to_email": None,  # Manager's email
            "team_members": [],  # List of subordinate emails
            "team_level": 0,  # Hierarchy level (0 = no manager)
            
            # Standard user fields
            "phone": user_data.phone,
            "department": user_data.departments,
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": current_user.get("email"),
            
            # Tata calling fields
            "calling_enabled": False,
            "tata_agent_id": None,
            "tata_extension": None,
            "tata_sync_status": "pending",
            "last_tata_sync": None,
            "auto_sync_enabled": True,
            "routing_method": None,
            "tata_agent_pool": [],
            "calling_status": "pending",
            "calling_setup_date": None
        }
        
        # Insert user
        result = await db.users.insert_one(user_doc)
        user_id = str(result.inserted_id)
        
        logger.info(f"✅ User created with ID: {user_id}, Role: {role_name}, Permissions: {len(effective_permissions)}")
        
        # Get the updated user data
        updated_user = await db.users.find_one({"_id": ObjectId(user_id)})
        
        # Prepare response
        user_response = {
            "id": user_id,
            "email": updated_user["email"],
            "username": updated_user["username"],
            "first_name": updated_user["first_name"],
            "last_name": updated_user["last_name"],
            "role": updated_user["role"],  # Legacy
            
            # 🆕 RBAC fields in response
            "role_id": str(updated_user["role_id"]) if updated_user.get("role_id") else None,
            "role_name": updated_user.get("role_name"),
            "is_super_admin": updated_user.get("is_super_admin", False),
            "permissions_count": len(updated_user.get("effective_permissions", [])),
            
            "phone": updated_user["phone"],
            "department": updated_user["department"],
            "is_active": updated_user["is_active"],
            "calling_enabled": updated_user.get("calling_enabled", False),
            "tata_sync_status": updated_user.get("tata_sync_status", "pending"),
            "calling_status": updated_user.get("calling_status"),
            "created_at": updated_user["created_at"].isoformat()
        }
        
        success_message = f"User registered successfully with role: {role_name}! 📞 Tata calling will be enabled on first login"
        
        response = {
            "success": True,
            "message": success_message,
            "user": user_response,
            "rbac_info": {
                "role_assigned": role_name,
                "permissions_granted": len(effective_permissions),
                "is_super_admin": is_super_admin
            },
            "note": "User will be auto-synced with Tata agents on first login"
        }
        
        logger.info(f"✅ User registration complete: {user_data.email}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration failed: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )

# =============================================================================
# 🆕 ENHANCED LOGIN WITH TATA AUTO-SYNC
# =============================================================================
@router.post("/login", response_model=LoginResponse)
async def login_user(request: Request, login_data: LoginRequest):
    """
    Enhanced user login endpoint with RBAC + Tata Tele auto-sync
    
    🆕 RBAC CHANGES:
    - Loads user's role and effective_permissions
    - Includes role_id, role_name, is_super_admin in JWT token
    - Returns effective_permissions in login response
    - Computes permissions if not cached or stale
    """
    db = get_database()
    rbac_service = RBACService()
    
    # Find user by email
    user = await db.users.find_one({"email": login_data.email})
    if not user:
        logger.warning(f"Login attempt with non-existent email: {login_data.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Check if account is locked
    if user.get("locked_until") and user["locked_until"] > datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is temporarily locked due to too many failed attempts"
        )
    
    # Verify password
    if not verify_password(login_data.password, user["hashed_password"]):
        # Increment failed login attempts
        failed_attempts = user.get("failed_login_attempts", 0) + 1
        update_data = {"failed_login_attempts": failed_attempts}
        
        # Lock account after 5 failed attempts
        if failed_attempts >= 5:
            update_data["locked_until"] = datetime.utcnow() + timedelta(minutes=30)
        
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": update_data}
        )
        
        logger.warning(f"Failed login attempt for {login_data.email}. Attempts: {failed_attempts}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Check if user is active
    if not user.get("is_active", False):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is disabled"
        )
    
    # 🆕 RBAC: Compute or refresh effective permissions
    effective_permissions = user.get("effective_permissions", [])
    permissions_last_computed = user.get("permissions_last_computed")
    
    # Recompute if permissions are stale (older than 24 hours) or missing
    should_recompute = (
        not effective_permissions or
        not permissions_last_computed or
        (datetime.utcnow() - permissions_last_computed).total_seconds() > 86400
    )
    
    if should_recompute:
        logger.info(f"Recomputing permissions for user {user['email']} during login")
        effective_permissions = await rbac_service.get_user_permissions(str(user["_id"]))
        
        # Update user with fresh permissions
        await db.users.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "effective_permissions": effective_permissions,
                    "permissions_last_computed": datetime.utcnow()
                }
            }
        )
    
    # 🆕 RBAC: Get role information
    role_id = user.get("role_id")
    role_name = user.get("role_name", "user")
    is_super_admin = user.get("is_super_admin", False)
    
    # If role_id exists but role_name is missing (legacy user), fetch from role
    if role_id and not role_name:
        role = await db.roles.find_one({"_id": ObjectId(role_id)})
        if role:
            role_name = role["name"]
            is_super_admin = role.get("type") == "system" and role.get("name") == "super_admin"
            
            # Update user with role info
            await db.users.update_one(
                {"_id": user["_id"]},
                {"$set": {"role_name": role_name, "is_super_admin": is_super_admin}}
            )
    
    # Update login tracking
    update_data = {
        "last_login": datetime.utcnow(),
        "last_activity": datetime.utcnow(),
        "failed_login_attempts": 0,
        "locked_until": None
    }

    # Store FCM token if provided
    if hasattr(login_data, 'fcm_token') and login_data.fcm_token:
        update_data["fcm_token"] = login_data.fcm_token
        update_data["fcm_token_updated_at"] = datetime.utcnow()
        logger.info(f"FCM token registered for user: {user['email']}")

    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": update_data,
            "$inc": {"login_count": 1}
        }
    )
    
    # Tata auto-sync (unchanged)
    calling_status = {
        "enabled": False,
        "sync_status": "not_attempted",
        "message": "Tata integration not available"
    }
    
    if TATA_INTEGRATION_AVAILABLE and user.get("auto_sync_enabled", True):
        try:
            logger.info(f"Starting Tata auto-sync for user: {user['email']}")
            calling_status = await tata_user_service.auto_sync_on_login(user)
            
            await db.users.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "calling_enabled": calling_status.get("enabled", False),
                        "tata_extension": calling_status.get("extension"),
                        "tata_agent_id": calling_status.get("agent_id"),
                        "tata_sync_status": calling_status.get("sync_status", "unknown"),
                        "last_tata_sync": datetime.utcnow()
                    }
                }
            )
            
            logger.info(f"Tata auto-sync completed for {user['email']}: {calling_status.get('sync_status')}")
            
        except Exception as e:
            logger.warning(f"Tata auto-sync failed for {user['email']}: {str(e)}")
            calling_status = {
                "enabled": False,
                "sync_status": "failed",
                "message": f"Auto-sync failed: {str(e)}"
            }
    
    # 🆕 RBAC: Create tokens with role and permission info
    token_data = {
        "sub": str(user["_id"]),
        "email": user["email"],
        "username": user["username"],
        
        # 🔄 LEGACY: Keep for backward compatibility
        "role": user.get("role", "user"),
        
        # 🆕 RBAC: New fields in JWT
        "role_id": str(role_id) if role_id else None,
        "role_name": role_name,
        "is_super_admin": is_super_admin,
        # Note: We don't include full permissions list in JWT (too large)
        # Instead, we fetch from database using get_current_active_user
    }
    
    access_token = security.create_access_token(token_data)

    if login_data.remember_me:
        refresh_token = security.create_refresh_token(token_data, expire_days=30)
    else:
        refresh_token = security.create_refresh_token(token_data, expire_days=7)
        
    # Store session info
    session_data = {
        "user_id": str(user["_id"]),
        "session_id": security.verify_token(access_token)["jti"],
        "created_at": datetime.utcnow(),
        "last_activity": datetime.utcnow(),
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }
    await db.user_sessions.insert_one(session_data)
    
    # 🆕 RBAC: Enhanced login response with permissions
    user_response = {
        "id": str(user["_id"]),
        "email": user["email"],
        "username": user["username"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "role": user.get("role", "user"),  # Legacy
        
        # 🆕 RBAC fields
        "role_id": str(role_id) if role_id else None,
        "role_name": role_name,
        "is_super_admin": is_super_admin,
        "effective_permissions": effective_permissions,  # Full permissions list
        "permissions_count": len(effective_permissions),
        
        # Team hierarchy
        "reports_to": user.get("reports_to_email"),
        "team_level": user.get("team_level", 0),
        
        # Calling fields
        "calling_enabled": calling_status.get("enabled", False),
        "tata_extension": calling_status.get("extension"),
        "tata_agent_id": calling_status.get("agent_id"),
        "sync_status": calling_status.get("sync_status", "unknown"),
        "ready_to_call": calling_status.get("enabled", False)
    }
    
    # Log successful login with RBAC info
    if calling_status.get("enabled"):
        logger.info(f"✅ Login: {user['email']} | Role: {role_name} | Permissions: {len(effective_permissions)} | Calling: Enabled (Ext: {calling_status.get('extension')})")
    else:
        logger.info(f"✅ Login: {user['email']} | Role: {role_name} | Permissions: {len(effective_permissions)} | Calling: {calling_status.get('sync_status')}")
    
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=security.access_token_expire_minutes * 60,
        user=user_response,
        calling_status=calling_status.get("sync_status", "unknown"),
        message=calling_status.get("message") if not calling_status.get("enabled") else None
    )


# =============================================================================
# EXISTING ENDPOINTS - UNCHANGED (keeping all your existing code)
# =============================================================================

@router.post("/logout", response_model=AuthResponse)
async def logout_user(
    logout_data: LogoutRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    User logout endpoint
    """
    db = get_database()
    
    try:
        # Remove user session
        await db.user_sessions.delete_many({"user_id": current_user["_id"]})
        
        logger.info(f"User logged out: {current_user['email']}")
        
        return AuthResponse(
            success=True,
            message="Successfully logged out"
        )
        
    except Exception as e:
        logger.error(f"Logout error for user {current_user['email']}: {e}")
        return AuthResponse(
            success=True,  # Return success even if session cleanup fails
            message="Logged out"
        )


@router.get("/me", response_model=UserResponse)
@convert_user_dates()
async def get_current_user_info(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get current user information with RBAC permissions and team hierarchy
    
    🆕 RBAC ADDITIONS:
    - Returns effective_permissions list
    - Returns role_id, role_name, is_super_admin
    - Returns team hierarchy (reports_to, team_level)
    - Returns permission overrides if any
    """
    try:
        # Handle departments (unchanged)
        departments = current_user.get("departments")
        old_department = current_user.get("department")
        
        if departments is not None:
            if isinstance(departments, str):
                department_list = [departments]
                departments_field = departments
            elif isinstance(departments, list):
                department_list = departments
                departments_field = departments
            else:
                department_list = []
                departments_field = [] if current_user.get("role") == "user" else "admin"
        elif old_department is not None:
            if current_user.get("role") == "admin":
                departments_field = "admin"
                department_list = ["admin"]
            else:
                if isinstance(old_department, str):
                    departments_field = [old_department.lower()]
                    department_list = [old_department.lower()]
                elif isinstance(old_department, list):
                    departments_field = [dept.lower() if isinstance(dept, str) else dept for dept in old_department]
                    department_list = [dept.lower() if isinstance(dept, str) else dept for dept in old_department]
                else:
                    departments_field = []
                    department_list = []
        else:
            if current_user.get("role") == "admin":
                departments_field = "admin"
                department_list = ["admin"]
            else:
                departments_field = []
                department_list = []
        
        # Calling status (unchanged)
        calling_enabled = current_user.get("calling_enabled", False)
        tata_extension = current_user.get("tata_extension")
        tata_agent_id = current_user.get("tata_agent_id")  
        sync_status = current_user.get("tata_sync_status", "unknown")
        calling_status = current_user.get("calling_status", "pending")
        
        ready_to_call = bool(
            calling_enabled and 
            sync_status in ["already_synced", "synced"] and
            tata_extension and 
            tata_agent_id
        )
        
        # 🆕 RBAC: Extract role and permission info
        role_id = current_user.get("role_id")
        role_name = current_user.get("role_name", current_user.get("role", "user"))
        is_super_admin = current_user.get("is_super_admin", False)
        effective_permissions = current_user.get("effective_permissions", [])
        permission_overrides = current_user.get("permission_overrides", [])
        
        # 🆕 RBAC: Team hierarchy info
        reports_to_email = current_user.get("reports_to_email")
        team_level = current_user.get("team_level", 0)
        team_members = current_user.get("team_members", [])
        
        return UserResponse(
            id=str(current_user["_id"]),
            email=current_user["email"],
            username=current_user["username"],
            first_name=current_user["first_name"],
            last_name=current_user["last_name"],
            role=current_user.get("role", "user"),  # Legacy
            is_active=current_user.get("is_active", True),
            phone=current_user.get("phone", ""),
            departments=departments_field,
            department_list=department_list,
            permissions=current_user.get("permissions", {}),  # Legacy lead permissions
            created_at=current_user.get("created_at"),
            last_login=current_user.get("last_login"),
            assigned_leads=current_user.get("assigned_leads", []),
            total_assigned_leads=current_user.get("total_assigned_leads", 0),
            
            # Calling fields
            extension_number=tata_extension,
            smartflo_agent_id=tata_agent_id,
            smartflo_user_id=current_user.get("tata_user_id"),
            calling_status=calling_status,
            calling_enabled=calling_enabled,
            tata_extension=tata_extension,
            tata_agent_id=tata_agent_id,
            sync_status=sync_status,
            ready_to_call=ready_to_call,
            
            # 🆕 RBAC: Add these fields to response
            role_id=str(role_id) if role_id else None,
            role_name=role_name,
            is_super_admin=is_super_admin,
            effective_permissions=effective_permissions,
            permission_overrides=permission_overrides,
            permissions_count=len(effective_permissions),
            
            # 🆕 RBAC: Team hierarchy
            reports_to=reports_to_email,
            team_level=team_level,
            team_members_count=len(team_members)
        )
        
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        logger.error(f"User data: {current_user}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user information"
        )

# =============================================================================
# EMERGENCY ADMIN AND DEBUG ENDPOINTS - UNCHANGED
# =============================================================================
@router.post("/emergency-admin", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_emergency_admin(user_data: UserCreate):
    """
    🚨 EMERGENCY ENDPOINT: Create super admin when database has no admins
    
    🆕 RBAC: Creates user with Super Admin role
    """
    try:
        db = get_database()
        
        # Security check: Only allow if NO admin users exist
        admin_count = await db.users.count_documents({"role": "admin"})
        if admin_count > 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Emergency endpoint disabled - Admin users already exist"
            )
        
        logger.warning("🚨 EMERGENCY ADMIN CREATION INITIATED")
        
        existing_user = await db.users.find_one({"email": user_data.email})
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists"
            )
        
        hashed_password = get_password_hash(user_data.password)
        
        # 🆕 RBAC: Try to assign Super Admin role
        super_admin_role = await db.roles.find_one({"name": "super_admin", "type": "system"})
        
        if super_admin_role:
            role_id = super_admin_role["_id"]
            role_name = "super_admin"
            is_super_admin = True
            effective_permissions = [p["permission_code"] for p in super_admin_role.get("permissions", []) if p.get("granted", False)]
        else:
            # Fallback if roles not seeded yet
            role_id = None
            role_name = "admin"
            is_super_admin = True
            effective_permissions = []
        
        user_doc = {
            "email": user_data.email,
            "username": user_data.username,
            "first_name": user_data.first_name,
            "last_name": user_data.last_name,
            "full_name": f"{user_data.first_name} {user_data.last_name}",
            "hashed_password": hashed_password,
            
            # Legacy
            "role": "admin",
            
            # 🆕 RBAC
            "role_id": role_id,
            "role_name": role_name,
            "is_super_admin": is_super_admin,
            "effective_permissions": effective_permissions,
            "permission_overrides": [],
            "permissions_last_computed": datetime.utcnow(),
            
            # Team hierarchy
            "reports_to": None,
            "reports_to_email": None,
            "team_members": [],
            "team_level": 0,
            
            "phone": user_data.phone,
            "department": user_data.department,
            "is_active": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": "emergency_system",
            "failed_login_attempts": 0,
            "login_count": 0,
            
            # Tata fields
            "calling_enabled": False,
            "tata_sync_status": "pending",
            "auto_sync_enabled": True
        }
        
        result = await db.users.insert_one(user_doc)
        user_id = str(result.inserted_id)
        
        logger.warning(f"🚨 EMERGENCY SUPER ADMIN CREATED: {user_data.email}")
        
        return {
            "success": True,
            "message": "🚨 EMERGENCY SUPER ADMIN CREATED! Remove this endpoint immediately!",
            "user": {
                "user_id": user_id,
                "email": user_data.email,
                "username": user_data.username,
                "first_name": user_data.first_name,
                "last_name": user_data.last_name,
                "role": "admin",
                "role_name": role_name,
                "is_super_admin": is_super_admin,
                "permissions_count": len(effective_permissions),
                "created_at": user_doc["created_at"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Emergency admin creation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Emergency admin creation failed: {str(e)}"
        )

        
@router.get("/debug-admin-users")
@convert_user_dates()
async def debug_admin_users():
    """
    🔍 TEMPORARY DIAGNOSTIC: Show existing admin users (emails only for security)
    ⚠️ REMOVE THIS ENDPOINT AFTER DEBUGGING!
    """
    try:
        db = get_database()
        
        # Find all admin users (but only return safe fields)
        admin_users = await db.users.find(
            {"role": "admin"}, 
            {
                "email": 1, 
                "username": 1, 
                "first_name": 1, 
                "last_name": 1, 
                "is_active": 1,
                "created_at": 1,
                "created_by": 1,
                "calling_enabled": 1,
                "tata_sync_status": 1
            }
        ).to_list(None)
        
        # Count total users by role
        admin_count = await db.users.count_documents({"role": "admin"})
        user_count = await db.users.count_documents({"role": "user"})
        total_count = await db.users.count_documents({})
        
        return {
            "database_status": "connected",
            "admin_users_found": admin_count,
            "regular_users_found": user_count,
            "total_users": total_count,
            "admin_users": [
                {
                    "email": user["email"],
                    "username": user.get("username", "N/A"),
                    "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                    "is_active": user.get("is_active", False),
                    "calling_enabled": user.get("calling_enabled", False),
                    "tata_sync_status": user.get("tata_sync_status", "unknown"),
                    "created_at": user.get("created_at"),
                    "created_by": user.get("created_by", "unknown")
                }
                for user in admin_users
            ],
            "next_steps": [
                "1. Try logging in with one of these admin emails",
                "2. If you forgot the password, you may need to reset it",
                "3. Remove this diagnostic endpoint after debugging"
            ]
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "database_status": "connection_failed"
        }

# =============================================================================
# ALL OTHER EXISTING ENDPOINTS REMAIN EXACTLY THE SAME...
# (Department management, user management, refresh token, etc.)
# I'm keeping the complete file structure but showing key sections
# =============================================================================

@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: Database = Depends(get_database)
):
    """
    Refresh access token using refresh token with token rotation
    """
    try:
        # Verify refresh token
        payload = security.verify_token(request.refresh_token)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
        # Check token type
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )
        
        # Check if token is blacklisted
        token_jti = payload.get("jti")
        if token_jti and await security.is_token_blacklisted(token_jti):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked"
            )
        
        # Get user from database
        user_id = payload.get("sub")
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        
        if not user or not user.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive"
            )
        
        # Create new tokens with same user data
        token_data = {
            "sub": str(user["_id"]),
            "email": user["email"],
            "username": user["username"],
            "role": user["role"]
        }

        new_access_token = security.create_access_token(token_data)
        new_refresh_token = security.create_refresh_token(token_data, expire_days=7)

        # Blacklist the old refresh token for security
        if token_jti:
            await security.blacklist_token(token_jti)

        # Update last activity
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {"last_activity": datetime.utcnow()}}
        )

        logger.info(f"Token refreshed for user: {user['email']} (with token rotation)")

        return RefreshTokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=security.access_token_expire_minutes * 60
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not refresh token"
        )

# =============================================================================
# 🆕 NEW: TATA SYNC MANAGEMENT ENDPOINTS
# =============================================================================

@router.post("/force-tata-sync", response_model=Dict[str, Any])
async def force_tata_sync(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Force Tata sync for current user (manual trigger)
    
    - **Manual Sync**: Trigger Tata agent sync outside of login
    - **Status Update**: Updates user's calling status immediately
    - **Error Handling**: Provides detailed sync failure information  
    """
    if not TATA_INTEGRATION_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tata integration service is not available"
        )
    
    try:
        db = get_database()
        user_id = str(current_user["_id"])
        
        logger.info(f"Manual Tata sync requested by user: {current_user['email']}")
        
        # Perform sync
        calling_status = await tata_user_service.auto_sync_on_login(current_user)
        
        # Update user record
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "calling_enabled": calling_status.get("enabled", False),
                    "tata_extension": calling_status.get("extension"),
                    "tata_agent_id": calling_status.get("agent_id"),
                    "tata_sync_status": calling_status.get("sync_status", "unknown"),
                    "last_tata_sync": datetime.utcnow()
                }
            }
        )
        
        return {
            "success": True,
            "message": "Tata sync completed",
            "sync_result": calling_status,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Manual Tata sync failed for {current_user['email']}: {str(e)}")
        return {
            "success": False,
            "message": f"Tata sync failed: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }

@router.get("/tata-sync-status", response_model=Dict[str, Any])
async def get_tata_sync_status(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get current user's Tata sync status and calling information
    
    - **Status Check**: Current sync status and calling capability
    - **Extension Info**: User's assigned Tata extension/DID  
    - **Sync History**: Last sync time and result
    """
    try:
        return {
            "success": True,
            "user_id": str(current_user["_id"]),
            "email": current_user["email"],
            "calling_enabled": current_user.get("calling_enabled", False),
            "tata_extension": current_user.get("tata_extension"),
            "tata_agent_id": current_user.get("tata_agent_id"), 
            "sync_status": current_user.get("tata_sync_status", "unknown"),
            "last_sync": current_user.get("last_tata_sync"),
            "auto_sync_enabled": current_user.get("auto_sync_enabled", True),
            "integration_available": TATA_INTEGRATION_AVAILABLE
        }
        
    except Exception as e:
        logger.error(f"Error getting Tata sync status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get sync status"
        )

# =============================================================================
# DEPARTMENT MANAGEMENT ENDPOINTS - COMPLETE IMPLEMENTATION
# =============================================================================

@router.get("/departments", response_model=Dict[str, Any])
async def get_all_departments(
    include_user_count: bool = Query(False, description="Include user count for each department"),
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get all available departments (only admin is predefined, rest are custom)
    Used for dropdowns in user creation and lead assignment
    """
    try:
        from ..models.user import DepartmentHelper
        
        logger.info(f"Getting departments for user: {current_user.get('email')}")
        
        # Get all departments (only admin predefined, rest custom)
        all_departments = await DepartmentHelper.get_all_departments()
        
        # Add user counts if requested
        if include_user_count:
            for dept in all_departments:
                dept["user_count"] = await DepartmentHelper.get_department_users_count(dept["name"])
        
        # Separate predefined (only admin) and custom
        predefined = [dept for dept in all_departments if dept.get("is_predefined", False)]
        custom = [dept for dept in all_departments if not dept.get("is_predefined", False)]
        
        return {
            "success": True,
            "departments": {
                "predefined": predefined,  # Only admin
                "custom": custom,          # All others
                "all": all_departments
            },
            "total_count": len(all_departments),
            "predefined_count": len(predefined),  # Should be 1 (admin)
            "custom_count": len(custom),
            "message": "Only 'admin' is predefined. All other departments are created by admins."
        }
        
    except Exception as e:
        logger.error(f"Error getting departments: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get departments"
        )

@router.post("/departments", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_department(
    department_data: DepartmentCreate,
    current_user: Dict[str, Any] = Depends(get_admin_user)  # Admin only
):
    """
    Create a new custom department (Admin only)
    All departments except 'admin' are created this way
    """
    try:
        from ..models.user import DepartmentHelper
        
        db = get_database()
        logger.info(f"Admin {current_user.get('email')} creating new department: {department_data.name}")
        
        # Check if department already exists (custom departments only, admin is always reserved)
        if department_data.name == "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create department named 'admin' - it is reserved for system administration"
            )
        
        # Check custom departments
        existing_custom = await db.departments.find_one({"name": department_data.name})
        if existing_custom:
            if existing_custom.get("is_active", True):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Department '{department_data.name}' already exists"
                )
            else:
                # Reactivate if it was deactivated
                await db.departments.update_one(
                    {"_id": existing_custom["_id"]},
                    {
                        "$set": {
                            "is_active": True,
                            "description": department_data.description,
                            "updated_at": datetime.utcnow(),
                            "reactivated_by": current_user.get("email")
                        }
                    }
                )
                return {
                    "success": True,
                    "message": f"Department '{department_data.name}' reactivated successfully",
                    "department_id": str(existing_custom["_id"]),
                    "action": "reactivated"
                }
        
        # Create new department
        department_doc = {
            "name": department_data.name,
            "display_name": department_data.name.replace('-', ' ').title(),
            "description": department_data.description,
            "is_active": department_data.is_active,
            "is_predefined": False,  # All created departments are custom
            "created_at": datetime.utcnow(),
            "created_by": current_user.get("email"),
            "updated_at": datetime.utcnow()
        }
        
        result = await db.departments.insert_one(department_doc)
        department_id = str(result.inserted_id)
        
        logger.info(f"✅ Custom department created: {department_data.name} by {current_user.get('email')}")
        
        return {
            "success": True,
            "message": f"Department '{department_data.name}' created successfully",
            "department": {
                "id": department_id,
                "name": department_data.name,
                "display_name": department_doc["display_name"],
                "description": department_data.description,
                "is_predefined": False,
                "is_active": True
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating department: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create department: {str(e)}"
        )

@router.post("/departments/bulk", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_departments_bulk(
    departments_list: List[DepartmentCreate],
    current_user: Dict[str, Any] = Depends(get_admin_user)  # Admin only
):
    """
    Create multiple departments at once (Admin only)
    Useful for initial setup or migrating from other systems
    """
    try:
        db = get_database()
        logger.info(f"Admin {current_user.get('email')} creating {len(departments_list)} departments in bulk")
        
        created_departments = []
        failed_departments = []
        
        for dept_data in departments_list:
            try:
                # Check if department already exists
                if dept_data.name == "admin":
                    failed_departments.append({
                        "name": dept_data.name,
                        "error": "Cannot create 'admin' department - it is reserved"
                    })
                    continue
                
                existing = await db.departments.find_one({"name": dept_data.name})
                if existing and existing.get("is_active", True):
                    failed_departments.append({
                        "name": dept_data.name,
                        "error": "Department already exists"
                    })
                    continue
                
                # Create department
                department_doc = {
                    "name": dept_data.name,
                    "display_name": dept_data.name.replace('-', ' ').title(),
                    "description": dept_data.description,
                    "is_active": dept_data.is_active,
                    "is_predefined": False,
                    "created_at": datetime.utcnow(),
                    "created_by": current_user.get("email"),
                    "updated_at": datetime.utcnow()
                }
                
                result = await db.departments.insert_one(department_doc)
                
                created_departments.append({
                    "id": str(result.inserted_id),
                    "name": dept_data.name,
                    "display_name": department_doc["display_name"],
                    "description": dept_data.description
                })
                
            except Exception as e:
                failed_departments.append({
                    "name": dept_data.name,
                    "error": str(e)
                })
        
        return {
            "success": True,
            "message": f"Bulk department creation completed",
            "created_count": len(created_departments),
            "failed_count": len(failed_departments),
            "created_departments": created_departments,
            "failed_departments": failed_departments
        }
        
    except Exception as e:
        logger.error(f"Error in bulk department creation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create departments in bulk: {str(e)}"
        )

@router.post("/departments/setup-starter", response_model=Dict[str, Any])
async def setup_starter_departments(
    current_user: Dict[str, Any] = Depends(get_admin_user)  # Admin only
):
    """
    Create a basic set of common departments for new installations
    Only works if no custom departments exist yet
    """
    try:
        db = get_database()
        logger.info(f"Admin {current_user.get('email')} setting up starter departments")
        
        # Check if any custom departments already exist
        existing_count = await db.departments.count_documents({})
        
        if existing_count > 0:
            existing_depts = await db.departments.find({}, {"name": 1}).to_list(None)
            dept_names = [dept["name"] for dept in existing_depts]
            
            return {
                "success": False,
                "message": "Starter departments not created - custom departments already exist",
                "existing_departments": dept_names,
                "suggestion": "Use the regular 'Create Department' endpoint to add more departments"
            }
        
        # Create starter departments
        starter_departments = [
            {
                "name": "sales",
                "display_name": "Sales",
                "description": "Sales and business development",
                "is_active": True,
                "is_predefined": False,
                "created_at": datetime.utcnow(),
                "created_by": current_user.get("email")
            },
            {
                "name": "marketing",
                "display_name": "Marketing", 
                "description": "Marketing and lead generation",
                "is_active": True,
                "is_predefined": False,
                "created_at": datetime.utcnow(),
                "created_by": current_user.get("email")
            },
            {
                "name": "support",
                "display_name": "Support",
                "description": "Customer support and assistance",
                "is_active": True,
                "is_predefined": False,
                "created_at": datetime.utcnow(),
                "created_by": current_user.get("email")
            },
            {
                "name": "operations",
                "display_name": "Operations",
                "description": "Business operations and processes",
                "is_active": True,
                "is_predefined": False,
                "created_at": datetime.utcnow(),
                "created_by": current_user.get("email")
            },
            {
                "name": "hr",
                "display_name": "HR",
                "description": "Human resources management",
                "is_active": True,
                "is_predefined": False,
                "created_at": datetime.utcnow(),
                "created_by": current_user.get("email")
            }
        ]
        
        # Insert starter departments
        result = await db.departments.insert_many(starter_departments)
        
        created_names = [dept["name"] for dept in starter_departments]
        
        logger.info(f"✅ Created {len(starter_departments)} starter departments: {created_names}")
        
        return {
            "success": True,
            "message": f"Created {len(starter_departments)} starter departments",
            "created_departments": created_names,
            "note": "You can now create users with these departments or add more departments as needed"
        }
        
    except Exception as e:
        logger.error(f"Error setting up starter departments: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to setup starter departments: {str(e)}"
        )

@router.put("/users/{user_id}/departments", response_model=Dict[str, Any])
async def update_user_departments(
    user_id: str,
    departments_data: Dict[str, Union[str, List[str]]],
    current_user: Dict[str, Any] = Depends(get_admin_user)  # Admin only
):
    """
    Update user departments (Admin only)
    Supports both single department (for admin) and multiple departments (for users)
    """
    try:
        from ..models.user import DepartmentHelper
        
        db = get_database()
        
        # Validate user exists
        target_user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        new_departments = departments_data.get("departments")
        if new_departments is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Departments field is required"
            )
        
        # Convert to list for validation
        if isinstance(new_departments, str):
            dept_list = [new_departments]
        else:
            dept_list = new_departments
        
        # Validate all departments exist
        invalid_departments = []
        for dept in dept_list:
            if not await DepartmentHelper.is_department_valid(dept):
                invalid_departments.append(dept)
        
        if invalid_departments:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid departments: {invalid_departments}. Use GET /departments to see available departments."
            )
        
        # Normalize departments based on user role
        user_role = target_user.get("role", "user")
        normalized_departments = DepartmentHelper.normalize_departments(
            new_departments, 
            user_role
        )
        
        # Update user
        update_result = await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "departments": normalized_departments,
                    "updated_at": datetime.utcnow(),
                    "departments_updated_by": current_user.get("email")
                }
            }
        )
        
        if update_result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No changes made to user departments"
            )
        
        logger.info(f"Admin {current_user.get('email')} updated departments for user {target_user.get('email')}: {normalized_departments}")
        
        return {
            "success": True,
            "message": f"Departments updated for user {target_user.get('email')}",
            "user": {
                "id": user_id,
                "email": target_user.get("email"),
                "name": f"{target_user.get('first_name', '')} {target_user.get('last_name', '')}".strip(),
                "role": user_role,
                "old_departments": target_user.get("departments", []),
                "new_departments": normalized_departments
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user departments: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user departments: {str(e)}"
        )

@router.get("/departments/{department_name}/users", response_model=Dict[str, Any])
@convert_user_dates()
async def get_department_users(
    department_name: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)  # Admin only
):
    """
    Get all users in a specific department (Admin only)
    """
    try:
        from ..models.user import DepartmentHelper
        
        db = get_database()
        
        # Validate department exists
        if not await DepartmentHelper.is_department_valid(department_name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department '{department_name}' not found"
            )
        
        # Get users in this department
        users_cursor = db.users.find(
            {
                "$or": [
                    {"departments": department_name},  # String format (admin)
                    {"departments": {"$in": [department_name]}}  # Array format (users)
                ],
                "is_active": True
            },
            {
                "hashed_password": 0  # Exclude password
            }
        )
        
        users = await users_cursor.to_list(None)
        
        # Process users for response
        department_users = []
        for user in users:
            departments = user.get("departments", [])
            department_users.append({
                "id": str(user["_id"]),
                "email": user["email"],
                "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                "role": user.get("role", "user"),
                "departments": departments,
                "assigned_leads_count": user.get("total_assigned_leads", 0),
                "calling_enabled": user.get("calling_enabled", False),
                "tata_sync_status": user.get("tata_sync_status", "pending"),
                "created_at": user.get("created_at"),
                "last_login": user.get("last_login")
            })
        
        return {
            "success": True,
            "department": department_name,
            "users": department_users,
            "total_users": len(department_users)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting department users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get department users"
        )

@router.delete("/departments/{department_id}", response_model=Dict[str, Any])
async def deactivate_department(
    department_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)  # Admin only
):
    """
    Deactivate a custom department (Admin only)
    Note: Cannot delete predefined departments, only custom ones
    """
    try:
        db = get_database()
        
        # Find the department
        department = await db.departments.find_one({"_id": ObjectId(department_id)})
        if not department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Department not found"
            )
        
        if department.get("is_predefined", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate predefined departments"
            )
        
        # Check if any users are using this department
        user_count = await db.users.count_documents({
            "$or": [
                {"departments": department["name"]},
                {"departments": {"$in": [department["name"]]}}
            ],
            "is_active": True
        })
        
        if user_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot deactivate department '{department['name']}'. {user_count} users are currently assigned to this department. Please reassign users first."
            )
        
        # Deactivate department
        await db.departments.update_one(
            {"_id": ObjectId(department_id)},
            {
                "$set": {
                    "is_active": False,
                    "deactivated_at": datetime.utcnow(),
                    "deactivated_by": current_user.get("email")
                }
            }
        )
        
        logger.info(f"Admin {current_user.get('email')} deactivated department: {department['name']}")
        
        return {
            "success": True,
            "message": f"Department '{department['name']}' deactivated successfully",
            "department_id": department_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating department: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate department"
        )

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)  # Admin only
):
    """
    Delete a user (Admin only)
    - Prevents self-deletion and deleting last admin
    - Reassigns user's leads to the admin performing deletion
    - Updates tasks to maintain data integrity
    - Soft deletes user (marks inactive)
    """
    try:
        db = get_database()
        
        # Find user by ID or email (flexible lookup)
        user_query = {"$or": [{"email": user_id}]}
        if ObjectId.is_valid(user_id):
            user_query["$or"].append({"_id": ObjectId(user_id)})
        
        user_to_delete = await db.users.find_one(user_query)
        
        if not user_to_delete:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user_email = user_to_delete["email"]
        user_name = f"{user_to_delete.get('first_name', '')} {user_to_delete.get('last_name', '')}".strip()
        current_admin_email = current_user.get("email")
        
        # Security checks
        if user_email == current_admin_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot delete your own account"
            )
        
        # Prevent deletion of last admin
        if user_to_delete.get("role") == "admin":
            admin_count = await db.users.count_documents({"role": "admin", "is_active": True})
            if admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot delete the last admin user. Create another admin first."
                )
        
        logger.info(f"Admin {current_admin_email} deleting user: {user_email}")
        
        # Step 1: Reassign leads to the deleting admin
        assigned_leads = await db.leads.count_documents({"assigned_to": user_email})
        if assigned_leads > 0:
            await db.leads.update_many(
                {"assigned_to": user_email},
                {
                    "$set": {
                        "assigned_to": None,  # Set to None for unassigned
                        "assigned_to_name": None,  # Clear the name as well
                        "reassignment_reason": f"User {user_email} was deleted - lead unassigned",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            logger.info(f"Reassigned {assigned_leads} leads to {current_admin_email}")
        
        # Step 2: Update tasks - preserve data but mark user as deleted
        tasks_assigned = await db.lead_tasks.count_documents({"assigned_to": user_email})
        if tasks_assigned > 0:
            await db.lead_tasks.update_many(
                {"assigned_to": user_email},
                {
                    "$set": {
                        "assigned_to": None,
                        "assigned_to_name": f"[Deleted User: {user_name}]",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
        
        tasks_created = await db.lead_tasks.count_documents({"created_by": str(user_to_delete["_id"])})
        if tasks_created > 0:
            await db.lead_tasks.update_many(
                {"created_by": str(user_to_delete["_id"])},
                {
                    "$set": {
                        "created_by_name": f"[Deleted User: {user_name}]",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
        
        # Step 3: Soft delete user (mark as inactive)
        deletion_result = await db.users.update_one(
            {"_id": user_to_delete["_id"]},
            {
                "$set": {
                    "is_active": False,
                    "deleted_at": datetime.utcnow(),
                    "deleted_by": current_admin_email,
                    "email_backup": user_email,
                    "email": f"[DELETED]_{user_email}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
                }
            }
        )
        
        if deletion_result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete user"
            )
        
        logger.info(f"✅ User {user_email} successfully deleted by {current_admin_email}")
        
        return {
            "success": True,
            "message": f"User {user_email} has been successfully deleted",
            "deleted_user": {
                "email": user_email,
                "name": user_name,
                "role": user_to_delete.get("role")
            },
            "summary": {
                "leads_reassigned": assigned_leads,
                "tasks_updated": tasks_assigned + tasks_created,
                "reassigned_to": current_admin_email
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete user: {str(e)}"
        )

@router.put("/users/{user_id}/departments", response_model=Dict[str, Any])
async def update_user_departments(
    user_id: str,
    departments_data: Dict[str, Union[str, List[str]]],
    current_user: Dict[str, Any] = Depends(get_admin_user)  # Admin only
):
    """
    Update user departments (Admin only)
    Supports both single department (for admin) and multiple departments (for users)
    """
    try:
        from ..models.user import DepartmentHelper
        
        db = get_database()
        
        # Validate user exists
        target_user = await db.users.find_one({"_id": ObjectId(user_id)})
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        new_departments = departments_data.get("departments")
        if new_departments is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Departments field is required"
            )
        
        # Convert to list for validation
        if isinstance(new_departments, str):
            dept_list = [new_departments]
        else:
            dept_list = new_departments
        
        # Validate all departments exist
        invalid_departments = []
        for dept in dept_list:
            if not await DepartmentHelper.is_department_valid(dept):
                invalid_departments.append(dept)
        
        if invalid_departments:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid departments: {invalid_departments}. Use GET /departments to see available departments."
            )
        
        # 🔥 Normalize departments based on user role
        user_role = target_user.get("role", "user")
        normalized_departments = DepartmentHelper.normalize_departments(
            new_departments, 
            user_role
        )
        
        # Update user
        update_result = await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "departments": normalized_departments,
                    "updated_at": datetime.utcnow(),
                    "departments_updated_by": current_user.get("email")
                }
            }
        )
        
        if update_result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No changes made to user departments"
            )
        
        logger.info(f"Admin {current_user.get('email')} updated departments for user {target_user.get('email')}: {normalized_departments}")
        
        return {
            "success": True,
            "message": f"Departments updated for user {target_user.get('email')}",
            "user": {
                "id": user_id,
                "email": target_user.get("email"),
                "name": f"{target_user.get('first_name', '')} {target_user.get('last_name', '')}".strip(),
                "role": user_role,
                "old_departments": target_user.get("departments", []),
                "new_departments": normalized_departments
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user departments: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user departments: {str(e)}"
        )

@router.get("/departments/{department_name}/users", response_model=Dict[str, Any])
async def get_department_users(
    department_name: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)  # Admin only
):
    """
    Get all users in a specific department (Admin only)
    """
    try:
        from ..models.user import DepartmentHelper
        
        db = get_database()
        
        # Validate department exists
        if not await DepartmentHelper.is_department_valid(department_name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Department '{department_name}' not found"
            )
        
        # Get users in this department
        users_cursor = db.users.find(
            {
                "$or": [
                    {"departments": department_name},  # String format (admin)
                    {"departments": {"$in": [department_name]}}  # Array format (users)
                ],
                "is_active": True
            },
            {
                "hashed_password": 0  # Exclude password
            }
        )
        
        users = await users_cursor.to_list(None)
        
        # Process users for response
        department_users = []
        for user in users:
            departments = user.get("departments", [])
            department_users.append({
                "id": str(user["_id"]),
                "email": user["email"],
                "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                "role": user.get("role", "user"),
                "departments": departments,
                "assigned_leads_count": user.get("total_assigned_leads", 0),
                "created_at": user.get("created_at"),
                "last_login": user.get("last_login")
            })
        
        return {
            "success": True,
            "department": department_name,
            "users": department_users,
            "total_users": len(department_users)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting department users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get department users"
        )

@router.delete("/departments/{department_id}", response_model=Dict[str, Any])
async def deactivate_department(
    department_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)  # Admin only
):
    """
    Deactivate a custom department (Admin only)
    Note: Cannot delete predefined departments, only custom ones
    """
    try:
        db = get_database()
        
        # Find the department
        department = await db.departments.find_one({"_id": ObjectId(department_id)})
        if not department:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Department not found"
            )
        
        if department.get("is_predefined", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate predefined departments"
            )
        
        # Check if any users are using this department
        user_count = await db.users.count_documents({
            "$or": [
                {"departments": department["name"]},
                {"departments": {"$in": [department["name"]]}}
            ],
            "is_active": True
        })
        
        if user_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot deactivate department '{department['name']}'. {user_count} users are currently assigned to this department. Please reassign users first."
            )
        
        # Deactivate department
        await db.departments.update_one(
            {"_id": ObjectId(department_id)},
            {
                "$set": {
                    "is_active": False,
                    "deactivated_at": datetime.utcnow(),
                    "deactivated_by": current_user.get("email")
                }
            }
        )
        
        logger.info(f"Admin {current_user.get('email')} deactivated department: {department['name']}")
        
        return {
            "success": True,
            "message": f"Department '{department['name']}' deactivated successfully",
            "department_id": department_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating department: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate department"
        )
    
# Add this endpoint to app/routers/auth.py

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_user: Dict[str, Any] = Depends(get_admin_user)  # Admin only
):
    """
    Delete a user (Admin only)
    - Prevents self-deletion and deleting last admin
    - Reassigns user's leads to the admin performing deletion
    - Updates tasks to maintain data integrity
    - Soft deletes user (marks inactive)
    """
    try:
        db = get_database()
        
        # Find user by ID or email (flexible lookup)
        user_query = {"$or": [{"email": user_id}]}
        if ObjectId.is_valid(user_id):
            user_query["$or"].append({"_id": ObjectId(user_id)})
        
        user_to_delete = await db.users.find_one(user_query)
        
        if not user_to_delete:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user_email = user_to_delete["email"]
        user_name = f"{user_to_delete.get('first_name', '')} {user_to_delete.get('last_name', '')}".strip()
        current_admin_email = current_user.get("email")
        
        # Security checks
        if user_email == current_admin_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot delete your own account"
            )
        
        # Prevent deletion of last admin
        if user_to_delete.get("role") == "admin":
            admin_count = await db.users.count_documents({"role": "admin", "is_active": True})
            if admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot delete the last admin user. Create another admin first."
                )
        
        logger.info(f"Admin {current_admin_email} deleting user: {user_email}")
        
        # Step 1: Reassign leads to the deleting admin
        assigned_leads = await db.leads.count_documents({"assigned_to": user_email})
        if assigned_leads > 0:
            await db.leads.update_many(
                {"assigned_to": user_email},
                {
                    "$set": {
                        "assigned_to": None,  # Set to None for unassigned
                        "assigned_to_name": None,  # Clear the name as well
                        "reassignment_reason": f"User {user_email} was deleted - lead unassigned",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            logger.info(f"Reassigned {assigned_leads} leads to {current_admin_email}")
        
        # Step 2: Update tasks - preserve data but mark user as deleted
        tasks_assigned = await db.lead_tasks.count_documents({"assigned_to": user_email})
        if tasks_assigned > 0:
            await db.lead_tasks.update_many(
                {"assigned_to": user_email},
                {
                    "$set": {
                        "assigned_to": None,
                        "assigned_to_name": f"[Deleted User: {user_name}]",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
        
        tasks_created = await db.lead_tasks.count_documents({"created_by": str(user_to_delete["_id"])})
        if tasks_created > 0:
            await db.lead_tasks.update_many(
                {"created_by": str(user_to_delete["_id"])},
                {
                    "$set": {
                        "created_by_name": f"[Deleted User: {user_name}]",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
        
        # Step 3: Soft delete user (mark as inactive)
        deletion_result = await db.users.update_one(
            {"_id": user_to_delete["_id"]},
            {
                "$set": {
                    "is_active": False,
                    "deleted_at": datetime.utcnow(),
                    "deleted_by": current_admin_email,
                    "email_backup": user_email,
                    "email": f"[DELETED]_{user_email}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
                }
            }
        )
        
        if deletion_result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete user"
            )
        
        logger.info(f"✅ User {user_email} successfully deleted by {current_admin_email}")
        
        return {
            "success": True,
            "message": f"User {user_email} has been successfully deleted",
            "deleted_user": {
                "email": user_email,
                "name": user_name,
                "role": user_to_delete.get("role")
            },
            "summary": {
                "leads_reassigned": assigned_leads,
                "tasks_updated": tasks_assigned + tasks_created,
                "reassigned_to": current_admin_email
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete user: {str(e)}"
        )


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: Database = Depends(get_database)
):
    """
    Refresh access token using refresh token with token rotation
    """
    try:
        # Verify refresh token
        payload = security.verify_token(request.refresh_token)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
        
        # Check token type
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )
        
        # Check if token is blacklisted
        token_jti = payload.get("jti")
        if token_jti and await security.is_token_blacklisted(token_jti):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked"
            )
        
        # Get user from database
        user_id = payload.get("sub")
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        
        if not user or not user.get("is_active", False):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive"
            )
        
        # Create new tokens with same user data
        token_data = {
            "sub": str(user["_id"]),
            "email": user["email"],
            "username": user["username"],
            "role": user["role"]
        }

        new_access_token = security.create_access_token(token_data)
        new_refresh_token = security.create_refresh_token(token_data, expire_days=7)

        # Blacklist the old refresh token for security
        if token_jti:
            await security.blacklist_token(token_jti)

        # Update last activity
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {"last_activity": datetime.utcnow()}}
        )

        logger.info(f"Token refreshed for user: {user['email']} (with token rotation)")

        return RefreshTokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=security.access_token_expire_minutes * 60
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not refresh token"
        )

# =============================================================================
# 🆕 NEW: TATA SYNC MANAGEMENT ENDPOINTS
# =============================================================================

@router.post("/force-tata-sync", response_model=Dict[str, Any])
async def force_tata_sync(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Force Tata sync for current user (manual trigger)
    
    - **Manual Sync**: Trigger Tata agent sync outside of login
    - **Status Update**: Updates user's calling status immediately
    - **Error Handling**: Provides detailed sync failure information  
    """
    if not TATA_INTEGRATION_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tata integration service is not available"
        )
    
    try:
        db = get_database()
        user_id = str(current_user["_id"])
        
        logger.info(f"Manual Tata sync requested by user: {current_user['email']}")
        
        # Perform sync
        calling_status = await tata_user_service.auto_sync_on_login(current_user)
        
        # Update user record
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "calling_enabled": calling_status.get("enabled", False),
                    "tata_extension": calling_status.get("extension"),
                    "tata_agent_id": calling_status.get("agent_id"),
                    "tata_sync_status": calling_status.get("sync_status", "unknown"),
                    "last_tata_sync": datetime.utcnow()
                }
            }
        )
        
        return {
            "success": True,
            "message": "Tata sync completed",
            "sync_result": calling_status,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Manual Tata sync failed for {current_user['email']}: {str(e)}")
        return {
            "success": False,
            "message": f"Tata sync failed: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }

@router.get("/tata-sync-status", response_model=Dict[str, Any])
async def get_tata_sync_status(
    current_user: Dict[str, Any] = Depends(get_current_active_user)
):
    """
    Get current user's Tata sync status and calling information
    
    - **Status Check**: Current sync status and calling capability
    - **Extension Info**: User's assigned Tata extension/DID  
    - **Sync History**: Last sync time and result
    """
    try:
        return {
            "success": True,
            "user_id": str(current_user["_id"]),
            "email": current_user["email"],
            "calling_enabled": current_user.get("calling_enabled", False),
            "tata_extension": current_user.get("tata_extension"),
            "tata_agent_id": current_user.get("tata_agent_id"), 
            "sync_status": current_user.get("tata_sync_status", "unknown"),
            "last_sync": current_user.get("last_tata_sync"),
            "auto_sync_enabled": current_user.get("auto_sync_enabled", True),
            "integration_available": TATA_INTEGRATION_AVAILABLE
        }
        
    except Exception as e:
        logger.error(f"Error getting Tata sync status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get sync status"
        )
