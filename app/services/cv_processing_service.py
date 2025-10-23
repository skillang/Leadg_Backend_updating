# app/services/cv_processing_service.py - CV Processing Business Logic Service

import uuid
import os
import asyncio
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from bson import ObjectId
import logging

from ..config.database import get_database
from ..models.cv_processing import (
    CVProcessingStatus, 
    CVExtractionData, 
    CVProcessingResult,
    CVExtractionUpdateRequest,
    CVToLeadRequest,
    CVProcessingStatsResponse
)
from ..models.lead import ExperienceLevel  # 🔧 ADD THIS IMPORT
from .cv_extraction_service import CVExtractionService
from .lead_service import lead_service

logger = logging.getLogger(__name__)

class CVProcessingService:
    """Service for managing CV processing workflow and business logic"""
    
    def __init__(self):
        self.extraction_service = CVExtractionService()
        self.temp_file_retention_hours = 24  # Keep temp files for 24 hours
        
    def get_db(self):
        """Get database instance"""
        return get_database()
    
    # ============================================================================
    # 🆕 NEW: EXPERIENCE MAPPING METHOD
    # ============================================================================
    
    def _map_experience_to_enum(self, raw_experience: str) -> Optional[ExperienceLevel]:
        """
        Enhanced experience mapping with better pattern matching for job descriptions
        """
        if not raw_experience or not isinstance(raw_experience, str):
            return None
        
        # Convert to lowercase for matching
        exp_text = raw_experience.lower().strip()
        
        # Handle job descriptions by looking for experience keywords first
        fresher_keywords = ['fresher', 'fresh graduate', 'new graduate', 'no experience', 'entry level', 'recent graduate']
        if any(keyword in exp_text for keyword in fresher_keywords):
            logger.info(f"Mapped experience '{raw_experience[:50]}...' to FRESHER")
            return ExperienceLevel.FRESHER
        
        # Look for date patterns to calculate experience (2024-2023 = 1 year)
        year_pattern = r'\b(20\d{2})\b'
        years = re.findall(year_pattern, exp_text)
        if len(years) >= 2:
            try:
                years = [int(y) for y in years]
                years.sort()
                total_experience = years[-1] - years[0]  # Latest year - earliest year
                
                if total_experience < 1:
                    logger.info(f"Calculated {total_experience} years from dates -> LESS_THAN_1_YEAR")
                    return ExperienceLevel.LESS_THAN_1_YEAR
                elif total_experience <= 3:
                    logger.info(f"Calculated {total_experience} years from dates -> ONE_TO_THREE_YEARS")
                    return ExperienceLevel.ONE_TO_THREE_YEARS
                elif total_experience <= 5:
                    logger.info(f"Calculated {total_experience} years from dates -> THREE_TO_FIVE_YEARS")
                    return ExperienceLevel.THREE_TO_FIVE_YEARS
                elif total_experience <= 10:
                    logger.info(f"Calculated {total_experience} years from dates -> FIVE_TO_TEN_YEARS")
                    return ExperienceLevel.FIVE_TO_TEN_YEARS
                else:
                    logger.info(f"Calculated {total_experience} years from dates -> MORE_THAN_TEN_YEARS")
                    return ExperienceLevel.MORE_THAN_TEN_YEARS
            except ValueError:
                pass
        
        # Look for explicit year mentions (3 years, 2 yrs, etc.)
        year_matches = re.findall(r'\b(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\b', exp_text)
        if year_matches:
            try:
                years = float(year_matches[0])  # Take first match
                if years < 1:
                    return ExperienceLevel.LESS_THAN_1_YEAR
                elif years <= 3:
                    return ExperienceLevel.ONE_TO_THREE_YEARS
                elif years <= 5:
                    return ExperienceLevel.THREE_TO_FIVE_YEARS
                elif years <= 10:
                    return ExperienceLevel.FIVE_TO_TEN_YEARS
                else:
                    return ExperienceLevel.MORE_THAN_TEN_YEARS
            except ValueError:
                pass
        
        # Additional simple patterns
        if any(keyword in exp_text for keyword in ['less than 1', 'under 1', '6 months', '8 months']):
            return ExperienceLevel.LESS_THAN_1_YEAR
        
        if any(keyword in exp_text for keyword in ['senior', 'lead', '10+', 'more than 10']):
            return ExperienceLevel.MORE_THAN_TEN_YEARS
        
        # If we have job titles/companies but no clear experience indicators, default to FRESHER
        job_indicators = ['intern', 'trainee', 'junior', 'associate']
        if any(indicator in exp_text for indicator in job_indicators):
            logger.info(f"Found job indicators in '{raw_experience[:50]}...' -> defaulting to FRESHER")
            return ExperienceLevel.FRESHER
        
        # If we can't determine clearly, return None and let user select manually
        logger.info(f"Could not map experience text to enum: '{raw_experience[:100]}...' - leaving as None")
        return None
    
    # ============================================================================
    # CV UPLOAD AND PROCESSING
    # ============================================================================
    
    async def process_uploaded_cv(
        self, 
        file_content: bytes, 
        filename: str, 
        mime_type: str,
        uploaded_by: str,
        uploaded_by_email: str
    ) -> Dict[str, Any]:
        """Process uploaded CV file and extract structured data"""
        db = self.get_db()
        processing_id = self._generate_processing_id()
        
        try:
            logger.info(f"Processing CV upload: {filename} by {uploaded_by_email}")
            
            # Step 1: Validate file
            validation_result = self.extraction_service.validate_file(file_content, filename, mime_type)
            if not validation_result["valid"]:
                return {
                    "success": False,
                    "message": f"File validation failed: {', '.join(validation_result['errors'])}",
                    "processing_id": processing_id,
                    "validation_errors": validation_result["errors"]
                }
            
            # Step 2: Create initial processing record
            processing_doc = {
                "processing_id": processing_id,
                "status": CVProcessingStatus.PROCESSING,
                "uploaded_by": ObjectId(uploaded_by) if ObjectId.is_valid(uploaded_by) else uploaded_by,
                "uploaded_by_email": uploaded_by_email,
                "original_filename": filename,
                "file_size": len(file_content),
                "mime_type": mime_type,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "reviewed": False,
                "converted_to_lead": False,
                "extraction_errors": [],
                "processing_notes": ""
            }
            
            # Insert processing record
            result = await db.cv_extractions.insert_one(processing_doc)
            if not result.inserted_id:
                return {
                    "success": False,
                    "message": "Failed to create processing record",
                    "processing_id": processing_id
                }
            
            # Step 3: Extract text and structured data
            try:
                text, file_info = self.extraction_service.extract_text_from_file(file_content, mime_type, filename)
                extraction_result = self.extraction_service.extract_all_details(text, filename)
                
                # Step 4: Update processing record with extracted data
                update_doc = {
                    "status": CVProcessingStatus.PENDING_REVIEW,
                    "extracted_data": extraction_result["extracted_data"],
                    "confidence_scores": extraction_result["confidence_scores"],
                    "file_metadata": file_info,
                    "extraction_metadata": extraction_result["extraction_metadata"],
                    "raw_text_length": len(text),
                    "processing_time_ms": extraction_result["extraction_metadata"]["processing_time_ms"],
                    "updated_at": datetime.utcnow()
                }
                
                await db.cv_extractions.update_one(
                    {"processing_id": processing_id},
                    {"$set": update_doc}
                )
                
                logger.info(f"✅ CV processing completed: {processing_id}")
                
                return {
                    "success": True,
                    "message": "CV processed successfully",
                    "processing_id": processing_id,
                    "status": CVProcessingStatus.PENDING_REVIEW,
                    "extracted_data": extraction_result["extracted_data"],
                    "extraction_metadata": extraction_result["extraction_metadata"],
                    "file_info": file_info
                }
                
            except Exception as extraction_error:
                # Update record with failure status
                await db.cv_extractions.update_one(
                    {"processing_id": processing_id},
                    {"$set": {
                        "status": CVProcessingStatus.FAILED,
                        "error_message": str(extraction_error),
                        "updated_at": datetime.utcnow()
                    }}
                )
                
                logger.error(f"❌ CV extraction failed for {processing_id}: {extraction_error}")
                
                return {
                    "success": False,
                    "message": f"CV extraction failed: {str(extraction_error)}",
                    "processing_id": processing_id,
                    "status": CVProcessingStatus.FAILED
                }
                
        except Exception as e:
            logger.error(f"❌ CV processing failed for {filename}: {e}")
            return {
                "success": False,
                "message": f"CV processing failed: {str(e)}",
                "processing_id": processing_id
            }
    
    # ============================================================================
    # CV EXTRACTION MANAGEMENT
    # ============================================================================
    
    async def get_cv_extractions(
        self,
        user_id: str,
        user_email: str,
        has_lead_permission: bool = False,
        status_filter: Optional[str] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get CV extractions with permission-based filtering"""
        db = self.get_db()
        
        try:
            # Build query based on permissions
            query = {}
            
            # Permission-based filtering
            if not has_lead_permission:
                # Regular users can only see their own CVs
                query["uploaded_by_email"] = user_email
            # Users with lead permission can see all CVs (no additional filter)
            
            # Status filtering
            if status_filter:
                query["status"] = status_filter
            
            # Get total count
            total_count = await db.cv_extractions.count_documents(query)
            
            # Calculate pagination
            skip = (page - 1) * limit
            total_pages = (total_count + limit - 1) // limit
            
            # Get extractions with sorting (most recent first)
            cursor = db.cv_extractions.find(query).sort("created_at", -1).skip(skip).limit(limit)
            extractions = await cursor.to_list(length=limit)
            
            # Format response
            formatted_extractions = []
            for extraction in extractions:
                formatted_extractions.append(self._format_extraction_response(extraction))
            
            return {
                "success": True,
                "extractions": formatted_extractions,
                "total_count": total_count,
                "page": page,
                "limit": limit,
                "total_pages": total_pages,
                "filters_applied": {
                    "status": status_filter,
                    "user_filter": "own" if not has_lead_permission else "all"
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting CV extractions: {e}")
            return {
                "success": False,
                "message": f"Error retrieving CV extractions: {str(e)}",
                "extractions": [],
                "total_count": 0
            }
    
    async def get_cv_extraction_by_id(
        self,
        processing_id: str,
        user_id: str,
        user_email: str,
        has_lead_permission: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Get single CV extraction by ID with permission check"""
        db = self.get_db()
        
        try:
            # Build query with permission check
            query = {"processing_id": processing_id}
            
            # Permission check
            if not has_lead_permission:
                query["uploaded_by_email"] = user_email
            
            extraction = await db.cv_extractions.find_one(query)
            
            if not extraction:
                return None
            
            return {
                "success": True,
                "extraction": self._format_extraction_response(extraction)
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting CV extraction {processing_id}: {e}")
            return None
    
    async def update_extraction_data(
        self,
        processing_id: str,
        update_request: CVExtractionUpdateRequest,
        user_id: str,
        user_email: str,
        has_lead_permission: bool = False
    ) -> Dict[str, Any]:
        """Update extracted CV data"""
        db = self.get_db()
        
        try:
            # Build query with permission check
            query = {"processing_id": processing_id}
            if not has_lead_permission:
                query["uploaded_by_email"] = user_email
            
            # Check if extraction exists and user has permission
            extraction = await db.cv_extractions.find_one(query)
            if not extraction:
                return {
                    "success": False,
                    "message": "CV extraction not found or access denied"
                }
            
            # Check if already converted
            if extraction.get("converted_to_lead", False):
                return {
                    "success": False,
                    "message": "Cannot update extraction data - already converted to lead"
                }
            
            # Build update document
            update_doc = {
                "updated_at": datetime.utcnow(),
                "reviewed": True,
                "reviewed_by": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id,
                "reviewed_at": datetime.utcnow()
            }
            
            # Update extracted data fields if provided
            extracted_data_updates = {}
            for field in ['name', 'email', 'phone', 'age', 'skills', 'education', 'experience']:
                value = getattr(update_request, field, None)
                if value is not None:
                    extracted_data_updates[f"extracted_data.{field}"] = value
            
            if extracted_data_updates:
                update_doc.update(extracted_data_updates)
            
            # Update processing notes if provided
            if update_request.processing_notes:
                update_doc["processing_notes"] = update_request.processing_notes
            
            # Update status to ready for conversion if not already
            if extraction.get("status") == CVProcessingStatus.PENDING_REVIEW:
                update_doc["status"] = CVProcessingStatus.READY_FOR_CONVERSION
            
            # Perform update
            result = await db.cv_extractions.update_one(
                {"processing_id": processing_id},
                {"$set": update_doc}
            )
            
            if result.modified_count == 0:
                return {
                    "success": False,
                    "message": "No changes were made to the extraction"
                }
            
            logger.info(f"✅ CV extraction updated: {processing_id} by {user_email}")
            
            return {
                "success": True,
                "message": "CV extraction updated successfully",
                "processing_id": processing_id,
                "status": update_doc.get("status", extraction.get("status"))
            }
            
        except Exception as e:
            logger.error(f"❌ Error updating CV extraction {processing_id}: {e}")
            return {
                "success": False,
                "message": f"Error updating extraction: {str(e)}"
            }
    
    # ============================================================================
    # 🔧 UPDATED: CV TO LEAD CONVERSION WITH EXPERIENCE MAPPING
    # ============================================================================
    
    async def convert_cv_to_lead(
        self,
        conversion_request: CVToLeadRequest,
        user_id: str,
        user_email: str
    ) -> Dict[str, Any]:
        """Convert CV extraction to lead with better validation and error handling"""
        db = self.get_db()
        processing_id = conversion_request.processing_id
        
        try:
            logger.info(f"Converting CV to lead: {processing_id} by {user_email}")
            
            # Step 1: Get and validate extraction
            extraction = await db.cv_extractions.find_one({"processing_id": processing_id})
            if not extraction:
                return {
                    "success": False,
                    "message": "CV extraction not found"
                }
            
            # Check if already converted
            if extraction.get("converted_to_lead", False):
                return {
                    "success": False,
                    "message": "CV has already been converted to lead",
                    "existing_lead_id": extraction.get("lead_id")
                }
            
            # Check status
            if extraction.get("status") not in [CVProcessingStatus.READY_FOR_CONVERSION, CVProcessingStatus.PENDING_REVIEW]:
                return {
                    "success": False,
                    "message": f"CV cannot be converted - current status: {extraction.get('status')}"
                }
            
            # Step 1.5: Validate category and source BEFORE creating lead
            if not conversion_request.category:
                return {
                    "success": False,
                    "message": "Category is required for lead conversion"
                }
            
            source_name = conversion_request.source or "cv_upload"
            validation_result = await self._validate_category_and_source(
                conversion_request.category, source_name
            )
            
            if not validation_result["category_valid"]:
                return {
                    "success": False,
                    "message": f"Category '{conversion_request.category}' not found or inactive. Please select a valid category."
                }
            
            if not validation_result["source_valid"]:
                return {
                    "success": False,
                    "message": f"Source '{source_name}' not found or inactive. Please contact admin to add this source."
                }
            
            # Step 2: Extract and process data
            extracted_data = extraction.get("extracted_data", {})
            raw_experience = conversion_request.experience or extracted_data.get("experience")
            mapped_experience = self._map_experience_to_enum(raw_experience) if raw_experience else None
            
            # Step 2.5: Validate required fields
            name = conversion_request.name or extracted_data.get("name", "")
            email = conversion_request.email or extracted_data.get("email", "")
            contact_number = conversion_request.contact_number or extracted_data.get("phone", "")
            
            if not name.strip():
                return {
                    "success": False,
                    "message": "Name is required for lead creation"
                }
            
            if not email.strip():
                return {
                    "success": False,
                    "message": "Email is required for lead creation"
                }
            
            if not contact_number.strip():
                return {
                    "success": False,
                    "message": "Contact number is required for lead creation"
                }
            
            # Import existing lead models
            from ..models.lead import LeadCreateComprehensive, LeadBasicInfo, LeadStatusAndTags, LeadAdditionalInfo
            
            # Step 3: Build lead data with validation
            try:
                lead_data = LeadCreateComprehensive(
                    basic_info=LeadBasicInfo(
                        name=name.strip(),
                        email=email.strip(),
                        contact_number=contact_number.strip(),
                        source=source_name,
                        category=conversion_request.category,
                        age=conversion_request.age or extracted_data.get("age"),
                        experience=mapped_experience,  # Can be None - that's OK
                        nationality=conversion_request.nationality
                    ),
                    status_and_tags=LeadStatusAndTags(
                        stage=conversion_request.stage or "initial",
                        lead_score=conversion_request.lead_score or 0,
                        tags=conversion_request.tags or ["CV Upload"]
                    ),
                    additional_info=LeadAdditionalInfo(
                        notes=self._build_lead_notes_from_cv(extraction, conversion_request.notes, raw_experience, mapped_experience)
                    ),
                   assignment=LeadAssignmentInfo(
                    assigned_to="unassigned" if conversion_request.assignment_method == "unassigned" else conversion_request.assign_to
                  )
                )
            except Exception as validation_error:
                logger.error(f"Lead data validation error: {str(validation_error)}")
                return {
                    "success": False,
                    "message": f"Lead data validation failed: {str(validation_error)}",
                    "processing_id": processing_id,
                    "validation_errors": [str(validation_error)]
                }
            
            # Step 4: Create lead using existing lead service
            logger.info(f"Creating lead with data: name={name}, email={email}, category={conversion_request.category}, experience={mapped_experience}")
            
            lead_result = await lead_service.create_lead_comprehensive(
                lead_data=lead_data,
                created_by=user_id,
                force_create=False
            )
            
            if not lead_result["success"]:
                logger.error(f"Lead creation failed: {lead_result.get('message', 'Unknown error')}")
                return {
                    "success": False,
                    "message": f"Lead creation failed: {lead_result['message']}",
                    "processing_id": processing_id,
                    "validation_errors": [lead_result.get("message", "Unknown error")]
                }
            
            # Step 5: Update extraction record as converted
            conversion_update = {
                "status": CVProcessingStatus.CONVERTED,
                "converted_to_lead": True,
                "lead_id": lead_result["lead"]["lead_id"],
                "converted_by": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id,
                "converted_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            await db.cv_extractions.update_one(
                {"processing_id": processing_id},
                {"$set": conversion_update}
            )
            
            # Step 6: Schedule cleanup (delete CV data after successful conversion)
            asyncio.create_task(self._schedule_cv_cleanup(processing_id, delay_minutes=1))  # 1 minute for t
            
            logger.info(f"✅ CV converted to lead: {processing_id} -> {lead_result['lead']['lead_id']} (experience: {mapped_experience})")
            
            return {
                "success": True,
                "message": "CV successfully converted to lead",
                "processing_id": processing_id,
                "lead_id": lead_result["lead"]["lead_id"],
                "lead_details": lead_result["lead"],
                "assignment_info": lead_result.get("assignment_info"),
                "validation_errors": [],
                "cleanup_scheduled": True,
                "experience_mapping": {
                    "raw_experience": raw_experience,
                    "mapped_experience": mapped_experience.value if mapped_experience else None,
                    "status": "mapped" if mapped_experience else "left_empty"
                } if raw_experience else None
            }
            
        except Exception as e:
            logger.error(f"❌ Error converting CV to lead {processing_id}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "success": False,
                "message": f"Conversion failed: {str(e)}",
                "processing_id": processing_id,
                "validation_errors": [str(e)]
            }
    
    # ============================================================================
    # CV DATA MANAGEMENT
    # ============================================================================
    
    async def delete_cv_extraction(
        self,
        processing_id: str,
        user_id: str,
        user_email: str,
        has_lead_permission: bool = False
    ) -> Dict[str, Any]:
        """Delete CV extraction (only if not converted to lead)"""
        db = self.get_db()
        
        try:
            # Build query with permission check
            query = {"processing_id": processing_id}
            if not has_lead_permission:
                query["uploaded_by_email"] = user_email
            
            # Check if extraction exists
            extraction = await db.cv_extractions.find_one(query)
            if not extraction:
                return {
                    "success": False,
                    "message": "CV extraction not found or access denied"
                }
            
            # Check if already converted to lead
            if extraction.get("converted_to_lead", False):
                return {
                    "success": False,
                    "message": "Cannot manually delete CV - already converted to lead. It will be automatically deleted within 5 minutes of conversion.",
                    "lead_id": extraction.get("lead_id"),
                    "converted_at": extraction.get("converted_at"),
                    "auto_cleanup_scheduled": True
                }

            
            # Delete the extraction
            result = await db.cv_extractions.delete_one({"processing_id": processing_id})
            
            if result.deleted_count == 0:
                return {
                    "success": False,
                    "message": "Failed to delete CV extraction"
                }
            
            logger.info(f"🗑️ CV extraction deleted: {processing_id} by {user_email}")
            
            return {
                "success": True,
                "message": "CV extraction deleted successfully",
                "processing_id": processing_id
            }
            
        except Exception as e:
            logger.error(f"❌ Error deleting CV extraction {processing_id}: {e}")
            return {
                "success": False,
                "message": f"Error deleting extraction: {str(e)}"
            }
    
    async def get_cv_processing_stats(
        self,
        user_id: str,
        user_email: str,
        has_lead_permission: bool = False
    ) -> CVProcessingStatsResponse:
        """Get CV processing statistics"""
        db = self.get_db()
        
        try:
            # Build base query for user permissions
            user_query = {} if has_lead_permission else {"uploaded_by_email": user_email}
            
            # Get overall stats
            total_uploads = await db.cv_extractions.count_documents({})
            processing_count = await db.cv_extractions.count_documents({"status": CVProcessingStatus.PROCESSING})
            pending_review_count = await db.cv_extractions.count_documents({"status": CVProcessingStatus.PENDING_REVIEW})
            ready_for_conversion_count = await db.cv_extractions.count_documents({"status": CVProcessingStatus.READY_FOR_CONVERSION})
            converted_count = await db.cv_extractions.count_documents({"status": CVProcessingStatus.CONVERTED})
            failed_count = await db.cv_extractions.count_documents({"status": CVProcessingStatus.FAILED})
            
            # Get user-specific stats
            user_upload_count = await db.cv_extractions.count_documents({**user_query})
            user_pending_count = await db.cv_extractions.count_documents({
                **user_query,
                "status": {"$in": [CVProcessingStatus.PENDING_REVIEW, CVProcessingStatus.READY_FOR_CONVERSION]}
            })
            
            # Calculate success rate
            total_processed = converted_count + failed_count
            success_rate = (converted_count / total_processed * 100) if total_processed > 0 else None
            
            # Get average processing time
            pipeline = [
                {"$match": {"processing_time_ms": {"$exists": True, "$ne": None}}},
                {"$group": {"_id": None, "avg_time": {"$avg": "$processing_time_ms"}}}
            ]
            avg_time_result = await db.cv_extractions.aggregate(pipeline).to_list(1)
            average_processing_time_ms = avg_time_result[0]["avg_time"] if avg_time_result else None
            
            return CVProcessingStatsResponse(
                total_uploads=total_uploads,
                processing_count=processing_count,
                pending_review_count=pending_review_count,
                ready_for_conversion_count=ready_for_conversion_count,
                converted_count=converted_count,
                failed_count=failed_count,
                user_upload_count=user_upload_count,
                user_pending_count=user_pending_count,
                average_processing_time_ms=average_processing_time_ms,
                success_rate=success_rate
            )
            
        except Exception as e:
            logger.error(f"❌ Error getting CV processing stats: {e}")
            return CVProcessingStatsResponse(
                total_uploads=0,
                processing_count=0,
                pending_review_count=0,
                ready_for_conversion_count=0,
                converted_count=0,
                failed_count=0,
                user_upload_count=0,
                user_pending_count=0
            )
    
    # ============================================================================
    # CLEANUP AND MAINTENANCE
    # ============================================================================
    
    async def _schedule_cv_cleanup(self, processing_id: str, delay_minutes: int = 5):
        """Schedule cleanup of CV data after successful conversion"""
        try:
            logger.info(f"⏰ Scheduling automatic deletion of CV {processing_id} in {delay_minutes} minutes")
            
            # Wait for the specified delay
            await asyncio.sleep(delay_minutes * 60)
            
            db = self.get_db()
            
            # Verify the CV was actually converted before cleanup
            extraction = await db.cv_extractions.find_one({
                "processing_id": processing_id,
                "converted_to_lead": True
            })
            
            if not extraction:
                logger.warning(f"❌ Automatic cleanup skipped - CV not found or not converted: {processing_id}")
                return
            
            # Delete the entire CV extraction record
            result = await db.cv_extractions.delete_one({
                "processing_id": processing_id,
                "converted_to_lead": True
            })
            
            if result.deleted_count > 0:
                logger.info(f"✅ CV automatically deleted after conversion: {processing_id} -> Lead: {extraction.get('lead_id')}")
            else:
                logger.error(f"❌ Automatic cleanup failed - could not delete: {processing_id}")
                
        except Exception as e:
            logger.error(f"❌ Error during automatic CV cleanup for {processing_id}: {e}")
    
    async def cleanup_old_failed_extractions(self, older_than_hours: int = 48) -> Dict[str, Any]:
        """Clean up old failed extraction records"""
        db = self.get_db()
        
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=older_than_hours)
            
            # Delete old failed records
            result = await db.cv_extractions.delete_many({
                "status": CVProcessingStatus.FAILED,
                "created_at": {"$lt": cutoff_time}
            })
            
            deleted_count = result.deleted_count
            logger.info(f"🧹 Cleaned up {deleted_count} old failed CV extractions")
            
            return {
                "success": True,
                "message": f"Cleaned up {deleted_count} old failed extractions",
                "deleted_count": deleted_count
            }
            
        except Exception as e:
            logger.error(f"❌ Error cleaning up old failed extractions: {e}")
            return {
                "success": False,
                "message": f"Cleanup failed: {str(e)}",
                "deleted_count": 0
            }
    
    async def cleanup_old_unconverted_extractions(self, older_than_days: int = 7) -> Dict[str, Any]:
        """Clean up old unconverted extraction records"""
        db = self.get_db()
        
        try:
            cutoff_time = datetime.utcnow() - timedelta(days=older_than_days)
            
            # Delete old unconverted records
            result = await db.cv_extractions.delete_many({
                "converted_to_lead": False,
                "status": {"$ne": CVProcessingStatus.PROCESSING},
                "created_at": {"$lt": cutoff_time}
            })
            
            deleted_count = result.deleted_count
            logger.info(f"🧹 Cleaned up {deleted_count} old unconverted CV extractions")
            
            return {
                "success": True,
                "message": f"Cleaned up {deleted_count} old unconverted extractions",
                "deleted_count": deleted_count
            }
            
        except Exception as e:
            logger.error(f"❌ Error cleaning up old unconverted extractions: {e}")
            return {
                "success": False,
                "message": f"Cleanup failed: {str(e)}",
                "deleted_count": 0
            }
    
    # ============================================================================
    # UTILITY METHODS
    # ============================================================================
    
    def _generate_processing_id(self) -> str:
        """Generate unique processing ID"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        return f"cv_{timestamp}_{unique_id}"
    
    def _format_extraction_response(self, extraction_doc: Dict[str, Any]) -> Dict[str, Any]:
        """Format extraction document for API response"""
        # Convert ObjectId to string
        if "_id" in extraction_doc:
            extraction_doc["_id"] = str(extraction_doc["_id"])
        
        if isinstance(extraction_doc.get("uploaded_by"), ObjectId):
            extraction_doc["uploaded_by"] = str(extraction_doc["uploaded_by"])
        
        if isinstance(extraction_doc.get("reviewed_by"), ObjectId):
            extraction_doc["reviewed_by"] = str(extraction_doc["reviewed_by"])
        
        if isinstance(extraction_doc.get("converted_by"), ObjectId):
            extraction_doc["converted_by"] = str(extraction_doc["converted_by"])
        
        # Build file_metadata structure expected by Pydantic model
        file_metadata = {
            "original_filename": extraction_doc.get("original_filename", ""),
            "file_size": extraction_doc.get("file_size", 0),
            "mime_type": extraction_doc.get("mime_type", ""),
            "processing_time_ms": int(extraction_doc.get("processing_time_ms", 0)),
            "extractor_version": extraction_doc.get("extraction_metadata", {}).get("extractor_version", "1.0")
        }
        
        # Build response document matching Pydantic model structure
        response_doc = {
            "processing_id": extraction_doc.get("processing_id"),
            "status": extraction_doc.get("status"),
            "extracted_data": extraction_doc.get("extracted_data", {}),
            "file_metadata": file_metadata,
            "uploaded_by": extraction_doc.get("uploaded_by"),
            "uploaded_by_email": extraction_doc.get("uploaded_by_email"),
            "created_at": extraction_doc.get("created_at"),
            "updated_at": extraction_doc.get("updated_at"),
            "reviewed": extraction_doc.get("reviewed", False),
            "reviewed_by": extraction_doc.get("reviewed_by"),
            "reviewed_at": extraction_doc.get("reviewed_at"),
            "converted_to_lead": extraction_doc.get("converted_to_lead", False),
            "lead_id": extraction_doc.get("lead_id"),
            "converted_by": extraction_doc.get("converted_by"),
            "converted_at": extraction_doc.get("converted_at"),
            "error_message": extraction_doc.get("error_message"),
            "extraction_errors": extraction_doc.get("extraction_errors", []),
            "processing_notes": extraction_doc.get("processing_notes", "")
        }
        
        # Remove None values
        response_doc = {k: v for k, v in response_doc.items() if v is not None}
        
        return response_doc
    
    def _build_lead_notes_from_cv(
        self, 
        extraction: Dict[str, Any], 
        additional_notes: Optional[str] = None,
        raw_experience: Optional[str] = None,
        mapped_experience: Optional[ExperienceLevel] = None
    ) -> str:
        """
        🔧 UPDATED: Build comprehensive lead notes from CV extraction data with experience mapping info
        """
        notes_parts = []
        
        # Add conversion header
        notes_parts.append("=== CONVERTED FROM CV UPLOAD ===")
        
        # Add file information
        filename = extraction.get("original_filename", "unknown")
        upload_date = extraction.get("created_at", datetime.utcnow()).strftime("%Y-%m-%d %H:%M")
        notes_parts.append(f"Original File: {filename}")
        notes_parts.append(f"Uploaded: {upload_date}")
        notes_parts.append("")
        
        # Add extraction quality information
        extraction_metadata = extraction.get("extraction_metadata", {})
        if extraction_metadata:
            overall_confidence = extraction_metadata.get("overall_confidence", 0)
            notes_parts.append(f"Extraction Confidence: {overall_confidence:.1%}")
            
            quality_issues = extraction_metadata.get("quality_issues", [])
            if quality_issues:
                notes_parts.append("Quality Issues:")
                for issue in quality_issues:
                    notes_parts.append(f"  • {issue}")
            notes_parts.append("")
        
        # Add extracted structured data
        extracted_data = extraction.get("extracted_data", {})
        if extracted_data.get("skills"):
            notes_parts.append(f"**Skills (from CV):** {extracted_data['skills']}")
        
        if extracted_data.get("education"):
            notes_parts.append(f"**Education (from CV):** {extracted_data['education']}")
        
        # 🆕 NEW: Show experience mapping result
        if raw_experience:
            notes_parts.append(f"**Experience (from CV):** {raw_experience}")
            if mapped_experience:
                notes_parts.append(f"**Experience Level:** {mapped_experience.value} (auto-mapped)")
            else:
                notes_parts.append(f"**Experience Level:** Could not auto-map - left empty for manual selection")
            notes_parts.append("")
        
        if extracted_data.get("age"):
            notes_parts.append(f"**Age (from CV):** {extracted_data['age']}")
        
        # Add processing notes if any
        processing_notes = extraction.get("processing_notes", "")
        if processing_notes:
            notes_parts.append("")
            notes_parts.append("**Processing Notes:**")
            notes_parts.append(processing_notes)
        
        # Add additional notes from conversion request
        if additional_notes:
            notes_parts.append("")
            notes_parts.append("**Additional Notes:**")
            notes_parts.append(additional_notes)
        
        # Add conversion metadata
        notes_parts.append("")
        notes_parts.append("=== CONVERSION METADATA ===")
        notes_parts.append(f"Processing ID: {extraction.get('processing_id', 'unknown')}")
        notes_parts.append(f"Converted: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        
        return "\n".join(notes_parts)
    
    def check_user_cv_permissions(self, user_role: str, has_lead_creation_permission: bool) -> Dict[str, bool]:
        """Check what CV operations user can perform"""
        return {
            "can_upload": True,  # All users can upload
            "can_view_own": True,  # All users can view their own
            "can_view_all": has_lead_creation_permission,  # Only lead creators can see all
            "can_edit": True,  # All users can edit (but only own unless has_lead_permission)
            "can_convert": has_lead_creation_permission,  # Only lead creators can convert
            "can_delete_own": True,  # All users can delete their own unconverted CVs
            "can_delete_any": has_lead_creation_permission  # Only lead creators can delete any
        }
    
    async def _validate_category_and_source(self, category: str, source: str) -> Dict[str, Any]:
        """Validate that category and source exist in database"""
        db = self.get_db()
        
        # Check category exists and is active
        category_exists = await db.lead_categories.find_one({
            "name": category, 
            "is_active": True
        })
        
        # Check source exists and is active  
        source_exists = await db.sources.find_one({
            "name": source, 
            "is_active": True
        })
        
        return {
            "category_valid": bool(category_exists),
            "source_valid": bool(source_exists),
            "category": category,
            "source": source
        }

# Create service instance
cv_processing_service = CVProcessingService()
            