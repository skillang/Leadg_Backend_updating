# app/utils/seed_permissions.py
# 🔄 UPDATED: 108 Permissions across 11 Categories

import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)


# ========================================
# PERMISSION DEFINITIONS (108 Total)
# ========================================

def get_all_permissions() -> List[Dict[str, Any]]:
    """
    Returns all 110 permission definitions
    Organized by 14 categories with subcategories
    
    Changes from v2 (108 permissions):
    - Added 'subcategory' field to all permissions
    - Split Dashboard Reporting into Dashboard and Reporting categories
    - Added subcategories under Lead Management (lead, lead_group)
    - Added subcategories under System Configuration (department, lead_category, status, stage, course_level, source)
    - Added subcategories under Communication (email, whatsapp, call)
    - Added subcategories under Content Activity (note, timeline, document)
    - Removed Specialized Modules category
    - Created separate categories for Facebook Leads, Batch, Notification
    - Moved Attendance to Content Activity
    """
    
    permissions = []
    
    # ========================================
    # CATEGORY 1: DASHBOARD (3 permissions)
    # ========================================
    
    dashboard_permissions = [
        {
            "code": "dashboard.view",
            "name": "View Dashboard",
            "description": "Can view personal dashboard with own stats",
            "category": "dashboard",
            "subcategory": None,
            "resource": "dashboard",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Analytics & Reports", "icon": "bar-chart"}
        },
        {
            "code": "dashboard.view_team",
            "name": "View Team Dashboard",
            "description": "Can view team dashboard with team stats",
            "category": "dashboard",
            "subcategory": None,
            "resource": "dashboard",
            "action": "view",
            "scope": "team",
            "is_system": True,
            "requires_permissions": ["dashboard.view"],
            "metadata": {"ui_group": "Analytics & Reports", "icon": "users"}
        },
        {
            "code": "dashboard.view_all",
            "name": "View All Dashboards",
            "description": "Can view organization-wide dashboard and analytics",
            "category": "dashboard",
            "subcategory": None,
            "resource": "dashboard",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["dashboard.view"],
            "metadata": {"ui_group": "Analytics & Reports", "icon": "globe"}
        }
    ]
    
    # ========================================
    # CATEGORY 2: REPORTING (3 permissions)
    # ========================================
    
    reporting_permissions = [
        {
            "code": "report.view",
            "name": "View Own Reports",
            "description": "Can view and generate reports for own data",
            "category": "reporting",
            "subcategory": None,
            "resource": "report",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Analytics & Reports", "icon": "file-text"}
        },
        {
            "code": "report.view_team",
            "name": "View Team Reports",
            "description": "Can view and generate reports for team data",
            "category": "reporting",
            "subcategory": None,
            "resource": "report",
            "action": "view",
            "scope": "team",
            "is_system": True,
            "requires_permissions": ["report.view"],
            "metadata": {"ui_group": "Analytics & Reports", "icon": "users"}
        },
        {
            "code": "report.view_all",
            "name": "View All Reports",
            "description": "Can view and generate organization-wide reports",
            "category": "reporting",
            "subcategory": None,
            "resource": "report",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["report.view"],
            "metadata": {"ui_group": "Analytics & Reports", "icon": "database"}
        }
    ]
    
    # ========================================
    # CATEGORY 3: LEAD MANAGEMENT (17 permissions)
    # SUBCATEGORIES: lead (10), lead_group (7)
    # ========================================
    
    lead_permissions = [
        # SUBCATEGORY: lead (10 permissions)
        {
            "code": "lead.view",
            "name": "View Own Leads",
            "description": "Can view own assigned leads",
            "category": "lead_management",
            "subcategory": "lead",
            "resource": "lead",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Lead Operations", "icon": "eye"}
        },
        {
            "code": "lead.view_team",
            "name": "View Team Leads",
            "description": "Can view team members' leads",
            "category": "lead_management",
            "subcategory": "lead",
            "resource": "lead",
            "action": "view",
            "scope": "team",
            "is_system": True,
            "requires_permissions": ["lead.view"],
            "metadata": {"ui_group": "Lead Operations", "icon": "users"}
        },
        {
            "code": "lead.view_all",
            "name": "View All Leads",
            "description": "Can view all leads in the system",
            "category": "lead_management",
            "subcategory": "lead",
            "resource": "lead",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["lead.view"],
            "metadata": {"ui_group": "Lead Operations", "icon": "database"}
        },
        {
            "code": "lead.add_single",
            "name": "Add Single Lead",
            "description": "Can add individual leads one at a time",
            "category": "lead_management",
            "subcategory": "lead",
            "resource": "lead",
            "action": "add",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Lead Operations", "icon": "plus"}
        },
        {
            "code": "lead.add_bulk",
            "name": "Add Bulk Leads",
            "description": "Can import multiple leads via Excel/CSV bulk upload",
            "category": "lead_management",
            "subcategory": "lead",
            "resource": "lead",
            "action": "add",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["lead.add_single"],
            "metadata": {"ui_group": "Lead Operations", "icon": "upload"}
        },
        {
            "code": "lead.add_via_cv",
            "name": "Add Lead from CV",
            "description": "Can create leads by uploading and parsing CV/resume files",
            "category": "lead_management",
            "subcategory": "lead",
            "resource": "lead",
            "action": "add",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["lead.add_single"],
            "metadata": {"ui_group": "Lead Operations", "icon": "file-text"}
        },
        {
            "code": "lead.update",
            "name": "Update Own Leads",
            "description": "Can edit and modify own assigned leads",
            "category": "lead_management",
            "subcategory": "lead",
            "resource": "lead",
            "action": "update",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["lead.view"],
            "metadata": {"ui_group": "Lead Operations", "icon": "edit"}
        },
        {
            "code": "lead.update_all",
            "name": "Update All Leads",
            "description": "Can edit and modify any lead in the system",
            "category": "lead_management",
            "subcategory": "lead",
            "resource": "lead",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["lead.view_all", "lead.update"],
            "metadata": {"ui_group": "Lead Operations", "icon": "edit"}
        },
        {
            "code": "lead.export",
            "name": "Export Leads",
            "description": "Can export lead data to CSV/Excel files",
            "category": "lead_management",
            "subcategory": "lead",
            "resource": "lead",
            "action": "export",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Lead Operations", "icon": "download"}
        },
        {
            "code": "lead.assign",
            "name": "Assign Leads",
            "description": "Can assign or reassign leads to other users",
            "category": "lead_management",
            "subcategory": "lead",
            "resource": "lead",
            "action": "assign",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["lead.view_all"],
            "metadata": {"ui_group": "Lead Operations", "icon": "user-plus"}
        },
        
        # SUBCATEGORY: lead_group (7 permissions)
        {
            "code": "lead_group.view",
            "name": "View Own Lead Groups",
            "description": "Can view own created lead groups",
            "category": "lead_management",
            "subcategory": "lead_group",
            "resource": "lead_group",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Lead Groups", "icon": "folder"}
        },
        {
            "code": "lead_group.view_team",
            "name": "View Team Lead Groups",
            "description": "Can view team members' lead groups",
            "category": "lead_management",
            "subcategory": "lead_group",
            "resource": "lead_group",
            "action": "view",
            "scope": "team",
            "is_system": True,
            "requires_permissions": ["lead_group.view"],
            "metadata": {"ui_group": "Lead Groups", "icon": "users"}
        },
        {
            "code": "lead_group.view_all",
            "name": "View All Lead Groups",
            "description": "Can view all lead groups in the system",
            "category": "lead_management",
            "subcategory": "lead_group",
            "resource": "lead_group",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["lead_group.view"],
            "metadata": {"ui_group": "Lead Groups", "icon": "database"}
        },
        {
            "code": "lead_group.create",
            "name": "Create Lead Groups",
            "description": "Can create new lead groups for organizing leads",
            "category": "lead_management",
            "subcategory": "lead_group",
            "resource": "lead_group",
            "action": "create",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Lead Groups", "icon": "plus"}
        },
        {
            "code": "lead_group.add",
            "name": "Add Leads to Groups",
            "description": "Can add leads to existing groups",
            "category": "lead_management",
            "subcategory": "lead_group",
            "resource": "lead_group",
            "action": "add",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["lead_group.create"],
            "metadata": {"ui_group": "Lead Groups", "icon": "folder-plus"}
        },
        {
            "code": "lead_group.delete",
            "name": "Delete Lead Groups",
            "description": "Can delete lead groups",
            "category": "lead_management",
            "subcategory": "lead_group",
            "resource": "lead_group",
            "action": "delete",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["lead_group.view"],
            "metadata": {"ui_group": "Lead Groups", "icon": "trash", "dangerous": True}
        },
        {
            "code": "lead_group.update",
            "name": "Update Lead Groups",
            "description": "Can modify lead group details and membership",
            "category": "lead_management",
            "subcategory": "lead_group",
            "resource": "lead_group",
            "action": "update",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["lead_group.view"],
            "metadata": {"ui_group": "Lead Groups", "icon": "edit"}
        }
    ]
    
    # ========================================
    # CATEGORY 4: CONTACT MANAGEMENT (6 permissions)
    # ========================================
    
    contact_permissions = [
        {
            "code": "contact.view",
            "name": "View Own Contacts",
            "description": "Can view contacts for own assigned leads",
            "category": "contact_management",
            "subcategory": None,
            "resource": "contact",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Contact Operations", "icon": "user"}
        },
        {
            "code": "contact.view_all",
            "name": "View All Contacts",
            "description": "Can view all contacts in the system",
            "category": "contact_management",
            "subcategory": None,
            "resource": "contact",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["contact.view"],
            "metadata": {"ui_group": "Contact Operations", "icon": "users"}
        },
        {
            "code": "contact.add",
            "name": "Add Contacts",
            "description": "Can create new contact records",
            "category": "contact_management",
            "subcategory": None,
            "resource": "contact",
            "action": "add",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Contact Operations", "icon": "plus"}
        },
        {
            "code": "contact.update_own",
            "name": "Update Own Contacts",
            "description": "Can edit contacts for own assigned leads",
            "category": "contact_management",
            "subcategory": None,
            "resource": "contact",
            "action": "update",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["contact.view"],
            "metadata": {"ui_group": "Contact Operations", "icon": "edit"}
        },
        {
            "code": "contact.update_all",
            "name": "Update All Contacts",
            "description": "Can edit any contact in the system",
            "category": "contact_management",
            "subcategory": None,
            "resource": "contact",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["contact.view_all"],
            "metadata": {"ui_group": "Contact Operations", "icon": "edit"}
        },
        {
            "code": "contact.delete",
            "name": "Delete Contacts",
            "description": "Can delete contact records",
            "category": "contact_management",
            "subcategory": None,
            "resource": "contact",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["contact.view_all"],
            "metadata": {"ui_group": "Contact Operations", "icon": "trash", "dangerous": True}
        }
    ]
    
    # ========================================
    # CATEGORY 5: TASK MANAGEMENT (9 permissions)
    # ========================================
    
    task_permissions = [
        {
            "code": "task.view",
            "name": "View Own Tasks",
            "description": "Can view own assigned tasks",
            "category": "task_management",
            "subcategory": None,
            "resource": "task",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Task Operations", "icon": "check-square"}
        },
        {
            "code": "task.view_team",
            "name": "View Team Tasks",
            "description": "Can view team members' tasks",
            "category": "task_management",
            "subcategory": None,
            "resource": "task",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Task Operations", "icon": "check-square"}
        },
        {
            "code": "task.view_all",
            "name": "View All Tasks",
            "description": "Can view all tasks in the system",
            "category": "task_management",
            "subcategory": None,
            "resource": "task",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["task.view"],
            "metadata": {"ui_group": "Task Operations", "icon": "list"}
        },
        {
            "code": "task.add",
            "name": "Add Tasks",
            "description": "Can create new tasks",
            "category": "task_management",
            "subcategory": None,
            "resource": "task",
            "action": "add",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Task Operations", "icon": "plus"}
        },
        {
            "code": "task.update_own",
            "name": "Update Own Tasks",
            "description": "Can edit own assigned tasks",
            "category": "task_management",
            "subcategory": None,
            "resource": "task",
            "action": "update",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["task.view"],
            "metadata": {"ui_group": "Task Operations", "icon": "edit"}
        },
        {
            "code": "task.update_team",
            "name": "Update Team Tasks",
            "description": "Can edit team members' tasks",
            "category": "task_management",
            "subcategory": None,
            "resource": "task",
            "action": "update",
            "scope": "team",
            "is_system": True,
            "requires_permissions": ["task.view_all"],
            "metadata": {"ui_group": "Task Operations", "icon": "users"}
        },
        {
            "code": "task.delete_own",
            "name": "Delete Own Tasks",
            "description": "Can delete own assigned tasks",
            "category": "task_management",
            "subcategory": None,
            "resource": "task",
            "action": "delete",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["task.view"],
            "metadata": {"ui_group": "Task Operations", "icon": "trash", "dangerous": True}
        },
        {
            "code": "task.delete_team",
            "name": "Delete Team Tasks",
            "description": "Can delete team members' tasks",
            "category": "task_management",
            "subcategory": None,
            "resource": "task",
            "action": "delete",
            "scope": "team",
            "is_system": True,
            "requires_permissions": ["task.view_all"],
            "metadata": {"ui_group": "Task Operations", "icon": "trash", "dangerous": True}
        },
        {
            "code": "task.delete_all",
            "name": "Delete All Tasks",
            "description": "Can delete any task in the system",
            "category": "task_management",
            "subcategory": None,
            "resource": "task",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["task.view_all"],
            "metadata": {"ui_group": "Task Operations", "icon": "trash", "dangerous": True}
        }
    ]
    
    # ========================================
    # CATEGORY 6: USER MANAGEMENT (5 permissions)
    # ========================================
    
    user_permissions = [
        {
            "code": "user.create",
            "name": "Create Users",
            "description": "Can create new user accounts",
            "category": "user_management",
            "subcategory": None,
            "resource": "user",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "User Administration", "icon": "user-plus", "dangerous": True}
        },
        {
            "code": "user.view",
            "name": "View Users",
            "description": "Can view user accounts and profiles",
            "category": "user_management",
            "subcategory": None,
            "resource": "user",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "User Administration", "icon": "users"}
        },
        {
            "code": "user.delete",
            "name": "Delete Users",
            "description": "Can delete user accounts",
            "category": "user_management",
            "subcategory": None,
            "resource": "user",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["user.view"],
            "metadata": {"ui_group": "User Administration", "icon": "trash", "dangerous": True}
        },
        {
            "code": "user.update",
            "name": "Update Users",
            "description": "Can edit user accounts and profiles",
            "category": "user_management",
            "subcategory": None,
            "resource": "user",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["user.view"],
            "metadata": {"ui_group": "User Administration", "icon": "edit", "dangerous": True}
        },
        {
            "code": "user.reset_password",
            "name": "Reset User Passwords",
            "description": "Can reset passwords for other users",
            "category": "user_management",
            "subcategory": None,
            "resource": "user",
            "action": "reset_password",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["user.view"],
            "metadata": {"ui_group": "User Administration", "icon": "key", "dangerous": True}
        }
    ]
    
    # ========================================
    # CATEGORY 7: ROLE & PERMISSION MANAGEMENT (5 permissions)
    # ========================================
    
    role_permissions = [
        {
            "code": "role.create",
            "name": "Create Roles",
            "description": "Can create new custom roles",
            "category": "role_permission_management",
            "subcategory": None,
            "resource": "role",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Role Administration", "icon": "shield", "dangerous": True}
        },
        {
            "code": "role.read",
            "name": "View Roles",
            "description": "Can view existing roles and their permissions",
            "category": "role_permission_management",
            "subcategory": None,
            "resource": "role",
            "action": "read",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Role Administration", "icon": "eye"}
        },
        {
            "code": "role.update",
            "name": "Update Roles",
            "description": "Can edit role permissions and settings",
            "category": "role_permission_management",
            "subcategory": None,
            "resource": "role",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["role.read"],
            "metadata": {"ui_group": "Role Administration", "icon": "edit", "dangerous": True}
        },
        {
            "code": "role.delete",
            "name": "Delete Roles",
            "description": "Can delete custom roles",
            "category": "role_permission_management",
            "subcategory": None,
            "resource": "role",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["role.read"],
            "metadata": {"ui_group": "Role Administration", "icon": "trash", "dangerous": True}
        },
        {
            "code": "permission.view",
            "name": "View Permissions",
            "description": "Can view all available system permissions",
            "category": "role_permission_management",
            "subcategory": None,
            "resource": "permission",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Role Administration", "icon": "shield"}
        }
    ]
    
    # ========================================
    # CATEGORY 8: SYSTEM CONFIGURATION (24 permissions)
    # SUBCATEGORIES: department (4), lead_category (4), status (4), stage (4), course_level (4), source (4)
    # ========================================
    
    system_config_permissions = [
        # SUBCATEGORY: department (4 permissions)
        {
            "code": "department.create",
            "name": "Create Departments",
            "description": "Can create new departments",
            "category": "system_configuration",
            "subcategory": "department",
            "resource": "department",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "building"}
        },
        {
            "code": "department.edit",
            "name": "Edit Departments",
            "description": "Can edit existing departments",
            "category": "system_configuration",
            "subcategory": "department",
            "resource": "department",
            "action": "edit",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "edit"}
        },
        {
            "code": "department.view",
            "name": "View Departments",
            "description": "Can view department list and details",
            "category": "system_configuration",
            "subcategory": "department",
            "resource": "department",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "eye"}
        },
        {
            "code": "department.delete",
            "name": "Delete Departments",
            "description": "Can delete departments",
            "category": "system_configuration",
            "subcategory": "department",
            "resource": "department",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "trash", "dangerous": True}
        },
        
        # SUBCATEGORY: lead_category (4 permissions)
        {
            "code": "lead_category.create",
            "name": "Create Lead Categories",
            "description": "Can create new lead categories",
            "category": "system_configuration",
            "subcategory": "lead_category",
            "resource": "lead_category",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "tag"}
        },
        {
            "code": "lead_category.edit",
            "name": "Edit Lead Categories",
            "description": "Can edit existing lead categories",
            "category": "system_configuration",
            "subcategory": "lead_category",
            "resource": "lead_category",
            "action": "edit",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "edit"}
        },
        {
            "code": "lead_category.view",
            "name": "View Lead Categories",
            "description": "Can view lead category list and details",
            "category": "system_configuration",
            "subcategory": "lead_category",
            "resource": "lead_category",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "eye"}
        },
        {
            "code": "lead_category.delete",
            "name": "Delete Lead Categories",
            "description": "Can delete lead categories",
            "category": "system_configuration",
            "subcategory": "lead_category",
            "resource": "lead_category",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "trash", "dangerous": True}
        },
        
        # SUBCATEGORY: status (4 permissions)
        {
            "code": "status.create",
            "name": "Create Statuses",
            "description": "Can create new lead statuses",
            "category": "system_configuration",
            "subcategory": "status",
            "resource": "status",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "flag"}
        },
        {
            "code": "status.edit",
            "name": "Edit Statuses",
            "description": "Can edit existing lead statuses",
            "category": "system_configuration",
            "subcategory": "status",
            "resource": "status",
            "action": "edit",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "edit"}
        },
        {
            "code": "status.view",
            "name": "View Statuses",
            "description": "Can view status list and details",
            "category": "system_configuration",
            "subcategory": "status",
            "resource": "status",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "eye"}
        },
        {
            "code": "status.delete",
            "name": "Delete Statuses",
            "description": "Can delete lead statuses",
            "category": "system_configuration",
            "subcategory": "status",
            "resource": "status",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "trash", "dangerous": True}
        },
        
        # SUBCATEGORY: stage (4 permissions)
        {
            "code": "stage.create",
            "name": "Create Stages",
            "description": "Can create new lead stages",
            "category": "system_configuration",
            "subcategory": "stage",
            "resource": "stage",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "layers"}
        },
        {
            "code": "stage.edit",
            "name": "Edit Stages",
            "description": "Can edit existing lead stages",
            "category": "system_configuration",
            "subcategory": "stage",
            "resource": "stage",
            "action": "edit",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "edit"}
        },
        {
            "code": "stage.view",
            "name": "View Stages",
            "description": "Can view stage list and details",
            "category": "system_configuration",
            "subcategory": "stage",
            "resource": "stage",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "eye"}
        },
        {
            "code": "stage.delete",
            "name": "Delete Stages",
            "description": "Can delete lead stages",
            "category": "system_configuration",
            "subcategory": "stage",
            "resource": "stage",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "trash", "dangerous": True}
        },
        
        # SUBCATEGORY: course_level (4 permissions)
        {
            "code": "course_level.create",
            "name": "Create Course Levels",
            "description": "Can create new course levels",
            "category": "system_configuration",
            "subcategory": "course_level",
            "resource": "course_level",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "book"}
        },
        {
            "code": "course_level.edit",
            "name": "Edit Course Levels",
            "description": "Can edit existing course levels",
            "category": "system_configuration",
            "subcategory": "course_level",
            "resource": "course_level",
            "action": "edit",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "edit"}
        },
        {
            "code": "course_level.view",
            "name": "View Course Levels",
            "description": "Can view course level list and details",
            "category": "system_configuration",
            "subcategory": "course_level",
            "resource": "course_level",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "eye"}
        },
        {
            "code": "course_level.delete",
            "name": "Delete Course Levels",
            "description": "Can delete course levels",
            "category": "system_configuration",
            "subcategory": "course_level",
            "resource": "course_level",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "trash", "dangerous": True}
        },
        
        # SUBCATEGORY: source (4 permissions)
        {
            "code": "source.create",
            "name": "Create Lead Sources",
            "description": "Can create new lead sources",
            "category": "system_configuration",
            "subcategory": "source",
            "resource": "source",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "target"}
        },
        {
            "code": "source.edit",
            "name": "Edit Lead Sources",
            "description": "Can edit existing lead sources",
            "category": "system_configuration",
            "subcategory": "source",
            "resource": "source",
            "action": "edit",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "edit"}
        },
        {
            "code": "source.view",
            "name": "View Lead Sources",
            "description": "Can view lead source list and details",
            "category": "system_configuration",
            "subcategory": "source",
            "resource": "source",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "eye"}
        },
        {
            "code": "source.delete",
            "name": "Delete Lead Sources",
            "description": "Can delete lead sources",
            "category": "system_configuration",
            "subcategory": "source",
            "resource": "source",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "System Configuration", "icon": "trash", "dangerous": True}
        }
    ]
    
    # ========================================
    # CATEGORY 9: COMMUNICATION (11 permissions)
    # SUBCATEGORIES: email (4), whatsapp (5), call (2)
    # ========================================
    
    communication_permissions = [
        # SUBCATEGORY: email (4 permissions)
        {
            "code": "email.send_single",
            "name": "Send Single Emails",
            "description": "Can send individual emails to leads/contacts",
            "category": "communication",
            "subcategory": "email",
            "resource": "email",
            "action": "send_single",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Communication", "icon": "mail"}
        },
        {
            "code": "email.send_bulk",
            "name": "Send Bulk Emails",
            "description": "Can send bulk email campaigns",
            "category": "communication",
            "subcategory": "email",
            "resource": "email",
            "action": "send_bulk",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["email.send_single"],
            "metadata": {"ui_group": "Communication", "icon": "send"}
        },
        {
            "code": "email.single_history",
            "name": "View Single Email History",
            "description": "Can view individual email history and logs",
            "category": "communication",
            "subcategory": "email",
            "resource": "email",
            "action": "single_history",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Communication", "icon": "clock"}
        },
        {
            "code": "email.bulk_history",
            "name": "View Bulk Email History",
            "description": "Can view all email campaign history and analytics",
            "category": "communication",
            "subcategory": "email",
            "resource": "email",
            "action": "bulk_history",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Communication", "icon": "bar-chart"}
        },
        
        # SUBCATEGORY: whatsapp (5 permissions)
        {
            "code": "whatsapp.send_single",
            "name": "Send Single WhatsApp",
            "description": "Can send individual WhatsApp messages",
            "category": "communication",
            "subcategory": "whatsapp",
            "resource": "whatsapp",
            "action": "send_single",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Communication", "icon": "message-circle"}
        },
        {
            "code": "whatsapp.send_bulk",
            "name": "Send Bulk WhatsApp",
            "description": "Can send bulk WhatsApp campaigns",
            "category": "communication",
            "subcategory": "whatsapp",
            "resource": "whatsapp",
            "action": "send_bulk",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["whatsapp.send_single"],
            "metadata": {"ui_group": "Communication", "icon": "send"}
        },
        {
            "code": "whatsapp.history_single",
            "name": "View Single WhatsApp History",
            "description": "Can view individual WhatsApp message history",
            "category": "communication",
            "subcategory": "whatsapp",
            "resource": "whatsapp",
            "action": "history_single",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Communication", "icon": "clock"}
        },
        {
            "code": "whatsapp.view_all",
            "name": "View All WhatsApp History",
            "description": "Can view all WhatsApp message history",
            "category": "communication",
            "subcategory": "whatsapp",
            "resource": "whatsapp",
            "action": "view_all",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Communication", "icon": "clock"}
        },
        {
            "code": "whatsapp.history_bulk",
            "name": "View Bulk WhatsApp History",
            "description": "Can view all WhatsApp campaign history and analytics",
            "category": "communication",
            "subcategory": "whatsapp",
            "resource": "whatsapp",
            "action": "history_bulk",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Communication", "icon": "bar-chart"}
        },
        
        # SUBCATEGORY: call (2 permissions)
        {
            "code": "call.make",
            "name": "Make Calls",
            "description": "Can make calls to leads/contacts via integrated calling",
            "category": "communication",
            "subcategory": "call",
            "resource": "call",
            "action": "make",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Communication", "icon": "phone"}
        },
        {
            "code": "call.history",
            "name": "View Call History",
            "description": "Can view call logs and history",
            "category": "communication",
            "subcategory": "call",
            "resource": "call",
            "action": "history",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Communication", "icon": "phone-call"}
        }
    ]
    
    # ========================================
    # CATEGORY 10: TEAM MANAGEMENT (5 permissions)
    # ========================================
    
    team_permissions = [
        {
            "code": "team.view",
            "name": "View Own Team",
            "description": "Can view own team information and members",
            "category": "team_management",
            "subcategory": None,
            "resource": "team",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Team Operations", "icon": "users"}
        },
        {
            "code": "team.view_all",
            "name": "View All Teams",
            "description": "Can view all teams in the organization",
            "category": "team_management",
            "subcategory": None,
            "resource": "team",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["team.view"],
            "metadata": {"ui_group": "Team Operations", "icon": "grid"}
        },
        {
            "code": "team.create",
            "name": "Create Teams",
            "description": "Can create new teams",
            "category": "team_management",
            "subcategory": None,
            "resource": "team",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Team Operations", "icon": "plus"}
        },
        {
            "code": "team.update",
            "name": "Update Teams",
            "description": "Can edit team information, add/remove members, assign team leads",
            "category": "team_management",
            "subcategory": None,
            "resource": "team",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["team.view"],
            "metadata": {"ui_group": "Team Operations", "icon": "edit"}
        },
        {
            "code": "team.delete",
            "name": "Delete Teams",
            "description": "Can delete teams",
            "category": "team_management",
            "subcategory": None,
            "resource": "team",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["team.view"],
            "metadata": {"ui_group": "Team Operations", "icon": "trash", "dangerous": True}
        }
    ]
    
    # ========================================
    # CATEGORY 11: CONTENT ACTIVITY (14 permissions)
    # SUBCATEGORIES: note (4), timeline (1), document (5), attendance (4)
    # ========================================
    
    content_permissions = [
        # SUBCATEGORY: note (4 permissions)
        {
            "code": "note.view",
            "name": "View Notes",
            "description": "Can view notes on leads",
            "category": "content_activity",
            "subcategory": "note",
            "resource": "note",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Content Management", "icon": "file-text"}
        },
        {
            "code": "note.add",
            "name": "Add Notes",
            "description": "Can add notes to leads",
            "category": "content_activity",
            "subcategory": "note",
            "resource": "note",
            "action": "add",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Content Management", "icon": "plus"}
        },
        {
            "code": "note.delete",
            "name": "Delete Notes",
            "description": "Can delete notes from leads",
            "category": "content_activity",
            "subcategory": "note",
            "resource": "note",
            "action": "delete",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["note.view"],
            "metadata": {"ui_group": "Content Management", "icon": "trash", "dangerous": True}
        },
        {
            "code": "note.update",
            "name": "Update Notes",
            "description": "Can edit existing notes",
            "category": "content_activity",
            "subcategory": "note",
            "resource": "note",
            "action": "update",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["note.view"],
            "metadata": {"ui_group": "Content Management", "icon": "edit"}
        },
        
        # SUBCATEGORY: timeline (1 permission)
        {
            "code": "timeline.view",
            "name": "View Activity Timeline",
            "description": "Can view lead activity timeline and history",
            "category": "content_activity",
            "subcategory": "timeline",
            "resource": "timeline",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Content Management", "icon": "clock"}
        },
        
        # SUBCATEGORY: document (5 permissions)
        {
            "code": "document.view",
            "name": "View Own Documents",
            "description": "Can view documents for own leads",
            "category": "content_activity",
            "subcategory": "document",
            "resource": "document",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Content Management", "icon": "file"}
        },
        {
            "code": "document.view_all",
            "name": "View All Documents",
            "description": "Can view all documents in the system",
            "category": "content_activity",
            "subcategory": "document",
            "resource": "document",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["document.view"],
            "metadata": {"ui_group": "Content Management", "icon": "folder"}
        },
        {
            "code": "document.add",
            "name": "Add Documents",
            "description": "Can upload documents to leads",
            "category": "content_activity",
            "subcategory": "document",
            "resource": "document",
            "action": "add",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Content Management", "icon": "upload"}
        },
        {
            "code": "document.delete",
            "name": "Delete Documents",
            "description": "Can delete documents from leads",
            "category": "content_activity",
            "subcategory": "document",
            "resource": "document",
            "action": "delete",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["document.view"],
            "metadata": {"ui_group": "Content Management", "icon": "trash", "dangerous": True}
        },
        {
            "code": "document.update",
            "name": "Update Documents",
            "description": "Can update document metadata and details",
            "category": "content_activity",
            "subcategory": "document",
            "resource": "document",
            "action": "update",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["document.view"],
            "metadata": {"ui_group": "Content Management", "icon": "edit"}
        },
        
        # SUBCATEGORY: attendance (4 permissions - moved from specialized_modules)
        {
            "code": "attendance.view",
            "name": "View Attendance",
            "description": "Can view batch attendance records",
            "category": "content_activity",
            "subcategory": "attendance",
            "resource": "attendance",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Batch Management", "icon": "check-circle"}
        },
        {
            "code": "attendance.add",
            "name": "Mark Attendance",
            "description": "Can mark attendance for batch sessions",
            "category": "content_activity",
            "subcategory": "attendance",
            "resource": "attendance",
            "action": "add",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "Batch Management", "icon": "check"}
        },
        {
            "code": "attendance.delete",
            "name": "Delete Attendance",
            "description": "Can delete attendance records",
            "category": "content_activity",
            "subcategory": "attendance",
            "resource": "attendance",
            "action": "delete",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["attendance.view"],
            "metadata": {"ui_group": "Batch Management", "icon": "trash", "dangerous": True}
        },
        {
            "code": "attendance.update",
            "name": "Update Attendance",
            "description": "Can modify attendance records",
            "category": "content_activity",
            "subcategory": "attendance",
            "resource": "attendance",
            "action": "update",
            "scope": "own",
            "is_system": True,
            "requires_permissions": ["attendance.view"],
            "metadata": {"ui_group": "Batch Management", "icon": "edit"}
        }
    ]
    
    # ========================================
    # CATEGORY 12: FACEBOOK LEADS (2 permissions)
    # Separated from specialized_modules
    # ========================================
    
    facebook_permissions = [
        {
            "code": "facebook_leads.view",
            "name": "View Facebook Leads",
            "description": "Can view leads imported from Facebook Lead Ads",
            "category": "facebook_leads",
            "subcategory": None,
            "resource": "facebook_leads",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Integrations", "icon": "facebook"}
        },
        {
            "code": "facebook_leads.convert",
            "name": "Convert Facebook Leads",
            "description": "Can convert Facebook leads to CRM leads",
            "category": "facebook_leads",
            "subcategory": None,
            "resource": "facebook_leads",
            "action": "convert",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["facebook_leads.view", "lead.add_single"],
            "metadata": {"ui_group": "Integrations", "icon": "refresh-cw"}
        }
    ]
    
    # ========================================
    # CATEGORY 13: BATCH (5 permissions)
    # Separated from specialized_modules
    # ========================================
    
    batch_permissions = [
        {
            "code": "batch.create",
            "name": "Create Batches",
            "description": "Can create new training batches",
            "category": "batch",
            "subcategory": None,
            "resource": "batch",
            "action": "create",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Batch Management", "icon": "package"}
        },
        {
            "code": "batch.view",
            "name": "View Batches",
            "description": "Can view batch information and details",
            "category": "batch",
            "subcategory": None,
            "resource": "batch",
            "action": "view",
            "scope": "all",
            "is_system": True,
            "metadata": {"ui_group": "Batch Management", "icon": "eye"}
        },
        {
            "code": "batch.add",
            "name": "Add Students to Batch",
            "description": "Can enroll students/leads into batches",
            "category": "batch",
            "subcategory": None,
            "resource": "batch",
            "action": "add",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["batch.view"],
            "metadata": {"ui_group": "Batch Management", "icon": "user-plus"}
        },
        {
            "code": "batch.delete",
            "name": "Delete Batches",
            "description": "Can delete training batches",
            "category": "batch",
            "subcategory": None,
            "resource": "batch",
            "action": "delete",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["batch.view"],
            "metadata": {"ui_group": "Batch Management", "icon": "trash", "dangerous": True}
        },
        {
            "code": "batch.update",
            "name": "Update Batches",
            "description": "Can modify batch information and settings",
            "category": "batch",
            "subcategory": None,
            "resource": "batch",
            "action": "update",
            "scope": "all",
            "is_system": True,
            "requires_permissions": ["batch.view"],
            "metadata": {"ui_group": "Batch Management", "icon": "edit"}
        }
    ]
    
    # ========================================
    # CATEGORY 14: NOTIFICATION (1 permission)
    # Separated from specialized_modules
    # ========================================
    
    notification_permissions = [
        {
            "code": "notification.view",
            "name": "View Notifications",
            "description": "Can view system notifications and alerts",
            "category": "notification",
            "subcategory": None,
            "resource": "notification",
            "action": "view",
            "scope": "own",
            "is_system": True,
            "metadata": {"ui_group": "System", "icon": "bell"}
        }
    ]
    
    # ========================================
    # COMBINE ALL PERMISSIONS
    # ========================================
    
    permissions.extend(dashboard_permissions)          # 3
    permissions.extend(reporting_permissions)          # 3
    permissions.extend(lead_permissions)               # 17
    permissions.extend(contact_permissions)            # 6
    permissions.extend(task_permissions)               # 9
    permissions.extend(user_permissions)               # 5
    permissions.extend(role_permissions)               # 5
    permissions.extend(system_config_permissions)      # 24
    permissions.extend(communication_permissions)      # 11
    permissions.extend(team_permissions)               # 5
    permissions.extend(content_permissions)            # 14
    permissions.extend(facebook_permissions)           # 2
    permissions.extend(batch_permissions)              # 5
    permissions.extend(notification_permissions)       # 1
    
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
    Seeds all 110 permissions into MongoDB
    
    Args:
        mongodb_url: MongoDB connection URL
        database_name: Database name
        
    Returns:
        dict: Seed result with counts
    """
    try:
        logger.info("🌱 Starting permission seeding (v3 - 110 permissions with subcategories)...")
        
        # Connect to MongoDB
        client = AsyncIOMotorClient(mongodb_url)
        db = client[database_name]
        
        # Get all permissions
        permissions = get_all_permissions()
        
        # Verify count
        if len(permissions) != 110:
            logger.warning(f"⚠️  Expected 110 permissions, got {len(permissions)}")
        
        # Check if permissions already exist
        existing_count = await db.permissions.count_documents({})
        
        if existing_count > 0:
            logger.info(f"ℹ️  Found {existing_count} existing permissions. Skipping seed.")
            logger.info(f"💡 Run migration script to update from 108 to 110 permissions")
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
        
        # Create indexes
        await db.permissions.create_index("code", unique=True)
        await db.permissions.create_index("category")
        await db.permissions.create_index("subcategory")  # NEW INDEX
        await db.permissions.create_index("resource")
        await db.permissions.create_index("action")
        await db.permissions.create_index([("category", 1), ("subcategory", 1)])  # COMPOUND INDEX
        
        logger.info(f"✅ Successfully seeded {inserted_count} permissions")
        
        # Log category breakdown
        categories = {}
        subcategories = {}
        
        for perm in permissions:
            cat = perm["category"]
            subcat = perm.get("subcategory")
            
            categories[cat] = categories.get(cat, 0) + 1
            
            if subcat:
                key = f"{cat}.{subcat}"
                subcategories[key] = subcategories.get(key, 0) + 1
        
        logger.info("📊 Permission breakdown by category:")
        for cat, count in sorted(categories.items()):
            logger.info(f"   - {cat}: {count} permissions")
        
        if subcategories:
            logger.info("📊 Permission breakdown by subcategory:")
            for subcat, count in sorted(subcategories.items()):
                logger.info(f"   - {subcat}: {count} permissions")
        
        return {
            "success": True,
            "message": f"Successfully seeded {inserted_count} permissions",
            "total_permissions": inserted_count,
            "new_permissions": inserted_count,
            "categories": categories,
            "subcategories": subcategories,
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
    Verifies that all 110 permissions exist in database
    
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
        
        # Verify subcategory structure
        subcategory_issues = []
        for perm in existing:
            if "subcategory" not in perm:
                subcategory_issues.append(perm.get("code", "unknown"))
        
        result = {
            "success": len(missing) == 0 and len(subcategory_issues) == 0,
            "total_expected": len(expected_codes),
            "total_existing": len(existing_codes),
            "missing_count": len(missing),
            "extra_count": len(extra),
            "subcategory_issues_count": len(subcategory_issues),
            "missing_permissions": sorted(list(missing)),
            "extra_permissions": sorted(list(extra)),
            "permissions_without_subcategory": subcategory_issues[:10]
        }
        
        if result["success"]:
            logger.info(f"✅ All {len(expected_codes)} permissions verified with subcategories")
        else:
            logger.warning(f"⚠️  Permission verification failed:")
            logger.warning(f"   Missing: {len(missing)} permissions")
            logger.warning(f"   Extra: {len(extra)} permissions")
            logger.warning(f"   Missing subcategory field: {len(subcategory_issues)} permissions")
            
            if missing:
                logger.warning(f"   Missing list: {sorted(list(missing))[:10]}...")
            if extra:
                logger.warning(f"   Extra list: {sorted(list(extra))[:10]}...")
            if subcategory_issues:
                logger.warning(f"   Without subcategory: {subcategory_issues[:10]}...")
        
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
    logger.info(f"🎯 Target: 110 permissions across 14 categories")
    logger.info(f"📋 Structure: Categories with subcategories support")
    
    # Seed permissions
    result = await seed_permissions(mongodb_url, database_name)
    
    if result["success"]:
        logger.info("✅ Permission seeding completed successfully")
        
        # Verify
        verification = await verify_permissions(mongodb_url, database_name)
        if verification["success"]:
            logger.info("✅ All 110 permissions verified with subcategories")
        else:
            logger.warning("⚠️  Verification found issues:")
            if verification.get('missing_permissions'):
                logger.warning(f"   Missing ({len(verification['missing_permissions'])}): {verification['missing_permissions'][:5]}...")
            if verification.get('extra_permissions'):
                logger.warning(f"   Extra ({len(verification['extra_permissions'])}): {verification['extra_permissions'][:5]}...")
            if verification.get('permissions_without_subcategory'):
                logger.warning(f"   Missing subcategory field ({len(verification['permissions_without_subcategory'])}): {verification['permissions_without_subcategory'][:5]}...")
    else:
        logger.error(f"❌ Permission seeding failed: {result.get('message')}")


if __name__ == "__main__":
    asyncio.run(main())