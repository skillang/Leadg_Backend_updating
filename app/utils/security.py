# app/utils/security.py - UPDATED FOR RBAC SYSTEM
# Changes: Added RBAC user management methods

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import jwt
from passlib.context import CryptContext
from ..config.settings import settings
from ..config.database import get_database
import uuid
import logging
import secrets
import hashlib
from bson import ObjectId

logger = logging.getLogger(__name__)

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class SecurityManager:
    def __init__(self):
        self.secret_key = settings.secret_key
        self.algorithm = settings.algorithm
        self.access_token_expire_minutes = settings.access_token_expire_minutes
        self.refresh_token_expire_days = settings.refresh_token_expire_days

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        try:
            return pwd_context.verify(plain_password, hashed_password)
        except Exception as e:
            logger.error(f"Password verification error: {e}")
            return False

    def get_password_hash(self, password: str) -> str:
        """Hash a password"""
        return pwd_context.hash(password)

    def create_access_token(self, data: Dict[str, Any]) -> str:
        """Create JWT access token"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes)
        
        # Add standard JWT claims
        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": str(uuid.uuid4()),  # Unique token ID for blacklisting
            "type": "access"
        })
        
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def create_refresh_token(self, data: Dict[str, Any], expire_days: int = None) -> str:
        """Create JWT refresh token with optional custom expiry"""
        to_encode = data.copy()
        
        # Use custom expiry or default
        days = expire_days or self.refresh_token_expire_days
        expire = datetime.utcnow() + timedelta(days=days)
        
        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": str(uuid.uuid4()),
            "type": "refresh"
        })
        
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode JWT token"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except jwt.InvalidTokenError as e:
            logger.error(f"Token verification failed: {e}")
            return None

    async def is_token_blacklisted(self, token_jti: str) -> bool:
        """Check if token is blacklisted"""
        try:
            db = get_database()
            result = await db.token_blacklist.find_one({"token_jti": token_jti})
            return result is not None
        except Exception as e:
            logger.error(f"Error checking token blacklist: {e}")
            return True  # Fail safe - treat as blacklisted

    async def blacklist_token(self, token_jti: str, expires_at: datetime = None):
        """Add token to blacklist"""
        try:
            db = get_database()
            
            # If expires_at not provided, set a default (7 days from now)
            if expires_at is None:
                expires_at = datetime.utcnow() + timedelta(days=7)
            
            await db.token_blacklist.insert_one({
                "token_jti": token_jti,
                "expires_at": expires_at,
                "blacklisted_at": datetime.utcnow()
            })
            logger.info(f"Token {token_jti} blacklisted successfully")
        except Exception as e:
            logger.error(f"Failed to blacklist token: {e}")

    # ============================================================================
    # 🆕 RBAC USER MANAGEMENT METHODS
    # ============================================================================

    async def assign_role_to_user(
        self,
        user_email: str,
        role_id: str,
        admin_email: str
    ) -> Dict[str, Any]:
        """
        Assign a role to a user and recompute their permissions
        
        Args:
            user_email: Email of user to update
            role_id: ID of role to assign
            admin_email: Email of admin making the change
            
        Returns:
            Updated user dict with new role
        """
        try:
            db = get_database()
            
            # Get user
            user = await db.users.find_one({"email": user_email, "is_active": True})
            if not user:
                raise ValueError(f"User {user_email} not found or inactive")
            
            # Get role
            role = await db.roles.find_one({"_id": ObjectId(role_id)})
            if not role:
                raise ValueError(f"Role {role_id} not found")
            
            # Update user with new role
            result = await db.users.update_one(
                {"email": user_email},
                {
                    "$set": {
                        "role_id": role_id,
                        "role_name": role.get("name"),
                        "permissions_last_computed": None,  # Force recompute
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count == 0:
                raise ValueError("Failed to update user role")
            
            # Update role's user count
            await db.roles.update_one(
                {"_id": ObjectId(role_id)},
                {"$inc": {"users_count": 1}}
            )
            
            # Decrease old role's user count (if had one)
            old_role_id = user.get("role_id")
            if old_role_id:
                await db.roles.update_one(
                    {"_id": ObjectId(old_role_id)},
                    {"$inc": {"users_count": -1}}
                )
            
            # Get updated user
            updated_user = await db.users.find_one({"email": user_email})
            updated_user["_id"] = str(updated_user["_id"])
            
            logger.info(f"✅ Assigned role {role.get('name')} to {user_email} by {admin_email}")
            
            return updated_user
            
        except Exception as e:
            logger.error(f"Error assigning role to user: {e}")
            raise

    async def recompute_user_permissions(self, user_email: str) -> Dict[str, Any]:
        """
        Recompute effective permissions for a user
        
        This will be called by rbac_service.compute_effective_permissions()
        
        Args:
            user_email: User to recompute permissions for
            
        Returns:
            Updated user with recomputed permissions
        """
        try:
            # Import here to avoid circular import
            from ..services.rbac_service import rbac_service
            
            db = get_database()
            
            # Get user
            user = await db.users.find_one({"email": user_email})
            if not user:
                raise ValueError(f"User {user_email} not found")
            
            # Compute effective permissions using rbac_service
            effective_permissions = await rbac_service.compute_effective_permissions(
                user_id=str(user["_id"]),
                db=db
            )
            
            # Update user
            result = await db.users.update_one(
                {"email": user_email},
                {
                    "$set": {
                        "effective_permissions": effective_permissions,
                        "permissions_last_computed": datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count == 0:
                logger.warning(f"No changes made when recomputing permissions for {user_email}")
            
            # Get updated user
            updated_user = await db.users.find_one({"email": user_email})
            updated_user["_id"] = str(updated_user["_id"])
            
            logger.info(f"✅ Recomputed permissions for {user_email}: {len(effective_permissions)} permissions")
            
            return updated_user
            
        except Exception as e:
            logger.error(f"Error recomputing user permissions: {e}")
            raise

    async def set_user_manager(
        self,
        user_email: str,
        manager_email: str,
        admin_email: str
    ) -> Dict[str, Any]:
        """
        Set a manager for a user (team hierarchy)
        
        Args:
            user_email: User to assign manager to
            manager_email: Manager's email
            admin_email: Admin making the change
            
        Returns:
            Updated user with manager info
        """
        try:
            # Import here to avoid circular import
            from ..services.team_service import team_service
            
            db = get_database()
            
            # Use team_service to handle hierarchy logic
            result = await team_service.set_manager(
                user_email=user_email,
                manager_email=manager_email,
                db=db
            )
            
            logger.info(f"✅ Set manager {manager_email} for {user_email} by {admin_email}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error setting user manager: {e}")
            raise

    # ============================================================================
    # 🔄 UPDATED: Enhanced user fetching with RBAC fields
    # ============================================================================

    async def get_user_with_permissions(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user from database with RBAC fields included
        Ensures backward compatibility by adding default values if missing
        """
        try:
            db = get_database()
            user_data = await db.users.find_one({"_id": ObjectId(user_id)})
            
            if user_data is None:
                return None
            
            # ============================================================================
            # 🆕 RBAC: Ensure new RBAC fields exist
            # ============================================================================
            
            # Role fields
            if "role_id" not in user_data:
                user_data["role_id"] = None
            if "role_name" not in user_data:
                user_data["role_name"] = None
            if "is_super_admin" not in user_data:
                user_data["is_super_admin"] = False
            
            # Team hierarchy fields
            if "reports_to" not in user_data:
                user_data["reports_to"] = None
            if "reports_to_name" not in user_data:
                user_data["reports_to_name"] = None
            if "team_members" not in user_data:
                user_data["team_members"] = []
            if "team_level" not in user_data:
                user_data["team_level"] = 0
            
            # Permission fields
            if "permission_overrides" not in user_data:
                user_data["permission_overrides"] = []
            if "effective_permissions" not in user_data:
                user_data["effective_permissions"] = []
            if "permissions_last_computed" not in user_data:
                user_data["permissions_last_computed"] = None
            
            # ============================================================================
            # 🔄 OLD: Ensure old permissions field exists for backward compatibility
            # ============================================================================
            
            if "permissions" not in user_data:
                # Add default old permissions
                default_permissions = {
                    "can_create_single_lead": False,
                    "can_create_bulk_leads": False,
                    "granted_by": None,
                    "granted_at": None,
                    "last_modified_by": None,
                    "last_modified_at": None
                }
                
                # Update user in database with default permissions
                update_doc = {
                    "permissions": default_permissions,
                    # Also add RBAC fields if missing
                    "role_id": user_data.get("role_id"),
                    "role_name": user_data.get("role_name"),
                    "is_super_admin": user_data.get("is_super_admin", False),
                    "reports_to": user_data.get("reports_to"),
                    "reports_to_name": user_data.get("reports_to_name"),
                    "team_members": user_data.get("team_members", []),
                    "team_level": user_data.get("team_level", 0),
                    "permission_overrides": user_data.get("permission_overrides", []),
                    "effective_permissions": user_data.get("effective_permissions", []),
                    "permissions_last_computed": user_data.get("permissions_last_computed")
                }
                
                await db.users.update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": update_doc}
                )
                
                # Add to current user data
                user_data["permissions"] = default_permissions
                
                logger.info(f"Added default RBAC fields for user {user_data.get('email')}")
            
            # Convert ObjectId to string for JSON serialization
            user_data["_id"] = str(user_data["_id"])
            
            # Convert team_members ObjectIds to strings
            if user_data.get("team_members"):
                user_data["team_members"] = [str(tm) if isinstance(tm, ObjectId) else tm for tm in user_data["team_members"]]
            
            # Convert reports_to ObjectId to string
            if user_data.get("reports_to") and isinstance(user_data["reports_to"], ObjectId):
                user_data["reports_to"] = str(user_data["reports_to"])
            
            return user_data
            
        except Exception as e:
            logger.error(f"Error fetching user with permissions: {e}")
            return None

    # ============================================================================
    # 🔄 OLD METHODS - Kept for backward compatibility
    # ============================================================================

    async def update_user_permissions(
        self, 
        user_email: str, 
        permissions: Dict[str, Any], 
        admin_email: str
    ) -> bool:
        """
        DEPRECATED: Update old 2-permission system
        
        This is kept for backward compatibility but should use permission overrides instead
        """
        try:
            db = get_database()
            
            update_data = {
                "permissions.can_create_single_lead": permissions.get("can_create_single_lead", False),
                "permissions.can_create_bulk_leads": permissions.get("can_create_bulk_leads", False),
                "permissions.last_modified_by": admin_email,
                "permissions.last_modified_at": datetime.utcnow()
            }
            
            # Set granted_by and granted_at only if granting new permissions
            if permissions.get("can_create_single_lead") or permissions.get("can_create_bulk_leads"):
                # Check if user already has granted_by set
                user = await db.users.find_one({"email": user_email})
                if user and not user.get("permissions", {}).get("granted_by"):
                    update_data["permissions.granted_by"] = admin_email
                    update_data["permissions.granted_at"] = datetime.utcnow()
            
            result = await db.users.update_one(
                {"email": user_email},
                {"$set": update_data}
            )
            
            success = result.modified_count > 0
            if success:
                logger.info(f"[DEPRECATED] Updated old permissions for {user_email} by {admin_email}")
            else:
                logger.warning(f"No user found or no changes made for {user_email}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error updating user permissions: {e}")
            return False

    async def get_all_users_with_permissions(self) -> list:
        """
        Get all active users with their permissions (old + new RBAC)
        """
        try:
            db = get_database()
            
            cursor = db.users.find(
                {"is_active": True},
                {
                    "email": 1,
                    "first_name": 1,
                    "last_name": 1,
                    "role": 1,  # Old field
                    "role_id": 1,  # New RBAC
                    "role_name": 1,  # New RBAC
                    "is_super_admin": 1,  # New RBAC
                    "permissions": 1,  # Old system
                    "permission_overrides": 1,  # New RBAC
                    "effective_permissions": 1,  # New RBAC
                    "team_level": 1,  # New RBAC
                    "created_at": 1,
                    "last_login": 1
                }
            )
            
            users = await cursor.to_list(None)
            
            # Ensure all users have both old and new permission fields
            for user in users:
                # Old permissions
                if "permissions" not in user:
                    user["permissions"] = {
                        "can_create_single_lead": False,
                        "can_create_bulk_leads": False,
                        "granted_by": None,
                        "granted_at": None,
                        "last_modified_by": None,
                        "last_modified_at": None
                    }
                
                # New RBAC fields
                if "role_id" not in user:
                    user["role_id"] = None
                if "role_name" not in user:
                    user["role_name"] = None
                if "is_super_admin" not in user:
                    user["is_super_admin"] = False
                if "permission_overrides" not in user:
                    user["permission_overrides"] = []
                if "effective_permissions" not in user:
                    user["effective_permissions"] = []
                if "team_level" not in user:
                    user["team_level"] = 0
                
                # Convert ObjectId to string
                user["_id"] = str(user["_id"])
            
            return users
            
        except Exception as e:
            logger.error(f"Error fetching users with permissions: {e}")
            return []

    # ============================================================================
    # PASSWORD RESET METHODS (UNCHANGED)
    # ============================================================================

    def generate_reset_token(self) -> str:
        """Generate secure password reset token"""
        return secrets.token_urlsafe(32)
    
    def hash_reset_token(self, token: str) -> str:
        """Hash reset token for secure storage"""
        return hashlib.sha256(token.encode()).hexdigest()
    
    def create_password_reset_token(self, data: Dict[str, Any], expire_minutes: int = 30) -> str:
        """Create JWT-based password reset token"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(minutes=expire_minutes)
        
        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": str(uuid.uuid4()),
            "type": "password_reset"
        })
        
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
    
    def verify_reset_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify password reset token"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            # Check if it's a password reset token
            if payload.get("type") != "password_reset":
                return None
                
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Password reset token has expired")
            return None
        except jwt.JWTError as e:
            logger.warning(f"Password reset token validation failed: {e}")
            return None

# ============================================================================
# GLOBAL INSTANCE & UTILITY FUNCTIONS
# ============================================================================

# Global security manager instance
security = SecurityManager()

# ============================================================================
# TOKEN & PASSWORD UTILITIES (UNCHANGED)
# ============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return security.verify_password(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return security.get_password_hash(password)

def create_access_token(data: Dict[str, Any]) -> str:
    return security.create_access_token(data)

def create_refresh_token(data: Dict[str, Any]) -> str:
    return security.create_refresh_token(data)

def generate_reset_token() -> str:
    return security.generate_reset_token()

def hash_reset_token(token: str) -> str:
    return security.hash_reset_token(token)

def create_password_reset_token(data: Dict[str, Any], expire_minutes: int = 30) -> str:
    return security.create_password_reset_token(data, expire_minutes)

def verify_reset_token(token: str) -> Optional[Dict[str, Any]]:
    return security.verify_reset_token(token)

# ============================================================================
# 🆕 RBAC USER MANAGEMENT UTILITIES
# ============================================================================

async def assign_role_to_user(user_email: str, role_id: str, admin_email: str) -> Dict[str, Any]:
    """Assign a role to a user"""
    return await security.assign_role_to_user(user_email, role_id, admin_email)

async def recompute_user_permissions(user_email: str) -> Dict[str, Any]:
    """Recompute effective permissions for a user"""
    return await security.recompute_user_permissions(user_email)

async def set_user_manager(user_email: str, manager_email: str, admin_email: str) -> Dict[str, Any]:
    """Set a manager for a user"""
    return await security.set_user_manager(user_email, manager_email, admin_email)

# ============================================================================
# 🔄 OLD PERMISSION UTILITIES (DEPRECATED but kept for compatibility)
# ============================================================================

async def get_user_with_permissions(user_id: str) -> Optional[Dict[str, Any]]:
    """Get user with permissions included (old + new RBAC)"""
    return await security.get_user_with_permissions(user_id)

async def update_user_permissions(user_email: str, permissions: Dict[str, Any], admin_email: str) -> bool:
    """DEPRECATED: Update old 2-permission system"""
    return await security.update_user_permissions(user_email, permissions, admin_email)

async def get_all_users_with_permissions() -> list:
    """Get all users with permissions for admin interface"""
    return await security.get_all_users_with_permissions()

# ============================================================================
# 🆕 RBAC PERMISSION CHECKING UTILITIES
# ============================================================================

def check_user_has_permission(user_data: Dict[str, Any], permission_code: str) -> bool:
    """
    Check if user has specific permission (NEW RBAC system)
    
    Args:
        user_data: User data from database
        permission_code: Permission code to check (e.g., 'lead.create')
    
    Returns:
        bool: True if user has permission
    """
    # Super admins have all permissions
    if user_data.get("is_super_admin", False):
        return True
    
    # Check effective permissions
    effective_permissions = user_data.get("effective_permissions", [])
    return permission_code in effective_permissions

def check_user_has_old_permission(user_data: Dict[str, Any], permission_name: str) -> bool:
    """
    DEPRECATED: Check if user has old 2-permission system permission
    
    Args:
        user_data: User data from database
        permission_name: Permission to check (e.g., 'can_create_single_lead')
    
    Returns:
        bool: True if user has permission
    """
    # Super admins have all permissions
    if user_data.get("is_super_admin", False):
        return True
    
    # Check old permissions
    permissions = user_data.get("permissions", {})
    return permissions.get(permission_name, False)

def get_user_permission_summary(user_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get summary of user's permissions for UI display (old + new system)
    
    Args:
        user_data: User data from database
        
    Returns:
        dict: Permission summary
    """
    # New RBAC system
    is_super_admin = user_data.get("is_super_admin", False)
    role_name = user_data.get("role_name")
    effective_permissions = user_data.get("effective_permissions", [])
    permission_overrides = user_data.get("permission_overrides", [])
    
    # Old system
    old_permissions = user_data.get("permissions", {})
    
    if is_super_admin:
        return {
            "is_super_admin": True,
            "role_name": "Super Admin",
            "permission_count": "All (69)",
            "has_overrides": len(permission_overrides) > 0,
            "can_create_single_lead": True,  # Old system compatibility
            "can_create_bulk_leads": True,  # Old system compatibility
            "can_manage_permissions": True,
            "permission_source": "super_admin"
        }
    
    return {
        "is_super_admin": False,
        "role_name": role_name or "Unknown",
        "permission_count": len(effective_permissions),
        "has_overrides": len(permission_overrides) > 0,
        
        # Old system permissions (for backward compatibility)
        "can_create_single_lead": old_permissions.get("can_create_single_lead", False),
        "can_create_bulk_leads": old_permissions.get("can_create_bulk_leads", False),
        
        # New RBAC info
        "effective_permissions": effective_permissions,
        "permission_source": "role_based" if role_name else "none",
        "granted_by": old_permissions.get("granted_by"),
        "granted_at": old_permissions.get("granted_at")
    }