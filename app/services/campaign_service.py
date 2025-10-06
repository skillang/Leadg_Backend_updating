# app/services/campaign_service.py
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from bson import ObjectId
import logging

from app.config.database import get_database
from app.models.automation_campaign import (
    AutomationCampaign,
    CampaignCreateRequest,
    CampaignResponse,
    CampaignStatus,
    CampaignType
)

logger = logging.getLogger(__name__)


class CampaignService:
    """Service for campaign CRUD operations"""
    
    def __init__(self):
        self.collection_name = "automation_campaigns"
    
    @property
    def db(self):
        """Get database connection"""
        return get_database()
    
    async def create_campaign(
        self,
        campaign_data: CampaignCreateRequest,
        created_by: str
    ) -> Dict[str, Any]:
        """
        Create a new automation campaign
        
        Args:
            campaign_data: Campaign configuration
            created_by: Admin email who created the campaign
            
        Returns:
            Dictionary with success status and campaign details
        """
        try:
            logger.info(f"Creating campaign: {campaign_data.campaign_name} by {created_by}")
            
            # Generate unique campaign ID
            campaign_id = f"CAMP_{ObjectId()}"
            
            # Calculate schedule if auto-schedule mode
            if not campaign_data.use_custom_dates:
                schedule_days = self._calculate_schedule_days(
                    campaign_data.campaign_duration_days,
                    campaign_data.message_limit
                )
                
                # Assign scheduled days to templates
                for i, template in enumerate(campaign_data.templates):
                    if i < len(schedule_days):
                        template.scheduled_day = schedule_days[i]
            
            # Prepare campaign document
            campaign_doc = {
                "campaign_id": campaign_id,
                "campaign_name": campaign_data.campaign_name,
                "campaign_type": campaign_data.campaign_type.value,
                
                # Filters
                "send_to_all": campaign_data.send_to_all,
                "stage_ids": campaign_data.stage_ids,
                "source_ids": campaign_data.source_ids,
                "category_ids": campaign_data.category_ids,
                
                # Settings
                "use_custom_dates": campaign_data.use_custom_dates,
                "campaign_duration_days": campaign_data.campaign_duration_days,
                "message_limit": campaign_data.message_limit,
                "send_time": campaign_data.send_time,
                "send_on_weekends": campaign_data.send_on_weekends,
                
                # Templates
                "templates": [template.dict() for template in campaign_data.templates],
                
                # Status
                "status": CampaignStatus.ACTIVE.value,
                "created_by": created_by,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            # Insert into database
            await self.db[self.collection_name].insert_one(campaign_doc)
            
            logger.info(f"Campaign created successfully: {campaign_id}")
            
           # Create schedule preview - UPDATED SECTION
            schedule_preview = []

            if campaign_data.use_custom_dates:
                # For custom dates, show only templates with custom dates
                for template in campaign_data.templates:
                    schedule_preview.append({
                        "template_name": template.template_name,
                        "send_date": template.custom_date,
                        "sequence": template.sequence_order
                    })
            else:
                # For auto-schedule, show ALL scheduled jobs based on message_limit
                templates = [template.dict() for template in campaign_data.templates]
                message_days = self._calculate_schedule_days(
                    campaign_data.campaign_duration_days,
                    campaign_data.message_limit
                )
                
                # Generate schedule for all messages (cycling through templates)
                for i in range(campaign_data.message_limit):
                    template = templates[i % len(templates)]
                    schedule_preview.append({
                        "template_name": template["template_name"],
                        "send_day": message_days[i],
                        "sequence": i + 1
                    })
            
            return {
                "success": True,
                "message": "Campaign created successfully",
                "campaign_id": campaign_id,
                "campaign_name": campaign_data.campaign_name,
                "total_scheduled_messages": len(schedule_preview),  # ADD THIS LINE
                "schedule_preview": schedule_preview
            }
            
        except Exception as e:
            logger.error(f"Error creating campaign: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to create campaign: {str(e)}"
            }
    
    async def get_campaign(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        """Get campaign by ID"""
        try:
            campaign = await self.db[self.collection_name].find_one(
                {"campaign_id": campaign_id}
            )
            
            if campaign:
                campaign["_id"] = str(campaign["_id"])
                
                # Expand templates to full schedule
                templates = campaign.get("templates", [])
                message_limit = campaign.get("message_limit", len(templates))
                use_custom_dates = campaign.get("use_custom_dates", False)
                
                expanded_schedule = []
                
                if use_custom_dates:
                    # For custom dates, return templates with renamed fields
                    for template in templates:
                        expanded_schedule.append({
                            "template_id": template.get("template_id"),
                            "template_name": template.get("template_name"),
                            "send_day": None,
                            "sequence": template.get("sequence_order"),
                            "custom_date": template.get("custom_date")
                        })
                else:
                    # For auto-schedule, expand based on message_limit
                    campaign_duration = campaign.get("campaign_duration_days", 30)
                    message_days = self._calculate_schedule_days(campaign_duration, message_limit)
                    
                    # Generate schedule for all messages (cycling through templates)
                    for i in range(message_limit):
                        template = templates[i % len(templates)]
                        expanded_schedule.append({
                            "template_id": template.get("template_id"),
                            "template_name": template.get("template_name"),
                            "send_day": message_days[i],
                            "sequence": i + 1,
                            "custom_date": None
                        })
                
                campaign["templates"] = expanded_schedule
            
            return campaign
            
        except Exception as e:
            logger.error(f"Error getting campaign {campaign_id}: {str(e)}")
            return None
        """Get campaign by ID"""
        try:
            campaign = await self.db[self.collection_name].find_one(
                {"campaign_id": campaign_id}
            )
            
            if campaign:
                campaign["_id"] = str(campaign["_id"])
            
            return campaign
            
        except Exception as e:
            logger.error(f"Error getting campaign {campaign_id}: {str(e)}")
            return None
    
    async def list_campaigns(
    self,
    campaign_type: Optional[str] = None,
    status: Optional[str] = None,
    created_by: Optional[str] = None,
    skip: int = 0,
    limit: int = 20
) -> Dict[str, Any]:
        """
        List campaigns with filtering - SHOWS ALL STATUSES BY DEFAULT
        
        Args:
            campaign_type: Filter by type (whatsapp/email)
            status: Filter by status (active/paused/deleted/completed/cancelled) - shows ALL if None
            created_by: Filter by creator email
            skip: Number of records to skip
            limit: Maximum records to return
            
        Returns:
            Dictionary with campaigns list and pagination info
        """
        try:
            # Build query
            query = {}
            
            if campaign_type:
                query["campaign_type"] = campaign_type
            
            # ✅ FIX: Show ALL statuses when no filter is applied
            # Only filter by status if explicitly provided
            if status:
                query["status"] = status
            # Don't add any default status filter - show everything including deleted
            
            if created_by:
                query["created_by"] = created_by
            
            # Get total count
            total = await self.db[self.collection_name].count_documents(query)
            
            # ✅ Calculate pagination metadata
            total_pages = (total + limit - 1) // limit if total > 0 else 0
            current_page = (skip // limit) + 1
            
            # Get campaigns
            cursor = self.db[self.collection_name].find(query)\
                .sort("created_at", -1)\
                .skip(skip)\
                .limit(limit)
            
            campaigns = await cursor.to_list(length=limit)
            
            # Convert ObjectId to string
            for campaign in campaigns:
                campaign["_id"] = str(campaign["_id"])
            
            # ✅ UNIVERSAL PAGINATION STRUCTURE (matches other endpoints)
            return {
                "success": True,
                "campaigns": campaigns,
                "total": total,
                "page": current_page,
                "limit": limit,
                "pages": total_pages,
                "has_next": current_page < total_pages,
                "has_prev": current_page > 1
            }
            
        except Exception as e:
            logger.error(f"Error listing campaigns: {str(e)}")
            return {
                "success": False,
                "campaigns": [],
                "total": 0,
                "page": 1,
                "limit": limit,
                "pages": 0,
                "has_next": False,
                "has_prev": False,
                "error": str(e)
            }


    async def update_campaign_status(
        self,
        campaign_id: str,
        new_status: str
    ) -> bool:
        """
        Update campaign status
        
        Args:
            campaign_id: Campaign ID
            new_status: New status (active/paused/deleted)
            
        Returns:
            True if successful
        """
        try:
            result = await self.db[self.collection_name].update_one(
                {"campaign_id": campaign_id},
                {
                    "$set": {
                        "status": new_status,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"Campaign {campaign_id} status updated to {new_status}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error updating campaign status: {str(e)}")
            return False
    
    async def delete_campaign(self, campaign_id: str) -> bool:
        """
        Soft delete campaign (mark as deleted)
        
        Args:
            campaign_id: Campaign ID
            
        Returns:
            True if successful
        """
        return await self.update_campaign_status(campaign_id, CampaignStatus.DELETED.value)
    
    async def pause_campaign(self, campaign_id: str) -> bool:
        """Pause campaign"""
        return await self.update_campaign_status(campaign_id, CampaignStatus.PAUSED.value)
    
    async def resume_campaign(self, campaign_id: str) -> bool:
        """Resume paused campaign"""
        return await self.update_campaign_status(campaign_id, CampaignStatus.ACTIVE.value)
    async def complete_campaign(self, campaign_id: str) -> bool:
        """Mark campaign as completed"""
        return await self.update_campaign_status(campaign_id, "completed")

    async def cancel_campaign(self, campaign_id: str) -> bool:
        """Mark campaign as cancelled"""
        return await self.update_campaign_status(campaign_id, "cancelled")
    
    def _calculate_schedule_days(
        self,
        duration_days: int,
        message_count: int
    ) -> List[int]:
        """
        Calculate schedule days with front-loaded distribution
        
        Args:
            duration_days: Total campaign duration
            message_count: Number of messages to send
            
        Returns:
            List of day numbers when messages should be sent
        """
        if message_count <= 0 or duration_days <= 0:
            return []
        
        schedule_days = []
        
        # Front-loaded pattern: 70% of messages in first 60% of duration
        first_half_days = int(duration_days * 0.6)
        first_half_messages = int(message_count * 0.7)
        
        # Calculate first half
        if first_half_messages > 0:
            interval = first_half_days / first_half_messages
            for i in range(first_half_messages):
                day = max(1, int(interval * (i + 1)))
                schedule_days.append(day)
        
        # Calculate second half
        remaining_messages = message_count - first_half_messages
        if remaining_messages > 0:
            remaining_days = duration_days - first_half_days
            interval = remaining_days / remaining_messages
            
            for i in range(remaining_messages):
                day = first_half_days + max(1, int(interval * (i + 1)))
                schedule_days.append(min(day, duration_days))
        
        # Ensure unique and sorted
        schedule_days = sorted(list(set(schedule_days)))
        
        # Ensure we have exactly message_count days
        while len(schedule_days) < message_count:
            schedule_days.append(duration_days)
        
        return schedule_days[:message_count]


# Global service instance
campaign_service = CampaignService()