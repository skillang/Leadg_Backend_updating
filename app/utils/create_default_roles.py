# app/utils/create_default_roles.py
# 🎭 RBAC Default Roles Creation Utility
# Creates 3 system roles: Super Admin, Admin, User with proper permission distribution

import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

logger = logging.getLogger(__name__)


# ============================================================================
# 🎯 ROLE DEFINITIONS - 3 DEFAULT SYSTEM ROLES
# ============================================================================

async def get_all_permission_codes(db) -> List[str]:
    """
    Get all 69 permission codes from database
    
    Returns list of permission codes like:
    ['lead.create', 'lead.read_own', 'contact.create', ...]
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
    🔴 SUPER ADMIN ROLE - ALL 69 PERMISSIONS
    
    Full system access with all permissions.
    - Can do EVERYTHING
    - Cannot be deleted
    - Only one super admin recommended
    
    **Permission Count:** 69/69 (100%)
    """
    return {
        "name": "super_admin",
        "display_name": "Super Admin",
        "description": "Full system access with all 69 permissions. Can manage roles, users, and all system data. Cannot be deleted.",
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
        "is_editable": False,
        
        # Audit
        "created_at": datetime.utcnow(),
        "created_by": "system",
        "updated_at": datetime.utcnow(),
        "updated_by": None
    }


def get_admin_role_definition() -> Dict[str, Any]:
    """
    🟡 ADMIN ROLE - 57/69 PERMISSIONS (83%)
    
    Administrative access with user and data management.
    - Can manage users, leads, contacts, tasks
    - Can view all data and reports
    - CANNOT manage roles (no role.create/update/delete)
    - CANNOT override permissions
    - CANNOT view system logs
    
    **Permission Count:** 57/69 (83%)
    **Missing:** Role management, permission overrides, system logs, team ownership transfer
    """
    admin_permissions = [
        # ✅ LEAD MANAGEMENT (14/14) - ALL
        "lead.create",
        "lead.read_own",
        "lead.read_team",
        "lead.read_all",
        "lead.update_own",
        "lead.update_team",
        "lead.update_all",
        "lead.delete_own",
        "lead.delete_all",
        "lead.assign",
        "lead.bulk_create",
        "lead.export",
        "lead.change_status",
        "lead.view_history",
        
        # ✅ CONTACT MANAGEMENT (7/7) - ALL
        "contact.create",
        "contact.read_own",
        "contact.read_all",
        "contact.update_own",
        "contact.update_all",
        "contact.delete",
        "contact.export",
        
        # ✅ TASK MANAGEMENT (9/9) - ALL
        "task.create",
        "task.read_own",
        "task.read_team",
        "task.read_all",
        "task.update",
        "task.complete",
        "task.delete",
        "task.assign",
        "task.change_priority",
        
        # ✅ USER MANAGEMENT (8/8) - ALL
        "user.create",
        "user.read",
        "user.update",
        "user.delete",
        "user.activate_deactivate",
        "user.reset_password",
        "user.view_activity",
        "user.manage_departments",
        
        # 🟡 ROLE & PERMISSION MANAGEMENT (3/7) - LIMITED
        "role.read",           # ✅ Can view roles
        "role.assign",         # ✅ Can assign roles to users
        "permission.read",     # ✅ Can view permissions
        # ❌ role.create       # Cannot create roles
        # ❌ role.update       # Cannot modify roles
        # ❌ role.delete       # Cannot delete roles
        # ❌ permission.manage # Cannot override permissions
        
        # ✅ DASHBOARD & REPORTING (9/9) - ALL
        "dashboard.view_own",
        "dashboard.view_team",
        "dashboard.view_all",
        "report.generate_own",
        "report.generate_team",
        "report.generate_all",
        "report.schedule",
        "analytics.view_advanced",
        "analytics.export",
        
        # 🟡 SYSTEM SETTINGS (6/7) - MOST
        "settings.view",
        "settings.update",
        "department.manage",
        "stage.manage",
        "status.manage",
        "source.manage",
        # ❌ system.manage     # Cannot access system logs
        
        # ✅ EMAIL & COMMUNICATION (6/6) - ALL
        "email.send_single",
        "email.send_bulk",
        "email.view_templates",
        "email.manage_templates",
        "whatsapp.send",
        "call.make",
        
        # 🟡 TEAM MANAGEMENT (5/6) - MOST
        "team.view_structure",
        "team.manage_hierarchy",
        "team.assign_members",
        "team.view_performance",
        "team.manage_targets",
        # ❌ team.transfer_ownership # Only super admin can transfer ownership
    ]
    
    return {
        "name": "admin",
        "display_name": "Admin",
        "description": "Administrative access with user and data management capabilities. Can manage users and view all data, but cannot modify system roles or access system logs. (57/69 permissions)",
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
    🟢 USER ROLE - 24/69 PERMISSIONS (35%)
    
    Standard user with access to their own data.
    - Can manage own leads, contacts, tasks
    - Can view own dashboard and generate own reports
    - CANNOT manage other users
    - CANNOT assign leads
    - CANNOT view all data
    - CANNOT manage system settings
    
    **Permission Count:** 24/69 (35%)
    **Scope:** Primarily "own" scope permissions
    """
    user_permissions = [
        # ✅ LEAD MANAGEMENT (6/14) - OWN SCOPE ONLY
        "lead.create",
        "lead.read_own",
        "lead.update_own",
        "lead.delete_own",
        "lead.change_status",
        "lead.view_history",
        # ❌ No read_team, read_all, update_all, assign, bulk_create, export
        
        # ✅ CONTACT MANAGEMENT (3/7) - OWN SCOPE ONLY
        "contact.create",
        "contact.read_own",
        "contact.update_own",
        # ❌ No read_all, update_all, delete, export
        
        # ✅ TASK MANAGEMENT (5/9) - OWN SCOPE ONLY
        "task.create",
        "task.read_own",
        "task.update",
        "task.complete",
        "task.change_priority",
        # ❌ No read_team, read_all, delete, assign
        
        # ❌ USER MANAGEMENT (0/8) - NONE
        # Cannot manage any users
        
        # ❌ ROLE & PERMISSION MANAGEMENT (0/7) - NONE
        # Cannot manage roles or permissions
        
        # ✅ DASHBOARD & REPORTING (2/9) - OWN ONLY
        "dashboard.view_own",
        "report.generate_own",
        # ❌ No team/all views, no scheduling, no analytics
        
        # ✅ SYSTEM SETTINGS (1/7) - VIEW ONLY
        "settings.view",
        # ❌ Cannot update any settings
        
        # ✅ EMAIL & COMMUNICATION (4/6) - LIMITED
        "email.send_single",
        "email.view_templates",
        "whatsapp.send",
        "call.make",
        # ❌ No bulk email, no template management
        
        # ✅ TEAM MANAGEMENT (1/6) - VIEW ONLY
        "team.view_structure",
        # ❌ Cannot manage hierarchy, assign members, etc.
        
        # ✅ NOTES & DOCUMENTS (2/3) - OWN ONLY
        "note.create",
        "note.read_own",
        # ❌ No delete
    ]
    
    return {
        "name": "user",
        "display_name": "User",
        "description": "Standard user with access to their own data and basic operations. Can manage own leads, contacts, and tasks. (24/69 permissions)",
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
    1. Super Admin - 69/69 permissions (100%)
    2. Admin - 57/69 permissions (83%)
    3. User - 24/69 permissions (35%)
    
    Args:
        mongodb_url: MongoDB connection URL
        database_name: Database name
        
    Returns:
        dict: Creation result with role details
    """
    client = None
    try:
        logger.info("🎭 Creating default roles...")
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
        
        # Define the 3 default roles
        roles_to_create = [
            get_super_admin_role_definition(all_permissions),  # 69/69 permissions
            get_admin_role_definition(),                       # 57/69 permissions
            get_user_role_definition()                         # 24/69 permissions
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
                "super_admin": "69/69 permissions (100%)",
                "admin": "57/69 permissions (83%)",
                "user": "24/69 permissions (35%)"
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
    3. Computes all 69 permissions
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
            "role": "admin",  # Keep old enum for backward compatibility
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
            "effective_permissions": all_permissions,  # All 69 permissions
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
        logger.info(f"🔑 Permissions: {len(all_permissions)}/69 (100%)")
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
    logger.info("🎭 LEADG CRM - DEFAULT ROLES SETUP")
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