# app/utils/create_default_roles.py
# 🎭 RBAC Default Roles Creation Utility - UPDATED for 108 Permissions
# Creates 3 system roles: Super Admin, Admin, User with proper permission distribution

import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

logger = logging.getLogger(__name__)


# ============================================================================
# 🎯 ROLE DEFINITIONS - 3 DEFAULT SYSTEM ROLES (108 Permissions)
# ============================================================================

async def get_all_permission_codes(db) -> List[str]:
    """
    Get all 108 permission codes from database
    
    Returns list of permission codes like:
    ['lead.view', 'lead.add_single', 'contact.add', ...]
    """
    try:
        permissions = await db.permissions.find(
            {"is_system": True},
            {"code": 1}
        ).to_list(length=None)
        
        codes = [p["code"] for p in permissions]
        logger.info(f"📋 Retrieved {len(codes)} permission codes from database")
        return codes
        
    except Exception as e:
        logger.error(f"Error getting permission codes: {e}")
        return []


def get_super_admin_role_definition(all_permissions: List[str]) -> Dict[str, Any]:
    """
    🔴 SUPER ADMIN ROLE - ALL 108 PERMISSIONS
    
    Full system access with all permissions.
    - Can do EVERYTHING
    - Cannot be deleted
    - ✅ CAN be edited by super admins (permissions can be modified)
    - Only one super admin recommended
    
    **Permission Count:** 108/108 (100%)
    """
    return {
        "name": "super_admin",
        "display_name": "Super Admin",
        "description": "Full system access with all 108 permissions. Can manage roles, users, and all system data. Cannot be deleted but can be edited by super admins.",
        "type": "system",
        "is_active": True,
        "permissions": [
            {"permission_code": code, "granted": True, "scope": None}
            for code in all_permissions
        ],
        
        # Quick access flags
        "can_manage_users": True,
        "can_assign_leads": True,
        "can_view_all_data": True,
        "can_export_data": True,
        "max_team_size": None,  # Unlimited
        "users_count": 0,
        
        # System protection
        "is_deletable": False,
        "is_editable": True,  # ✅ CHANGED: Super admins can edit this role
        
        # Audit
        "created_at": datetime.utcnow(),
        "created_by": "system",
        "updated_at": datetime.utcnow(),
        "updated_by": None
    }


def get_admin_role_definition() -> Dict[str, Any]:
    """
    🟡 ADMIN ROLE - 85/108 PERMISSIONS (79%)
    
    Administrative access with user and data management.
    - Can manage users, leads, contacts, tasks, documents, notes
    - Can view all data and reports
    - Can manage teams
    - Can manage system configuration
    - CANNOT delete roles (only view/update)
    - CANNOT delete users
    - CANNOT view permission overrides
    
    **Permission Count:** 85/108 (79%)
    **Missing:** Some dangerous system operations
    """
    admin_permissions = [
        # ✅ DASHBOARD & REPORTING (6/6) - ALL
        "dashboard.view",
        "dashboard.view_team",
        "dashboard.view_all",
        "report.view",
        "report.view_team",
        "report.view_all",
        
        # ✅ LEAD MANAGEMENT (17/17) - ALL
        # My Leads (10)
        "lead.view",
        "lead.view_team",
        "lead.view_all",
        "lead.add_single",
        "lead.add_bulk",
        "lead.add_via_cv",
        "lead.update",
        "lead.update_all",
        "lead.export",
        "lead.assign",
        
        # Lead Groups (7)
        "lead_group.view",
        "lead_group.view_team",
        "lead_group.view_all",
        "lead_group.create",
        "lead_group.add",
        "lead_group.delete",
        "lead_group.update",
        
        # ✅ CONTACT MANAGEMENT (6/6) - ALL
        "contact.view",
        "contact.view_all",
        "contact.add",
        "contact.update_own",
        "contact.update_all",
        "contact.delete",
        
        # ✅ TASK MANAGEMENT (8/8) - ALL
        "task.view",
        "task.view_all",
        "task.add",
        "task.update_own",
        "task.update_team",
        "task.delete_own",
        "task.delete_team",
        "task.delete_all",
        
        # 🟡 USER MANAGEMENT (4/5) - MOST
        "user.create",
        "user.view",
        # ❌ "user.delete",        # Cannot delete users (super admin only)
        "user.update",
        "user.reset_password",
        
        # 🟡 ROLE & PERMISSION MANAGEMENT (4/5) - MOST
        "role.create",
        "role.read",
        "role.update",
        # ❌ "role.delete",        # Cannot delete roles (super admin only)
        "permission.view",
        
        # ✅ SYSTEM CONFIGURATION (24/24) - ALL
        # Department (4)
        "department.create",
        "department.edit",
        "department.view",
        "department.delete",
        
        # Lead Category (4)
        "lead_category.create",
        "lead_category.edit",
        "lead_category.view",
        "lead_category.delete",
        
        # Status (4)
        "status.create",
        "status.edit",
        "status.view",
        "status.delete",
        
        # Stages (4)
        "stage.create",
        "stage.edit",
        "stage.view",
        "stage.delete",
        
        # Course Level (4)
        "course_level.create",
        "course_level.edit",
        "course_level.view",
        "course_level.delete",
        
        # Lead Source (4)
        "source.create",
        "source.edit",
        "source.view",
        "source.delete",
        
        # ✅ COMMUNICATION (10/10) - ALL
        # Email (4)
        "email.send_single",
        "email.send_bulk",
        "email.view_single",
        "email.view_bulk",
        
        # WhatsApp (4)
        "whatsapp.send_single",
        "whatsapp.send_bulk",
        "whatsapp.view_single",
        "whatsapp.view_bulk",
        
        # Call (2)
        "call.make",
        "call.history",
        
        # ✅ TEAM MANAGEMENT (5/5) - ALL
        "team.view",
        "team.view_all",
        "team.create",
        "team.update",
        "team.delete",
        
        # ✅ CONTENT & ACTIVITY (10/10) - ALL
        # Notes (4)
        "note.view",
        "note.add",
        "note.delete",
        "note.update",
        
        # Timeline (1)
        "timeline.view",
        
        # Documents (5)
        "document.view",
        "document.view_all",
        "document.add",
        "document.delete",
        "document.update",
        
        # ✅ SPECIALIZED MODULES (12/12) - ALL
        # Attendance (4)
        "attendance.view",
        "attendance.add",
        "attendance.delete",
        "attendance.update",
        
        # Facebook Leads (2)
        "facebook_leads.view",
        "facebook_leads.convert",
        
        # Batch (5)
        "batch.create",
        "batch.view",
        "batch.add",
        "batch.delete",
        "batch.update",
        
        # Notification (1)
        "notification.view"
    ]
    
    return {
        "name": "admin",
        "display_name": "Admin",
        "description": "Administrative access with user and data management capabilities. Can manage users and view all data, but cannot delete users or roles. (85/108 permissions)",
        "type": "system",
        "is_active": True,
        "permissions": [
            {"permission_code": code, "granted": True, "scope": None}
            for code in admin_permissions
        ],
        
        # Quick access flags
        "can_manage_users": True,
        "can_assign_leads": True,
        "can_view_all_data": True,
        "can_export_data": True,
        "max_team_size": None,  # Unlimited
        "users_count": 0,
        
        # System protection
        "is_deletable": False,
        "is_editable": True,  # Can be edited but not deleted
        
        # Audit
        "created_at": datetime.utcnow(),
        "created_by": "system",
        "updated_at": datetime.utcnow(),
        "updated_by": None
    }


def get_user_role_definition() -> Dict[str, Any]:
    """
    🟢 USER ROLE - 28/108 PERMISSIONS (26%)
    
    Standard user with access to their own data.
    - Can manage own leads, contacts, tasks, notes, documents
    - Can view own dashboard and generate own reports
    - Can send communications
    - CANNOT manage other users
    - CANNOT assign leads
    - CANNOT view all data
    - CANNOT manage system settings
    - CANNOT manage teams
    
    **Permission Count:** 28/108 (26%)
    **Scope:** Primarily "own" scope permissions
    """
    user_permissions = [
        # ✅ DASHBOARD & REPORTING (2/6) - OWN ONLY
        "dashboard.view",
        "report.view",
        # ❌ No team/all views
        
        # ✅ LEAD MANAGEMENT (4/17) - OWN SCOPE ONLY
        # My Leads
        "lead.view",
        "lead.add_single",
        "lead.update",
        "lead.add_via_cv",
        # ❌ No view_team, view_all, add_bulk, update_all, export, assign
        # ❌ No lead groups
        
        # ✅ CONTACT MANAGEMENT (3/6) - OWN SCOPE ONLY
        "contact.view",
        "contact.add",
        "contact.update_own",
        # ❌ No view_all, update_all, delete
        
        # ✅ TASK MANAGEMENT (3/8) - OWN SCOPE ONLY
        "task.view",
        "task.add",
        "task.update_own",
        # ❌ No view_all, update_team, delete operations
        
        # ❌ USER MANAGEMENT (0/5) - NONE
        # Cannot manage any users
        
        # ❌ ROLE & PERMISSION MANAGEMENT (0/5) - NONE
        # Cannot manage roles or permissions
        
        # ❌ SYSTEM CONFIGURATION (0/24) - NONE
        # Cannot manage any system configuration
        
        # ✅ COMMUNICATION (6/10) - LIMITED
        # Email (2)
        "email.send_single",
        "email.view_single",
        # ❌ No bulk email
        
        # WhatsApp (2)
        "whatsapp.send_single",
        "whatsapp.view_single",
        # ❌ No bulk WhatsApp
        
        # Call (2)
        "call.make",
        "call.history",
        
        # ✅ TEAM MANAGEMENT (1/5) - VIEW ONLY
        "team.view",
        # ❌ Cannot manage teams
        
        # ✅ CONTENT & ACTIVITY (6/10) - OWN ONLY
        # Notes (4)
        "note.view",
        "note.add",
        "note.delete",
        "note.update",
        
        # Timeline (1)
        "timeline.view",
        
        # Documents (1)
        "document.view",
        # ❌ No document.add, delete, update, view_all
        
        # ✅ SPECIALIZED MODULES (3/12) - LIMITED
        # Attendance (2)
        "attendance.view",
        "attendance.add",
        # ❌ No delete, update
        
        # Batch (1)
        "batch.view",
        # ❌ No create, add, delete, update
        
        # Notification (1) - Changed from 0 to 1
        "notification.view",
        
        # ❌ No Facebook Leads
    ]
    
    return {
        "name": "user",
        "display_name": "User",
        "description": "Standard user with access to their own data and basic operations. Can manage own leads, contacts, tasks, and notes. (28/108 permissions)",
        "type": "system",
        "is_active": True,
        "permissions": [
            {"permission_code": code, "granted": True, "scope": None}
            for code in user_permissions
        ],
        
        # Quick access flags
        "can_manage_users": False,
        "can_assign_leads": False,
        "can_view_all_data": False,
        "can_export_data": False,
        "max_team_size": 0,
        "users_count": 0,
        
        # System protection
        "is_deletable": False,
        "is_editable": True,  # Can be edited but not deleted
        
        # Audit
        "created_at": datetime.utcnow(),
        "created_by": "system",
        "updated_at": datetime.utcnow(),
        "updated_by": None
    }


# ============================================================================
# 🔧 ROLE CREATION FUNCTIONS
# ============================================================================

async def create_default_roles(
    mongodb_url: str,
    database_name: str
) -> Dict[str, Any]:
    """
    Create the 3 default system roles
    
    **Roles Created:**
    1. Super Admin - 108/108 permissions (100%)
    2. Admin - 85/108 permissions (79%)
    3. User - 28/108 permissions (26%)
    
    Args:
        mongodb_url: MongoDB connection URL
        database_name: Database name
        
    Returns:
        dict: Creation result with role details
    """
    client = None
    try:
        logger.info("🎭 Creating default roles (v2 - 108 permissions)...")
        logger.info(f"📦 Database: {database_name}")
        
        # Connect to MongoDB
        client = AsyncIOMotorClient(mongodb_url)
        db = client[database_name]
        
        # Check if roles already exist
        existing_count = await db.roles.count_documents({"type": "system"})
        
        if existing_count >= 3:
            logger.info(f"ℹ️  Found {existing_count} system roles already exist")
            
            # Get existing roles for info
            existing_roles = await db.roles.find({"type": "system"}).to_list(length=None)
            role_info = [
                {
                    "name": r["name"],
                    "display_name": r["display_name"],
                    "id": str(r["_id"]),
                    "permissions_count": len(r.get("permissions", [])),
                    "users_count": r.get("users_count", 0)
                }
                for r in existing_roles
            ]
            
            return {
                "success": True,
                "message": "Default roles already exist",
                "roles_created": 0,
                "skipped": True,
                "existing_roles": role_info
            }
        
        # Get all permission codes from database
        all_permissions = await get_all_permission_codes(db)
        
        if not all_permissions:
            logger.warning("⚠️  No permissions found in database!")
            logger.warning("⚠️  Please run permission seeding first: python -m app.utils.seed_permissions")
            return {
                "success": False,
                "message": "No permissions found. Please run permission seeding first.",
                "error": "missing_permissions",
                "hint": "Run: python -m app.utils.seed_permissions"
            }
        
        logger.info(f"📋 Found {len(all_permissions)} permissions in database")
        
        if len(all_permissions) != 108:
            logger.warning(f"⚠️  Expected 108 permissions, found {len(all_permissions)}")
            logger.warning(f"⚠️  This may indicate incomplete permission seeding")
        
        # Define the 3 default roles
        roles_to_create = [
            get_super_admin_role_definition(all_permissions),  # 108/108 permissions
            get_admin_role_definition(),                       # 85/108 permissions
            get_user_role_definition()                         # 28/108 permissions
        ]
        
        created_roles = []
        
        for role_def in roles_to_create:
            # Check if role already exists by name
            existing = await db.roles.find_one({"name": role_def["name"]})
            
            if existing:
                logger.info(f"ℹ️  Role '{role_def['display_name']}' already exists, skipping")
                created_roles.append({
                    "name": role_def["name"],
                    "display_name": role_def["display_name"],
                    "id": str(existing["_id"]),
                    "permissions_count": len(role_def["permissions"]),
                    "existed": True
                })
                continue
            
            # Insert new role
            result = await db.roles.insert_one(role_def)
            role_id = str(result.inserted_id)
            
            created_roles.append({
                "name": role_def["name"],
                "display_name": role_def["display_name"],
                "id": role_id,
                "permissions_count": len(role_def["permissions"]),
                "description": role_def["description"],
                "existed": False
            })
            
            logger.info(f"✅ Created role: {role_def['display_name']} ({len(role_def['permissions'])} permissions)")
        
        # Create indexes for performance
        try:
            await db.roles.create_index("name", unique=True)
            await db.roles.create_index("type")
            await db.roles.create_index("is_active")
            logger.info("✅ Created role indexes")
        except Exception as e:
            logger.warning(f"Index creation warning (may already exist): {e}")
        
        # Calculate summary
        new_roles = [r for r in created_roles if not r.get("existed")]
        existing_roles = [r for r in created_roles if r.get("existed")]
        
        logger.info("=" * 60)
        logger.info("🎉 DEFAULT ROLES SETUP COMPLETE")
        logger.info("=" * 60)
        logger.info(f"✅ Created: {len(new_roles)} new roles")
        logger.info(f"ℹ️  Existing: {len(existing_roles)} roles")
        logger.info(f"📊 Total: {len(created_roles)} system roles")
        logger.info("=" * 60)
        
        for role in created_roles:
            status = "CREATED" if not role.get("existed") else "EXISTS"
            logger.info(f"  [{status}] {role['display_name']}: {role['permissions_count']} permissions")
        
        logger.info("=" * 60)
        
        return {
            "success": True,
            "message": f"Created {len(new_roles)} default roles",
            "roles_created": len(new_roles),
            "roles_existed": len(existing_roles),
            "roles": created_roles,
            "skipped": False,
            "summary": {
                "super_admin": "108/108 permissions (100%)",
                "admin": "85/108 permissions (79%)",
                "user": "28/108 permissions (26%)"
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error creating default roles: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"Failed to create default roles: {str(e)}",
            "error": str(e)
        }
    finally:
        if client:
            client.close()


# ============================================================================
# 👤 SUPER ADMIN USER CREATION
# ============================================================================

async def create_super_admin_user(
    mongodb_url: str,
    database_name: str,
    email: str,
    password: str,
    first_name: str,
    last_name: str
) -> Dict[str, Any]:
    """
    Create super admin user from .env configuration
    
    **What This Does:**
    1. Creates user with super_admin role
    2. Sets is_super_admin flag
    3. Computes all 108 permissions
    4. Updates role users_count
    
    Args:
        mongodb_url: MongoDB connection URL
        database_name: Database name
        email: Super admin email
        password: Super admin password (will be hashed)
        first_name: First name
        last_name: Last name
        
    Returns:
        dict: Creation result
    """
    client = None
    try:
        logger.info(f"👤 Creating super admin user: {email}")
        
        # Connect to MongoDB
        client = AsyncIOMotorClient(mongodb_url)
        db = client[database_name]
        
        # Check if user already exists
        existing_user = await db.users.find_one({"email": email})
        
        if existing_user:
            logger.info(f"ℹ️  User {email} already exists")
            
            # Ensure user has super_admin role
            super_admin_role = await db.roles.find_one({"name": "super_admin"})
            
            if super_admin_role:
                # Update user to have super admin role
                update_result = await db.users.update_one(
                    {"email": email},
                    {
                        "$set": {
                            "role_id": super_admin_role["_id"],
                            "role_name": "super_admin",
                            "is_super_admin": True,
                            "is_active": True,
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                
                if update_result.modified_count > 0:
                    logger.info(f"✅ Updated {email} with super admin privileges")
                else:
                    logger.info(f"ℹ️  User {email} already has super admin privileges")
            
            return {
                "success": True,
                "message": f"Super admin user {email} already exists",
                "user_id": str(existing_user["_id"]),
                "email": email,
                "created": False,
                "updated": update_result.modified_count > 0 if super_admin_role else False
            }
        
        # Get super admin role
        super_admin_role = await db.roles.find_one({"name": "super_admin"})
        
        if not super_admin_role:
            raise Exception("Super admin role not found. Please create default roles first.")
        
        logger.info(f"📋 Found super_admin role with {len(super_admin_role.get('permissions', []))} permissions")
        
        # Hash password
        try:
            from app.utils.security import get_password_hash
        except ImportError:
            # Fallback if import fails
            from passlib.context import CryptContext
            pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
            get_password_hash = pwd_context.hash
        
        hashed_password = get_password_hash(password)
        
        # Get all permission codes for effective_permissions
        all_permissions = await get_all_permission_codes(db)
        
        # Create super admin user document
        user_doc = {
            # Basic Info
            "email": email,
            "username": email.split("@")[0],
            "first_name": first_name,
            "last_name": last_name,
            "full_name": f"{first_name} {last_name}",
            "password": hashed_password,
            
            # Role Info (old + new)
            # "role": "admin",  # Keep old enum for backward compatibility
            "role_id": super_admin_role["_id"],
            "role_name": "super_admin",
            "is_super_admin": True,
            
            # Status
            "is_active": True,
            "departments": ["admin"],
            "phone": None,
            
            # Timestamps
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "last_login": None,
            
            # RBAC Fields
            "reports_to": None,
            "reports_to_email": None,
            "reports_to_name": None,
            "team_members": [],
            "team_level": 0,
            "permission_overrides": [],
            "effective_permissions": all_permissions,  # All 108 permissions
            "permissions_last_computed": datetime.utcnow(),
            
            # Lead Assignment
            "can_create_single_lead": True,
            "can_create_bulk_leads": True,
            "assigned_leads": [],
            "total_assigned_leads": 0,
            
            # Calling
            "calling_enabled": False,
            "calling": {
                "status": "disabled",
                "smartflo_user_id": None
            }
        }
        
        # Insert user
        result = await db.users.insert_one(user_doc)
        user_id = str(result.inserted_id)
        
        # Update role users_count
        await db.roles.update_one(
            {"_id": super_admin_role["_id"]},
            {"$inc": {"users_count": 1}}
        )
        
        logger.info("=" * 60)
        logger.info("🎉 SUPER ADMIN USER CREATED")
        logger.info("=" * 60)
        logger.info(f"📧 Email: {email}")
        logger.info(f"🆔 User ID: {user_id}")
        logger.info(f"🎭 Role: Super Admin")
        logger.info(f"🔑 Permissions: {len(all_permissions)}/108 (100%)")
        logger.info("=" * 60)
        
        return {
            "success": True,
            "message": f"Super admin user {email} created successfully",
            "user_id": user_id,
            "email": email,
            "role": "super_admin",
            "permissions_count": len(all_permissions),
            "created": True
        }
        
    except Exception as e:
        logger.error(f"❌ Error creating super admin user: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "message": f"Failed to create super admin user: {str(e)}",
            "error": str(e)
        }
    finally:
        if client:
            client.close()


# ============================================================================
# 🚀 CLI EXECUTION (Manual Setup)
# ============================================================================

async def main():
    """
    Main execution function for manual setup
    
    **Usage:**
    ```bash
    python -m app.utils.create_default_roles
    ```
    
    **Environment Variables Required:**
    - MONGODB_URL
    - DATABASE_NAME
    - SUPER_ADMIN_EMAIL (optional)
    - SUPER_ADMIN_PASSWORD (optional)
    - SUPER_ADMIN_FIRST_NAME (optional)
    - SUPER_ADMIN_LAST_NAME (optional)
    """
    import os
    from dotenv import load_dotenv
    
    # Load environment variables
    load_dotenv()
    
    logger.info("=" * 60)
    logger.info("🎭 LEADG CRM - DEFAULT ROLES SETUP (v2 - 108 Permissions)")
    logger.info("=" * 60)
    
    # Get database config
    mongodb_url = os.getenv("MONGODB_URL")
    database_name = os.getenv("DATABASE_NAME", "CRM_permission")
    
    if not mongodb_url:
        logger.error("❌ MONGODB_URL not found in environment variables")
        logger.error("Please set MONGODB_URL in your .env file")
        return
    
    logger.info(f"📦 Database: {database_name}")
    logger.info("")
    
    # Step 1: Create default roles
    logger.info("STEP 1: Creating Default Roles")
    logger.info("-" * 60)
    
    roles_result = await create_default_roles(mongodb_url, database_name)
    
    if not roles_result["success"]:
        logger.error(f"❌ Failed to create roles: {roles_result.get('message')}")
        return
    
    logger.info("")
    
    # Step 2: Create super admin user (if configured)
    logger.info("STEP 2: Creating Super Admin User")
    logger.info("-" * 60)
    
    super_admin_email = os.getenv("SUPER_ADMIN_EMAIL")
    super_admin_password = os.getenv("SUPER_ADMIN_PASSWORD")
    super_admin_first_name = os.getenv("SUPER_ADMIN_FIRST_NAME", "Super")
    super_admin_last_name = os.getenv("SUPER_ADMIN_LAST_NAME", "Admin")
    
    if super_admin_email and super_admin_password:
        logger.info(f"👤 Creating super admin: {super_admin_email}")
        
        user_result = await create_super_admin_user(
            mongodb_url,
            database_name,
            super_admin_email,
            super_admin_password,
            super_admin_first_name,
            super_admin_last_name
        )
        
        if user_result["success"]:
            logger.info("")
            logger.info("=" * 60)
            logger.info("✅ SETUP COMPLETED SUCCESSFULLY")
            logger.info("=" * 60)
            logger.info(f"🎭 Roles Created: {roles_result.get('roles_created', 0)}")
            logger.info(f"👤 Super Admin: {super_admin_email}")
            logger.info("=" * 60)
            logger.info("")
            logger.info("🔐 Next Steps:")
            logger.info("1. Update your .env file with super admin credentials")
            logger.info("2. Start your application: uvicorn app.main:app --reload")
            logger.info("3. Login with super admin credentials")
            logger.info("4. Create additional users and assign roles")
            logger.info("=" * 60)
        else:
            logger.error(f"❌ Failed to create super admin: {user_result.get('message')}")
    else:
        logger.warning("⚠️  Super admin credentials not found in .env")
        logger.warning("")
        logger.warning("To create a super admin user, add these to your .env:")
        logger.warning("  SUPER_ADMIN_EMAIL=admin@yourcompany.com")
        logger.warning("  SUPER_ADMIN_PASSWORD=YourSecurePassword123!")
        logger.warning("  SUPER_ADMIN_FIRST_NAME=Super")
        logger.warning("  SUPER_ADMIN_LAST_NAME=Admin")
        logger.warning("")
        logger.warning("Then run this script again.")


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Run async main
    asyncio.run(main())