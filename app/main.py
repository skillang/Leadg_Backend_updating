# app/main.py - Updated with Real-time WhatsApp Support, Skillang Integration and Admin Call Dashboard

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
from .routers import (
    auth, leads, tasks, notes, documents, timeline, contacts, lead_categories, 
    stages, statuses, course_levels, sources, whatsapp, emails, permissions, 
    tata_auth, tata_calls, tata_users, bulk_whatsapp, realtime, notifications, 
    integrations, admin_calls, password_reset ,cv_processing ,facebook_leads, automation_campaigns, fcm_notifications, fcm_test, groups
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("🚀 Starting LeadG CRM API...")
    await connect_to_mongo()
    
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
    
    # Initialize default permissions for existing users
    await initialize_user_permissions()
    logger.info("✅ User permissions initialized")
    
    # Initialize real-time WhatsApp service integration
    await initialize_realtime_whatsapp_service()
    logger.info("✅ Real-time WhatsApp service initialized")
    
    logger.info("✅ Application startup complete")
    
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

async def initialize_user_permissions():
    """Initialize default permissions for existing users who don't have permissions field"""
    try:
        from .config.database import get_database
        
        db = get_database()
        
        # Find users without permissions field
        users_without_permissions = await db.users.count_documents({"permissions": {"$exists": False}})
        
        if users_without_permissions > 0:
            logger.info(f"🔒 Found {users_without_permissions} users without permissions field")
            
            # Add default permissions to users who don't have them
            result = await db.users.update_many(
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
            
            logger.info(f"🔒 Added default permissions to {result.modified_count} users")
        else:
            logger.info("🔒 All users already have permissions field")
            
    except Exception as e:
        logger.warning(f"Error initializing user permissions: {e}")

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

# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="LeadG CRM - Customer Relationship Management API with Real-time WhatsApp, Email Functionality, Granular Permissions, Call Analytics and Skillang Integration",
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

# Health check with all modules including admin dashboard
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "message": "LeadG CRM API is running",
        "version": settings.version,
        "modules": [
            "auth", "leads", "tasks", "notes", "documents", "timeline", "contacts", 
            "stages", "statuses", "course-levels", "sources", "whatsapp", "realtime", 
            "emails", "permissions", "tata-auth", "tata-calls", "tata-users", 
            "bulk-whatsapp", "integrations", "admin-calls" , "cv-processing","automation-campaigns","groups"
        ]
    }

# Root endpoint with admin dashboard
@app.get("/")
async def root():
    return {
        "message": "Welcome to LeadG CRM API",
        "version": settings.version,
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
            "tata-auth": "/tata-auth",
            "tata-calls": "/tata-calls",
            "tata-users": "/tata-users",
            "bulk-whatsapp": "/bulk-whatsapp",
            "integrations": "/integrations",
            "admin": "/admin",  # NEW: Admin dashboard
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

# NEW: admin call dashboard router
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
    prefix="/facebook",  # Add prefix here
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

app.include_router(fcm_test.router, prefix="/fcm-test", tags=["FCM Testing"])



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )