# app/config/settings.py - Updated with RBAC, Email (ZeptoMail), Tata Tele, and Skillang Integration configuration
from pydantic_settings import BaseSettings
from typing import List
import secrets
import json
import os
from dotenv import load_dotenv
from typing import Optional

# Load .env file before anything else
load_dotenv(override=True)

class Settings(BaseSettings):
    # App Config
    app_name: str = "LeadG CRM API"
    version: str = "2.0.0"  # 🆕 RBAC Version
    debug: bool = True
    
    # Security
    secret_key: str = "your-secret-key-here"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    
    # ============================================================================
    # 🆕 RBAC - SUPER ADMIN CONFIGURATION
    # ============================================================================
    super_admin_email: str = "superadmin@leadg.com"
    super_admin_password: str = "SecurePassword123!"
    super_admin_first_name: str = "Super"
    super_admin_last_name: str = "Admin"
    
    # ============================================================================
    # 🆕 RBAC - ROLE MANAGEMENT CONFIGURATION
    # ============================================================================
    max_custom_roles: int = 50
    min_users_per_role: int = 0
    allow_role_deletion: bool = True
    default_new_user_role: str = "user"
    
    # ============================================================================
    # 🆕 RBAC - PERMISSION SYSTEM CONFIGURATION
    # ============================================================================
    enable_permission_overrides: bool = True
    permission_cache_ttl: int = 3600  # 1 hour in seconds
    enable_permission_audit: bool = True
    
    # ============================================================================
    # 🆕 RBAC - TEAM HIERARCHY CONFIGURATION
    # ============================================================================
    max_hierarchy_depth: int = 5
    enable_nested_team_view: bool = True
    allow_nested_team_access: bool = True
    
    # ============================================================================
    # 🆕 RBAC - MIGRATION & INITIALIZATION
    # ============================================================================
    auto_create_default_roles: bool = True
    auto_migrate_existing_users: bool = True
    auto_seed_permissions: bool = True
    
    # MongoDB Atlas Configuration
    mongodb_url: str = "mongodb+srv://username:password@cluster.mongodb.net/database?retryWrites=true&w=majority"
    database_name: str = "CRM_permission"  # 🆕 Changed to new RBAC database
    
    # MongoDB Atlas Connection Options
    mongodb_max_pool_size: int = 10
    mongodb_min_pool_size: int = 1
    mongodb_max_idle_time_ms: int = 30000
    mongodb_server_selection_timeout_ms: int = 5000
    mongodb_connect_timeout_ms: int = 10000
    mongodb_socket_timeout_ms: int = 10000
    
    # WhatsApp Business API Configuration
    whatsapp_base_url: str = "https://wa.mydreamstechnology.in/api"
    whatsapp_license_number: str = ""
    whatsapp_api_key: str = ""
    
    # CMS Configuration
    cms_base_url: str = "https://cms.skillang.com/api"
    cms_templates_endpoint: str = "whatsapp-templates?populate=*"
    
    # 🆕 EMAIL CMS CONFIGURATION
    email_templates_endpoint: str = "mail-templates"  # Email-specific endpoint
    
    # 🆕 EMAIL CONFIGURATION (ZEPTOMAIL)
    zeptomail_url: str = "api.zeptomail.in/"
    zeptomail_token: str = ""
    max_bulk_recipients: int = 500
    email_rate_limit: int = 100
    min_schedule_minutes: int = 5
    max_schedule_days: int = 30

    # 🆕 SKILLANG INTEGRATION SETTINGS
    skillang_integration_enabled: bool = True
    skillang_api_key: str = "skillang-secure-api-key-2024"
    system_user_email: str = "system@skillang.com"
    skillang_frontend_domain: str = "https://skillang.com"

    # 🆕 NEW: Tata Tele Integration Settings
    tata_api_base_url: str = "https://api-smartflo.tatateleservices.com"
    tata_email: Optional[str] = None
    tata_password: Optional[str] = None
    tata_api_timeout: int = 30
    tata_api_retries: int = 3
    tata_encryption_key: Optional[str] = None
    tata_support_api_key: Optional[str] = None
    
    # Call configuration
    default_call_timeout: int = 300
    max_concurrent_calls: int = 50
    call_log_retention_days: int = 365
    max_sync_batch_size: int = 10
    
    # Webhook configuration
    tata_webhook_secret: Optional[str] = None
    tata_webhook_url: Optional[str] = None
    
    # Rate Limiting
    rate_limit_requests: int = 100
    rate_limit_window: int = 60
    
    # Email Configuration (SMTP - keep existing for backward compatibility)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@leadg.com"
    smtp_from_name: str = "LeadG CRM"

    # Facebook Leads Integration Configuration
    facebook_app_id: str = ""
    facebook_app_secret: str = ""
    facebook_page_access_token: str = ""
    facebook_page_id: str = ""
    facebook_api_version: str = "v18.0"
    facebook_webhook_verify_token: str = "leadg_webhook_2024_secure"

    # Facebook API URLs
    facebook_graph_api_url: str = "https://graph.facebook.com"
    
    # File Upload Configuration
    max_file_size: int = 10485760  # 10MB
    allowed_file_types: List[str] = ["image/jpeg", "image/png", "application/pdf", "text/csv"]
    upload_directory: str = "uploads/"
    
    # Redis Configuration (optional)
    redis_url: str = "redis://localhost:6379"
    redis_db: int = 0
    
    # Logging Configuration
    log_level: str = "INFO"
    log_file: str = "logs/app.log"
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "allow"
    
    def __init__(self, **kwargs):
        # Reload .env again to ensure loading
        load_dotenv(override=True)
        
        super().__init__(**kwargs)
        
        # Override with environment variables if they exist
        if os.getenv("SECRET_KEY"):
            self.secret_key = os.getenv("SECRET_KEY")
        if os.getenv("DEBUG"):
            self.debug = os.getenv("DEBUG").lower() == "true"
        
        # ============================================================================
        # 🆕 RBAC ENVIRONMENT VARIABLES
        # ============================================================================
        
        # Super Admin Configuration
        if os.getenv("SUPER_ADMIN_EMAIL"):
            self.super_admin_email = os.getenv("SUPER_ADMIN_EMAIL")
        if os.getenv("SUPER_ADMIN_PASSWORD"):
            self.super_admin_password = os.getenv("SUPER_ADMIN_PASSWORD")
        if os.getenv("SUPER_ADMIN_FIRST_NAME"):
            self.super_admin_first_name = os.getenv("SUPER_ADMIN_FIRST_NAME")
        if os.getenv("SUPER_ADMIN_LAST_NAME"):
            self.super_admin_last_name = os.getenv("SUPER_ADMIN_LAST_NAME")
        
        # Role Management Configuration
        if os.getenv("MAX_CUSTOM_ROLES"):
            self.max_custom_roles = int(os.getenv("MAX_CUSTOM_ROLES"))
        if os.getenv("MIN_USERS_PER_ROLE"):
            self.min_users_per_role = int(os.getenv("MIN_USERS_PER_ROLE"))
        if os.getenv("ALLOW_ROLE_DELETION"):
            self.allow_role_deletion = os.getenv("ALLOW_ROLE_DELETION").lower() == "true"
        if os.getenv("DEFAULT_NEW_USER_ROLE"):
            self.default_new_user_role = os.getenv("DEFAULT_NEW_USER_ROLE")
        
        # Permission System Configuration
        if os.getenv("ENABLE_PERMISSION_OVERRIDES"):
            self.enable_permission_overrides = os.getenv("ENABLE_PERMISSION_OVERRIDES").lower() == "true"
        if os.getenv("PERMISSION_CACHE_TTL"):
            self.permission_cache_ttl = int(os.getenv("PERMISSION_CACHE_TTL"))
        if os.getenv("ENABLE_PERMISSION_AUDIT"):
            self.enable_permission_audit = os.getenv("ENABLE_PERMISSION_AUDIT").lower() == "true"
        
        # Team Hierarchy Configuration
        if os.getenv("MAX_HIERARCHY_DEPTH"):
            self.max_hierarchy_depth = int(os.getenv("MAX_HIERARCHY_DEPTH"))
        if os.getenv("ENABLE_NESTED_TEAM_VIEW"):
            self.enable_nested_team_view = os.getenv("ENABLE_NESTED_TEAM_VIEW").lower() == "true"
        if os.getenv("ALLOW_NESTED_TEAM_ACCESS"):
            self.allow_nested_team_access = os.getenv("ALLOW_NESTED_TEAM_ACCESS").lower() == "true"
        
        # Migration & Initialization Configuration
        if os.getenv("AUTO_CREATE_DEFAULT_ROLES"):
            self.auto_create_default_roles = os.getenv("AUTO_CREATE_DEFAULT_ROLES").lower() == "true"
        if os.getenv("AUTO_MIGRATE_EXISTING_USERS"):
            self.auto_migrate_existing_users = os.getenv("AUTO_MIGRATE_EXISTING_USERS").lower() == "true"
        if os.getenv("AUTO_SEED_PERMISSIONS"):
            self.auto_seed_permissions = os.getenv("AUTO_SEED_PERMISSIONS").lower() == "true"
        
        # MongoDB Atlas environment variable handling
        if os.getenv("MONGODB_URL"):
            self.mongodb_url = os.getenv("MONGODB_URL")
        if os.getenv("DATABASE_NAME"):
            self.database_name = os.getenv("DATABASE_NAME")
        if os.getenv("MONGODB_MAX_POOL_SIZE"):
            self.mongodb_max_pool_size = int(os.getenv("MONGODB_MAX_POOL_SIZE"))
        if os.getenv("MONGODB_MIN_POOL_SIZE"):
            self.mongodb_min_pool_size = int(os.getenv("MONGODB_MIN_POOL_SIZE"))
        if os.getenv("MONGODB_MAX_IDLE_TIME_MS"):
            self.mongodb_max_idle_time_ms = int(os.getenv("MONGODB_MAX_IDLE_TIME_MS"))
        if os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS"):
            self.mongodb_server_selection_timeout_ms = int(os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS"))
        
        # WhatsApp configuration
        if os.getenv("WHATSAPP_BASE_URL"):
            self.whatsapp_base_url = os.getenv("WHATSAPP_BASE_URL")
        if os.getenv("WHATSAPP_LICENSE_NUMBER"):
            self.whatsapp_license_number = os.getenv("WHATSAPP_LICENSE_NUMBER")
        if os.getenv("WHATSAPP_API_KEY"):
            self.whatsapp_api_key = os.getenv("WHATSAPP_API_KEY")
        
        # CMS configuration
        if os.getenv("CMS_BASE_URL"):
            self.cms_base_url = os.getenv("CMS_BASE_URL")
        if os.getenv("CMS_TEMPLATES_ENDPOINT"):
            self.cms_templates_endpoint = os.getenv("CMS_TEMPLATES_ENDPOINT")
        
        # 🆕 EMAIL CMS CONFIGURATION
        if os.getenv("EMAIL_TEMPLATES_ENDPOINT"):
            self.email_templates_endpoint = os.getenv("EMAIL_TEMPLATES_ENDPOINT")
        
        # 🆕 ZEPTOMAIL EMAIL CONFIGURATION
        if os.getenv("ZEPTOMAIL_URL"):
            self.zeptomail_url = os.getenv("ZEPTOMAIL_URL")
        if os.getenv("ZEPTOMAIL_TOKEN"):
            self.zeptomail_token = os.getenv("ZEPTOMAIL_TOKEN")
        if os.getenv("MAX_BULK_RECIPIENTS"):
            self.max_bulk_recipients = int(os.getenv("MAX_BULK_RECIPIENTS"))
        if os.getenv("EMAIL_RATE_LIMIT"):
            self.email_rate_limit = int(os.getenv("EMAIL_RATE_LIMIT"))
        if os.getenv("MIN_SCHEDULE_MINUTES"):
            self.min_schedule_minutes = int(os.getenv("MIN_SCHEDULE_MINUTES"))
        if os.getenv("MAX_SCHEDULE_DAYS"):
            self.max_schedule_days = int(os.getenv("MAX_SCHEDULE_DAYS"))

        # 🆕 SKILLANG INTEGRATION ENVIRONMENT VARIABLES
        if os.getenv("SKILLANG_INTEGRATION_ENABLED"):
            self.skillang_integration_enabled = os.getenv("SKILLANG_INTEGRATION_ENABLED").lower() == "true"
        if os.getenv("SKILLANG_API_KEY"):
            self.skillang_api_key = os.getenv("SKILLANG_API_KEY")
        if os.getenv("SYSTEM_USER_EMAIL"):
            self.system_user_email = os.getenv("SYSTEM_USER_EMAIL")
        if os.getenv("SKILLANG_FRONTEND_DOMAIN"):
            self.skillang_frontend_domain = os.getenv("SKILLANG_FRONTEND_DOMAIN")
        
        # 🆕 NEW: TATA TELE ENVIRONMENT VARIABLES
        if os.getenv("TATA_API_BASE_URL"):
            self.tata_api_base_url = os.getenv("TATA_API_BASE_URL")
        if os.getenv("TATA_EMAIL"):
            self.tata_email = os.getenv("TATA_EMAIL")
        if os.getenv("TATA_PASSWORD"):
            self.tata_password = os.getenv("TATA_PASSWORD")
        if os.getenv("TATA_API_TIMEOUT"):
            self.tata_api_timeout = int(os.getenv("TATA_API_TIMEOUT"))
        if os.getenv("TATA_API_RETRIES"):
            self.tata_api_retries = int(os.getenv("TATA_API_RETRIES"))
        if os.getenv("TATA_ENCRYPTION_KEY"):
            self.tata_encryption_key = os.getenv("TATA_ENCRYPTION_KEY")
        if os.getenv("TATA_SUPPORT_API_KEY"):
            self.tata_support_api_key = os.getenv("TATA_SUPPORT_API_KEY")
        
        # Call configuration
        if os.getenv("DEFAULT_CALL_TIMEOUT"):
            self.default_call_timeout = int(os.getenv("DEFAULT_CALL_TIMEOUT"))
        if os.getenv("MAX_CONCURRENT_CALLS"):
            self.max_concurrent_calls = int(os.getenv("MAX_CONCURRENT_CALLS"))
        if os.getenv("CALL_LOG_RETENTION_DAYS"):
            self.call_log_retention_days = int(os.getenv("CALL_LOG_RETENTION_DAYS"))
        if os.getenv("MAX_SYNC_BATCH_SIZE"):
            self.max_sync_batch_size = int(os.getenv("MAX_SYNC_BATCH_SIZE"))
        
        # Webhook configuration
        if os.getenv("TATA_WEBHOOK_SECRET"):
            self.tata_webhook_secret = os.getenv("TATA_WEBHOOK_SECRET")
        if os.getenv("TATA_WEBHOOK_URL"):
            self.tata_webhook_url = os.getenv("TATA_WEBHOOK_URL")
        
        # Email configuration (existing SMTP)
        if os.getenv("SMTP_HOST"):
            self.smtp_host = os.getenv("SMTP_HOST")
        if os.getenv("SMTP_PORT"):
            self.smtp_port = int(os.getenv("SMTP_PORT"))
        if os.getenv("SMTP_USERNAME"):
            self.smtp_username = os.getenv("SMTP_USERNAME")
        if os.getenv("SMTP_PASSWORD"):
            self.smtp_password = os.getenv("SMTP_PASSWORD")
        if os.getenv("SMTP_FROM_EMAIL"):
            self.smtp_from_email = os.getenv("SMTP_FROM_EMAIL")
        if os.getenv("SMTP_FROM_NAME"):
            self.smtp_from_name = os.getenv("SMTP_FROM_NAME")
        
        # File upload configuration
        if os.getenv("MAX_FILE_SIZE"):
            self.max_file_size = int(os.getenv("MAX_FILE_SIZE"))
        if os.getenv("UPLOAD_DIRECTORY"):
            self.upload_directory = os.getenv("UPLOAD_DIRECTORY")
        if os.getenv("ALLOWED_FILE_TYPES"):
            try:
                self.allowed_file_types = json.loads(os.getenv("ALLOWED_FILE_TYPES"))
            except:
                pass
        
        # Server configuration
        if os.getenv("HOST"):
            self.host = os.getenv("HOST")
        if os.getenv("PORT"):
            self.port = int(os.getenv("PORT"))
        
        # Rate limiting
        if os.getenv("RATE_LIMIT_REQUESTS"):
            self.rate_limit_requests = int(os.getenv("RATE_LIMIT_REQUESTS"))
        if os.getenv("RATE_LIMIT_WINDOW"):
            self.rate_limit_window = int(os.getenv("RATE_LIMIT_WINDOW"))
        
        # Redis configuration
        if os.getenv("REDIS_URL"):
            self.redis_url = os.getenv("REDIS_URL")
        if os.getenv("REDIS_DB"):
            self.redis_db = int(os.getenv("REDIS_DB"))
        
        # Logging configuration
        if os.getenv("LOG_LEVEL"):
            self.log_level = os.getenv("LOG_LEVEL")
        if os.getenv("LOG_FILE"):
            self.log_file = os.getenv("LOG_FILE")
    
    def get_allowed_origins(self) -> List[str]:
        """Get allowed origins from env or default"""
        origins_str = os.getenv("ALLOWED_ORIGINS", '["http://localhost:3000", "http://127.0.0.1:3000"]')
        try:
            return json.loads(origins_str)
        except:
            return [origin.strip() for origin in origins_str.split(",")]
    
    def get_mongodb_connection_options(self) -> dict:
        """Get MongoDB Atlas connection options"""
        return {
            "maxPoolSize": self.mongodb_max_pool_size,
            "minPoolSize": self.mongodb_min_pool_size,
            "maxIdleTimeMS": self.mongodb_max_idle_time_ms,
            "serverSelectionTimeoutMS": self.mongodb_server_selection_timeout_ms,
            "connectTimeoutMS": self.mongodb_connect_timeout_ms,
            "socketTimeoutMS": self.mongodb_socket_timeout_ms,
            "retryWrites": True,
            "w": "majority"
        }
    
    def is_atlas_connection(self) -> bool:
        """Check if using MongoDB Atlas"""
        return "mongodb+srv://" in self.mongodb_url or "mongodb.net" in self.mongodb_url
    
    def get_upload_path(self) -> str:
        """Get full upload directory path"""
        if not os.path.exists(self.upload_directory):
            os.makedirs(self.upload_directory, exist_ok=True)
        return self.upload_directory
    
    def is_email_configured(self) -> bool:
        """Check if email is properly configured"""
        return bool(self.smtp_username) and bool(self.smtp_password)
    
    # 🆕 NEW: ZeptoMail configuration helper
    def is_zeptomail_configured(self) -> bool:
        """Check if ZeptoMail is properly configured"""
        return bool(self.zeptomail_token) and bool(self.zeptomail_url)
    
    # 🆕 NEW: Get ZeptoMail configuration
    def get_zeptomail_config(self) -> dict:
        """Get ZeptoMail configuration dictionary"""
        return {
            "url": self.zeptomail_url,
            "token": self.zeptomail_token,
            "max_bulk_recipients": self.max_bulk_recipients,
            "rate_limit": self.email_rate_limit,
            "min_schedule_minutes": self.min_schedule_minutes,
            "max_schedule_days": self.max_schedule_days
        }

    # 🆕 NEW: Skillang integration configuration helper
    def is_skillang_configured(self) -> bool:
        """Check if Skillang integration is properly configured"""
        return bool(self.skillang_integration_enabled) and bool(self.skillang_api_key)

    def get_skillang_config(self) -> dict:
        """Get Skillang configuration dictionary"""
        return {
            "integration_enabled": self.skillang_integration_enabled,
            "api_key": self.skillang_api_key,
            "system_user_email": self.system_user_email,
            "frontend_domain": self.skillang_frontend_domain
        }
    
    # 🆕 NEW: Tata Tele configuration helper
    def is_tata_configured(self) -> bool:
        """Check if Tata Tele integration is properly configured"""
        return bool(
            self.tata_email and 
            self.tata_password and 
            self.tata_encryption_key
        )
    
    # 🆕 NEW: Get Tata Tele configuration
    def get_tata_config(self) -> dict:
        """Get Tata Tele configuration dictionary"""
        return {
            "api_base_url": self.tata_api_base_url,
            "email": self.tata_email,
            "password": self.tata_password,
            "api_timeout": self.tata_api_timeout,
            "api_retries": self.tata_api_retries,
            "encryption_key": self.tata_encryption_key,
            "support_api_key": self.tata_support_api_key,
            "default_call_timeout": self.default_call_timeout,
            "max_concurrent_calls": self.max_concurrent_calls,
            "call_log_retention_days": self.call_log_retention_days,
            "max_sync_batch_size": self.max_sync_batch_size,
            "webhook_secret": self.tata_webhook_secret,
            "webhook_url": self.tata_webhook_url
        }
    
    def is_whatsapp_configured(self) -> bool:
        """Check if WhatsApp is properly configured"""
        return bool(self.whatsapp_license_number) and bool(self.whatsapp_api_key)
    
    def get_whatsapp_config(self) -> dict:
        """Get WhatsApp configuration dictionary"""
        return {
            "base_url": self.whatsapp_base_url,
            "license_number": self.whatsapp_license_number,
            "api_key": self.whatsapp_api_key
        }
    
    def get_cms_config(self) -> dict:
        """Get CMS configuration dictionary"""
        return {
            "base_url": self.cms_base_url,
            "templates_endpoint": self.cms_templates_endpoint
        }
    
    # ============================================================================
    # 🆕 RBAC CONFIGURATION HELPERS
    # ============================================================================
    
    def get_rbac_config(self) -> dict:
        """Get complete RBAC configuration dictionary"""
        return {
            # Super Admin
            "super_admin_email": self.super_admin_email,
            "super_admin_password": self.super_admin_password,
            "super_admin_first_name": self.super_admin_first_name,
            "super_admin_last_name": self.super_admin_last_name,
            
            # Role Management
            "max_custom_roles": self.max_custom_roles,
            "min_users_per_role": self.min_users_per_role,
            "allow_role_deletion": self.allow_role_deletion,
            "default_new_user_role": self.default_new_user_role,
            
            # Permission System
            "enable_permission_overrides": self.enable_permission_overrides,
            "permission_cache_ttl": self.permission_cache_ttl,
            "enable_permission_audit": self.enable_permission_audit,
            
            # Team Hierarchy
            "max_hierarchy_depth": self.max_hierarchy_depth,
            "enable_nested_team_view": self.enable_nested_team_view,
            "allow_nested_team_access": self.allow_nested_team_access,
            
            # Initialization
            "auto_create_default_roles": self.auto_create_default_roles,
            "auto_migrate_existing_users": self.auto_migrate_existing_users,
            "auto_seed_permissions": self.auto_seed_permissions
        }
    
    def is_rbac_enabled(self) -> bool:
        """Check if RBAC is properly configured"""
        return bool(
            self.super_admin_email and 
            self.super_admin_password and
            self.max_custom_roles > 0
        )
    
    def should_initialize_rbac(self) -> bool:
        """Check if RBAC should be initialized on startup"""
        return (
            self.auto_create_default_roles or 
            self.auto_seed_permissions or 
            self.auto_migrate_existing_users
        )

# Global settings instance
settings = Settings()

# 🆕 CRITICAL: Add the missing get_settings function
def get_settings() -> Settings:
    """Get global settings instance - Required by Tata services"""
    return settings