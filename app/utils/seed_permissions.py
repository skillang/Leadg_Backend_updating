

import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)


# ========================================
# PERMISSION DEFINITIONS (69 Total)
# ========================================

def get_all_permissions() -> List[Dict[str, Any]]:
    """
    Returns all 69 permission definitions
    Organized by 9 categories
    """
    
    permissions = []
    
    # ========================================
    # CATEGORY 1: LEAD MANAGEMENT (14 permissions)
    # ========================================
    
    lead_permissions = [
        {
            "code": "lead.create",
            "name": "Create Leads",
            "description": "Can create new leads",
            "category": "lead_management",
            "resource": "lead",
            "action": "create",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Lead Operations", "icon": "plus"}
        },
        {
            "code": "lead.read_own",
            "name": "Read Own Leads",
            "description": "Can view own leads only",
            "category": "lead_management",
            "resource": "lead",
            "action": "read",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Lead Operations", "icon": "eye"}
        },
        {
            "code": "lead.read_team",
            "name": "Read Team Leads",
            "description": "Can view team members' leads",
            "category": "lead_management",
            "resource": "lead",
            "action": "read",
            "scope": "team",
            "is_system": True,
            "requires_permissions": ["lead.read_own"],
            "metadata": {"ui_group": "Lead Operations", "icon": "users"}
        },
        {
            "code": "lead.read_all",
            "name": "Read All Leads",
            "description": "Can view all leads in the system",
            "category": "lead_management",
            "resource": "lead",
            "action": "read",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["lead.read_own"],
            "metadata": {"ui_group": "Lead Operations", "icon": "database"}
        },
        {
            "code": "lead.update_own",
            "name": "Update Own Leads",
            "description": "Can edit own leads",
            "category": "lead_management",
            "resource": "lead",
            "action": "update",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["lead.read_own"],
            "metadata": {"ui_group": "Lead Operations", "icon": "edit"}
        },
        {
            "code": "lead.update_team",
            "name": "Update Team Leads",
            "description": "Can edit team members' leads",
            "category": "lead_management",
            "resource": "lead",
            "action": "update",
            "scope": "team",
            "is_system": True,
            "requires_permissions": ["lead.read_team", "lead.update_own"],
            "metadata": {"ui_group": "Lead Operations"}
        },
        {
            "code": "lead.update_all",
            "name": "Update All Leads",
            "description": "Can edit any lead in the system",
            "category": "lead_management",
            "resource": "lead",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["lead.read_all", "lead.update_own"],
            "metadata": {"ui_group": "Lead Operations"}
        },
        {
            "code": "lead.delete_own",
            "name": "Delete Own Leads",
            "description": "Can delete own leads",
            "category": "lead_management",
            "resource": "lead",
            "action": "delete",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["lead.read_own"],
            "metadata": {"ui_group": "Lead Operations", "icon": "trash", "dangerous": True}
        },
        {
            "code": "lead.delete_all",
            "name": "Delete All Leads",
            "description": "Can delete any lead in the system",
            "category": "lead_management",
            "resource": "lead",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["lead.read_all"],
            "metadata": {"ui_group": "Lead Operations", "icon": "trash", "dangerous": True}
        },
        {
            "code": "lead.assign",
            "name": "Assign Leads",
            "description": "Can assign leads to other users",
            "category": "lead_management",
            "resource": "lead",
            "action": "assign",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["lead.read_all"],
            "metadata": {"ui_group": "Lead Operations", "icon": "user-plus"}
        },
        {
            "code": "lead.bulk_create",
            "name": "Bulk Create Leads",
            "description": "Can create multiple leads at once via import/bulk",
            "category": "lead_management",
            "resource": "lead",
            "action": "bulk_create",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["lead.create"],
            "metadata": {"ui_group": "Lead Operations", "icon": "upload"}
        },
        {
            "code": "lead.export",
            "name": "Export Leads",
            "description": "Can export lead data to CSV/Excel",
            "category": "lead_management",
            "resource": "lead",
            "action": "export",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Lead Operations", "icon": "download"}
        },
        {
            "code": "lead.change_status",
            "name": "Change Lead Status",
            "description": "Can change lead status/stage",
            "category": "lead_management",
            "resource": "lead",
            "action": "change_status",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["lead.update_own"],
            "metadata": {"ui_group": "Lead Operations"}
        },
        {
            "code": "lead.view_history",
            "name": "View Lead History",
            "description": "Can view lead activity history and timeline",
            "category": "lead_management",
            "resource": "lead",
            "action": "view_history",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["lead.read_own"],
            "metadata": {"ui_group": "Lead Operations", "icon": "clock"}
        }
    ]
    
    # ========================================
    # CATEGORY 2: CONTACT MANAGEMENT (7 permissions)
    # ========================================
    
    contact_permissions = [
        {
            "code": "contact.create",
            "name": "Create Contacts",
            "description": "Can create new contacts",
            "category": "contact_management",
            "resource": "contact",
            "action": "create",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Contact Operations"}
        },
        {
            "code": "contact.read_own",
            "name": "Read Own Contacts",
            "description": "Can view own contacts",
            "category": "contact_management",
            "resource": "contact",
            "action": "read",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Contact Operations"}
        },
        {
            "code": "contact.read_all",
            "name": "Read All Contacts",
            "description": "Can view all contacts in the system",
            "category": "contact_management",
            "resource": "contact",
            "action": "read",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["contact.read_own"],
            "metadata": {"ui_group": "Contact Operations"}
        },
        {
            "code": "contact.update_own",
            "name": "Update Own Contacts",
            "description": "Can edit own contacts",
            "category": "contact_management",
            "resource": "contact",
            "action": "update",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["contact.read_own"],
            "metadata": {"ui_group": "Contact Operations"}
        },
        {
            "code": "contact.update_all",
            "name": "Update All Contacts",
            "description": "Can edit any contact in the system",
            "category": "contact_management",
            "resource": "contact",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["contact.read_all"],
            "metadata": {"ui_group": "Contact Operations"}
        },
        {
            "code": "contact.delete",
            "name": "Delete Contacts",
            "description": "Can delete contacts",
            "category": "contact_management",
            "resource": "contact",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["contact.read_all"],
            "metadata": {"ui_group": "Contact Operations", "dangerous": True}
        },
        {
            "code": "contact.export",
            "name": "Export Contacts",
            "description": "Can export contact data",
            "category": "contact_management",
            "resource": "contact",
            "action": "export",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Contact Operations"}
        }
    ]
    
    # ========================================
    # CATEGORY 3: TASK MANAGEMENT (9 permissions)
    # ========================================
    
    task_permissions = [
        {
            "code": "task.create",
            "name": "Create Tasks",
            "description": "Can create new tasks",
            "category": "task_management",
            "resource": "task",
            "action": "create",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Task Operations"}
        },
        {
            "code": "task.read_own",
            "name": "Read Own Tasks",
            "description": "Can view own tasks",
            "category": "task_management",
            "resource": "task",
            "action": "read",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Task Operations"}
        },
        {
            "code": "task.read_team",
            "name": "Read Team Tasks",
            "description": "Can view team members' tasks",
            "category": "task_management",
            "resource": "task",
            "action": "read",
            "scope": "team",
            "is_system": True,
            "requires_permissions": ["task.read_own"],
            "metadata": {"ui_group": "Task Operations"}
        },
        {
            "code": "task.read_all",
            "name": "Read All Tasks",
            "description": "Can view all tasks in the system",
            "category": "task_management",
            "resource": "task",
            "action": "read",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["task.read_own"],
            "metadata": {"ui_group": "Task Operations"}
        },
        {
            "code": "task.update_own",
            "name": "Update Own Tasks",
            "description": "Can edit own tasks",
            "category": "task_management",
            "resource": "task",
            "action": "update",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["task.read_own"],
            "metadata": {"ui_group": "Task Operations"}
        },
        {
            "code": "task.update_all",
            "name": "Update All Tasks",
            "description": "Can edit any task in the system",
            "category": "task_management",
            "resource": "task",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["task.read_all"],
            "metadata": {"ui_group": "Task Operations"}
        },
        {
            "code": "task.delete",
            "name": "Delete Tasks",
            "description": "Can delete tasks",
            "category": "task_management",
            "resource": "task",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["task.read_all"],
            "metadata": {"ui_group": "Task Operations", "dangerous": True}
        },
        {
            "code": "task.assign",
            "name": "Assign Tasks",
            "description": "Can assign tasks to other users",
            "category": "task_management",
            "resource": "task",
            "action": "assign",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["task.read_all"],
            "metadata": {"ui_group": "Task Operations"}
        },
        {
            "code": "task.change_priority",
            "name": "Change Task Priority",
            "description": "Can change task priority levels",
            "category": "task_management",
            "resource": "task",
            "action": "change_priority",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["task.update_own"],
            "metadata": {"ui_group": "Task Operations"}
        }
    ]
    
    # ========================================
    # CATEGORY 4: USER MANAGEMENT (8 permissions)
    # ========================================
    
    user_permissions = [
        {
            "code": "user.create",
            "name": "Create Users",
            "description": "Can create new user accounts",
            "category": "user_management",
            "resource": "user",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "User Administration", "dangerous": True}
        },
        {
            "code": "user.read",
            "name": "View Users",
            "description": "Can view user accounts and profiles",
            "category": "user_management",
            "resource": "user",
            "action": "read",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "User Administration"}
        },
        {
            "code": "user.update",
            "name": "Update Users",
            "description": "Can edit user accounts and profiles",
            "category": "user_management",
            "resource": "user",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["user.read"],
            "metadata": {"ui_group": "User Administration", "dangerous": True}
        },
        {
            "code": "user.delete",
            "name": "Delete Users",
            "description": "Can delete user accounts",
            "category": "user_management",
            "resource": "user",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["user.read"],
            "metadata": {"ui_group": "User Administration", "dangerous": True}
        },
        {
            "code": "user.activate_deactivate",
            "name": "Activate/Deactivate Users",
            "description": "Can enable or disable user accounts",
            "category": "user_management",
            "resource": "user",
            "action": "activate_deactivate",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["user.read"],
            "metadata": {"ui_group": "User Administration"}
        },
        {
            "code": "user.reset_password",
            "name": "Reset User Passwords",
            "description": "Can reset passwords for other users",
            "category": "user_management",
            "resource": "user",
            "action": "reset_password",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["user.read"],
            "metadata": {"ui_group": "User Administration", "dangerous": True}
        },
        {
            "code": "user.view_activity",
            "name": "View User Activity",
            "description": "Can view user login history and activity logs",
            "category": "user_management",
            "resource": "user",
            "action": "view_activity",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["user.read"],
            "metadata": {"ui_group": "User Administration"}
        },
        {
            "code": "user.manage_departments",
            "name": "Manage User Departments",
            "description": "Can assign or change user departments",
            "category": "user_management",
            "resource": "user",
            "action": "manage_departments",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["user.update"],
            "metadata": {"ui_group": "User Administration"}
        }
    ]
    
    # ========================================
    # CATEGORY 5: ROLE & PERMISSION MANAGEMENT (7 permissions)
    # ========================================
    
    role_permissions = [
        {
            "code": "role.create",
            "name": "Create Roles",
            "description": "Can create new custom roles",
            "category": "role_permission_management",
            "resource": "role",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Role Administration", "dangerous": True}
        },
        {
            "code": "role.read",
            "name": "View Roles",
            "description": "Can view existing roles and their permissions",
            "category": "role_permission_management",
            "resource": "role",
            "action": "read",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Role Administration"}
        },
        {
            "code": "role.update",
            "name": "Update Roles",
            "description": "Can edit role permissions and settings",
            "category": "role_permission_management",
            "resource": "role",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["role.read"],
            "metadata": {"ui_group": "Role Administration", "dangerous": True}
        },
        {
            "code": "role.delete",
            "name": "Delete Roles",
            "description": "Can delete custom roles",
            "category": "role_permission_management",
            "resource": "role",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["role.read"],
            "metadata": {"ui_group": "Role Administration", "dangerous": True}
        },
        {
            "code": "role.assign",
            "name": "Assign Roles to Users",
            "description": "Can assign or change user roles",
            "category": "role_permission_management",
            "resource": "role",
            "action": "assign",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["role.read", "user.read"],
            "metadata": {"ui_group": "Role Administration", "dangerous": True}
        },
        {
            "code": "permission.view",
            "name": "View Permissions",
            "description": "Can view all available permissions",
            "category": "role_permission_management",
            "resource": "permission",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Role Administration"}
        },
        {
            "code": "permission.override",
            "name": "Override User Permissions",
            "description": "Can grant or deny specific permissions to individual users",
            "category": "role_permission_management",
            "resource": "permission",
            "action": "override",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["user.read", "permission.view"],
            "metadata": {"ui_group": "Role Administration", "dangerous": True}
        }
    ]
    
    # ========================================
    # CATEGORY 6: DASHBOARD & REPORTING (9 permissions)
    # ========================================
    
    dashboard_permissions = [
        {
            "code": "dashboard.view_own",
            "name": "View Own Dashboard",
            "description": "Can view personal dashboard with own stats",
            "category": "dashboard_reporting",
            "resource": "dashboard",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Analytics & Reports"}
        },
        {
            "code": "dashboard.view_team",
            "name": "View Team Dashboard",
            "description": "Can view team dashboard with team stats",
            "category": "dashboard_reporting",
            "resource": "dashboard",
            "action": "view",
            "scope": "team",
            "is_system": True,
            "requires_permissions": ["dashboard.view_own"],
            "metadata": {"ui_group": "Analytics & Reports"}
        },
        {
            "code": "dashboard.view_all",
            "name": "View Organization Dashboard",
            "description": "Can view organization-wide dashboard and analytics",
            "category": "dashboard_reporting",
            "resource": "dashboard",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["dashboard.view_own"],
            "metadata": {"ui_group": "Analytics & Reports"}
        },
        {
            "code": "report.generate_own",
            "name": "Generate Own Reports",
            "description": "Can generate reports for own data",
            "category": "dashboard_reporting",
            "resource": "report",
            "action": "generate",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Analytics & Reports"}
        },
        {
            "code": "report.generate_team",
            "name": "Generate Team Reports",
            "description": "Can generate reports for team data",
            "category": "dashboard_reporting",
            "resource": "report",
            "action": "generate",
            "scope": "team",
            "is_system": True,
            "requires_permissions": ["report.generate_own"],
            "metadata": {"ui_group": "Analytics & Reports"}
        },
        {
            "code": "report.generate_all",
            "name": "Generate Organization Reports",
            "description": "Can generate organization-wide reports",
            "category": "dashboard_reporting",
            "resource": "report",
            "action": "generate",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["report.generate_own"],
            "metadata": {"ui_group": "Analytics & Reports"}
        },
        {
            "code": "report.schedule",
            "name": "Schedule Reports",
            "description": "Can schedule automated report generation",
            "category": "dashboard_reporting",
            "resource": "report",
            "action": "schedule",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["report.generate_all"],
            "metadata": {"ui_group": "Analytics & Reports"}
        },
        {
            "code": "analytics.view_advanced",
            "name": "View Advanced Analytics",
            "description": "Can access advanced analytics and insights",
            "category": "dashboard_reporting",
            "resource": "analytics",
            "action": "view_advanced",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Analytics & Reports"}
        },
        {
            "code": "analytics.export",
            "name": "Export Analytics Data",
            "description": "Can export analytics data and visualizations",
            "category": "dashboard_reporting",
            "resource": "analytics",
            "action": "export",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Analytics & Reports"}
        }
    ]
    
    # ========================================
    # CATEGORY 7: SYSTEM SETTINGS (7 permissions)
    # ========================================
    
    system_permissions = [
        {
            "code": "settings.view",
            "name": "View System Settings",
            "description": "Can view system configuration settings",
            "category": "system_settings",
            "resource": "settings",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Administration"}
        },
        {
            "code": "settings.update",
            "name": "Update System Settings",
            "description": "Can modify system configuration settings",
            "category": "system_settings",
            "resource": "settings",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["settings.view"],
            "metadata": {"ui_group": "System Administration", "dangerous": True}
        },
        {
            "code": "department.manage",
            "name": "Manage Departments",
            "description": "Can create, edit, and delete departments",
            "category": "system_settings",
            "resource": "department",
            "action": "manage",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Administration"}
        },
        {
            "code": "stage.manage",
            "name": "Manage Lead Stages",
            "description": "Can create, edit, and delete lead stages",
            "category": "system_settings",
            "resource": "stage",
            "action": "manage",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Administration"}
        },
        {
            "code": "status.manage",
            "name": "Manage Lead Statuses",
            "description": "Can create, edit, and delete lead statuses",
            "category": "system_settings",
            "resource": "status",
            "action": "manage",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Administration"}
        },
        {
            "code": "source.manage",
            "name": "Manage Lead Sources",
            "description": "Can create, edit, and delete lead sources",
            "category": "system_settings",
            "resource": "source",
            "action": "manage",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Administration"}
        },
        {
            "code": "logs.view",
            "name": "View System Logs",
            "description": "Can view system activity logs and audit trails",
            "category": "system_settings",
            "resource": "logs",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Administration"}
        }
    ]
    
    # ========================================
    # CATEGORY 8: EMAIL & COMMUNICATION (6 permissions)
    # ========================================
    
    communication_permissions = [
        {
            "code": "email.send_single",
            "name": "Send Single Emails",
            "description": "Can send individual emails to leads/contacts",
            "category": "email_communication",
            "resource": "email",
            "action": "send_single",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Communication"}
        },
        {
            "code": "email.send_bulk",
            "name": "Send Bulk Emails",
            "description": "Can send bulk/campaign emails",
            "category": "email_communication",
            "resource": "email",
            "action": "send_bulk",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["email.send_single"],
            "metadata": {"ui_group": "Communication"}
        },
        {
            "code": "email.view_templates",
            "name": "View Email Templates",
            "description": "Can view email templates",
            "category": "email_communication",
            "resource": "email",
            "action": "view_templates",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Communication"}
        },
        {
            "code": "email.manage_templates",
            "name": "Manage Email Templates",
            "description": "Can create and edit email templates",
            "category": "email_communication",
            "resource": "email",
            "action": "manage_templates",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["email.view_templates"],
            "metadata": {"ui_group": "Communication"}
        },
        {
            "code": "whatsapp.send",
            "name": "Send WhatsApp Messages",
            "description": "Can send WhatsApp messages to leads/contacts",
            "category": "email_communication",
            "resource": "whatsapp",
            "action": "send",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Communication"}
        },
        {
            "code": "call.make",
            "name": "Make Calls",
            "description": "Can make calls to leads/contacts",
            "category": "email_communication",
            "resource": "call",
            "action": "make",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Communication"}
        }
    ]
    
    # ========================================
    # CATEGORY 9: TEAM MANAGEMENT (8 permissions) 🔄 UPDATED
    # ========================================
    
    team_permissions = [
        {
            "code": "team.create",
            "name": "Create Teams",
            "description": "Can create new teams",
            "category": "team_management",
            "resource": "team",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Team Operations", "icon": "plus"}
        },
        {
            "code": "team.view_structure",
            "name": "View Team Structure",
            "description": "Can view organizational team structure",
            "category": "team_management",
            "resource": "team",
            "action": "view_structure",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Team Operations"}
        },
        {
            "code": "team.update",
            "name": "Update Teams",
            "description": "Can edit team information and settings",
            "category": "team_management",
            "resource": "team",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["team.view_structure"],
            "metadata": {"ui_group": "Team Operations"}
        },
        {
            "code": "team.delete",
            "name": "Delete Teams",
            "description": "Can delete teams",
            "category": "team_management",
            "resource": "team",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["team.view_structure"],
            "metadata": {"ui_group": "Team Operations", "dangerous": True}
        },
        {
            "code": "team.manage_members",
            "name": "Manage Team Members",
            "description": "Can add or remove users from teams",
            "category": "team_management",
            "resource": "team",
            "action": "manage_members",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["team.view_structure"],
            "metadata": {"ui_group": "Team Operations"}
        },
        {
            "code": "team.change_lead",
            "name": "Change Team Lead",
            "description": "Can change team lead for teams",
            "category": "team_management",
            "resource": "team",
            "action": "change_lead",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["team.manage_members"],
            "metadata": {"ui_group": "Team Operations", "dangerous": True}
        },
        {
            "code": "team.view_performance",
            "name": "View Team Performance",
            "description": "Can view team performance metrics and KPIs",
            "category": "team_management",
            "resource": "team",
            "action": "view_performance",
            "scope": "team",
            "is_system": True,
            "metadata": {"ui_group": "Team Operations"}
        },
        {
            "code": "team.manage_targets",
            "name": "Manage Team Targets",
            "description": "Can set and modify team targets/goals",
            "category": "team_management",
            "resource": "team",
            "action": "manage_targets",
            "scope": "team",
            "is_system": True,
            "requires_permissions": ["team.view_performance"],
            "metadata": {"ui_group": "Team Operations"}
        }
    ]
 
    # ========================================
    # COMBINE ALL PERMISSIONS
    # ========================================
    
    permissions.extend(lead_permissions)
    permissions.extend(contact_permissions)
    permissions.extend(task_permissions)
    permissions.extend(user_permissions)
    permissions.extend(role_permissions)
    permissions.extend(dashboard_permissions)
    permissions.extend(system_permissions)
    permissions.extend(communication_permissions)
    permissions.extend(team_permissions)
    
    # Add timestamps to all permissions
    now = datetime.utcnow()
    for perm in permissions:
        perm["created_at"] = now
        perm["updated_at"] = now
    
    return permissions


# ========================================
# SEED FUNCTIONS
# ========================================

async def seed_permissions(mongodb_url: str, database_name: str) -> Dict[str, Any]:
    """
    Seeds all 69 permissions into MongoDB
    
    Args:
        mongodb_url: MongoDB connection URL
        database_name: Database name
        
    Returns:
        dict: Seed result with counts
    """
    try:
        logger.info("🌱 Starting permission seeding...")
        
        # Connect to MongoDB
        client = AsyncIOMotorClient(mongodb_url)
        db = client[database_name]
        
        # Get all permissions
        permissions = get_all_permissions()
        
        # Check if permissions already exist
        existing_count = await db.permissions.count_documents({})
        
        if existing_count > 0:
            logger.info(f"ℹ️  Found {existing_count} existing permissions. Skipping seed.")
            return {
                "success": True,
                "message": "Permissions already seeded",
                "total_permissions": existing_count,
                "new_permissions": 0,
                "skipped": True
            }
        
        # Insert all permissions
        result = await db.permissions.insert_many(permissions)
        inserted_count = len(result.inserted_ids)
        
        # Create unique index on code
        await db.permissions.create_index("code", unique=True)
        await db.permissions.create_index("category")
        await db.permissions.create_index("resource")
        
        logger.info(f"✅ Successfully seeded {inserted_count} permissions")
        
        # Log category breakdown
        categories = {}
        for perm in permissions:
            cat = perm["category"]
            categories[cat] = categories.get(cat, 0) + 1
        
        logger.info("📊 Permission breakdown by category:")
        for cat, count in categories.items():
            logger.info(f"   - {cat}: {count} permissions")
        
        return {
            "success": True,
            "message": f"Successfully seeded {inserted_count} permissions",
            "total_permissions": inserted_count,
            "new_permissions": inserted_count,
            "categories": categories,
            "skipped": False
        }
        
    except Exception as e:
        logger.error(f"❌ Error seeding permissions: {e}")
        return {
            "success": False,
            "message": f"Failed to seed permissions: {str(e)}",
            "error": str(e)
        }
    finally:
        client.close()


async def verify_permissions(mongodb_url: str, database_name: str) -> Dict[str, Any]:
    """
    Verifies that all 69 permissions exist in database
    
    Returns:
        dict: Verification result
    """
    try:
        logger.info("🔍 Verifying permissions...")
        
        client = AsyncIOMotorClient(mongodb_url)
        db = client[database_name]
        
        # Get expected permissions
        expected_permissions = get_all_permissions()
        expected_codes = {p["code"] for p in expected_permissions}
        
        # Get existing permissions
        existing = await db.permissions.find({}).to_list(length=None)
        existing_codes = {p["code"] for p in existing}
        
        # Find missing and extra
        missing = expected_codes - existing_codes
        extra = existing_codes - expected_codes
        
        result = {
            "success": len(missing) == 0,
            "total_expected": len(expected_codes),
            "total_existing": len(existing_codes),
            "missing_count": len(missing),
            "extra_count": len(extra),
            "missing_permissions": list(missing),
            "extra_permissions": list(extra)
        }
        
        if result["success"]:
            logger.info(f"✅ All {len(expected_codes)} permissions verified")
        else:
            logger.warning(f"⚠️  Permission verification failed: {len(missing)} missing, {len(extra)} extra")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Error verifying permissions: {e}")
        return {
            "success": False,
            "error": str(e)
        }
    finally:
        client.close()


# ========================================
# CLI EXECUTION
# ========================================

async def main():
    """Main execution for manual seeding"""
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    mongodb_url = os.getenv("MONGODB_URL")
    database_name = os.getenv("DATABASE_NAME", "CRM_permission")
    
    if not mongodb_url:
        logger.error("❌ MONGODB_URL not found in environment variables")
        return
    
    logger.info(f"📦 Database: {database_name}")
    
    # Seed permissions
    result = await seed_permissions(mongodb_url, database_name)
    
    if result["success"]:
        logger.info("✅ Permission seeding completed successfully")
        
        # Verify
        verification = await verify_permissions(mongodb_url, database_name)
        if verification["success"]:
            logger.info("✅ All permissions verified")
        else:
            logger.warning("⚠️  Verification found issues:")
            logger.warning(f"   Missing: {verification.get('missing_permissions', [])}")
            logger.warning(f"   Extra: {verification.get('extra_permissions', [])}")
    else:
        logger.error(f"❌ Permission seeding failed: {result.get('message')}")


if __name__ == "__main__":
    asyncio.run(main())