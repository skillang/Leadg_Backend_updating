# app/main.py
# 🔄 RBAC-ENABLED: Updated with Role-Based Access Control Support
# ✅ Added: Permission seeding, default roles creation, RBAC routers

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import time

from .config.settings import settings
# Import the correct scheduler functions
from app.utils.whatsapp_scheduler import start_whatsapp_scheduler, stop_whatsapp_scheduler
from app.utils.campaign_cron import start_campaign_cron, stop_campaign_cron
from .config.database import connect_to_mongo, close_mongo_connection

# 🔄 UPDATED: Added roles and team routers
from .routers import (
    auth, leads, tasks, notes, documents, timeline, contacts, lead_categories, 
    stages, statuses, course_levels, sources, whatsapp, emails, permissions, 
    tata_auth, tata_calls, tata_users, bulk_whatsapp, realtime, notifications, 
    integrations, admin_calls, password_reset, cv_processing, facebook_leads, 
    automation_campaigns, fcm_notifications, fcm_test, groups,
    roles, team  # 🆕 NEW: RBAC routers
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager with RBAC initialization"""
    # Startup
    logger.info("🚀 Starting LeadG CRM API...")
    await connect_to_mongo()
    
    # 🆕 NEW: Seed RBAC permissions (69 permissions across 9 categories)
    await seed_rbac_permissions()
    logger.info("✅ RBAC permissions seeded")
    
    # 🆕 NEW: Create default roles (Super Admin, Admin, User)
    await create_default_roles()
    logger.info("✅ Default roles created")
    
    # 🆕 NEW: Create super admin user from .env
    await create_super_admin_from_env()
    logger.info("✅ Super admin user initialized")
    
    # Setup default stages if none exist
    await setup_default_stages()
    logger.info("✅ Default stages setup completed")
    
    # Setup default statuses if none exist
    await setup_default_statuses()
    logger.info("✅ Default statuses setup completed")
    
    # Check course levels collection (admin must create manually)
    await setup_default_course_levels()
    logger.info("✅ Course levels collection checked")
    
    # Check sources collection (admin must create manually)
    await setup_default_sources()
    logger.info("✅ Sources collection checked")
    
    # Check email configuration and start scheduler
    await check_email_configuration()
    logger.info("✅ Email configuration checked")
    
    # Start email scheduler
    await start_email_scheduler()
    logger.info("✅ Email scheduler started")
    
    # Check Skillang integration configuration
    await check_skillang_integration()
    logger.info("✅ Skillang integration configuration checked")
    
    # Start WhatsApp scheduler
    try:
        await start_whatsapp_scheduler()
        logger.info("✅ WhatsApp scheduler started successfully")
    except Exception as e:
        logger.error(f"❌ Failed to start WhatsApp scheduler: {e}")
        logger.warning("⚠️ Continuing without WhatsApp scheduler")

    try:
        await start_campaign_cron()
        logger.info("✅ Campaign automation cron started successfully")
    except Exception as e:
        logger.error(f"❌ Failed to start campaign cron: {e}")
        logger.warning("⚠️ Continuing without campaign automation")
    
    # 🔄 UPDATED: Initialize RBAC permissions for existing users
    await initialize_user_rbac_permissions()
    logger.info("✅ User RBAC permissions initialized")
    
    # Initialize real-time WhatsApp service integration
    await initialize_realtime_whatsapp_service()
    logger.info("✅ Real-time WhatsApp service initialized")
    
    logger.info("=" * 60)
    logger.info("✅ APPLICATION STARTUP COMPLETE")
    logger.info("=" * 60)
    logger.info("🎭 RBAC System: Enabled")
    logger.info("🔑 Permissions: 69 across 9 categories")
    logger.info("👥 Default Roles: Super Admin, Admin, User")
    logger.info("=" * 60)
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down LeadG CRM API...")
    
    # Stop WhatsApp scheduler
    try:
        await stop_whatsapp_scheduler()
        logger.info("✅ WhatsApp scheduler stopped")
    except Exception as e:
        logger.error(f"❌ Error stopping WhatsApp scheduler: {e}")
    
    try:
        await stop_campaign_cron()
        logger.info("✅ Campaign cron stopped")
    except Exception as e:
        logger.error(f"❌ Error stopping campaign cron: {e}")
    
    # Cleanup real-time connections
    await cleanup_realtime_connections()
    logger.info("✅ Real-time connections cleaned up")
    
    await close_mongo_connection()
    logger.info("✅ Application shutdown complete")


# ============================================================================
# 🆕 NEW: RBAC INITIALIZATION FUNCTIONS
# ============================================================================

async def seed_rbac_permissions():
    """
    Seed all 69 RBAC permissions into the database
    
    This function runs on startup and ensures all system permissions exist.
    If permissions already exist, it skips creation.
    """
    try:
        from app.utils.seed_permissions import seed_permissions
        
        logger.info("🔑 Seeding RBAC permissions...")
        
        result = await seed_permissions(
            mongodb_url=settings.mongodb_url,
            database_name=settings.database_name
        )
        
        if result["success"]:
            if result.get("skipped"):
                logger.info(f"ℹ️  Permissions already seeded: {result['total_permissions']} permissions exist")
            else:
                logger.info(f"✅ Seeded {result['permissions_created']} permissions")
                logger.info(f"📊 Categories: {result['categories_created']}")
        else:
            logger.error(f"❌ Failed to seed permissions: {result.get('message')}")
            
    except Exception as e:
        logger.error(f"❌ Error seeding RBAC permissions: {e}")
        logger.warning("⚠️ Application will continue but RBAC may not work correctly")


async def create_default_roles():
    """
    Create 3 default system roles:
    - Super Admin (69/69 permissions)
    - Admin (57/69 permissions)
    - User (24/69 permissions)
    
    This function runs on startup and ensures default roles exist.
    """
    try:
        from app.utils.create_default_roles import create_default_roles as create_roles_func
        
        logger.info("🎭 Creating default roles...")
        
        result = await create_roles_func(
            mongodb_url=settings.mongodb_url,
            database_name=settings.database_name
        )
        
        if result["success"]:
            if result.get("skipped"):
                logger.info(f"ℹ️  Default roles already exist")
                for role in result.get("existing_roles", []):
                    logger.info(f"   - {role['display_name']}: {role['permissions_count']} permissions")
            else:
                logger.info(f"✅ Created {result['roles_created']} default roles")
                for role in result.get("roles", []):
                    if not role.get("existed"):
                        logger.info(f"   - {role['display_name']}: {role['permissions_count']} permissions")
        else:
            logger.error(f"❌ Failed to create default roles: {result.get('message')}")
            if result.get("error") == "missing_permissions":
                logger.error("⚠️ Please ensure permissions are seeded first")
            
    except Exception as e:
        logger.error(f"❌ Error creating default roles: {e}")
        logger.warning("⚠️ Application will continue but role assignment may not work")


async def create_super_admin_from_env():
    """
    Create super admin user from environment variables
    
    Reads from .env:
    - SUPER_ADMIN_EMAIL
    - SUPER_ADMIN_PASSWORD
    - SUPER_ADMIN_FIRST_NAME
    - SUPER_ADMIN_LAST_NAME
    """
    try:
        # Check if super admin credentials are configured
        super_admin_email = settings.super_admin_email
        super_admin_password = settings.super_admin_password
        
        if not super_admin_email or not super_admin_password:
            logger.info("ℹ️  Super admin credentials not configured in .env")
            logger.info("   To create super admin, add to .env:")
            logger.info("   - SUPER_ADMIN_EMAIL=admin@yourcompany.com")
            logger.info("   - SUPER_ADMIN_PASSWORD=SecurePassword123!")
            return
        
        from app.utils.create_default_roles import create_super_admin_user
        
        logger.info(f"👤 Creating super admin user: {super_admin_email}")
        
        result = await create_super_admin_user(
            mongodb_url=settings.mongodb_url,
            database_name=settings.database_name,
            email=super_admin_email,
            password=super_admin_password,
            first_name=settings.super_admin_first_name or "Super",
            last_name=settings.super_admin_last_name or "Admin"
        )
        
        if result["success"]:
            if result.get("created"):
                logger.info(f"✅ Super admin user created: {super_admin_email}")
                logger.info(f"🔑 User ID: {result['user_id']}")
            else:
                logger.info(f"ℹ️  Super admin user already exists: {super_admin_email}")
        else:
            logger.error(f"❌ Failed to create super admin: {result.get('message')}")
            
    except Exception as e:
        logger.error(f"❌ Error creating super admin user: {e}")
        logger.warning("⚠️ You may need to create super admin manually")


async def initialize_user_rbac_permissions():
    """
    🔄 UPDATED: Initialize RBAC permissions for existing users
    
    Migrates users from old permission system to new RBAC system:
    - Assigns default 'user' role to users without role_id
    - Computes effective_permissions from role
    - Preserves old lead permissions as metadata
    """
    try:
        from .config.database import get_database
        from .services.rbac_service import RBACService
        
        db = get_database()
        rbac_service = RBACService()
        
        # Find users without role_id (not migrated to RBAC)
        users_without_role = await db.users.count_documents({
            "role_id": {"$exists": False}
        })
        
        if users_without_role > 0:
            logger.info(f"🔄 Found {users_without_role} users without RBAC role")
            logger.info("🔄 Migrating users to RBAC system...")
            
            # Get default 'user' role
            user_role = await db.roles.find_one({"name": "user"})
            
            if not user_role:
                logger.error("❌ Default 'user' role not found - cannot migrate users")
                return
            
            # Migrate users
            migrated_count = 0
            users = await db.users.find({"role_id": {"$exists": False}}).to_list(None)
            
            for user in users:
                try:
                    user_id = str(user["_id"])
                    
                    # Get effective permissions from role
                    effective_permissions = await rbac_service.get_user_permissions(user_id)
                    
                    # Update user with RBAC fields
                    await db.users.update_one(
                        {"_id": user["_id"]},
                        {
                            "$set": {
                                "role_id": user_role["_id"],
                                "role_name": "user",
                                "effective_permissions": effective_permissions,
                                "permissions_last_computed": time.time(),
                                "permission_overrides": [],
                                "reports_to": None,
                                "reports_to_email": None,
                                "reports_to_name": None,
                                "team_members": [],
                                "team_level": 0
                            }
                        }
                    )
                    
                    migrated_count += 1
                    
                except Exception as e:
                    logger.error(f"Error migrating user {user.get('email')}: {e}")
            
            # Update role users_count
            await db.roles.update_one(
                {"_id": user_role["_id"]},
                {"$inc": {"users_count": migrated_count}}
            )
            
            logger.info(f"✅ Migrated {migrated_count} users to RBAC system")
        else:
            logger.info("✅ All users already have RBAC roles")
        
        # Ensure all users have permissions field (backward compatibility)
        users_without_old_permissions = await db.users.count_documents({
            "permissions": {"$exists": False}
        })
        
        if users_without_old_permissions > 0:
            await db.users.update_many(
                {"permissions": {"$exists": False}},
                {
                    "$set": {
                        "permissions": {
                            "can_create_single_lead": False,
                            "can_create_bulk_leads": False,
                            "granted_by": None,
                            "granted_at": None,
                            "last_modified_by": None,
                            "last_modified_at": None
                        }
                    }
                }
            )
            logger.info(f"✅ Added legacy permissions field to {users_without_old_permissions} users")
            
    except Exception as e:
        logger.error(f"❌ Error initializing RBAC permissions: {e}")
        logger.warning("⚠️ Some users may not have proper RBAC permissions")


# ============================================================================
# EXISTING STARTUP FUNCTIONS (Preserved)
# ============================================================================

async def startup_event():
    from .services.password_reset_service import password_reset_service
    import asyncio
    
    async def cleanup_tokens_periodically():
        while True:
            try:
                await password_reset_service.cleanup_expired_tokens()
                await asyncio.sleep(4 * 60 * 60)  # 4 hours
            except Exception as e:
                logger.error(f"Token cleanup error: {e}")
                await asyncio.sleep(60 * 60)  # Retry in 1 hour
    
    asyncio.create_task(cleanup_tokens_periodically())

async def setup_default_stages():
    """Setup default stages on startup"""
    try:
        from .models.lead_stage import StageHelper
        
        created_count = await StageHelper.create_default_stages()
        if created_count:
            logger.info(f"Created {created_count} default stages")
        else:
            logger.info("Default stages already exist")
            
    except Exception as e:
        logger.warning(f"Error setting up default stages: {e}")

async def setup_default_statuses():
    """Setup default statuses on startup"""
    try:
        from .models.lead_status import StatusHelper
        
        created_count = await StatusHelper.create_default_statuses()
        if created_count:
            logger.info(f"Created {created_count} default statuses")
        else:
            logger.info("Default statuses already exist")
            
    except Exception as e:
        logger.warning(f"Error setting up default statuses: {e}")

async def setup_default_course_levels():
    """Check course levels collection exists - admin must create all course levels manually"""
    try:
        from .config.database import get_database
        
        db = get_database()
        
        # Just check if collection exists, don't create any defaults
        existing_count = await db.course_levels.count_documents({})
        
        if existing_count == 0:
            logger.info("📚 Course levels collection empty - admin must create course levels manually")
        else:
            active_count = await db.course_levels.count_documents({"is_active": True})
            logger.info(f"📚 Course levels: {existing_count} total, {active_count} active")
            
    except Exception as e:
        logger.warning(f"Error checking course levels: {e}")

async def setup_default_sources():
    """Check sources collection exists - admin must create all sources manually"""
    try:
        from .config.database import get_database
        
        db = get_database()
        
        # Just check if collection exists, don't create any defaults
        existing_count = await db.sources.count_documents({})
        
        if existing_count == 0:
            logger.info("📍 Sources collection empty - admin must create sources manually")
        else:
            active_count = await db.sources.count_documents({"is_active": True})
            logger.info(f"📍 Sources: {existing_count} total, {active_count} active")
            
    except Exception as e:
        logger.warning(f"Error checking sources: {e}")

async def start_email_scheduler():
    """Start the background email scheduler"""
    try:
        if settings.is_zeptomail_configured():
            from .services.email_scheduler import email_scheduler
            await email_scheduler.start_scheduler()
            logger.info("📧 Email scheduler started successfully")
        else:
            logger.info("📧 Email scheduler disabled - ZeptoMail not configured")
    except Exception as e:
        logger.warning(f"⚠️ Failed to start email scheduler: {e}")
        logger.info("📧 Email functionality will work without scheduling")

async def check_email_configuration():
    """Check email (ZeptoMail) configuration on startup"""
    try:
        if settings.is_zeptomail_configured():
            logger.info("📧 ZeptoMail configuration found - email functionality enabled")
            
            # Test connection in background (don't block startup)
            try:
                from .services.zepto_client import zepto_client
                test_result = await zepto_client.test_connection()
                if test_result["success"]:
                    logger.info("✅ ZeptoMail connection test successful")
                else:
                    logger.warning(f"⚠️ ZeptoMail connection test failed: {test_result.get('message')}")
            except Exception as e:
                logger.warning(f"⚠️ ZeptoMail connection test error: {e}")
        else:
            logger.warning("📧 ZeptoMail not configured - email functionality disabled")
            logger.info("   To enable emails: Set ZEPTOMAIL_URL and ZEPTOMAIL_TOKEN in .env")
            
    except Exception as e:
        logger.warning(f"Error checking email configuration: {e}")

async def check_skillang_integration():
    """Check Skillang integration configuration on startup"""
    try:
        if settings.is_skillang_configured():
            skillang_config = settings.get_skillang_config()
            logger.info("🔗 Skillang integration configuration found")
            logger.info(f"   Frontend domain: {skillang_config['frontend_domain']}")
            logger.info(f"   System user: {skillang_config['system_user_email']}")
            logger.info("🚀 Skillang form integration enabled")
        else:
            logger.warning("🔗 Skillang integration not configured - integration disabled")
            logger.info("   To enable: Set SKILLANG_INTEGRATION_ENABLED and SKILLANG_API_KEY in .env")
            
    except Exception as e:
        logger.warning(f"Error checking Skillang integration configuration: {e}")

async def initialize_realtime_whatsapp_service():
    """Initialize real-time WhatsApp service with dependency injection"""
    try:
        # Import real-time manager and WhatsApp service
        from .services.realtime_service import realtime_manager
        from .services.whatsapp_message_service import whatsapp_message_service
        
        # Inject real-time manager into WhatsApp service
        whatsapp_message_service.set_realtime_manager(realtime_manager)
        
        logger.info("🔗 Real-time manager injected into WhatsApp service")
        logger.info("📱 Real-time WhatsApp notifications enabled")
        
    except Exception as e:
        logger.warning(f"⚠️ Failed to initialize real-time WhatsApp service: {e}")
        logger.info("📱 WhatsApp will work without real-time notifications")

async def cleanup_realtime_connections():
    """Cleanup all real-time connections on application shutdown"""
    try:
        from .services.realtime_service import realtime_manager
        
        # Get total active connections before cleanup
        total_connections = sum(len(connections) for connections in realtime_manager.user_connections.values())
        
        if total_connections > 0:
            logger.info(f"🧹 Cleaning up {total_connections} active real-time connections")
            
            # Clear all connections
            realtime_manager.user_connections.clear()
            realtime_manager.user_unread_leads.clear()
            
            logger.info("✅ All real-time connections cleaned up")
        else:
            logger.info("🧹 No active real-time connections to cleanup")
            
    except Exception as e:
        logger.warning(f"⚠️ Error during real-time connections cleanup: {e}")


# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="LeadG CRM - Customer Relationship Management API with RBAC, Real-time WhatsApp, Email, Granular Permissions, Call Analytics and Skillang Integration",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# Add CORS middleware with Skillang domain support
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins() + [settings.skillang_frontend_domain],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add processing time to response headers"""
    start_time = time.time()
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response
    except Exception as e:
        logger.error(f"Request failed: {request.method} {request.url} - Error: {str(e)}", exc_info=True)
        raise

# Health check with all modules including RBAC
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "message": "LeadG CRM API is running",
        "version": settings.version,
        "rbac_enabled": True,  # 🆕 NEW
        "modules": [
            "auth", "leads", "tasks", "notes", "documents", "timeline", "contacts", 
            "stages", "statuses", "course-levels", "sources", "whatsapp", "realtime", 
            "emails", "permissions", "tata-auth", "tata-calls", "tata-users", 
            "bulk-whatsapp", "integrations", "admin-calls", "cv-processing",
            "automation-campaigns", "groups",
            "roles", "team"  # 🆕 NEW: RBAC modules
        ]
    }

# Root endpoint with RBAC info
@app.get("/")
async def root():
    return {
        "message": "Welcome to LeadG CRM API with RBAC",
        "version": settings.version,
        "rbac": {  # 🆕 NEW
            "enabled": True,
            "permissions": 69,
            "categories": 9,
            "default_roles": ["super_admin", "admin", "user"]
        },
        "docs": "/docs" if settings.debug else "Docs disabled in production",
        "endpoints": {
            "auth": "/auth",
            "leads": "/leads",
            "tasks": "/tasks", 
            "notes": "/notes",
            "documents": "/documents",
            "timeline": "",
            "contacts": "/contacts",
            "stages": "/stages",
            "statuses": "/statuses",
            "course-levels": "/course-levels",
            "sources": "/sources",
            "lead-categories": "/lead-categories",
            "whatsapp": "/whatsapp",
            "realtime": "/realtime",
            "emails": "/emails",
            "permissions": "/permissions",
            "roles": "/roles",  # 🆕 NEW
            "team": "/team",  # 🆕 NEW
            "tata-auth": "/tata-auth",
            "tata-calls": "/tata-calls",
            "tata-users": "/tata-users",
            "bulk-whatsapp": "/bulk-whatsapp",
            "integrations": "/integrations",
            "admin": "/admin",
            "groups": "/groups",
            "health": "/health"
        }
    }

# Include all routers with specific prefixes
app.include_router(
    auth.router,
    prefix="/auth",
    tags=["Authentication"]
)

app.include_router(
    password_reset.router,
    prefix="/auth/password-reset",
    tags=["Password Reset"]
)

app.include_router(
    leads.router,
    prefix="/leads",
    tags=["Leads"]
)

app.include_router(
    tasks.router,
    prefix="/tasks",
    tags=["Tasks"]
)

app.include_router(
    notes.router,
    prefix="/notes",
    tags=["Notes"]
)

app.include_router(
    documents.router,
    prefix="/documents",
    tags=["Documents"]
)

app.include_router(
    timeline.router,
    prefix="",
    tags=["Timeline"]
)

app.include_router(
    contacts.router,
    prefix="/contacts",
    tags=["Contacts"]
)

app.include_router(
    groups.router,
    prefix="/groups",
    tags=["Groups"]
)

app.include_router(
    lead_categories.router,
    prefix="/lead-categories",
    tags=["Lead Categories"]
)

app.include_router(
    stages.router,
    prefix="/stages",
    tags=["Stages"]
)

app.include_router(
    statuses.router,
    prefix="/statuses",
    tags=["Statuses"]
)

app.include_router(
    course_levels.router,
    prefix="/course-levels",
    tags=["Course Levels"]
)

app.include_router(
    sources.router,
    prefix="/sources",
    tags=["Sources"]
)

app.include_router(
    whatsapp.router,
    prefix="/whatsapp",
    tags=["WhatsApp"]
)

app.include_router(
    realtime.router,
    prefix="/realtime",
    tags=["Real-time Notifications"]
)

app.include_router(
    emails.router,
    prefix="/emails",
    tags=["Emails"]
)

app.include_router(
    permissions.router,
    prefix="/permissions",
    tags=["Permissions"]
)

# 🆕 NEW: RBAC Routers
app.include_router(
    roles.router,
    prefix="/roles",
    tags=["RBAC - Roles"]
)

app.include_router(
    team.router,
    tags=["RBAC - Team Management"]
)

app.include_router(
    tata_auth.router,
    prefix="/tata-auth",
    tags=["Tata Authentication"]
)

app.include_router(
    tata_calls.router,
    prefix="/tata-calls",
    tags=["Tata Calls"]
)

app.include_router(
    tata_users.router,
    prefix="/tata-users", 
    tags=["Tata User Sync"]
)

app.include_router(
    bulk_whatsapp.router,
    prefix="/bulk-whatsapp", 
    tags=["Bulk WhatsApp"]
)

app.include_router(
    notifications.router,
    prefix="/notifications", 
    tags=["Notifications"]
)

app.include_router(
    integrations.router,
    prefix="/integrations",
    tags=["Integrations"]
)

app.include_router(
    admin_calls.router,
    prefix="/admin",
    tags=["Admin Dashboard"]
)

app.include_router(
    cv_processing.router,
    prefix="/cv",
    tags=["CV Processing"]
)

app.include_router(
    facebook_leads.router,
    prefix="/facebook",
    tags=["Facebook Integration"]
)

app.include_router(
    automation_campaigns.router,
    prefix="/campaigns",
    tags=["Automation Campaigns"]
)

app.include_router(
    fcm_notifications.router, 
    prefix="/fcm", 
    tags=["FCM Notifications"]
)

app.include_router(
    fcm_test.router,
    prefix="/fcm-test",
    tags=["FCM Testing"]
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )