import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import time
import os

import logging

from services.ocr.entities import Document, ExtractionResult, ProcessingContext, ProcessingStatus, DocumentMetadata, ProcessingRequest

from services.ocr.strategies import (
    PDFProcessingStrategy, MSOfficeProcessingStrategy, 
    ImageProcessingStrategy, UnsupportedDocumentStrategy
)
from services.ocr.adapters import (
    AzureDocumentIntelligenceAdapter, OpenAIVisionAdapter, LibreOfficeAdapter, EnvironmentConfigurationService
)
from services.ocr.error_handling import SmartErrorHandler, CircuitBreaker, HealthCheck
from services.data import AzureBlobStorageAdapter, LocalFileStorageAdapter
from services.ocr.base import DocumentOrchestrationService, TextExtractionService, QualityAssuranceService

logger = logging.getLogger(__name__)



class OCRPipeline:
    """Main application class that wires up all dependencies"""
    
    def __init__(self, env_variables: dict):
        # Configuration
        self.config_service = EnvironmentConfigurationService(env_variables)
        
        # Error handling
        self.error_handler = SmartErrorHandler()
        self.circuit_breaker = CircuitBreaker()
        self.health_check = HealthCheck()
        
        # External service adapters
        self._setup_adapters()
        
        # Application services
        self._setup_application_services()
        
        # Processing strategies
        self._setup_processing_strategies()
        
        # Main orchestrator
        self.orchestrator = DocumentOrchestrationService(
            processors=self.processors,
            error_handler=self.error_handler,
            config_service=self.config_service
        )
    
    def _setup_adapters(self):
        """Setup external service adapters"""
        ai_config = self.config_service.get_ai_config()
        storage_config = self.config_service.get_storage_config()
        
        # OCR Service
        self.ocr_service = AzureDocumentIntelligenceAdapter(
            endpoint=ai_config['form_recognizer_endpoint'],
            api_key=ai_config['form_recognizer_key'],
            storage_type=storage_config['type'],
            local_storage_path=storage_config.get('base_path')
        )
        
        # Vision Service
        self.vision_service = OpenAIVisionAdapter(
            api_key=ai_config['openai_key'],
            endpoint=ai_config['openai_endpoint'],
            deployment_name=ai_config['openai_deployment'],
            storage_type=storage_config['type']
        )
        
        # Storage Service
        if storage_config['type'] == 'local':
            self.storage_service = LocalFileStorageAdapter(
                base_path=storage_config['base_path'],
                base_url=storage_config['base_url']
            )
        else:
            self.storage_service = AzureBlobStorageAdapter(
                connection_string=storage_config['connection_string'],
                container_name=storage_config['container_name']
            )
        
        # Conversion Service
        self.conversion_service = LibreOfficeAdapter()
    
    def _setup_application_services(self):
        """Setup application layer services"""
        self.text_extraction_service = TextExtractionService(
            ocr_service=self.ocr_service,
            vision_service=self.vision_service,
            storage_service=self.storage_service
        )
        
        self.quality_service = QualityAssuranceService()
    
    def _setup_processing_strategies(self):
        """Setup document processing strategies"""
        # PDF Strategy
        pdf_strategy = PDFProcessingStrategy(
            conversion_service=self.conversion_service,
            storage_service=self.storage_service,
            text_extraction_service=self.text_extraction_service
        )
        
        # MS Office Strategy
        ms_office_strategy = MSOfficeProcessingStrategy(
            conversion_service=self.conversion_service,
            pdf_strategy=pdf_strategy
        )
        
        # Image Strategy
        image_strategy = ImageProcessingStrategy(
            text_extraction_service=self.text_extraction_service
        )
        
        # Fallback Strategy
        unsupported_strategy = UnsupportedDocumentStrategy()
        
        # Order matters - more specific strategies first
        self.processors = [
            pdf_strategy,
            ms_office_strategy,
            image_strategy,
            unsupported_strategy  # Always last
        ]
    
    async def process_document(self, request: ProcessingRequest) -> dict:
        """Main processing method with improved error handling and quality checks"""
        results = []
        
        if not request.attachments:
            return {"message": "No documents to process"}
        
        for attachment in request.attachments:
            try:
                # Create Document entity
                document = Document(
                    url=attachment.url,
                    document_type=attachment.file_type,
                    metadata=DocumentMetadata(
                        request_id=str(request.request_id),
                        user_email=request.user_email,
                        context_id=request.context_id,
                        context_name=request.context_name,
                        document_name=attachment.name,
                        attachment_id=attachment.attachment_id,
                        extra_metadata=request.metadata  # Store any additional metadata
                    )
                )
                
                # Process with circuit breaker protection
                extraction_result = await self.circuit_breaker.call(
                    self.orchestrator.process_document,
                    document
                )
                
                # TODO: add quality assessment
                
                # Store quality assessment in bronze structure if available
                bronze_paths = extraction_result.metadata.get('bronze_base_folder')
                if bronze_paths:
                    from services.data import BronzeStorageService
                    bronze_storage = BronzeStorageService(self.storage_service)
                    try:
                        bronze_paths_dict = bronze_storage.get_bronze_paths(document)

                        # Store extraction result in bronze structure 
                        bronze_extraction_urls = await bronze_storage.store_extraction_result(extraction_result, bronze_paths_dict)
                        
                        # Create final manifest
                        all_stored_urls = {
                            **extraction_result.metadata.get('bronze_storage_urls', {}),
                            **bronze_extraction_urls
                        }
                        
                        manifest_url = await bronze_storage.create_bronze_manifest(document, all_stored_urls, bronze_paths_dict)
                        extraction_result.metadata['bronze_manifest_url'] = manifest_url
                        
                        logger.info(f"Complete bronze structure created for {document.metadata.document_name}")
                        
                    except Exception as e:
                        logger.warning(f"Error completing bronze structure: {str(e)}")
                        extraction_result.metadata['bronze_error'] = str(e)
                
                results.append({
                    "document_name": document.metadata.document_name,
                    "status": "success",
                    "extraction_result": extraction_result,
                    #"quality_score": extraction_result.confidence_score
                })
                
            except Exception as e:
                logger.error(f"Failed to process {attachment.document_name}: {str(e)}")
                results.append({
                    "document_name": attachment.document_name,
                    "status": "failed",
                    "error": str(e)
                })
        
        return {
            "message": f"Processed {len(results)} documents",
            "results": results,
            "health_status": self.health_check.get_overall_health()
        }
    
    async def check_health(self) -> dict:
        """Health check endpoint"""
        # Check each service
        await self.health_check.check_service_health(
            "ocr_service", 
            lambda: self.ocr_service.extract_text_from_image("test_url", {"timeout": 5})
        )
        
        await self.health_check.check_service_health(
            "storage_service",
            lambda: self.storage_service.download_file("test_url")
        )
        
        return self.health_check.get_overall_health()