# app/routers/admin_calls.py
# OPTIMIZED Admin Call Dashboard API Endpoints with Role-based Access Control
# Uses TATA API server-side filtering - REMOVED Python filtering and debug endpoints

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from ..utils.performance_calculator import performance_calculator
from ..services.tata_admin_service import tata_admin_service
from ..services.analytics_service import analytics_service
from ..services.tata_auth_service import tata_auth_service
from ..services.rbac_service import RBACService
from ..models.admin_dashboard import (
    AdminDashboardResponse, UserPerformanceResponse, PerformanceRankingResponse,
    RecordingPlayResponse, FilterOptionsResponse, DashboardFilters, PlayRecordingRequest,
    CallStatusFilter, CallDirectionFilter, DashboardError,
    ComprehensivePeakHoursResponse, PeakAnsweredHoursResponse, PeakMissedHoursResponse
)
from ..utils.dependencies import get_current_active_user, get_user_with_permission
from ..utils.tata_access_validator import validate_user_tata_access, get_empty_call_response

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize RBAC service
rbac_service = RBACService()

# =============================================================================
# UTILITY FUNCTION FOR ROLE-BASED ACCESS
# =============================================================================

def apply_role_based_user_filter(current_user: Dict, requested_user_id: Optional[str] = None) -> str:
    """
    Apply role-based filtering for user data access
    
    Args:
        current_user: Current authenticated user
        requested_user_id: User ID requested in the API call
        
    Returns:
        str: The user ID that should be used for data filtering
    """
    user_role = current_user.get("role")
    current_user_id = str(current_user.get("_id", ""))
    
    if user_role == "admin":
        # Admins can access any user's data
        return requested_user_id or current_user_id
    else:
        # Regular users can only access their own data
        if requested_user_id and requested_user_id != current_user_id:
            logger.warning(f"User {current_user.get('email')} attempted to access data for user {requested_user_id}")
        return current_user_id

# =============================================================================
# MAIN DASHBOARD ENDPOINT - OPTIMIZED WITH ROLE-BASED ACCESS
# =============================================================================

@router.get("/call-dashboard")
async def get_admin_call_dashboard(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    user_id: Optional[str] = Query(None, description="Individual user ID for detailed view"),
   
    # TATA API Filter Parameters
    agents: Optional[str] = Query(None, description="Comma-separated agent numbers or user IDs"),
    call_type: Optional[str] = Query(None, description="Call type filter: c=answered, m=missed"),
    direction: Optional[str] = Query(None, description="Call direction: inbound/outbound"),
    department: Optional[str] = Query(None, description="Comma-separated department IDs"),
    duration: Optional[str] = Query(None, description="Duration value for filtering"),
    operator: Optional[str] = Query(None, description="Duration operator: >, <, >=, <=, !="),
    callerid: Optional[str] = Query(None, description="Filter by caller ID"),
    destination: Optional[str] = Query(None, description="Filter by destination number"),
    services: Optional[str] = Query(None, description="Comma-separated services"),
    did_number: Optional[str] = Query(None, description="Filter by DID number"),
    broadcast: Optional[str] = Query(None, description="Filter broadcast calls"),
    ivr: Optional[str] = Query(None, description="Comma-separated IVR IDs"),
    
    # Legacy parameters (converted to TATA format)
    user_ids: Optional[str] = Query(None, description="Comma-separated user IDs (converted to agents)"),
    call_status: str = Query("all", description="Call status: all/answered/missed (converted to call_type)"),
    call_direction: str = Query("all", description="Call direction: all/inbound/outbound (converted to direction)"),
    
    # Pagination for tata teli
    limit: int = Query(2000, ge=1, le=500, description="Records per page"),
    page: int = Query(1, ge=1, description="Page number"),
    current_user: Dict = Depends(get_user_with_permission("report.view"))
):
    """
    🔄 RBAC-ENABLED: Admin dashboard using TATA API server-side filtering
    
    **Required Permission:** `report.view`
    
    **Access Levels:**
    - `report.view` - View own call reports
    - `report.view_team` - View team reports
    - `report.view_all` - View all reports (admin)
    """
    try:
        # Check permission levels
        has_view_all = await rbac_service.check_permission(current_user, "report.view_all")
        has_view_team = await rbac_service.check_permission(current_user, "report.view_team")
        
        current_user_id = str(current_user.get("_id", ""))
        
        # Permission-based access control
        if not has_view_all and not has_view_team:
            # Users with only report.view can see their own data
            user_id = current_user_id
            user_ids = current_user_id
            
            logger.info(f"User {current_user.get('email')} accessing own dashboard")
        else:
            logger.info(f"User {current_user.get('email')} accessing full dashboard - Level: {'all' if has_view_all else 'team'}")
        
        # Initialize agent mapping
        await tata_admin_service.initialize_agent_mapping()
        
        # Set default date range
        if not date_from or not date_to:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            date_from = start_date.strftime("%Y-%m-%d")
            date_to = end_date.strftime("%Y-%m-%d")
    
        # Format dates for TATA API
        from_date = f"{date_from} 00:00:00"
        to_date = f"{date_to} 23:59:59"
    
        # Build TATA API query parameters
        tata_params = {
            'from_date': from_date,
            'to_date': to_date,
            'page': str(page),
            'limit': str(limit)
        }
        
        individual_user_filter = None
        filter_info = {"applied": False, "scope": "all_users"}
        
        if user_id:
            # Find user's agent for filtering
            for agent_number, mapping in tata_admin_service.agent_user_mapping.items():
                if mapping.get("user_id") == user_id:
                    individual_user_filter = mapping.get("tata_agent_id")
                    break
            
            if individual_user_filter:
                tata_params['agents'] = individual_user_filter
                filter_info["applied"] = True
                filter_info["scope"] = "individual_user"
                filter_info["user_id"] = user_id
        
        # Convert legacy user_ids to agents parameter with permission-based filtering
        if user_ids and not agents:
            # Check if user_ids is "0" or "all" which means all users
            if user_ids in ["0", "all"] and has_view_all:
                # Only users with view_all can see all users
                logger.info("User with view_all permission requested all users")
            else:
                # Convert internal user IDs to TATA agent IDs
                user_id_list = [uid.strip() for uid in user_ids.split(',')]
                
                # Apply permission-based filtering to user_id_list
                if not has_view_all:
                    user_id_list = [current_user_id]  # Force to current user only
                
                tata_agent_ids = []
                
                for uid in user_id_list:
                    # Find the TATA agent ID for this user
                    for agent_number, mapping in tata_admin_service.agent_user_mapping.items():
                        if mapping.get("user_id") == uid:
                            tata_agent_id = mapping.get("tata_agent_id")
                            if tata_agent_id:
                                tata_agent_ids.append(tata_agent_id)
                                break
                
                # 🔥 CRITICAL SECURITY FIX: Handle non-TATA users
                if not has_view_all and not tata_agent_ids:
                    # Non-TATA users should see NO call data
                    logger.info(f"Non-TATA user {current_user.get('email')} has no call access")
                    return {
                        "success": True,
                        "message": "Call data requires TATA integration",
                        "total_calls": 0,
                        "total_users": 0,
                        "total_recordings": 0,
                        "overall_success_rate": 0.0,
                        "user_stats": [],
                        "recent_calls": [],
                        "top_performers": [],
                        "date_range": f"{date_from} to {date_to}",
                        "data_fetched_at": datetime.utcnow(),
                        "access_level": "non_tata_user",
                        "available_features": ["leads", "tasks", "contacts", "notes"],
                        "restricted_features": ["calls", "analytics", "recordings"],
                        "filters_applied": {
                            "date_from": date_from,
                            "date_to": date_to,
                            "user_restriction": "no_call_access"
                        }
                    }
                
                if tata_agent_ids:
                    agents = ','.join(tata_agent_ids)
                    logger.info(f"Converted user IDs {user_ids} to TATA agent IDs: {agents}")
                else:
                    logger.warning(f"No TATA agent IDs found for user IDs: {user_ids}")
        
        # Convert legacy call_status to call_type
        if call_status != "all" and not call_type:
            call_type = "c" if call_status == "answered" else "m"
        
        # Convert legacy call_direction to direction
        if call_direction != "all" and not direction:
            direction = call_direction
        
        # Apply TATA API filters
        if agents:
            tata_params['agents'] = agents
            
        if call_type:
            tata_params['call_type'] = call_type
            
        if direction:
            tata_params['direction'] = direction
            
        if department:
            tata_params['department'] = department
            
        if duration and operator:
            tata_params['duration'] = duration
            tata_params['operator'] = operator
            
        if callerid:
            tata_params['callerid'] = callerid
            
        if destination:
            tata_params['destination'] = destination
            
        if services:
            tata_params['services'] = services
            
        if did_number:
            tata_params['did_number'] = did_number
            
        if broadcast:
            tata_params['broadcast'] = broadcast
            
        if ivr:
            tata_params['ivr'] = ivr
        
        logger.info(f"TATA API call with params: {tata_params}")
        
        # Make single optimized TATA API call
        tata_response = await tata_admin_service.fetch_call_records_with_filters(
            params=tata_params
        )
        
        if not tata_response.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"TATA API call failed: {tata_response.get('error')}"
            )
        
        # Extract data from TATA response
        tata_data = tata_response.get("data", {})
        call_records = tata_data.get("results", [])
        total_count = tata_data.get("count", 0)
        
        logger.info(f"TATA API returned {len(call_records)} records out of {total_count} total")
        
        # Calculate statistics directly from TATA filtered data
        user_stats_dict = {}

        for record in call_records:
            agent_number = record.get("agent_number", "")
            if not agent_number:
                continue
            
            # Map agent to user
            user_mapping = tata_admin_service.map_agent_to_user(agent_number)
            user_id = user_mapping.get("user_id")
            
            if not user_id or user_id.startswith("unknown_"):
                continue
            
            # Initialize user stats if not exists
            if user_id not in user_stats_dict:
                user_stats_dict[user_id] = {
                    "user_id": user_id,
                    "user_name": user_mapping.get("user_name", "Unknown"),
                    "agent_number": agent_number,
                    "total_calls": 0,
                    "answered_calls": 0,
                    "missed_calls": 0,
                    "total_duration": 0,
                    "recordings_count": 0
                }
            
            # Update stats
            stats = user_stats_dict[user_id]
            stats["total_calls"] += 1
            
            if record.get("status") == "answered":
                stats["answered_calls"] += 1
                stats["total_duration"] += record.get("call_duration", 0)
            else:
                stats["missed_calls"] += 1
            
            if record.get("recording_url"):
                stats["recordings_count"] += 1

        # Calculate success rates and averages
        for user_id, stats in user_stats_dict.items():
            stats["success_rate"] = round(
                (stats["answered_calls"] / stats["total_calls"]) * 100, 2
            ) if stats["total_calls"] > 0 else 0.0
            
            stats["avg_call_duration"] = round(
                stats["total_duration"] / stats["answered_calls"], 2
            ) if stats["answered_calls"] > 0 else 0.0
        
        # Calculate top performers
        top_performers = []
        if user_stats_dict:
            try:
                user_stats_list = list(user_stats_dict.values()) if user_stats_dict else []
                top_performers = performance_calculator.rank_performers(
                    user_stats=user_stats_list,
                    top_n=10
                )
            except Exception as e:
                logger.warning(f"Error calculating top performers: {e}")
        
        # Calculate summary statistics
        total_calls = len(call_records)
        total_answered = sum(1 for r in call_records if r.get("status") == "answered")
        total_recordings = sum(1 for r in call_records if r.get("recording_url"))
        overall_success_rate = (total_answered / total_calls * 100) if total_calls > 0 else 0.0
        
        # Build optimized response
        response_data = {
            "success": True,
            "access_level": "admin" if has_view_all else ("team" if has_view_team else "user"),
            "data_scope": "all_users" if has_view_all else ("team" if has_view_team else "current_user_only"),
            "restricted_to_user": current_user.get("email") if not has_view_all and not has_view_team else None,
            "total_calls": total_calls,
            "total_count_all_pages": total_count,
            "total_users": len(user_stats_dict),
            "total_recordings": total_recordings,
            "overall_success_rate": round(overall_success_rate, 2),
            "user_stats": list(user_stats_dict.values()),
            "top_performers": top_performers,
            "date_range": f"{date_from} to {date_to}",
            "data_fetched_at": datetime.utcnow(),
            "filters_applied": {
                "date_from": date_from,
                "date_to": date_to,
                "tata_filters": {k: v for k, v in tata_params.items() if k not in ['from_date', 'to_date', 'page', 'limit']}
            },
            "optimization_info": {
                "filtering_method": "tata_api_server_side",
                "python_filtering_removed": True,
                "api_calls_made": 1,
                "records_processed": len(call_records)
            }
        }
        
        # Log admin activity
        try:
            await tata_admin_service.log_admin_activity(
                admin_user_id=str(current_user.get("user_id") or current_user.get("_id", "unknown")),
                admin_email=current_user.get("email", "unknown"),
                action="viewed_call_dashboard_optimized",
                details={
                    "date_range": f"{date_from} to {date_to}",
                    "access_level": "admin" if has_view_all else ("team" if has_view_team else "user"),
                    "data_scope": "all_users" if has_view_all else ("team" if has_view_team else "current_user_only"),
                    "total_records": total_calls,
                    "filtering_method": "tata_api_server_side",
                    "filters_used": len([k for k, v in tata_params.items() if k not in ['from_date', 'to_date', 'page', 'limit']])
                }
            )
        except Exception as e:
            logger.warning(f"Error logging admin activity: {e}")
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in optimized admin call dashboard: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "error": str(e),
                "message": "Failed to fetch optimized dashboard data"
            }
        )

@router.get("/recent-calls")
async def get_recent_calls(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=200, description="Records per page"),
    page: int = Query(1, ge=1, description="Page number"),
    user_ids: Optional[str] = Query(None, description="Comma-separated user IDs"),
    call_status: str = Query("all", description="Call status filter"),
    current_user: Dict = Depends(get_user_with_permission("call.history"))
):
    """
    🔄 RBAC-ENABLED: Get recent call records with pagination and filtering
    
    **Required Permission:** `call.history`
    
    **Access Levels:**
    - `call.history` - View own call history
    - `report.view_all` - View all call history
    """
    try:
        # Check permission level
        has_view_all = await rbac_service.check_permission(current_user, "report.view_all")
        current_user_id = str(current_user.get("_id", ""))
        
        # Permission-based filtering
        if not has_view_all:
            # Force non-admin users to see only their own data
            user_ids = current_user_id
            logger.info(f"User {current_user.get('email')} restricted to own recent calls")
        else:
            logger.info(f"User {current_user.get('email')} accessing all recent calls")
        
        await tata_admin_service.initialize_agent_mapping()
        
        # Set default dates
        if not date_from or not date_to:
            today = datetime.now()
            date_from = today.strftime("%Y-%m-%d")
            date_to = today.strftime("%Y-%m-%d")
        
        # Build TATA params
        tata_params = {
            'from_date': f"{date_from} 00:00:00",
            'to_date': f"{date_to} 23:59:59",
            'page': str(page),
            'limit': str(limit)
        }
        
        # Add filters with permission-based restrictions
        if user_ids and user_ids != "all":
            # Convert user IDs to agent IDs
            user_id_list = [uid.strip() for uid in user_ids.split(',')]
            
            # Apply permission-based filtering
            if not has_view_all:
                user_id_list = [current_user_id]
            
            tata_agent_ids = []
            for user_id in user_id_list:
                for agent_number, mapping in tata_admin_service.agent_user_mapping.items():
                    if mapping.get("user_id") == user_id:
                        tata_agent_id = mapping.get("tata_agent_id")
                        if tata_agent_id:
                            tata_agent_ids.append(tata_agent_id)
                        break

            # Handle non-TATA users
            if not has_view_all and not tata_agent_ids:
                # Non-TATA users should see NO call data
                logger.info(f"Non-TATA user {current_user.get('email')} has no call access")
                return {
                    "success": True,
                    "message": "Recent calls require TATA integration",
                    "recent_calls": [],
                    "pagination": {
                        "current_page": page,
                        "limit": limit,
                        "total_pages": 1,
                        "has_more": False,
                        "total_records": 0
                    },
                    "access_level": "non_tata_user",
                    "date_range": f"{date_from} to {date_to}",
                    "retrieved_at": datetime.utcnow()
                }

            if tata_agent_ids:
                tata_params['agents'] = ','.join(tata_agent_ids)
        
        if call_status != "all":
            tata_params['call_type'] = "c" if call_status == "answered" else "m"
        
        # Fetch records
        tata_response = await tata_admin_service.fetch_call_records_with_filters(
            params=tata_params
        )
        
        if not tata_response.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"TATA API call failed: {tata_response.get('error')}"
            )
        
        # Parse records
        tata_data = tata_response.get("data", {})
        call_records = tata_data.get("results", [])
        total_count = tata_data.get("count", 0)
        
        recent_calls = []
        for record in call_records:
            try:
                parsed_record = tata_admin_service.parse_call_record(record)
                recent_calls.append(parsed_record.dict())
            except Exception as e:
                logger.warning(f"Error parsing call record: {e}")
                continue
        
        return {
            "success": True,
            "access_level": "admin" if has_view_all else "user",
            "data_scope": "all_users" if has_view_all else "current_user_only",
            "recent_calls": recent_calls,
            "pagination": {
                "current_page": page,
                "limit": limit,
                "total_pages": (total_count + limit - 1) // limit if total_count > 0 else 1,
                "has_more": page * limit < total_count,
                "total_records": total_count
            },
            "filters_applied": {
                "date_from": date_from,
                "date_to": date_to,
                "user_ids": user_ids,
                "call_status": call_status
            },
            "retrieved_at": datetime.utcnow()
        }
        
    except Exception as e:
        logger.error(f"Error getting recent calls: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch recent calls: {str(e)}"
        )

# =============================================================================
# USER PERFORMANCE ENDPOINT - OPTIMIZED WITH ROLE-BASED ACCESS
# =============================================================================

@router.get("/user-performance/{user_id}")
async def get_user_call_performance(
    user_id: str,
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    include_day_comparison: bool = Query(True, description="Include day-to-day comparison"),
    current_user: Dict = Depends(get_user_with_permission("report.view"))
):
    """
    🔄 RBAC-ENABLED: User performance analytics
    
    **Required Permission:** `report.view`
    
    **Access Control:**
    - Users with `report.view` can view their own performance
    - Users with `report.view_all` can view any user's performance
    """
    try:
        # PERMISSION-BASED ACCESS CONTROL
        has_view_all = await rbac_service.check_permission(current_user, "report.view_all")
        current_user_id = str(current_user.get("user_id") or current_user.get("_id"))
        
        # Apply permission-based filtering
        if not has_view_all:
            # Non-admin users can only view their own performance
            if user_id != current_user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only view your own performance data"
                )
            logger.info(f"User {current_user.get('email')} viewing own performance")
        else:
            logger.info(f"Admin {current_user.get('email')} viewing performance for user: {user_id}")
        
        # Initialize agent mapping
        await tata_admin_service.initialize_agent_mapping()
        
        # Find user's agent number
        user_agent_number = None
        user_name = "Unknown"
        for agent_number, mapping in tata_admin_service.agent_user_mapping.items():
            if mapping.get("user_id") == user_id:
                user_agent_number = mapping.get("tata_agent_id")
                user_name = mapping.get("user_name", "Unknown")
                break
        
        if not user_agent_number:
            raise HTTPException(
                status_code=404,
                detail=f"User {user_id} not found in agent mapping"
            )
        
        # Set default dates to today
        if not date_from:
            date_from = datetime.now().strftime("%Y-%m-%d")
        if not date_to:
            date_to = datetime.now().strftime("%Y-%m-%d")
        
        # Fetch all user records in date range
        all_user_records = await tata_admin_service.fetch_all_user_call_records(
            user_agent_number=user_agent_number,
            from_date=f"{date_from} 00:00:00",
            to_date=f"{date_to} 23:59:59"
        )
        
        # Calculate performance stats
        performance_data = tata_admin_service.calculate_user_performance_from_records(
            user_id=user_id,
            user_name=user_name,
            call_records=all_user_records,
            date_from=date_from,
            date_to=date_to
        )
        
        # Build stats object
        stats = {
            "user_id": user_id,
            "user_name": user_name,
            "agent_number": user_agent_number,
            "daily_calls": performance_data["total_calls"],
            "daily_answered": performance_data["answered_calls"],
            "daily_missed": performance_data["missed_calls"],
            "success_rate": performance_data["success_rate"],
            "avg_call_duration": performance_data["avg_call_duration"]
        }
        
        # Get day comparison if requested
        day_comparison = []
        if include_day_comparison and all_user_records:
            day_comparison = await tata_admin_service.get_day_to_day_comparison(
                user_id=user_id,
                start_date=datetime.strptime(date_from, "%Y-%m-%d"),
                end_date=datetime.strptime(date_to, "%Y-%m-%d")
            )
        
        # Parse call records for response
        call_records_parsed = []
        for record in all_user_records[:10]:  # Limit to recent 10 calls
            try:
                parsed_record = tata_admin_service.parse_call_record(record)
                call_records_parsed.append(parsed_record.dict())
            except Exception as e:
                logger.warning(f"Error parsing call record: {e}")
                continue
        
        # Build response
        response = {
            "success": True,
            "user_id": user_id,
            "user_name": user_name,
            "agent_number": user_agent_number,
            "viewer_access_level": "admin" if has_view_all else "user",
            "can_view_others": has_view_all,
            "stats": stats,
            "day_comparison": day_comparison,
            "call_records": call_records_parsed,
            "ranking": None,
            "period_analyzed": f"Date Range ({date_from} to {date_to})",
            "analysis_date": datetime.utcnow(),
            "optimization_info": {
                "filtering_method": "tata_api_agent_filter",
                "user_records_found": len(all_user_records),
                "agent_number_used": user_agent_number,
                "permission_level": "view_all" if has_view_all else "view_own"
            }
        }
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user performance: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch user performance: {str(e)}"
        )

# =============================================================================
# PERFORMANCE RANKING ENDPOINTS - OPTIMIZED
# =============================================================================

@router.get("/weekly-performers", response_model=PerformanceRankingResponse)
async def get_weekly_performers(
    week_offset: int = Query(0, description="Weeks back from current week (0=current, 1=last week)"),
    top_n: int = Query(10, description="Number of top performers to return"),
    current_user: Dict = Depends(get_user_with_permission("report.view_team"))
):
    """
    🔄 RBAC-ENABLED: Get weekly top performers using TATA API filtering
    
    **Required Permission:** `report.view_team` or `report.view_all`
    """
    try:
        # Permission check is handled by decorator
        # Users with report.view_team or report.view_all can access
        
        # Calculate week dates
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday()) - timedelta(weeks=week_offset)
        week_end = week_start + timedelta(days=6)
        
        # Implementation continues with existing logic...
        # (Keep rest of the function as-is)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting weekly performers: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch weekly performers: {str(e)}"
        )

@router.get("/monthly-performers", response_model=PerformanceRankingResponse)
async def get_monthly_performers(
    year: Optional[int] = Query(None, description="Year (defaults to current year)"),
    month: Optional[int] = Query(None, description="Month 1-12 (defaults to current month)"),
    top_n: int = Query(10, description="Number of top performers to return"),
    current_user: Dict = Depends(get_user_with_permission("report.view_team"))
):
    """
    🔄 RBAC-ENABLED: Get monthly top performers using TATA API filtering
    
    **Required Permission:** `report.view_team` or `report.view_all`
    """
    try:
        # Permission check is handled by decorator
        # Users with report.view_team or report.view_all can access
        
        # Use current month if not specified
        now = datetime.now()
        year = year or now.year
        month = month or now.month
        
        # Validate month
        if not (1 <= month <= 12):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Month must be between 1 and 12"
            )
        
        # Implementation continues with existing logic...
        # (Keep rest of the function as-is)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting monthly performers: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch monthly performers: {str(e)}"
        )

# =============================================================================
# RECORDING MANAGEMENT ENDPOINTS - OPTIMIZED WITH ROLE-BASED ACCESS
# =============================================================================

@router.post("/play-recording")
async def play_user_recording(
    recording_request: PlayRecordingRequest,
    request: Request,
    date_from: Optional[str] = Query(None, description="Dashboard date range start (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Dashboard date range end (YYYY-MM-DD)"),
    current_user: Dict = Depends(get_current_active_user)
):
    """
    OPTIMIZED: Recording access with role-based permissions
    """
    try:
        user_role = current_user.get("role")
        current_user_id = str(current_user.get("_id", ""))
        
        # Role-based access control for recordings
        if user_role != "admin":
            # Non-admin users can only access their own recordings
            if recording_request.user_id != current_user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only access your own call recordings"
                )
            logger.info(f"Non-admin user {current_user.get('email')} accessing own recording")
        else:
            logger.info(f"Admin {current_user.get('email')} requesting recording {recording_request.call_id}")
        
        await tata_admin_service.initialize_agent_mapping()
        
        # Find user details
        user_name = "Unknown"
        user_agent_number = None
        for agent_number, mapping in tata_admin_service.agent_user_mapping.items():
            if mapping.get("user_id") == recording_request.user_id:
                user_name = mapping.get("user_name", "Unknown")
                user_agent_number = mapping.get("tata_agent_id") 
                break
        
        # Use provided date range or smart fallback
        if date_from and date_to:
            # Use exact dashboard date range
            from_date = f"{date_from} 00:00:00"
            to_date = f"{date_to} 23:59:59"
            logger.info(f"Using provided date range: {date_from} to {date_to}")
        else:
            # Smart fallback: try recent dates first
            today = datetime.now()
            from_date = today.strftime("%Y-%m-%d 00:00:00")
            to_date = today.strftime("%Y-%m-%d 23:59:59")
            logger.info(f"Using today's date as fallback: {today.strftime('%Y-%m-%d')}")
        
        search_id = recording_request.call_id
        
        # Progressive search strategies (much more efficient)
        strategies = []
        
        if date_from and date_to:
            # If date range provided, search only that range
            strategies = [
                {
                    'from_date': from_date,
                    'to_date': to_date,
                    'page': '1',
                    'limit': '500'
                }
            ]
        else:
            # Progressive fallback for unknown date ranges
            today = datetime.now()
            strategies = [
                # Strategy 1: Today only
                {
                    'from_date': today.strftime("%Y-%m-%d 00:00:00"),
                    'to_date': today.strftime("%Y-%m-%d 23:59:59"),
                    'page': '1',
                    'limit': '200'
                },
                # Strategy 2: Last 3 days
                {
                    'from_date': (today - timedelta(days=3)).strftime("%Y-%m-%d 00:00:00"),
                    'to_date': today.strftime("%Y-%m-%d 23:59:59"),
                    'page': '1',
                    'limit': '500'
                },
                # Strategy 3: Last 7 days
                {
                    'from_date': (today - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00"),
                    'to_date': today.strftime("%Y-%m-%d 23:59:59"),
                    'page': '1',
                    'limit': '1000'
                }
            ]
        
        target_call = None
        for i, tata_params in enumerate(strategies):
            logger.info(f"Trying search strategy {i+1}: {tata_params}")
            
            tata_response = await tata_admin_service.fetch_call_records_with_filters(
                params=tata_params
            )
            
            if tata_response.get("success"):
                all_records = tata_response.get("data", {}).get("results", [])
                logger.info(f"Strategy {i+1} returned {len(all_records)} records")
                
                # Search through results for matching call ID
                for record in all_records:
                    if (record.get("id") == search_id or 
                        record.get("call_id") == search_id or 
                        record.get("uuid") == search_id):
                        target_call = record
                        logger.info(f"Found call using strategy {i+1}: {record.get('id')}")
                        break
                
                if target_call:
                    break
            else:
                logger.warning(f"Strategy {i+1} failed: {tata_response.get('error')}")
        
        if not target_call:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "call_not_found",
                    "message": f"Call {recording_request.call_id} not found in date range",
                    "searched_date_range": f"{date_from or 'recent days'} to {date_to or 'today'}",
                    "strategies_tried": len(strategies),
                    "suggestion": "Call might be outside the searched date range"
                }
            )
        
        recording_url = target_call.get("recording_url")
        
        if not recording_url:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "no_recording",
                    "message": f"No recording available for call {recording_request.call_id}",
                    "call_info": {
                        "id": target_call.get("id"),
                        "date": target_call.get("date"),
                        "time": target_call.get("time"),
                        "status": target_call.get("status"),
                        "agent": target_call.get("agent_name")
                    }
                }
            )
        
        # Log activity
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        
        await tata_admin_service.log_admin_activity(
            admin_user_id=str(current_user.get("user_id") or current_user.get("_id")),
            admin_email=current_user.get("email"),
            action="played_recording",
            target_user_id=recording_request.user_id,
            target_user_name=user_name,
            details={
                "call_id": recording_request.call_id,
                "reason": recording_request.reason,
                "recording_url": recording_url,
                "call_date": target_call.get("date"),
                "call_time": target_call.get("time"),
                "call_duration": target_call.get("call_duration", 0),
                "agent_name": target_call.get("agent_name"),
                "search_date_range": f"{date_from or 'recent'} to {date_to or 'today'}",
                "access_level": user_role
            },
            ip_address=client_ip,
            user_agent=user_agent
        )
        
        return {
            "success": True,
            "message": "Recording access granted",
            "recording_url": recording_url,
            "call_id": recording_request.call_id,
            "access_level": user_role,
            "call_info": {
                "date": target_call.get("date"),
                "time": target_call.get("time"),
                "duration": target_call.get("call_duration", 0),
                "status": target_call.get("status"),
                "agent_name": target_call.get("agent_name"),
                "client_number": target_call.get("client_number")
            },
            "access_logged": True,
            "expires_at": datetime.utcnow() + timedelta(hours=1),
            "accessed_by": current_user.get("email"),
            "access_reason": recording_request.reason
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error playing recording: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to access recording: {str(e)}"
        )

@router.get("/user-recordings/{user_id}")
async def get_user_recordings(
    user_id: str,
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(20, ge=1, le=100, description="Records per page"),
    page: int = Query(1, ge=1, description="Page number"),
    current_user: Dict = Depends(get_current_active_user)
):
    """
    Get user recordings using TATA API agent filtering with role-based access
    """
    try:
        user_role = current_user.get("role")
        current_user_id = str(current_user.get("_id", ""))
        
        # Role-based access control
        if user_role != "admin":
            # Non-admin users can only view their own recordings
            if user_id != current_user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only view your own recordings"
                )
            logger.info(f"Non-admin user {current_user.get('email')} viewing own recordings")
        else:
            logger.info(f"Admin {current_user.get('email')} requesting recordings for user {user_id}")
        
        # Initialize agent mapping
        await tata_admin_service.initialize_agent_mapping()
        
        # Find user's agent number
        user_agent_number = None
        user_name = "Unknown"
        for agent_number, mapping in tata_admin_service.agent_user_mapping.items():
            if mapping.get("user_id") == user_id:
                user_agent_number = mapping.get("tata_agent_id")
                user_name = mapping.get("user_name", "Unknown")
                break
        
        if not user_agent_number:
            available_users = [
                {"user_id": m["user_id"], "user_name": m["user_name"]}
                for m in tata_admin_service.agent_user_mapping.values()
                if m.get("user_id") and m.get("user_name")
            ]
            
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "user_not_found",
                    "message": f"User {user_id} not found in agent mapping",
                    "available_users": available_users[:10] if user_role == "admin" else []
                }
            )
        
        # Set default date range
        if not date_from or not date_to:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            date_from = start_date.strftime("%Y-%m-%d")
            date_to = end_date.strftime("%Y-%m-%d")
        
        # Format dates
        from_date = f"{date_from} 00:00:00"
        to_date = f"{date_to} 23:59:59"
        
        logger.info(f"Fetching recordings for {user_name} ({user_agent_number})")
        
        # Use TATA API with agent filter
        tata_params = {
            'from_date': from_date,
            'to_date': to_date,
            'agents': user_agent_number,
            'page': str(page),
            'limit': str(limit * 2)  # Get more records since not all have recordings
        }
        
        tata_response = await tata_admin_service.fetch_call_records_with_filters(
            params=tata_params
        )
        
        if not tata_response.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"TATA API call failed: {tata_response.get('error')}"
            )
        
        # Extract and filter for recordings only
        tata_data = tata_response.get("data", {})
        all_records = tata_data.get("results", [])
        
        # Filter only records with recordings
        recordings_only = [
            record for record in all_records 
            if record.get("recording_url")
        ]
        
        # Apply pagination to recordings
        start_index = (page - 1) * limit
        end_index = start_index + limit
        paginated_recordings = recordings_only[start_index:end_index]
        
        # Process recordings
        formatted_recordings = []
        for record in paginated_recordings:
            try:
                recording_info = {
                    "call_id": record.get("id") or record.get("call_id"),
                    "uuid": record.get("uuid"),
                    "recording_url": record.get("recording_url"),
                    "date": record.get("date"),
                    "time": record.get("time"),
                    "call_duration": record.get("call_duration", 0),
                    "answered_seconds": record.get("answered_seconds", 0),
                    "direction": record.get("direction"),
                    "status": record.get("status"),
                    "client_number": record.get("client_number"),
                    "agent_name": record.get("agent_name"),
                    "service": record.get("service"),
                    "hangup_cause": record.get("hangup_cause"),
                    "description": record.get("description"),
                    "call_quality": "good" if record.get("call_duration", 0) > 30 else "short",
                    "has_recording": True,
                    "created_at": f"{record.get('date')} {record.get('time')}",
                    "circle": record.get("circle", {})
                }
                formatted_recordings.append(recording_info)
            except Exception as e:
                logger.warning(f"Error formatting recording: {e}")
                continue
        
        # Calculate statistics
        total_recordings = len(recordings_only)
        total_duration = sum(r["call_duration"] for r in formatted_recordings)
        avg_duration = total_duration / len(formatted_recordings) if formatted_recordings else 0
        answered_recordings = [r for r in formatted_recordings if r["status"] == "answered"]
        
        # Build response
        response = {
            "success": True,
            "user_id": user_id,
            "user_name": user_name,
            "agent_number": user_agent_number,
            "viewer_role": user_role,
            "recordings": formatted_recordings,
            "pagination": {
                "current_page": page,
                "limit": limit,
                "total_recordings": total_recordings,
                "total_pages": (total_recordings + limit - 1) // limit if total_recordings > 0 else 1,
                "has_more": end_index < total_recordings,
                "has_previous": page > 1
            },
            "statistics": {
                "recordings_on_this_page": len(formatted_recordings),
                "total_recordings_found": total_recordings,
                "total_duration_minutes": round(total_duration / 60, 2),
                "average_duration_seconds": round(avg_duration, 2),
                "answered_recordings": len(answered_recordings)
            },
            "query_info": {
                "date_range": f"{date_from} to {date_to}",
                "filtering_method": "tata_api_agent_filter",
                "user_agent_number": user_agent_number
            },
            "retrieved_at": datetime.utcnow()
        }
        
        # Log activity
        await tata_admin_service.log_admin_activity(
            admin_user_id=str(current_user.get("user_id") or current_user.get("_id")),
            admin_email=current_user.get("email"),
            action="viewed_user_recordings",
            target_user_id=user_id,
            target_user_name=user_name,
            details={
                "date_range": f"{date_from} to {date_to}",
                "page": page,
                "recordings_returned": len(formatted_recordings),
                "filtering_method": "tata_api_agent_filter",
                "access_level": user_role
            }
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user recordings: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch user recordings: {str(e)}"
        )

@router.get("/recording/{call_id}")
async def get_recording_details(
    call_id: str,
    current_user: Dict = Depends(get_current_active_user)
):
    """
    Get recording details using TATA API call_id filter with role-based access
    """
    try:
        user_role = current_user.get("role")
        logger.info(f"User {current_user.get('email')} requesting recording details for {call_id} - Role: {user_role}")
        
        # Use TATA API to search by call_id
        today = datetime.now()
        from_date = (today - timedelta(days=30)).strftime("%Y-%m-%d 00:00:00")
        to_date = today.strftime("%Y-%m-%d 23:59:59")
        
        tata_params = {
            'from_date': from_date,
            'to_date': to_date,
            'call_id': call_id,
            'page': '1',
            'limit': '1'
        }
        
        tata_response = await tata_admin_service.fetch_call_records_with_filters(
            params=tata_params
        )
        
        if not tata_response.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"TATA API search failed: {tata_response.get('error')}"
            )
        
        # Extract call record
        tata_data = tata_response.get("data", {})
        call_records = tata_data.get("results", [])
        
        if not call_records:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "call_not_found",
                    "message": f"Call {call_id} not found",
                    "suggestion": "Call might be older than 30 days or call ID is incorrect"
                }
            )
        
        target_call = call_records[0]
        recording_url = target_call.get("recording_url")
        
        # Find associated user and apply role-based access
        agent_number = target_call.get("agent_number")
        user_info = {"user_id": "unknown", "user_name": "Unknown"}
        
        await tata_admin_service.initialize_agent_mapping()
        for agent, mapping in tata_admin_service.agent_user_mapping.items():
            if agent == agent_number:
                user_info = {
                    "user_id": mapping.get("user_id", "unknown"),
                    "user_name": mapping.get("user_name", "Unknown")
                }
                break
        
        # Role-based access control
        if user_role != "admin":
            current_user_id = str(current_user.get("_id", ""))
            if user_info["user_id"] != current_user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only view details of your own call recordings"
                )
        
        if not recording_url:
            return {
                "success": True,
                "has_recording": False,
                "message": "Call found but no recording available",
                "viewer_role": user_role,
                "call_info": {
                    "call_id": target_call.get("id"),
                    "date": target_call.get("date"),
                    "time": target_call.get("time"),
                    "status": target_call.get("status"),
                    "duration": target_call.get("call_duration", 0)
                }
            }
        
        return {
            "success": True,
            "has_recording": True,
            "recording_url": recording_url,
            "viewer_role": user_role,
            "call_details": {
                "call_id": target_call.get("id"),
                "uuid": target_call.get("uuid"),
                "date": target_call.get("date"),
                "time": target_call.get("time"),
                "duration": target_call.get("call_duration", 0),
                "answered_seconds": target_call.get("answered_seconds", 0),
                "direction": target_call.get("direction"),
                "status": target_call.get("status"),
                "service": target_call.get("service"),
                "agent_name": target_call.get("agent_name"),
                "agent_number": agent_number,
                "client_number": target_call.get("client_number"),
                "did_number": target_call.get("did_number"),
                "hangup_cause": target_call.get("hangup_cause"),
                "description": target_call.get("description"),
                "circle": target_call.get("circle")
            },
            "user_info": user_info,
            "recording_info": {
                "recording_url": recording_url,
                "estimated_duration": target_call.get("call_duration", 0),
                "recording_quality": "good" if target_call.get("call_duration", 0) > 30 else "short",
                "file_format": "audio/wav",
                "can_download": True
            },
            "retrieved_at": datetime.utcnow()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting recording details: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get recording details: {str(e)}"
        )

# =============================================================================
# FILTER OPTIONS ENDPOINT - ROLE-BASED USER LIST
# =============================================================================

@router.get("/filter-options", response_model=FilterOptionsResponse)
async def get_filter_options(
    current_user: Dict = Depends(get_current_active_user)
):
    """Get available filter options with role-based user list"""
    try:
        user_role = current_user.get("role")
        available_users = []
        
        if user_role == "admin":
            # Admins see all users
            await tata_admin_service.initialize_agent_mapping()
            available_users = [
                {"user_id": mapping["user_id"], "user_name": mapping["user_name"]}
                for mapping in tata_admin_service.agent_user_mapping.values()
            ]
            logger.info(f"Admin {current_user.get('email')} - showing all {len(available_users)} users")
        else:
            # Regular users see only themselves
            available_users = [{
                "user_id": str(current_user.get("_id", "")),
                "user_name": f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip() or current_user.get('email', 'Me')
            }]
            logger.info(f"Regular user {current_user.get('email')} - showing only own profile")
        
        # Set date ranges
        today = datetime.now()
        min_date = (today - timedelta(days=90)).strftime("%Y-%m-%d")
        max_date = today.strftime("%Y-%m-%d")
        
        return FilterOptionsResponse(
            success=True,
            available_users=available_users,
            min_date=min_date,
            max_date=max_date,
            call_statuses=["all", "answered", "missed"],
            call_directions=["all", "inbound", "outbound"],
        )
        
    except Exception as e:
        logger.error(f"Error getting filter options: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch filter options: {str(e)}"
        )

# =============================================================================
# SUMMARY STATISTICS ENDPOINT - ROLE-BASED DATA ACCESS
# =============================================================================

@router.get("/summary-stats")
async def get_summary_statistics(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    user_ids: Optional[str] = Query(None, description="Comma-separated user IDs to filter"),
    user_id: Optional[str] = Query(None, description="Individual user ID for detailed view"),
    charts: Optional[str] = Query("all", description="Comma-separated chart types: gauge,scatter,historical trends,heatmap,duration,peaks,forecast,matrix"),
    current_user: Dict = Depends(get_current_active_user)
):
    """Get summary statistics with comprehensive peak hours analysis and role-based access control"""
    try:
        user_role = current_user.get("role")
        current_user_id = str(current_user.get("_id", ""))
        
        # Role-based data filtering
        if user_role != "admin":
            # Non-admin users can only see their own data
            user_ids = current_user_id  # Force to current user only
            user_id = current_user_id   # Force to current user only
            logger.info(f"Non-admin user {current_user.get('email')} restricted to own data")
        else:
            logger.info(f"Admin user {current_user.get('email')} accessing summary statistics")
        
        filter_info = {"applied": False, "scope": "all_users"}
        logger.info(f"User {current_user.get('email')} requesting summary statistics - Role: {user_role}")
        
        # Initialize agent mapping
        await tata_admin_service.initialize_agent_mapping()
        
        # Set default date to today only
        if not date_from or not date_to:
            today = datetime.now()
            date_from = today.strftime("%Y-%m-%d")
            date_to = today.strftime("%Y-%m-%d")
        
        # Format for TATA API
        from_date = f"{date_from} 00:00:00"
        to_date = f"{date_to} 23:59:59"
        
        # Build TATA params - Default: fetch ALL records or user-specific
        tata_params = {
            'from_date': from_date,
            'to_date': to_date,
            'page': '1',
            'limit': '2000'  # Increased limit for better analysis
        }
        
        # Apply user filtering with role-based restrictions
        if user_ids:
            user_list = [uid.strip() for uid in user_ids.split(",")]
            
            # Apply role-based filtering to user list
            if user_role != "admin":
                user_list = [current_user_id]  # Override with current user only
            
            agent_ids = []
            
            # Map user_ids to agent_numbers
            for user_id_item in user_list:
                for _, mapping in tata_admin_service.agent_user_mapping.items():
                    if mapping.get("user_id") == user_id_item:
                        tata_agent_id = mapping.get("tata_agent_id")
                        if tata_agent_id:
                            agent_ids.append(tata_agent_id)
                        break

            # Only apply agent filter if we found matching agent numbers
            if agent_ids:
                tata_params['agents'] = ",".join(agent_ids)
                filter_info = {
                    "applied": True,
                    "scope": "filtered_users" if user_role == "admin" else "current_user_only",
                    "user_count": len(user_list),
                    "user_ids": user_list,
                    "agent_id": agent_ids,
                    "role_restricted": user_role != "admin"
                }
                logger.info(f"Filtering summary stats for users: {user_list} -> agents: {agent_ids}")
            else:
                logger.warning(f"No agent numbers found for user_ids: {user_list}")
                
                # 🔥 CRITICAL SECURITY FIX: Handle non-TATA users
                if user_role != "admin":
                    # Non-TATA users should see NO call data
                    logger.info(f"Non-TATA user {current_user.get('email')} has no call access - returning empty stats")
                    return {
                        "success": True,
                        "message": "Call statistics require TATA integration",
                        "total_calls": 0,
                        "total_answered": 0,
                        "total_missed": 0,
                        "success_rate": 0.0,
                        "user_stats": [],
                        "peak_hours": {"answered": [], "missed": []},
                        "trends": {"trend": "no_data", "change_percent": 0.0},
                        "performance_summary": {
                            "total_users": 0,
                            "avg_success_rate": 0.0,
                            "total_talk_time": 0
                        },
                        "access_level": "non_tata_user",
                        "date_range": f"{date_from} to {date_to}",
                        "calculated_at": datetime.utcnow(),
                        "filter_info": {
                            "applied": True,
                            "scope": "no_call_access",
                            "user_restriction": "non_tata_user"
                        }
                    }
                
                filter_info = {
                    "applied": False,
                    "scope": "all_users" if user_role == "admin" else "current_user_only",
                    "warning": f"No agents found for provided user_ids: {user_list}",
                    "role_restricted": user_role != "admin"
                }
        
        # Use TATA API to fetch summary data
        tata_response = await tata_admin_service.fetch_call_records_with_filters(
            params=tata_params
        )
        
        if not tata_response.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"TATA API call failed: {tata_response.get('error')}"
            )
        
        # Extract call records
        tata_data = tata_response.get("data", {})
        call_records = tata_data.get("results", [])
        total_count = tata_data.get("count", 0)
        
        logger.info(f"Analyzing {len(call_records)} call records - Scope: {filter_info.get('scope')}")
        
        # Calculate basic statistics
        total_calls = len(call_records)
        total_answered = sum(1 for r in call_records if r.get("status") == "answered")
        total_missed = total_calls - total_answered
        total_duration = sum(r.get("call_duration", 0) for r in call_records if r.get("status") == "answered")
        total_recordings = sum(1 for r in call_records if r.get("recording_url"))
        # Get unique users
        unique_agents = set(r.get("agent_number") for r in call_records if r.get("agent_number"))
        unique_users = len(unique_agents)
        
        # Calculate number of days in the date range
        date_range_start = datetime.strptime(date_from, "%Y-%m-%d")
        date_range_end = datetime.strptime(date_to, "%Y-%m-%d")
        days_in_range = (date_range_end - date_range_start).days + 1
        
        # Calculate averages
        avg_calls_per_day = total_calls / days_in_range if total_calls > 0 and days_in_range > 0 else 0
        avg_duration = total_duration / total_answered if total_answered > 0 else 0
        success_rate = (total_answered / total_calls * 100) if total_calls > 0 else 0
        
        # Calculate trends
        trend_data = performance_calculator.calculate_trend_analysis(call_records, days_in_range)
        
        # Calculate comprehensive peak hours analysis
        comprehensive_peak_hours = performance_calculator.calculate_comprehensive_peak_hours(
            call_records=call_records
        )

        basic_peak_hours = performance_calculator.calculate_peak_hours(call_records)
    
        # Combine peak hours data
        combined_peak_hours = {
            # Basic peak hours data (existing structure)
            "peak_hours": basic_peak_hours.get("peak_hours", []),
            "total_calls": basic_peak_hours.get("total_calls", total_calls),
            "hourly_distribution": basic_peak_hours.get("hourly_distribution", {}),
            
            # Comprehensive analysis data
            "peak_answered_hours": comprehensive_peak_hours.get("peak_answered_hours", []),
            "peak_missed_hours": comprehensive_peak_hours.get("peak_missed_hours", []),
            "insights": {
                "best_calling_time": comprehensive_peak_hours.get("analysis_metadata", {}).get("most_active_hour"),
                "best_answer_time": comprehensive_peak_hours.get("analysis_metadata", {}).get("best_answer_hour"), 
                "worst_miss_time": comprehensive_peak_hours.get("analysis_metadata", {}).get("worst_miss_hour"),
                "overall_answer_rate": round(success_rate, 2)
            },
            "analysis_metadata": comprehensive_peak_hours.get("analysis_metadata", {})
        }
        
        chart_data = {}
        
        user_stats_dict = {}

        # Process call records to build user statistics (add this entire block)
        for record in call_records:
            agent_number = record.get("agent_number", "")
            if not agent_number:
                continue
            
            # Map agent to user
            user_mapping = tata_admin_service.map_agent_to_user(agent_number)
            user_id = user_mapping.get("user_id")
            
            if not user_id or user_id.startswith("unknown_"):
                continue
            
            # Initialize user stats if not exists
            if user_id not in user_stats_dict:
                user_stats_dict[user_id] = {
                    "user_id": user_id,
                    "user_name": user_mapping.get("user_name", "Unknown"),
                    "agent_number": agent_number,
                    "total_calls": 0,
                    "answered_calls": 0,
                    "missed_calls": 0,
                    "total_duration": 0,
                    "recordings_count": 0
                }
            
            # Update stats
            stats = user_stats_dict[user_id]
            stats["total_calls"] += 1
            
            if record.get("status") == "answered":
                stats["answered_calls"] += 1
                stats["total_duration"] += record.get("call_duration", 0)
            else:
                stats["missed_calls"] += 1
            
            if record.get("recording_url"):
                stats["recordings_count"] += 1

        # Calculate success rates
        for user_id, stats in user_stats_dict.items():
            stats["success_rate"] = round(
                (stats["answered_calls"] / stats["total_calls"]) * 100, 2
            ) if stats["total_calls"] > 0 else 0.0
            
            stats["avg_call_duration"] = round(
                stats["total_duration"] / stats["answered_calls"], 2
            ) if stats["answered_calls"] > 0 else 0.0

        requested_charts = [c.strip() for c in charts.split(",")] if charts and charts != "all" else [
            "gauge", "scatter", "trends", "heatmap", "duration", "peaks", "matrix"
        ]

        if "gauge" in requested_charts:
            trend_data["performance_gauge"] = analytics_service.calculate_performance_gauge(
                current_success_rate=success_rate,
                previous_period_rate=None
            )

        if "scatter" in requested_charts:
    # Only generate scatter plot if there are multiple users (for admins) or single user data
            if user_role == "admin" and not user_id:
                # Team scatter plot for admins
                trend_data["volume_efficiency_scatter"] = analytics_service.generate_scatter_plot_data(
                    list(user_stats_dict.values()) if user_stats_dict else []
                )
            elif user_role != "admin":
                # Individual user scatter plot data
                trend_data["volume_efficiency_scatter"] = analytics_service.generate_scatter_plot_data(
                    list(user_stats_dict.values()) if user_stats_dict else []
                )

        if "trends" in requested_charts:
            trend_data["temporal_trends"] = analytics_service.calculate_temporal_trends(
                call_records=call_records,
                date_from=date_from,
                date_to=date_to
            )

        if "heatmap" in requested_charts:
            trend_data["hourly_heatmap"] = analytics_service.generate_hourly_heatmap(call_records)

        if "duration" in requested_charts:
            trend_data["duration_distribution"] = analytics_service.calculate_duration_distribution(call_records)

        if "peaks" in requested_charts:
            trend_data["peak_hours_analysis"] = analytics_service.analyze_peak_hours(call_records)

        if "trends" in requested_charts and trend_data.get("temporal_trends"):
            trend_data["historical_analysis"] = analytics_service.calculate_historical_trends(
                trend_data["temporal_trends"]["daily_series"]
            )

        if "matrix" in requested_charts:
            if user_role == "admin" and not user_id:
                # Team matrix for admins viewing all users
                trend_data["efficiency_matrix"] = analytics_service.calculate_efficiency_matrix(
                    list(user_stats_dict.values()) if user_stats_dict else []
                )
            elif user_role != "admin":
                # Individual user matrix (might be simplified for single user)
                trend_data["efficiency_matrix"] = analytics_service.calculate_efficiency_matrix(
                    list(user_stats_dict.values()) if user_stats_dict else []
                )

        # Add metadata about available charts
        trend_data["charts_available"] = list(requested_charts)
        trend_data["view_type"] = "individual" if user_id else "team"


        # Build response
        response_data = {
            "success": True,
            "user_role": user_role,
            "date_range": f"{date_from} to {date_to}",
            "filter_info": filter_info,
            "summary": {
                "total_calls": total_calls,
                "total_calls_all_pages": total_count,
                "total_answered": total_answered,
                "total_missed": total_missed,
                "total_duration_minutes": round(total_duration / 60, 2),
                "total_recordings": total_recordings,
                "unique_users": unique_users,
                "success_rate": round(success_rate, 2),
                "avg_calls_per_day": round(avg_calls_per_day, 2),
                "avg_call_duration_seconds": round(avg_duration, 2)
            },
            "trends": trend_data,
            "peak_hours": combined_peak_hours,
            "optimization_info": {
                "filtering_method": "tata_api_server_side",
                "records_analyzed": total_calls,
                "total_available": total_count,
                "role_based_filtering": user_role != "admin"  
            },
            "calculated_at": datetime.utcnow()
        }
        
        # Log activity
        await tata_admin_service.log_admin_activity(
            admin_user_id=str(current_user.get("user_id") or current_user.get("_id", "unknown")),
            admin_email=current_user.get("email", "unknown"),
            action="viewed_summary_statistics_with_comprehensive_peak_hours",
            details={
                "date_range": f"{date_from} to {date_to}",
                "total_calls_analyzed": total_calls,
                "scope": filter_info.get("scope", "all_users"),
                "user_filter_applied": filter_info.get("applied", False),
                "filtered_user_count": filter_info.get("user_count", 0),
                "filtering_method": "tata_api_server_side",
                "days_in_range": days_in_range
            }
        )
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting summary statistics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch summary statistics: {str(e)}"
        )

# =============================================================================
# EXPORT ENDPOINT - OPTIMIZED
# =============================================================================

@router.get("/export-call-data")
async def export_call_data(
    date_from: str = Query(..., description="Start date (YYYY-MM-DD)"),
    date_to: str = Query(..., description="End date (YYYY-MM-DD)"),
    format: str = Query("json", description="Export format (json, csv)"),
    user_ids: Optional[str] = Query(None, description="Comma-separated user IDs"),
    call_type: Optional[str] = Query(None, description="Call type filter"),
    direction: Optional[str] = Query(None, description="Direction filter"),
    current_user: Dict = Depends(get_current_active_user)
):
    """Export call data using TATA API filtering"""
    try:
        logger.info(f"Admin {current_user['email']} exporting call data")
        
        # Format dates
        from_date = f"{date_from} 00:00:00"
        to_date = f"{date_to} 23:59:59"
        
        # Build TATA params for export
        tata_params = {
            'from_date': from_date,
            'to_date': to_date,
            'page': '1',
            'limit': '5000'  # Limit for exports
        }
        
        # Apply user filters
        if user_ids:
            await tata_admin_service.initialize_agent_mapping()
            user_list = [uid.strip() for uid in user_ids.split(",")]
            agent_numbers = []
            for user_id in user_list:
                for agent_number, mapping in tata_admin_service.agent_user_mapping.items():
                    if mapping.get("user_id") == user_id:
                        agent_numbers.append(agent_number)
            if agent_numbers:
                tata_params['agents'] = ",".join(agent_numbers)
        
        if call_type:
            tata_params['call_type'] = call_type
        
        if direction:
            tata_params['direction'] = direction
        
        # Fetch records using TATA API
        tata_response = await tata_admin_service.fetch_call_records_with_filters(
            params=tata_params
        )
        
        if not tata_response.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"TATA API call failed: {tata_response.get('error')}"
            )
        
        # Extract and parse records
        tata_data = tata_response.get("data", {})
        call_records = tata_data.get("results", [])
        
        parsed_records = []
        for record in call_records:
            try:
                parsed_record = tata_admin_service.parse_call_record(record)
                parsed_records.append(parsed_record.dict())
            except Exception as e:
                logger.warning(f"Error parsing record for export: {e}")
                continue
        
        # Log admin activity
        await tata_admin_service.log_admin_activity(
            admin_user_id=str(current_user.get("user_id") or current_user.get("_id")),
            admin_email=current_user["email"],
            action="exported_call_data_optimized",
            details={
                "date_range": f"{date_from} to {date_to}",
                "format": format,
                "record_count": len(parsed_records),
                "user_filter": user_ids,
                "filtering_method": "tata_api_server_side"
            }
        )
        
        if format.lower() == "csv":
            # Convert to CSV format
            import csv
            import io
            
            output = io.StringIO()
            if parsed_records:
                fieldnames = parsed_records[0].keys()
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(parsed_records)
            
            from fastapi.responses import Response
            return Response(
                content=output.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename=call_data_{date_from}_to_{date_to}.csv"}
            )
        else:
            # Return JSON
            return {
                "success": True,
                "export_format": format,
                "date_range": f"{date_from} to {date_to}",
                "record_count": len(parsed_records),
                "filtering_method": "tata_api_server_side",
                "data": parsed_records,
                "exported_at": datetime.utcnow()
            }
        
    except Exception as e:
        logger.error(f"Error exporting call data: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to export call data: {str(e)}"
        )

# =============================================================================
# ADMIN ACTIVITY LOGS ENDPOINT
# =============================================================================

@router.get("/admin-activity-logs")
async def get_admin_activity_logs(
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    action_type: Optional[str] = Query(None, description="Filter by action type"),
    limit: int = Query(50, description="Maximum records to return"),
    current_user: Dict = Depends(get_current_active_user)
):
    """Get admin activity logs for auditing purposes"""
    try:
        # Set default date range
        if not date_from or not date_to:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            date_from = start_date.strftime("%Y-%m-%d")
            date_to = end_date.strftime("%Y-%m-%d")
        
        # Query admin activity logs from database
        db = tata_admin_service._get_db()
        if not db:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database not available"
            )
        
        # Build query
        query = {
            "timestamp": {
                "$gte": datetime.strptime(f"{date_from} 00:00:00", "%Y-%m-%d %H:%M:%S"),
                "$lte": datetime.strptime(f"{date_to} 23:59:59", "%Y-%m-%d %H:%M:%S")
            }
        }
        
        if action_type:
            query["action"] = action_type
        
        # Fetch logs
        logs_cursor = db.admin_activity_logs.find(query).sort("timestamp", -1).limit(limit)
        logs = await logs_cursor.to_list(length=limit)
        
        # Convert ObjectId to string
        for log in logs:
            log["_id"] = str(log["_id"])
        
        return {
            "success": True,
            "date_range": f"{date_from} to {date_to}",
            "action_filter": action_type,
            "log_count": len(logs),
            "logs": logs,
            "retrieved_at": datetime.utcnow()
        }
        
    except Exception as e:
        logger.error(f"Error fetching admin activity logs: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch activity logs: {str(e)}"
        )