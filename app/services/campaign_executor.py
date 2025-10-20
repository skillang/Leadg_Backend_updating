# app/services/campaign_executor.py
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from bson import ObjectId
import logging
from app.decorators.timezone_decorator import ist_time_to_utc_datetime

from app.config.database import get_database
from app.models.campaign_tracking import (
    CampaignEnrollment,
    CampaignJob,
    TrackingStatus,
    JobType
)
from app.services.campaign_service import campaign_service

logger = logging.getLogger(__name__)


class CampaignExecutor:
    """Service for executing campaigns - enrollment and job creation"""
    
    def __init__(self):
        self.enrollment_collection = "campaign_tracking"
        self.jobs_collection = "campaign_tracking"  # Same collection, different job_type
    
    @property
    def db(self):
        """Get database connection"""
        return get_database()
    
    async def enroll_leads_in_campaign(self, campaign_id: str) -> Dict[str, Any]:
        """
        Find matching leads and enroll them in campaign
        
        Args:
            campaign_id: Campaign ID
            
        Returns:
            Dictionary with enrollment results
        """
        try:
            logger.info(f"Starting enrollment for campaign: {campaign_id}")
            
            # Get campaign details
            campaign = await campaign_service.get_campaign(campaign_id)
            if not campaign:
                return {
                    "success": False,
                    "message": "Campaign not found"
                }
            
            if campaign["status"] != "active":
                return {
                    "success": False,
                    "message": f"Campaign is {campaign['status']}, not active"
                }
            
            # Find matching leads
            matching_leads = await self._find_matching_leads(campaign)
            
            if not matching_leads:
                logger.info(f"No matching leads found for campaign {campaign_id}")
                return {
                    "success": True,
                    "message": "No matching leads found",
                    "enrolled_count": 0
                }
            
            logger.info(f"Found {len(matching_leads)} matching leads for campaign {campaign_id}")
            
            # Enroll each lead
            enrolled_count = 0
            for lead in matching_leads:
                success = await self._enroll_single_lead(campaign, lead)
                if success:
                    enrolled_count += 1
            
            logger.info(f"Enrolled {enrolled_count} leads in campaign {campaign_id}")
            
            return {
                "success": True,
                "message": f"Enrolled {enrolled_count} leads",
                "enrolled_count": enrolled_count,
                "total_matching": len(matching_leads)
            }
            
        except Exception as e:
            logger.error(f"Error enrolling leads in campaign {campaign_id}: {str(e)}")
            return {
                "success": False,
                "message": f"Enrollment failed: {str(e)}",
                "enrolled_count": 0
            }
    
    async def _find_matching_leads(self, campaign: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find leads that match campaign criteria with proper AND/OR logic"""
        try:
            # Step 1: Build base filter query
            base_query = {}
            
            if campaign["send_to_all"]:
                logger.info("Campaign set to send_to_all - targeting ALL leads")
                # base_query remains empty for send_to_all
            else:
                # ✅ VALIDATION: At least one filter must be present
                has_stage_filter = bool(campaign.get("stage_ids"))
                has_source_filter = bool(campaign.get("source_ids"))
                has_category_filter = bool(campaign.get("category_ids"))
                
                if not (has_stage_filter or has_source_filter or has_category_filter):
                    logger.error("No filters provided and send_to_all is False")
                    raise ValueError(
                        "At least one filter (stage_ids, source_ids, or category_ids) must be provided "
                        "when send_to_all is False"
                    )
                
                # Convert IDs to names
                stage_names = []
                source_names = []
                category_names = []
                
                # ✅ IMPORTANT: Only fetch if IDs are explicitly provided
                if has_stage_filter:
                    stage_names = await self._convert_stage_ids_to_names(campaign["stage_ids"])
                    logger.info(f"Stage names from IDs: {stage_names}")
                    
                    if not stage_names:
                        logger.warning(f"No valid stages found for provided stage_ids: {campaign['stage_ids']}")
                
                if has_source_filter:
                    source_names = await self._convert_source_ids_to_names(campaign["source_ids"])
                    logger.info(f"Source names from IDs: {source_names}")
                    
                    if not source_names:
                        logger.warning(f"No valid sources found for provided source_ids: {campaign['source_ids']}")
                
                if has_category_filter:
                    category_names = await self._convert_category_ids_to_names(campaign["category_ids"])
                    logger.info(f"Category names from IDs: {category_names}")
                    
                    if not category_names:
                        logger.warning(f"No valid categories found for provided category_ids: {campaign['category_ids']}")
                
                # Build filter conditions using AND logic (all provided filters must match)
                conditions = []
                
                if stage_names:
                    if len(stage_names) == 1:
                        conditions.append({"stage": stage_names[0]})
                    else:
                        conditions.append({"stage": {"$in": stage_names}})
                
                if source_names:
                    if len(source_names) == 1:
                        conditions.append({"source": source_names[0]})
                    else:
                        conditions.append({"source": {"$in": source_names}})
                
                if category_names:
                    if len(category_names) == 1:
                        conditions.append({"category": category_names[0]})
                    else:
                        conditions.append({"category": {"$in": category_names}})
                
                # ✅ SAFETY CHECK: Ensure we have at least one valid condition
                if not conditions:
                    logger.error("No valid conditions after ID to name conversion")
                    raise ValueError(
                        "Could not convert provided IDs to valid stage/source/category names. "
                        "Please check that the provided IDs are correct."
                    )
                
                # Combine conditions with AND logic (all conditions must be true)
                if len(conditions) == 1:
                    base_query = conditions[0]
                elif len(conditions) > 1:
                    base_query = {"$and": conditions}
            
            # Step 2: Add contact info requirement
            contact_conditions = []
            
            if campaign["campaign_type"] == "whatsapp":
                contact_filter = {
                    "$or": [
                        {"contact_number": {"$exists": True, "$ne": "", "$ne": None}},
                        {"phone_number": {"$exists": True, "$ne": "", "$ne": None}}
                    ]
                }
                contact_conditions.append(contact_filter)
                    
            elif campaign["campaign_type"] == "email":
                contact_conditions.append({"email": {"$exists": True, "$ne": "", "$ne": None}})
            
            # Step 3: Combine base query with contact filter
            final_query = {}
            
            if base_query and contact_conditions:
                # Both base query and contact filter exist
                final_query = {"$and": [base_query] + contact_conditions}
            elif base_query:
                # Only base query
                final_query = base_query
            elif contact_conditions:
                # Only contact filter (send_to_all case)
                final_query = contact_conditions[0] if len(contact_conditions) == 1 else {"$and": contact_conditions}
            
            # Step 4: Exclude already enrolled leads
            already_enrolled = await self.db[self.enrollment_collection].find(
                {"campaign_id": campaign["campaign_id"], "job_type": "enrollment"},
                {"lead_id": 1}
            ).to_list(None)
            
            enrolled_lead_ids = [doc["lead_id"] for doc in already_enrolled]
            
            if enrolled_lead_ids:
                if final_query:
                    final_query = {"$and": [final_query, {"lead_id": {"$nin": enrolled_lead_ids}}]}
                else:
                    final_query = {"lead_id": {"$nin": enrolled_lead_ids}}
            
            logger.info(f"Final lead query: {final_query}")
            
            # Step 5: Execute query
            leads = await self.db.leads.find(final_query).to_list(None)
            logger.info(f"Found {len(leads)} matching leads")
            return leads
            
        except ValueError as ve:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.error(f"Error finding matching leads: {str(e)}")
            return []

    async def _convert_stage_ids_to_names(self, stage_ids: List[str]) -> List[str]:
        """Convert stage ObjectIds to stage names"""
        try:
            stage_object_ids = [ObjectId(sid) for sid in stage_ids]
            stages = await self.db.lead_stages.find(
                {"_id": {"$in": stage_object_ids}}
            ).to_list(None)
            return [stage["name"] for stage in stages]
        except Exception as e:
            logger.error(f"Error converting stage IDs to names: {str(e)}")
            return []

    async def _convert_source_ids_to_names(self, source_ids: List[str]) -> List[str]:
        """Convert source ObjectIds to source names"""
        try:
            logger.info(f"Converting source IDs: {source_ids}")  # ADD THIS
            source_object_ids = [ObjectId(sid) for sid in source_ids]
            logger.info(f"ObjectIds created: {source_object_ids}")  # ADD THIS
            
            sources = await self.db.sources.find(
                {"_id": {"$in": source_object_ids}}
            ).to_list(None)
            
            logger.info(f"Found sources: {sources}")  # ADD THIS
            result = [source["name"] for source in sources]
            logger.info(f"Converted to names: {result}")  # ADD THIS
            return result
        except Exception as e:
            logger.error(f"Error converting source IDs to names: {str(e)}")
            return []
    

    async def _convert_category_ids_to_names(self, category_ids: List[str]) -> List[str]:
        """Convert category ObjectIds to category names"""
        try:
            logger.info(f"Converting category IDs: {category_ids}")
            category_object_ids = [ObjectId(cid) for cid in category_ids]
            logger.info(f"ObjectIds created: {category_object_ids}")
            
            categories = await self.db.lead_categories.find(
                {"_id": {"$in": category_object_ids}}
            ).to_list(None)
            
            logger.info(f"Found categories: {categories}")
            result = [category["name"] for category in categories]
            logger.info(f"Converted to names: {result}")
            return result
        except Exception as e:
            logger.error(f"Error converting category IDs to names: {str(e)}")
            return []
    async def _enroll_single_lead(
        self,
        campaign: Dict[str, Any],
        lead: Dict[str, Any]
    ) -> bool:
        """
        Enroll a single lead and create all message jobs
        
        Args:
            campaign: Campaign document
            lead: Lead document
            
        Returns:
            True if successful
        """
        try:
            campaign_id = campaign["campaign_id"]
            lead_id = lead["lead_id"]
            
            # Create enrollment record
            enrollment_doc = {
                "campaign_id": campaign_id,
                "lead_id": lead_id,
                "job_type": "enrollment",
                
                "enrolled_at": datetime.utcnow(),
                "enrolled_with_stage": lead.get("stage"),
                "enrolled_with_source": lead.get("source"),
                "enrolled_with_category": lead.get("category"),
                
                "messages_sent": 0,
                "current_sequence": 0,
                "status": TrackingStatus.ACTIVE.value,
                
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            await self.db[self.enrollment_collection].insert_one(enrollment_doc)
            
            # Create message jobs
            await self._create_message_jobs(campaign, lead, enrollment_doc)
            
            logger.debug(f"Lead {lead_id} enrolled in campaign {campaign_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error enrolling lead {lead.get('lead_id')}: {str(e)}")
            return False
    
    async def _create_message_jobs(
    self,
    campaign: Dict[str, Any],
    lead: Dict[str, Any],
    enrollment: Dict[str, Any]
) -> None:
        """Create looped message jobs with decay distribution pattern"""
        try:
            campaign_id = campaign["campaign_id"]
            lead_id = lead["lead_id"]
            enrollment_time = enrollment["enrolled_at"]
            
            message_limit = campaign.get("message_limit", 10)
            campaign_days = campaign.get("campaign_duration_days", 30)
            templates = campaign["templates"]
            send_time = campaign.get("send_time", "10:00")
            
            if not templates:
                logger.error("No templates provided for campaign")
                return
            
            # Calculate decay pattern distribution
            message_days = self._calculate_decay_distribution(message_limit, campaign_days)
            
            jobs = []
            
            for message_number in range(message_limit):
                # Get template (loop through templates)
                template = templates[message_number % len(templates)]
                
                # Get the day for this message
                day_offset = message_days[message_number]
                
                # Calculate execution datetime
                target_date = enrollment_time + timedelta(days=day_offset)
                execute_at = ist_time_to_utc_datetime(target_date, send_time)
                
                job_doc = {
                    "campaign_id": campaign_id,
                    "lead_id": lead_id,
                    "job_type": "message_job",
                    "channel": campaign["campaign_type"],
                    "template_name": template["template_name"],
                    "sequence_order": message_number + 1,
                    "execute_at": execute_at,
                    "status": TrackingStatus.PENDING.value,
                    "attempts": 0,
                    "max_attempts": 3,
                    "created_at": datetime.utcnow()
                }
                jobs.append(job_doc)
                
                logger.debug(f"Message {message_number + 1}: Day {day_offset}, Template: {template['template_name']}")
            
            if jobs:
                await self.db[self.jobs_collection].insert_many(jobs)
                logger.info(f"Created {len(jobs)} decay-pattern jobs for lead {lead_id} over {campaign_days} days")
                
        except Exception as e:
            logger.error(f"Error creating message jobs: {str(e)}")



    def _calculate_decay_distribution(self, message_count: int, total_days: int) -> List[float]:
        """
        Calculate message distribution with decay pattern (frequent early, sparse later)
        
        Pattern: Day 0, 1, 3, 6, 10, 15, 18, 22, 26, 29...
        
        Args:
            message_count: Number of messages to send
            total_days: Campaign duration in days
            
        Returns:
            List of days when messages should be sent
        """
        if message_count == 0:
            return []
        
        if message_count == 1:
            return [0]
        
        days = [0]  # First message on day 0
        current_day = 0
        
        # Define gap progression (starts small, grows larger)
        for i in range(1, message_count):
            if i == 1:
                gap = 1  # Day 1
            elif i == 2:
                gap = 2  # Day 3
            elif i == 3:
                gap = 3  # Day 6
            elif i == 4:
                gap = 4  # Day 10
            elif i == 5:
                gap = 5  # Day 15
            else:
                gap = 3  # Then every 3-4 days
            
            current_day += gap
            
            # Ensure we don't exceed total_days
            if current_day >= total_days:
                current_day = total_days - (message_count - i)
            
            days.append(min(current_day, total_days - 1))
        
        return days

    async def check_lead_criteria_change(
    self,
    lead_id: str,
    new_stage: Optional[str] = None,
    new_source: Optional[str] = None,
    new_category: Optional[str] = None
) -> None:
        """
        Check if lead still matches campaign criteria after stage/source change
        
        Args:
            lead_id: Lead ID
            new_stage: New stage NAME (if changed)
            new_source: New source NAME (if changed)
        """
        try:
            logger.info(f"Checking campaign criteria for lead {lead_id}")
            
            # Get the lead to check current stage/source
            lead = await self.db.leads.find_one({"lead_id": lead_id})
            if not lead:
                logger.error(f"Lead {lead_id} not found")
                return
            
            # Use provided values or get from lead document
            current_stage = new_stage or lead.get("stage")
            current_source = new_source or lead.get("source")
            current_category = new_category or lead.get("category") 
            
            logger.info(f"Lead {lead_id} current stage: {current_stage}, source: {current_source}, category: {current_category}")  
            
            # Get all active enrollments for this lead
            enrollments = await self.db[self.enrollment_collection].find({
                "lead_id": lead_id,
                "job_type": "enrollment",
                "status": TrackingStatus.ACTIVE.value
            }).to_list(None)
            
            if not enrollments:
                logger.debug(f"No active campaign enrollments for lead {lead_id}")
                return
            
            # Check each enrollment
            for enrollment in enrollments:
                campaign = await campaign_service.get_campaign(enrollment["campaign_id"])
                
                if not campaign:
                    continue
                
                # Check if lead still matches criteria
                still_matches = await self._check_criteria_match(
                    campaign,
                    current_stage,
                    current_source,
                    current_category
                )
                
                logger.info(f"Campaign {campaign['campaign_id']} match result: {still_matches}")
                
                if not still_matches:
                    # Pause this enrollment
                    await self._pause_enrollment(enrollment["campaign_id"], lead_id)
                    logger.info(f"Paused campaign {enrollment['campaign_id']} for lead {lead_id} - criteria no longer match")
            
        except Exception as e:
            logger.error(f"Error checking lead criteria: {str(e)}")
    
    async def _check_criteria_match(
    self,
    campaign: Dict[str, Any],
    current_stage: Optional[str],  # Stage NAME from lead
    current_source: Optional[str],
    current_category: Optional[str] = None
  # Source NAME from lead
) -> bool:
        """
        Check if lead still matches campaign criteria
        
        Args:
            campaign: Campaign document
            current_stage: Lead's current stage NAME
            current_source: Lead's current source NAME
        
        Returns:
            True if still matches
        """
        try:
            if campaign["send_to_all"]:
                logger.info("Campaign is send_to_all, returning True")
                return True
            
            # Get required stage and source names from campaign
            required_stages = []
            required_sources = []
            required_categories = []
            
            if campaign.get("stage_ids"):
                required_stages = await self._convert_stage_ids_to_names(campaign["stage_ids"])
                logger.info(f"Required stages: {required_stages}, Current stage: {current_stage}")
            
            if campaign.get("source_ids"):
                required_sources = await self._convert_source_ids_to_names(campaign["source_ids"])
                logger.info(f"Required sources: {required_sources}, Current source: {current_source}")
            if campaign.get("category_ids"):  # ✅ NEW BLOCK
                required_categories = await self._convert_category_ids_to_names(campaign["category_ids"])
                logger.info(f"Required categories: {required_categories}, Current category: {current_category}")
            
            # Check based on what's configured in campaign
            matches = []
            
            if required_stages:
                stage_match = current_stage in required_stages
                matches.append(stage_match)
                logger.info(f"Stage match: {stage_match}")
            
            if required_sources:
                source_match = current_source in required_sources
                matches.append(source_match)
                logger.info(f"Source match: {source_match}")
            
            if required_categories:  # ✅ NEW BLOCK
                category_match = current_category in required_categories
                matches.append(category_match)
                logger.info(f"Category match: {category_match}")
            
            # All specified criteria must match (AND logic)
            if not matches:
                # No criteria specified - should not happen but return True
                logger.warning("No stage, source, or category criteria in campaign")
                return True
            
            # Return True only if ALL matches are True
            result = all(matches)
            logger.info(f"Overall match result: {result} (all of {matches})")
            return result
            
        except Exception as e:
            logger.error(f"Error checking criteria match: {str(e)}")
            return False
    
    async def _pause_enrollment(self, campaign_id: str, lead_id: str) -> None:
        """Pause enrollment and cancel pending jobs"""
        try:
            # Update enrollment status
            await self.db[self.enrollment_collection].update_one(
                {
                    "campaign_id": campaign_id,
                    "lead_id": lead_id,
                    "job_type": "enrollment"
                },
                {
                    "$set": {
                        "status": TrackingStatus.CRITERIA_NOT_MATCHED.value,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            # Cancel pending jobs
            await self.db[self.jobs_collection].update_many(
                {
                    "campaign_id": campaign_id,
                    "lead_id": lead_id,
                    "job_type": "message_job",
                    "status": TrackingStatus.PENDING.value
                },
                {
                    "$set": {
                        "status": TrackingStatus.CANCELLED.value,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"Error pausing enrollment: {str(e)}")

    async def check_and_complete_campaign(self, campaign_id: str) -> None:
        """
        Check if campaign has finished all messages and mark as completed
        
        Args:
            campaign_id: Campaign ID to check
        """
        try:
            logger.info(f"Checking completion status for campaign {campaign_id}")
            
            # Get campaign
            campaign = await campaign_service.get_campaign(campaign_id)
            if not campaign:
                logger.error(f"Campaign {campaign_id} not found")
                return
            
            # Only check active campaigns
            if campaign["status"] != "active":
                logger.debug(f"Campaign {campaign_id} is {campaign['status']}, skipping completion check")
                return
            
            # Count total message jobs for this campaign
            total_jobs = await self.db[self.jobs_collection].count_documents({
                "campaign_id": campaign_id,
                "job_type": "message_job"
            })
            
            if total_jobs == 0:
                logger.debug(f"No message jobs found for campaign {campaign_id}")
                return
            
            # Count pending jobs
            pending_jobs = await self.db[self.jobs_collection].count_documents({
                "campaign_id": campaign_id,
                "job_type": "message_job",
                "status": TrackingStatus.PENDING.value
            })
            
            logger.info(f"Campaign {campaign_id}: {pending_jobs} pending out of {total_jobs} total jobs")
            
            # If no pending jobs, mark campaign as completed
            if pending_jobs == 0:
                success = await campaign_service.complete_campaign(campaign_id)
                if success:
                    logger.info(f"✅ Campaign {campaign_id} marked as COMPLETED - all messages sent")
                    
                    # Also update all active enrollments to completed
                    await self.db[self.enrollment_collection].update_many(
                        {
                            "campaign_id": campaign_id,
                            "job_type": "enrollment",
                            "status": TrackingStatus.ACTIVE.value
                        },
                        {
                            "$set": {
                                "status": TrackingStatus.COMPLETED.value,
                                "updated_at": datetime.utcnow()
                            }
                        }
                    )
                    logger.info(f"Updated all enrollments to completed for campaign {campaign_id}")
                else:
                    logger.error(f"Failed to mark campaign {campaign_id} as completed")
                    
        except Exception as e:
            logger.error(f"Error checking campaign completion: {str(e)}")
# Global service instance
campaign_executor = CampaignExecutor()