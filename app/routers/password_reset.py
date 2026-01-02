# app/routers/password_reset.py
# Password Reset API Endpoints for LeadG CRM
# Handles both user self-service and admin-initiated password resets

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from typing import Dict, Any, Optional
import logging
from datetime import datetime

from ..services.password_reset_service import password_reset_service
from ..utils.dependencies import get_admin_user, get_current_active_user
from ..models.password_reset import (
    ForgotPasswordRequest, ForgotPasswordResponse,
    ResetPasswordRequest, ResetPasswordResponse,
    AdminResetPasswordRequest, AdminResetPasswordResponse,
    ValidateResetTokenResponse, PasswordResetStats,
    ResetMethod, ResetTokenInfo
)

logger = logging.getLogger(__name__)

# Create router with tags
router = APIRouter(tags=["Password Reset"])

def get_client_ip(request: Request) -> str:
    """Extract client IP address from request"""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def get_user_agent(request: Request) -> str:
    """Extract user agent from request"""
    return request.headers.get("user-agent", "unknown")

# ============================================================================
# USER SELF-SERVICE ENDPOINTS (Public - No Auth Required)
# ============================================================================

@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    request: Request,
    forgot_request: ForgotPasswordRequest
):
    """
    🔓 **PUBLIC ENDPOINT** - User forgot password request
    
    **Features:**
    - Email enumeration protection (always returns success message)
    - Rate limiting (5 attempts per user per day)
    - IP-based rate limiting for additional security
    - Secure token generation with 30-minute expiration
    - Automatic email sending with reset link
    
    **Security:**
    - No authentication required
    - Logs IP address and user agent for security
    - Always returns same success message regardless of email validity
    """
    try:
        # Extract security information
        ip_address = get_client_ip(request)
        user_agent = get_user_agent(request)
        
        logger.info(f"Password reset requested for email: {forgot_request.email} from IP: {ip_address}")
        
        # Process forgot password request
        result = await password_reset_service.forgot_password(
            email=forgot_request.email,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error in forgot password endpoint: {e}")
        # Return generic error to prevent information disclosure
        return ForgotPasswordResponse(
            success=False,
            message="An unexpected error occurred. Please try again later.",
            email_sent=False
        )

@router.get("/validate-token", response_model=ValidateResetTokenResponse)
async def validate_reset_token(
    token: str = Query(..., description="Password reset token to validate")
):
    """
    🔓 **PUBLIC ENDPOINT** - Validate password reset token
    
    **Purpose:**
    - Frontend calls this before showing password reset form
    - Checks if token is valid, not expired, and not already used
    - Returns token information without exposing sensitive data
    
    **Security:**
    - No authentication required
    - Token validation only (no sensitive operations)
    - Prevents expired token submission attempts
    """
    try:
        logger.info(f"Token validation requested for token: {token[:8]}...")
        
        result = await password_reset_service.validate_reset_token(token)
        return result
        
    except Exception as e:
        logger.error(f"Error validating reset token: {e}")
        return ValidateResetTokenResponse(
            valid=False,
            message="An error occurred while validating the token"
        )

@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    request: Request,
    reset_request: ResetPasswordRequest
):
    """
    🔓 **PUBLIC ENDPOINT** - Reset password using valid token
    
    **Features:**
    - Password strength validation (8+ chars, letters + numbers)
    - Token validation and expiration check
    - Secure password hashing before storage
    - Automatic token revocation after use
    - Audit logging with IP address
    
    **Security:**
    - No authentication required
    - One-time token usage (token is marked as used)
    - Revokes all other active tokens for the user
    - Logs successful password changes
    """
    try:
        ip_address = get_client_ip(request)
        
        logger.info(f"Password reset attempt with token: {reset_request.token[:8]}... from IP: {ip_address}")
        
        # Process password reset
        result = await password_reset_service.reset_password(
            token=reset_request.token,
            new_password=reset_request.new_password,
            ip_address=ip_address
        )
        
        if result.success:
            logger.info(f"Password successfully reset for user: {result.user_email} from IP: {ip_address}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in reset password endpoint: {e}")
        return ResetPasswordResponse(
            success=False,
            message="An unexpected error occurred. Please try again later.",
            requires_login=False
        )

# ============================================================================
# ADMIN-ONLY ENDPOINTS (Authentication Required)
# ============================================================================

@router.post("/admin/reset-user-password", response_model=AdminResetPasswordResponse)
async def admin_reset_user_password(
    admin_request: AdminResetPasswordRequest,
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    🔐 **ADMIN ONLY** - Reset any user's password
    
    **Two Reset Methods:**
    1. **Email Link** - Sends reset email to user (recommended)
    2. **Temporary Password** - Sets temp password directly (emergency use)
    
    **Features:**
    - Admin can reset any user's password
    - Optional force password change on next login
    - Custom notification message
    - Full audit trail with admin attribution
    - Email notifications to affected user
    
    **Permission:** Admin role required
    """
    try:
        admin_email = current_user.get("email", "unknown_admin")
        
        logger.info(f"Admin {admin_email} initiating password reset for user: {admin_request.user_email}")
        logger.info(f"Reset method: {admin_request.reset_method}, Force change: {admin_request.force_change_on_login}")
        
        # Validate admin is not resetting their own password this way
        if admin_email.lower() == admin_request.user_email.lower():
            logger.warning(f"Admin {admin_email} attempted to reset own password via admin endpoint")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admins should use the regular forgot password flow to reset their own password"
            )
        
        # Process admin password reset
        result = await password_reset_service.admin_reset_password(
            admin_email=admin_email,
            target_user_email=admin_request.user_email,
            reset_method=admin_request.reset_method,
            temporary_password=admin_request.temporary_password,
            force_change_on_login=admin_request.force_change_on_login,
            notification_message=admin_request.notification_message
        )
        
        if result.success:
            logger.info(f"Admin {admin_email} successfully reset password for {admin_request.user_email}")
        else:
            logger.warning(f"Admin password reset failed: {result.message}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in admin reset password endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing the password reset"
        )

@router.get("/admin/reset-statistics", response_model=PasswordResetStats)
async def get_password_reset_statistics(
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    🔐 **ADMIN ONLY** - Get password reset statistics for dashboard
    
    **Returns:**
    - Total requests today/week/month
    - Successful resets count
    - Pending/expired token counts
    - User vs admin initiated breakdown
    
    **Purpose:** Admin dashboard metrics and security monitoring
    """
    try:
        admin_email = current_user.get("email", "unknown_admin")
        logger.info(f"Admin {admin_email} requested password reset statistics")
        
        stats = await password_reset_service.get_reset_statistics()
        return stats
        
    except Exception as e:
        logger.error(f"Error getting password reset statistics: {e}")
        # Return empty stats on error
        return PasswordResetStats()

@router.post("/admin/cleanup-expired-tokens")
async def cleanup_expired_tokens(
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    🔐 **ADMIN ONLY** - Manually trigger cleanup of expired tokens
    
    **Purpose:**
    - Remove old/expired password reset tokens from database
    - Usually runs automatically, but admin can trigger manually
    - Helps maintain database performance and security
    
    **Security:** Only removes tokens older than 48 hours
    """
    try:
        admin_email = current_user.get("email", "unknown_admin")
        logger.info(f"Admin {admin_email} triggered manual token cleanup")
        
        await password_reset_service.cleanup_expired_tokens()
        
        return {
            "success": True,
            "message": "Expired tokens cleanup completed successfully",
            "triggered_by": admin_email,
            "timestamp": datetime.utcnow()
        }
        
    except Exception as e:
        logger.error(f"Error during manual token cleanup: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cleanup expired tokens"
        )

@router.get("/admin/user-reset-history")
async def get_user_reset_history(
    user_email: str = Query(..., description="User email to get reset history for"),
    limit: int = Query(10, ge=1, le=50, description="Number of records to return"),
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    🔐 **ADMIN ONLY** - Get password reset history for specific user
    
    **Features:**
    - View all password reset attempts for a user
    - Shows timestamps, IP addresses, success/failure
    - Helps with security investigation and user support
    - Limited to recent attempts for performance
    
    **Security:** Admin can view any user's reset history
    """
    try:
        admin_email = current_user.get("email", "unknown_admin")
        logger.info(f"Admin {admin_email} requested reset history for user: {user_email}")
        
        from ..config.database import get_database
        db = get_database()
        
        # Get recent reset attempts for user
        reset_history = await db.password_reset_tokens.find(
            {"user_email": user_email.lower()},
            {
                "token": 0  # Exclude actual token from response
            }
        ).sort("created_at", -1).limit(limit).to_list(None)
        
        # Convert ObjectId to string for JSON serialization
        for record in reset_history:
            record["_id"] = str(record["_id"])
        
        return {
            "success": True,
            "user_email": user_email,
            "total_records": len(reset_history),
            "reset_history": reset_history,
            "requested_by": admin_email,
            "timestamp": datetime.utcnow()
        }
        
    except Exception as e:
        logger.error(f"Error getting user reset history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user reset history"
        )
# ============================================================================
# ADVANCED ADMIN ENDPOINTS (Optional - for future enhancement)
# ============================================================================

@router.post("/admin/revoke-user-tokens")
async def revoke_user_reset_tokens(
    user_email: str = Query(..., description="User email to revoke tokens for"),
    current_user: Dict[str, Any] = Depends(get_admin_user)
):
    """
    🔐 **ADMIN ONLY** - Revoke all active password reset tokens for a user
    
    **Use Cases:**
    - Security incident response
    - User reports suspicious password reset emails
    - Emergency token revocation
    
    **Security:** Only affects password reset tokens, not login sessions
    """
    try:
        admin_email = current_user.get("email", "unknown_admin")
        logger.info(f"Admin {admin_email} revoking all reset tokens for user: {user_email}")
        
        from ..config.database import get_database
        from ..models.password_reset import ResetTokenStatus
        
        db = get_database()
        
        # Get user to verify existence
        user = await db.users.find_one({"email": user_email.lower(), "is_active": True})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found or inactive"
            )
        
        user_id = str(user["_id"])
        
        # Revoke all active tokens
        result = await db.password_reset_tokens.update_many(
            {
                "user_id": user_id,
                "status": ResetTokenStatus.ACTIVE
            },
            {
                "$set": {
                    "status": ResetTokenStatus.REVOKED,
                    "revoked_at": datetime.utcnow(),
                    "revoked_by": admin_email
                }
            }
        )
        
        logger.info(f"Admin {admin_email} revoked {result.modified_count} tokens for user {user_email}")
        
        return {
            "success": True,
            "message": f"Successfully revoked {result.modified_count} active tokens",
            "user_email": user_email,
            "tokens_revoked": result.modified_count,
            "revoked_by": admin_email,
            "timestamp": datetime.utcnow()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revoking user tokens: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke user tokens"
        )