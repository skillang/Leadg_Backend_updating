# app/config/database.py - Enhanced with Multi-Assignment and Selective Round Robin Indexes + WhatsApp Support + Bulk WhatsApp + UNIFIED NOTIFICATIONS

import motor.motor_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import logging
from .settings import settings

logger = logging.getLogger(__name__)

# Global database client
_client: AsyncIOMotorClient = None
_database: AsyncIOMotorDatabase = None

async def connect_to_mongo():
    """Create database connection"""
    global _client, _database
    
    try:
        logger.info("🔌 Connecting to MongoDB...")
        
        _client = AsyncIOMotorClient(
            settings.mongodb_url,
            maxPoolSize=settings.mongodb_max_pool_size,
            minPoolSize=settings.mongodb_min_pool_size,
            maxIdleTimeMS=settings.mongodb_max_idle_time_ms,
            serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms
        )
        
        _database = _client[settings.database_name]
        
        # Test connection
        await _database.command("ping")
        logger.info("✅ Connected to MongoDB successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to connect to MongoDB: {e}")
        raise

def get_database() -> AsyncIOMotorDatabase:
    """Get database instance"""
    global _database
    if _database is None:
        raise RuntimeError("Database not initialized. Call connect_to_mongo() first.")
    return _database

async def close_mongo_connection():
    """Close database connection"""
    global _client
    if _client:
        _client.close()
        logger.info("🔌 MongoDB connection closed")

async def create_indexes():
    """Create database indexes for optimal performance with enhanced multi-assignment support and WhatsApp integration"""
    try:
        db = get_database()
        logger.info("📊 Creating enhanced database indexes...")
        
        # ============================================================================
        # USERS COLLECTION INDEXES (ENHANCED)
        # ============================================================================
        await db.users.create_index("email", unique=True)
        await db.users.create_index("username", unique=True)
        await db.users.create_index([("role", 1), ("is_active", 1)])
        await db.users.create_index("created_at")
        
        # 🆕 NEW: Enhanced indexes for selective round robin
        await db.users.create_index([("role", 1), ("is_active", 1), ("total_assigned_leads", 1)])
        await db.users.create_index("total_assigned_leads")  # For round robin load balancing
        await db.users.create_index("departments")  # For department-based assignment
        await db.users.create_index([("departments", 1), ("is_active", 1)])
        await db.users.create_index([("email", 1), ("is_active", 1)])  # Fast user validation
        await db.users.create_index("fcm_token")  # For FCM push notifications
        
        logger.info("✅ Enhanced Users indexes created")
        
        # ============================================================================
        # LEADS COLLECTION INDEXES (ENHANCED WITH MULTI-ASSIGNMENT + WHATSAPP)
        # ============================================================================
        await db.leads.create_index("lead_id", unique=True)
        await db.leads.create_index("email")
        await db.leads.create_index("contact_number")
        
        # 🆕 NEW: Enhanced assignment indexes for multi-user assignment
        await db.leads.create_index("assigned_to")  # Primary assignment
        await db.leads.create_index("co_assignees")  # Co-assignee queries
        await db.leads.create_index("is_multi_assigned")  # Filter multi-assigned leads
        await db.leads.create_index([("assigned_to", 1), ("is_multi_assigned", 1)])  # Compound for user queries
        await db.leads.create_index([("co_assignees", 1), ("is_multi_assigned", 1)])  # Co-assignee queries
        
        # Multi-assignment compound indexes for efficient user lead queries
        await db.leads.create_index([("assigned_to", 1), ("status", 1)])
        await db.leads.create_index([("assigned_to", 1), ("created_at", -1)])
        await db.leads.create_index([("co_assignees", 1), ("status", 1)])
        await db.leads.create_index([("co_assignees", 1), ("created_at", -1)])
        
        # Enhanced assignment method tracking
        await db.leads.create_index("assignment_method")  # Track assignment methods
        await db.leads.create_index([("assignment_method", 1), ("created_at", -1)])
        
        # Existing essential indexes
        await db.leads.create_index([("created_by", 1), ("created_at", -1)])
        await db.leads.create_index([("stage", 1), ("created_at", -1)])
        await db.leads.create_index([("category", 1), ("stage", 1)])
        await db.leads.create_index("tags")
        await db.leads.create_index("source")
        await db.leads.create_index("status")
        await db.leads.create_index("created_at")
        await db.leads.create_index("updated_at")
        
        # 🆕 NEW: Indexes for new optional fields
        await db.leads.create_index("age")
        await db.leads.create_index("experience")
        await db.leads.create_index("nationality")
        await db.leads.create_index([("category", 1), ("age", 1)])  # Category-age analysis
        await db.leads.create_index([("nationality", 1), ("category", 1)])  # Nationality-category analysis
        
        # 🆕 NEW: Indexes for dynamic course_level field
        await db.leads.create_index("course_level")  # Course level queries
        await db.leads.create_index([("course_level", 1), ("created_at", -1)])  # Course level with date
        await db.leads.create_index([("course_level", 1), ("category", 1)])  # Course level-category analysis
        
        # 🆕 NEW: WHATSAPP ACTIVITY INDEXES FOR LEADS
        await db.leads.create_index("last_whatsapp_activity")  # Sort by WhatsApp activity
        await db.leads.create_index("whatsapp_message_count")  # Filter leads with messages
        await db.leads.create_index("unread_whatsapp_count")  # Find leads with unread messages
        await db.leads.create_index("whatsapp_has_unread")  # 🔥 NEW: Boolean flag for faster unread queries
        await db.leads.create_index([("assigned_to", 1), ("unread_whatsapp_count", 1)])  # User's unread messages
        await db.leads.create_index([("assigned_to", 1), ("whatsapp_has_unread", 1)])  # 🔥 NEW: Fast user unread lookup
        await db.leads.create_index([("last_whatsapp_activity", -1), ("assigned_to", 1)])  # Recent WhatsApp activity per user
        await db.leads.create_index([("unread_whatsapp_count", 1), ("last_whatsapp_activity", -1)])  # Unread messages by recent activity
        await db.leads.create_index([("whatsapp_message_count", 1), ("assigned_to", 1)])  # Message count per user
        
        # 🆕 NEW: Phone number index for bulk WhatsApp targeting
        await db.leads.create_index("phone_number")  # Essential for bulk WhatsApp recipient selection
        await db.leads.create_index([("phone_number", 1), ("assigned_to", 1)])  # Phone + assignment for permission checks
        await db.leads.create_index([("phone_number", 1), ("status", 1)])  # Phone + status for filtering
        
        logger.info("✅ Enhanced Leads indexes with WhatsApp fields created")
        
        # ============================================================================
        # 🆕 NEW: WHATSAPP MESSAGES COLLECTION INDEXES
        # ============================================================================
        logger.info("📱 Creating WhatsApp Messages collection indexes...")
        
        whatsapp_messages_collection = db.whatsapp_messages
        await whatsapp_messages_collection.create_index("message_id", unique=True)  # Unique WhatsApp message ID
        await whatsapp_messages_collection.create_index("lead_id")  # Query by lead
        await whatsapp_messages_collection.create_index("phone_number")  # Match incoming messages by phone
        
        # Status and type indexes
        await whatsapp_messages_collection.create_index("direction")  # Filter incoming/outgoing
        await whatsapp_messages_collection.create_index("status")  # Filter by delivery status
        await whatsapp_messages_collection.create_index("message_type")  # Filter by message type
        
        # Timestamp indexes for sorting
        await whatsapp_messages_collection.create_index("timestamp")  # Sort by time
        await whatsapp_messages_collection.create_index([("timestamp", -1)])  # Recent messages first
        
        # Compound indexes for efficient chat queries
        await whatsapp_messages_collection.create_index([("lead_id", 1), ("timestamp", 1)])  # Chat history queries
        await whatsapp_messages_collection.create_index([("lead_id", 1), ("timestamp", -1)])  # Recent chat history
        await whatsapp_messages_collection.create_index([("lead_id", 1), ("direction", 1)])  # Filter by direction per lead
        await whatsapp_messages_collection.create_index([("phone_number", 1), ("timestamp", 1)])  # Phone-based queries
        await whatsapp_messages_collection.create_index([("lead_id", 1), ("status", 1)])  # Message status per lead
        
        # User activity indexes
        await whatsapp_messages_collection.create_index("sent_by_user_id")  # Messages sent by specific user
        await whatsapp_messages_collection.create_index([("sent_by_user_id", 1), ("timestamp", -1)])  # User activity timeline
        
        # Performance indexes for dashboard queries
        await whatsapp_messages_collection.create_index([("direction", 1), ("timestamp", -1)])  # Recent incoming/outgoing
        await whatsapp_messages_collection.create_index([("status", 1), ("direction", 1)])  # Status-direction analysis
        await whatsapp_messages_collection.create_index([("lead_id", 1), ("direction", 1), ("status", 1)])  # Complete message filtering
        
        # Unread message tracking
        await whatsapp_messages_collection.create_index([("direction", 1), ("is_read", 1)])  # Unread incoming messages
        await whatsapp_messages_collection.create_index([("lead_id", 1), ("direction", 1), ("is_read", 1)])  # Unread per lead
        
        logger.info("✅ WhatsApp Messages indexes created")
        
        # ============================================================================
        # 🆕 NEW: BULK WHATSAPP JOBS COLLECTION INDEXES
        # ============================================================================
        logger.info("📤 Creating Bulk WhatsApp Jobs collection indexes...")
        
        bulk_whatsapp_collection = db.bulk_whatsapp_jobs
        
        # Essential indexes for job management
        await bulk_whatsapp_collection.create_index("job_id", unique=True)  # Unique job identifier
        await bulk_whatsapp_collection.create_index("created_by")  # Permission-based job access
        await bulk_whatsapp_collection.create_index("status")  # Filter jobs by status
        await bulk_whatsapp_collection.create_index("created_at")  # Sort jobs by creation time
        await bulk_whatsapp_collection.create_index("updated_at")  # Sort by last update
        
        # Scheduling indexes (CRITICAL for scheduler performance)
        await bulk_whatsapp_collection.create_index("is_scheduled")  # Filter scheduled vs immediate jobs
        await bulk_whatsapp_collection.create_index("scheduled_time")  # Sort by scheduled time
        await bulk_whatsapp_collection.create_index([("is_scheduled", 1), ("scheduled_time", 1)])  # Scheduled jobs by time
        await bulk_whatsapp_collection.create_index([("status", 1), ("is_scheduled", 1)])  # Pending scheduled jobs
        
        # Performance indexes for job listing and monitoring
        await bulk_whatsapp_collection.create_index([("created_by", 1), ("created_at", -1)])  # User's jobs by date
        await bulk_whatsapp_collection.create_index([("created_by", 1), ("status", 1)])  # User's jobs by status
        await bulk_whatsapp_collection.create_index([("status", 1), ("created_at", -1)])  # Jobs by status and date
        await bulk_whatsapp_collection.create_index([("status", 1), ("updated_at", -1)])  # Active jobs by update time
        
        # Job type and configuration indexes
        await bulk_whatsapp_collection.create_index("message_type")  # Filter template vs text jobs
        await bulk_whatsapp_collection.create_index("template_name")  # Find jobs using specific templates
        await bulk_whatsapp_collection.create_index("target_type")  # Filter by targeting method
        
        # Progress and statistics indexes
        await bulk_whatsapp_collection.create_index("total_recipients")  # Sort by job size
        await bulk_whatsapp_collection.create_index("success_count")  # Sort by success rate
        await bulk_whatsapp_collection.create_index("failed_count")  # Find failed jobs
        await bulk_whatsapp_collection.create_index([("status", 1), ("success_count", 1)])  # Completed jobs by success
        
        # Time-based indexes for cleanup and analytics
        await bulk_whatsapp_collection.create_index("started_at")  # Sort by execution start
        await bulk_whatsapp_collection.create_index("completed_at")  # Sort by completion time
        await bulk_whatsapp_collection.create_index("cancelled_at")  # Track cancelled jobs
        
        # Compound indexes for complex queries
        await bulk_whatsapp_collection.create_index([("created_by", 1), ("message_type", 1), ("created_at", -1)])
        await bulk_whatsapp_collection.create_index([("status", 1), ("is_scheduled", 1), ("scheduled_time", 1)])
        await bulk_whatsapp_collection.create_index([("message_type", 1), ("status", 1), ("created_at", -1)])
        
        # Cleanup indexes (for old job removal)
        await bulk_whatsapp_collection.create_index([("status", 1), ("completed_at", 1)])  # Old completed jobs
        await bulk_whatsapp_collection.create_index([("status", 1), ("cancelled_at", 1)])  # Old cancelled jobs
        
        logger.info("✅ Bulk WhatsApp Jobs indexes created")

        logger.info("🤖 Creating Automation Campaigns collection indexes...")

        campaigns_collection = db.automation_campaigns

        # Essential indexes for campaign management
        await campaigns_collection.create_index("campaign_id", unique=True)
        await campaigns_collection.create_index("campaign_type")  # whatsapp or email
        await campaigns_collection.create_index("status")  # active, paused, deleted
        await campaigns_collection.create_index("created_by")
        await campaigns_collection.create_index("created_at")

        # Filter indexes
        await campaigns_collection.create_index("send_to_all")
        await campaigns_collection.create_index("stage_ids")
        await campaigns_collection.create_index("source_ids")

        # Scheduling indexes
        await campaigns_collection.create_index("use_custom_dates")
        await campaigns_collection.create_index([("status", 1), ("created_at", -1)])
        await campaigns_collection.create_index([("campaign_type", 1), ("status", 1)])
        await campaigns_collection.create_index([("created_by", 1), ("created_at", -1)])

        logger.info("✅ Automation Campaigns indexes created")

        # ============================================================================
        # 🆕 NEW: CAMPAIGN TRACKING COLLECTION INDEXES
        # ============================================================================
        logger.info("📊 Creating Campaign Tracking collection indexes...")

        tracking_collection = db.campaign_tracking

        # Essential tracking indexes
        await tracking_collection.create_index("campaign_id")
        await tracking_collection.create_index("lead_id")
        await tracking_collection.create_index([("campaign_id", 1), ("lead_id", 1)], unique=True)

        # Status and execution indexes
        await tracking_collection.create_index("status")  # active, paused, completed
        await tracking_collection.create_index("job_type")  # enrollment or job
        await tracking_collection.create_index("execute_at")
        await tracking_collection.create_index([("status", 1), ("execute_at", 1)])

        # Performance indexes
        await tracking_collection.create_index([("campaign_id", 1), ("status", 1)])
        await tracking_collection.create_index([("lead_id", 1), ("status", 1)])
        await tracking_collection.create_index([("status", 1), ("created_at", -1)])
        await tracking_collection.create_index("created_at")

        logger.info("✅ Campaign Tracking indexes created")

        # ============================================================================
        # 🔥 UPDATED: NOTIFICATION HISTORY COLLECTION INDEXES (UNIFIED SYSTEM)
        # ============================================================================
        logger.info("📨 Creating Notification History collection indexes...")
        
        notification_history_collection = db.notification_history
        
        # Essential indexes for notification history
        await notification_history_collection.create_index("notification_id", unique=True)  # Unique notification identifier
        await notification_history_collection.create_index("user_email")  # Query by user (assigned user)
        await notification_history_collection.create_index("notification_type")  # Filter by type
        await notification_history_collection.create_index("lead_id")  # Query by lead
        await notification_history_collection.create_index("task_id")  # Query by task
        await notification_history_collection.create_index("created_at")  # Sort by time
        await notification_history_collection.create_index([("created_at", -1)])  # Recent notifications first
        
        # 🔥 NEW: Unified notification visibility indexes
        await notification_history_collection.create_index("visible_to_users")  # Array index for user visibility
        await notification_history_collection.create_index("visible_to_admins")  # Boolean index for admin visibility
        await notification_history_collection.create_index([("visible_to_users", 1), ("created_at", -1)])  # User notifications timeline
        await notification_history_collection.create_index([("visible_to_admins", 1), ("created_at", -1)])  # Admin notifications timeline
        
        # 🔥 NEW: Multi-user read tracking indexes
        await notification_history_collection.create_index("read_by")  # Object field for per-user read status
        
        # Compound indexes for efficient unified queries
        await notification_history_collection.create_index([("user_email", 1), ("created_at", -1)])  # Primary user timeline
        await notification_history_collection.create_index([("user_email", 1), ("notification_type", 1)])  # User notifications by type
        await notification_history_collection.create_index([("visible_to_users", 1), ("notification_type", 1)])  # Visible notifications by type
        await notification_history_collection.create_index([("lead_id", 1), ("created_at", -1)])  # Lead notification timeline
        await notification_history_collection.create_index([("task_id", 1), ("created_at", -1)])  # Task notification timeline
        await notification_history_collection.create_index([("user_email", 1), ("lead_id", 1)])  # User notifications for specific lead
        await notification_history_collection.create_index([("user_email", 1), ("task_id", 1)])  # User notifications for specific task
        
        # Performance indexes for history queries
        await notification_history_collection.create_index([("notification_type", 1), ("created_at", -1)])  # Type-based history
        await notification_history_collection.create_index([("user_email", 1), ("created_at", -1), ("notification_type", 1)])  # Complete user history
        
        # 🔥 UPDATED: Read status tracking with per-user support
        await notification_history_collection.create_index("read_at")  # Legacy read tracking (optional)
        await notification_history_collection.create_index([("user_email", 1), ("read_at", 1)])  # Legacy user read status
        
        # 🔥 NEW: Combined visibility and read status indexes for unified notification endpoint
        await notification_history_collection.create_index([
            ("visible_to_users", 1),
            ("notification_type", 1),
            ("created_at", -1)
        ])  # Efficient filtering for unified endpoint
        
        await notification_history_collection.create_index([
            ("visible_to_admins", 1),
            ("notification_type", 1),
            ("created_at", -1)
        ])  # Admin-specific unified filtering
        
        # 🔥 NEW: Role-based display optimization
        await notification_history_collection.create_index([
            ("notification_type", 1),
            ("visible_to_users", 1),
            ("visible_to_admins", 1)
        ])  # Role-based notification queries
        
        logger.info("✅ Unified Notification History indexes created")



        # ============================================================================
        # LEAD_STAGES COLLECTION INDEXES
        # ============================================================================
        await db.lead_stages.create_index("name", unique=True)
        await db.lead_stages.create_index([("is_active", 1), ("sort_order", 1)])
        await db.lead_stages.create_index("is_default")
        await db.lead_stages.create_index("created_by")
        await db.lead_stages.create_index("created_at")
        logger.info("✅ Lead Stages indexes created")
        
        # ============================================================================
        # LEAD_STATUSES COLLECTION INDEXES
        # ============================================================================
        await db.lead_statuses.create_index("name", unique=True)
        await db.lead_statuses.create_index([("is_active", 1), ("sort_order", 1)])
        await db.lead_statuses.create_index("is_default")
        await db.lead_statuses.create_index("created_by")
        await db.lead_statuses.create_index("created_at")
        logger.info("✅ Lead Statuses indexes created")
        
        # ============================================================================
        # 🆕 NEW: COURSE_LEVELS COLLECTION INDEXES
        # ============================================================================
        await db.course_levels.create_index("name", unique=True)  # Unique course level names
        await db.course_levels.create_index([("is_active", 1), ("sort_order", 1)])  # Active course levels sorted
        await db.course_levels.create_index("is_default")  # Find default course level
        await db.course_levels.create_index("sort_order")  # Sort for display order
        await db.course_levels.create_index([("name", 1), ("is_active", 1)])  # Compound for fast lookups
        await db.course_levels.create_index("created_at")  # For sorting by creation date
        await db.course_levels.create_index("created_by")  # Track who created course levels
        logger.info("✅ Course Levels indexes created")
        
        # ============================================================================
        # 🆕 NEW: SOURCES COLLECTION INDEXES
        # ============================================================================
        await db.sources.create_index("name", unique=True)  # Unique source names
        await db.sources.create_index([("is_active", 1), ("sort_order", 1)])  # Active sources sorted
        await db.sources.create_index("is_default")  # Find default source
        await db.sources.create_index("sort_order")  # Sort for display order
        await db.sources.create_index([("name", 1), ("is_active", 1)])  # Compound for fast lookups
        await db.sources.create_index("created_at")  # For sorting by creation date
        await db.sources.create_index("created_by")  # Track who created sources
        logger.info("✅ Sources indexes created")


        # ============================================================================
# 🆕 NEW: CV EXTRACTIONS COLLECTION INDEXES
# ============================================================================
        await db.cv_extractions.create_index("processing_id", unique=True)  # Unique processing identifier
        await db.cv_extractions.create_index([("uploaded_by", 1), ("created_at", -1)])  # User's CVs by date
        await db.cv_extractions.create_index([("status", 1), ("created_at", -1)])  # CVs by status and date
        await db.cv_extractions.create_index("uploaded_by_email")  # Quick user email lookup
        await db.cv_extractions.create_index("converted_to_lead")  # Filter converted/unconverted CVs
        await db.cv_extractions.create_index([("status", 1), ("uploaded_by", 1)])  # User's CVs by status
        await db.cv_extractions.create_index("created_at")  # Sort by upload time
        await db.cv_extractions.create_index([("converted_to_lead", 1), ("created_at", -1)])  # Conversion tracking
        logger.info("✅ CV Extractions indexes created")
                
        # ============================================================================
        # TASKS COLLECTION INDEXES (ENHANCED)
        # ============================================================================
        await db.lead_tasks.create_index([("lead_id", 1), ("created_at", -1)])
        await db.lead_tasks.create_index([("assigned_to", 1), ("status", 1)])
        await db.lead_tasks.create_index([("assigned_to", 1), ("due_datetime", 1)])
        await db.lead_tasks.create_index([("created_by", 1), ("created_at", -1)])
        await db.lead_tasks.create_index("lead_object_id")
        await db.lead_tasks.create_index("task_type")
        await db.lead_tasks.create_index("priority")
        await db.lead_tasks.create_index("status")
        await db.lead_tasks.create_index("due_datetime")
        await db.lead_tasks.create_index([("status", 1), ("due_datetime", 1)])
        
        # 🆕 NEW: Enhanced task assignment indexes for multi-assignment scenarios
        await db.lead_tasks.create_index([("lead_id", 1), ("assigned_to", 1)])
        await db.lead_tasks.create_index([("assigned_to", 1), ("created_at", -1)])
        
        logger.info("✅ Enhanced Tasks indexes created")
        
        # ============================================================================
        # LEAD_ACTIVITIES COLLECTION INDEXES (ENHANCED)
        # ============================================================================
        await db.lead_activities.create_index([("lead_id", 1), ("created_at", -1)])
        await db.lead_activities.create_index([("lead_object_id", 1), ("created_at", -1)])
        await db.lead_activities.create_index([("created_by", 1), ("created_at", -1)])
        await db.lead_activities.create_index("activity_type")
        await db.lead_activities.create_index([("activity_type", 1), ("created_at", -1)])
        await db.lead_activities.create_index("created_at")
        await db.lead_activities.create_index("is_system_generated")
        
        # 🆕 NEW: Multi-assignment activity tracking
        await db.lead_activities.create_index([("lead_id", 1), ("activity_type", 1)])
        await db.lead_activities.create_index([("activity_type", 1), ("is_system_generated", 1)])
        
        # 🆕 NEW: Bulk WhatsApp activity tracking indexes
        await db.lead_activities.create_index([("activity_type", 1), ("lead_id", 1)])  # Find bulk WhatsApp activities
        await db.lead_activities.create_index([("lead_id", 1), ("activity_type", 1), ("created_at", -1)])  # Lead activity history
        
        logger.info("✅ Enhanced Activities indexes created")
        
        # ============================================================================
        # 🆕 NEW: LEAD_COUNTERS COLLECTION INDEXES
        # ============================================================================
        await db.lead_counters.create_index("category", unique=True)
        await db.lead_counters.create_index("_id", unique=True)  # For sequence counters
        logger.info("✅ Lead Counters indexes created")
        
        # ============================================================================
        # AUTHENTICATION COLLECTIONS INDEXES
        # ============================================================================
        await db.token_blacklist.create_index("token_jti", unique=True)
        await db.token_blacklist.create_index("expires_at", expireAfterSeconds=0)
        await db.token_blacklist.create_index("blacklisted_at")
        
        await db.user_sessions.create_index([("user_id", 1), ("created_at", -1)])
        await db.user_sessions.create_index("session_id", unique=True)
        await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
        await db.user_sessions.create_index([("user_id", 1), ("is_active", 1)])
        logger.info("✅ Authentication indexes created")
        
        # ============================================================================
        # 🆕 NEW: FUTURE COLLECTIONS INDEXES (READY FOR IMPLEMENTATION)
        # ============================================================================
        
        # Lead Notes Collection indexes (for future implementation)
        try:
            await db.lead_notes.create_index([("lead_id", 1), ("created_at", -1)])
            await db.lead_notes.create_index([("created_by", 1), ("created_at", -1)])
            await db.lead_notes.create_index("tags")
            await db.lead_notes.create_index([("lead_id", 1), ("tags", 1)])
            await db.lead_notes.create_index("title")  # For title searches
            logger.info("✅ Notes indexes created")
        except:
            logger.info("ℹ️ Notes collection not yet created - indexes will be created when collection exists")
        
        # Lead Documents Collection indexes (for future implementation)
        try:
            await db.lead_documents.create_index([("lead_id", 1), ("created_at", -1)])
            await db.lead_documents.create_index([("created_by", 1), ("status", 1)])
            await db.lead_documents.create_index("document_type")
            await db.lead_documents.create_index("status")
            await db.lead_documents.create_index([("lead_id", 1), ("document_type", 1)])
            await db.lead_documents.create_index([("status", 1), ("created_at", -1)])
            logger.info("✅ Documents indexes created")
        except:
            logger.info("ℹ️ Documents collection not yet created - indexes will be created when collection exists")
        
        # Lead Contacts Collection indexes (for future implementation)
        try:
            await db.lead_contacts.create_index([("lead_id", 1), ("is_primary", -1)])
            await db.lead_contacts.create_index("email")
            await db.lead_contacts.create_index("contact_number")
            await db.lead_contacts.create_index("role")
            await db.lead_contacts.create_index([("lead_id", 1), ("role", 1)])
            await db.lead_contacts.create_index([("lead_id", 1), ("is_primary", 1)])
            logger.info("✅ Contacts indexes created")
        except:
            logger.info("ℹ️ Contacts collection not yet created - indexes will be created when collection exists")
        
        logger.info("🎯 All enhanced database indexes created successfully!")
        logger.info("📱 WhatsApp chat functionality fully supported!")
        logger.info("📤 Bulk WhatsApp messaging fully optimized!")
        logger.info("🚀 System optimized for multi-user assignment, selective round robin, dynamic course levels & sources, and complete WhatsApp integration!")
        
    except Exception as e:
        logger.error(f"❌ Error creating indexes: {e}")
        # Don't fail the application startup if index creation fails
        logger.warning("⚠️ Continuing without optimal indexes - some queries may be slower")

async def get_collection_stats():
    """Get database collection statistics with enhanced metrics including WhatsApp and Bulk WhatsApp"""
    try:
        db = get_database()
        
        collections = [
            "users",
            "leads", 
            "lead_stages",
            "lead_statuses",
            "course_levels",
            "sources",
            "lead_tasks",
            "lead_activities",
            "lead_counters",
            "whatsapp_messages",  # WhatsApp messages collection
            "bulk_whatsapp_jobs",
            "automation_campaigns",      # ADD THIS
            "campaign_tracking",         # ADD THIS            
            "notification_history", 
            "token_blacklist",
            "user_sessions",
            # Future collections
            "lead_notes",
            "lead_documents", 
            "lead_contacts"
        ]
        
        stats = {}
        total_documents = 0
        
        for collection_name in collections:
            try:
                count = await db[collection_name].count_documents({})
                stats[collection_name] = count
                total_documents += count
                
                # Get additional stats for key collections
                if collection_name == "leads":
                    multi_assigned = await db[collection_name].count_documents({"is_multi_assigned": True})
                    stats[f"{collection_name}_multi_assigned"] = multi_assigned
                    
                    unassigned = await db[collection_name].count_documents({"assigned_to": None})
                    stats[f"{collection_name}_unassigned"] = unassigned
                    
                    # WhatsApp activity stats
                    with_whatsapp = await db[collection_name].count_documents({"whatsapp_message_count": {"$gt": 0}})
                    stats[f"{collection_name}_with_whatsapp"] = with_whatsapp
                    
                    unread_whatsapp = await db[collection_name].count_documents({"unread_whatsapp_count": {"$gt": 0}})
                    stats[f"{collection_name}_unread_whatsapp"] = unread_whatsapp
                    
                    # 🆕 NEW: Phone number stats for bulk WhatsApp
                    with_phone = await db[collection_name].count_documents({"phone_number": {"$exists": True, "$ne": "", "$ne": None}})
                    stats[f"{collection_name}_with_phone"] = with_phone
                    
                elif collection_name == "users":
                    active_users = await db[collection_name].count_documents({"is_active": True})
                    stats[f"{collection_name}_active"] = active_users
                    
                elif collection_name == "whatsapp_messages":
                    # WhatsApp message stats
                    incoming = await db[collection_name].count_documents({"direction": "incoming"})
                    stats[f"{collection_name}_incoming"] = incoming
                    
                    outgoing = await db[collection_name].count_documents({"direction": "outgoing"})
                    stats[f"{collection_name}_outgoing"] = outgoing
                    
                    unread = await db[collection_name].count_documents({"direction": "incoming", "is_read": False})
                    stats[f"{collection_name}_unread"] = unread
                
                # 🆕 NEW: Bulk WhatsApp jobs stats
                elif collection_name == "bulk_whatsapp_jobs":
                    # Job status breakdown
                    pending = await db[collection_name].count_documents({"status": "pending"})
                    stats[f"{collection_name}_pending"] = pending
                    
                    processing = await db[collection_name].count_documents({"status": "processing"})
                    stats[f"{collection_name}_processing"] = processing
                    
                    completed = await db[collection_name].count_documents({"status": "completed"})
                    stats[f"{collection_name}_completed"] = completed
                    
                    failed = await db[collection_name].count_documents({"status": "failed"})
                    stats[f"{collection_name}_failed"] = failed
                    
                    # Scheduled vs immediate jobs
                    scheduled = await db[collection_name].count_documents({"is_scheduled": True})
                    stats[f"{collection_name}_scheduled"] = scheduled
                    
                    immediate = await db[collection_name].count_documents({"is_scheduled": False})
                    stats[f"{collection_name}_immediate"] = immediate
                    
                    # Message type breakdown
                    template_jobs = await db[collection_name].count_documents({"message_type": "template"})
                    stats[f"{collection_name}_template"] = template_jobs
                    
                    text_jobs = await db[collection_name].count_documents({"message_type": "text"})
                    stats[f"{collection_name}_text"] = text_jobs
                
                # 🆕 NEW: Automation campaigns stats
                elif collection_name == "automation_campaigns":
                    active = await db[collection_name].count_documents({"status": "active"})
                    stats[f"{collection_name}_active"] = active
                    
                    paused = await db[collection_name].count_documents({"status": "paused"})
                    stats[f"{collection_name}_paused"] = paused
                    
                    whatsapp = await db[collection_name].count_documents({"campaign_type": "whatsapp"})
                    stats[f"{collection_name}_whatsapp"] = whatsapp
                    
                    email = await db[collection_name].count_documents({"campaign_type": "email"})
                    stats[f"{collection_name}_email"] = email

                elif collection_name == "campaign_tracking":
                    pending = await db[collection_name].count_documents({"status": "pending"})
                    stats[f"{collection_name}_pending"] = pending
                    
                    completed = await db[collection_name].count_documents({"status": "completed"})
                    stats[f"{collection_name}_completed"] = completed

                elif collection_name == "notification_history":
                    # Notification type breakdown
                    whatsapp_notifications = await db[collection_name].count_documents({"notification_type": "new_whatsapp_message"})
                    stats[f"{collection_name}_whatsapp"] = whatsapp_notifications
                    
                    system_notifications = await db[collection_name].count_documents({"notification_type": "system_notification"})
                    stats[f"{collection_name}_system"] = system_notifications
                    
                    # Read status tracking
                    unread_notifications = await db[collection_name].count_documents({"read_at": None})
                    stats[f"{collection_name}_unread"] = unread_notifications    
                # Stats for course levels and sources
                elif collection_name == "course_levels":
                    active_count = await db[collection_name].count_documents({"is_active": True})
                    stats[f"{collection_name}_active"] = active_count
                    
                elif collection_name == "sources":
                    active_count = await db[collection_name].count_documents({"is_active": True})
                    stats[f"{collection_name}_active"] = active_count
                    
            except Exception as collection_error:
                stats[collection_name] = 0
                logger.debug(f"Collection {collection_name} not found or error: {collection_error}")
        
        stats["total_documents"] = total_documents
        stats["collections_found"] = len([k for k, v in stats.items() if v > 0 and not k.startswith("total")])
        
        return stats
        
    except Exception as e:
        logger.error(f"Error getting collection stats: {e}")
        return {"error": str(e)}

async def get_index_stats():
    """Get index statistics for performance monitoring including WhatsApp and Bulk WhatsApp collections"""
    try:
        db = get_database()
        
        collections = ["users", "leads", "lead_tasks", "lead_activities", "course_levels", "sources", "whatsapp_messages", "bulk_whatsapp_jobs", "notification_history"]  # Added bulk WhatsApp collection
        index_stats = {}
        
        for collection_name in collections:
            try:
                collection = db[collection_name]
                indexes = await collection.list_indexes().to_list(None)
                index_stats[collection_name] = {
                    "index_count": len(indexes),
                    "indexes": [idx.get("name", "unknown") for idx in indexes]
                }
            except Exception as e:
                index_stats[collection_name] = {"error": str(e)}
        
        return index_stats
        
    except Exception as e:
        logger.error(f"Error getting index stats: {e}")
        return {"error": str(e)}

# Database lifecycle management
async def init_database():
    """Initialize database connection and indexes"""
    await connect_to_mongo()
    await create_indexes()
    
    # Log database status
    stats = await get_collection_stats()
    logger.info(f"📊 Database initialized with {stats.get('collections_found', 0)} collections")
    logger.info(f"📈 Total documents: {stats.get('total_documents', 0)}")
    
    if stats.get('leads', 0) > 0:
        logger.info(f"🎯 Leads: {stats.get('leads', 0)} total, {stats.get('leads_multi_assigned', 0)} multi-assigned, {stats.get('leads_unassigned', 0)} unassigned")
        logger.info(f"📱 WhatsApp: {stats.get('leads_with_whatsapp', 0)} leads with messages, {stats.get('leads_unread_whatsapp', 0)} with unread")
        logger.info(f"📞 Bulk Ready: {stats.get('leads_with_phone', 0)} leads with phone numbers")
    
    if stats.get('users', 0) > 0:
        logger.info(f"👥 Users: {stats.get('users', 0)} total, {stats.get('users_active', 0)} active")
    
    # Course levels and sources stats
    if stats.get('course_levels', 0) > 0:
        logger.info(f"📚 Course Levels: {stats.get('course_levels', 0)} total, {stats.get('course_levels_active', 0)} active")
    
    if stats.get('sources', 0) > 0:
        logger.info(f"📍 Sources: {stats.get('sources', 0)} total, {stats.get('sources_active', 0)} active")
    
    # WhatsApp messages stats
    if stats.get('whatsapp_messages', 0) > 0:
        logger.info(f"💬 WhatsApp: {stats.get('whatsapp_messages', 0)} total messages, {stats.get('whatsapp_messages_incoming', 0)} incoming, {stats.get('whatsapp_messages_outgoing', 0)} outgoing")
        if stats.get('whatsapp_messages_unread', 0) > 0:
            logger.info(f"📬 Unread WhatsApp messages: {stats.get('whatsapp_messages_unread', 0)}")
    
    # 🆕 NEW: Bulk WhatsApp jobs stats
    if stats.get('bulk_whatsapp_jobs', 0) > 0:
        logger.info(f"📤 Bulk WhatsApp: {stats.get('bulk_whatsapp_jobs', 0)} total jobs")
        logger.info(f"   ├─ Pending: {stats.get('bulk_whatsapp_jobs_pending', 0)}, Processing: {stats.get('bulk_whatsapp_jobs_processing', 0)}")
        logger.info(f"   ├─ Completed: {stats.get('bulk_whatsapp_jobs_completed', 0)}, Failed: {stats.get('bulk_whatsapp_jobs_failed', 0)}")
        logger.info(f"   └─ Scheduled: {stats.get('bulk_whatsapp_jobs_scheduled', 0)}, Immediate: {stats.get('bulk_whatsapp_jobs_immediate', 0)}")
    
    if stats.get('automation_campaigns', 0) > 0:
        logger.info(f"🤖 Campaigns: {stats.get('automation_campaigns', 0)} total")
        logger.info(f"   ├─ Active: {stats.get('automation_campaigns_active', 0)}, Paused: {stats.get('automation_campaigns_paused', 0)}")
        logger.info(f"   └─ WhatsApp: {stats.get('automation_campaigns_whatsapp', 0)}, Email: {stats.get('automation_campaigns_email', 0)}")

async def cleanup_database():
    """Cleanup database resources"""
    try:
        # Close any open cursors or connections
        await close_mongo_connection()
        logger.info("🧹 Database cleanup completed")
    except Exception as e:
        logger.error(f"Error during database cleanup: {e}")

# Health check functions
async def test_database_connection():
    """Test database operations and performance"""
    try:
        db = get_database()
        
        # Test basic operations
        ping_result = await db.command("ping")
        logger.info(f"✅ Database ping successful: {ping_result}")
        
        # Test collections access
        collections = await db.list_collection_names()
        logger.info(f"📂 Available collections: {len(collections)}")
        
        # Test index efficiency on leads collection (most critical)
        if "leads" in collections:
            explain_result = await db.leads.find({"assigned_to": {"$ne": None}}).explain()
            logger.info("🔍 Lead query performance test completed")
        
        # Test WhatsApp collection if exists
        if "whatsapp_messages" in collections:
            logger.info("📱 WhatsApp messages collection available")
        
        # 🆕 NEW: Test bulk WhatsApp collection if exists
        if "bulk_whatsapp_jobs" in collections:
            logger.info("📤 Bulk WhatsApp jobs collection available")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Database test failed: {e}")
        return False

# Export functions
__all__ = [
    "get_database",
    "connect_to_mongo", 
    "close_mongo_connection",
    "create_indexes",
    "get_collection_stats",
    "get_index_stats",
    "init_database",
    "cleanup_database",
    "test_database_connection"
]