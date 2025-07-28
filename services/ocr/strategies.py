import asyncio
import tempfile
import os
import logging
from typing import List
from pathlib import Path

from services.interfaces import IDocumentProcessor, IConversionService, IStorageService
from services.ocr.entities import Document, ExtractionResult, ProcessingContext, DocumentType
from services.ocr.base import TextExtractionService

logger = logging.getLogger(__name__)

class PDFProcessingStrategy(IDocumentProcessor):
    """Strategy for processing PDF documents"""
    
    def __init__(
        self,
        conversion_service: IConversionService,
        storage_service: IStorageService,
        text_extraction_service: TextExtractionService
    ):
        self.conversion_service = conversion_service
        self.storage_service = storage_service
        self.text_extraction_service = text_extraction_service
    
    async def can_process(self, document: Document) -> bool:
        return document.document_type == DocumentType.PDF
    
    async def process(self, document: Document, context: ProcessingContext) -> ExtractionResult:
        """Process PDF using complete Document Intelligence analysis with selective figure extraction"""
        temp_dir = None
        try:
            # Create temporary directory
            temp_dir = tempfile.mkdtemp()
            pdf_path = os.path.join(temp_dir, "document.pdf")
            
            # Download PDF
            logger.info(f"Downloading PDF: {document.metadata.document_name}")
            pdf_content = await self.storage_service.download_file(document.url)
            with open(pdf_path, 'wb') as f:
                f.write(pdf_content)
            
            # Upload PDF to storage for Document Intelligence processing (if not already accessible)
            pdf_url = document.url
            if not self._is_accessible_url(document.url):
                logger.info("Uploading PDF to accessible storage for Document Intelligence")
                storage_path = f"processed_pdfs/{document.metadata.document_name}.pdf"
                pdf_url = await self.storage_service.upload_file(pdf_content, storage_path)
            
            # Get AI Vision thresholds from context if available
            ai_vision_thresholds = getattr(context, 'ai_vision_thresholds', None)
            
            # Process the complete PDF with Document Intelligence and extract figures if needed
            logger.info("Processing complete PDF with Document Intelligence")
            extraction_result = await self.text_extraction_service.extract_from_pdf(
                pdf_url=pdf_url,
                pdf_path=pdf_path,
                use_ai_vision=True,
                ai_vision_thresholds=ai_vision_thresholds,
                document=document  # Pass document for bronze storage
            )
            
            # Create result with enhanced metadata including bronze storage info
            return ExtractionResult(
                document_id=document.metadata.document_name,
                content=extraction_result['content'],
                confidence_score=extraction_result.get('confidence'),
                metadata={
                    "processing_method": "complete_pdf_with_selective_figures",
                    "figures_count": extraction_result.get('figures_count', 0),
                    "figures_analyzed": extraction_result.get('figures_analyzed', 0),
                    "figures_skipped": extraction_result.get('figures_skipped', 0),
                    "has_figures": extraction_result.get('has_figures', False),
                    "figures_urls": extraction_result.get('figures_urls', []),
                    "figure_analysis_decisions": extraction_result.get('figure_analysis_decisions', []),
                    "ai_vision_enabled": extraction_result.get('ai_vision_enabled', False),
                    "thresholds_applied": extraction_result.get('thresholds_applied', {}),
                    "pdf_url": pdf_url,
                    "temp_dir": temp_dir,
                    "bronze_storage_urls": extraction_result.get('bronze_storage_urls', {}),
                    "bronze_base_folder": extraction_result.get('bronze_base_folder'),
                    "processing_data": extraction_result.get('processing_data', {})
                }
            )
            
        except Exception as e:
            logger.error(f"Error processing PDF: {str(e)}")
            raise
        finally:
            # Cleanup handled by context manager or separate service
            if temp_dir and context.cleanup_temp_files:
                await self._cleanup_temp_directory(temp_dir)
    
    def _is_accessible_url(self, url: str) -> bool:
        """Check if URL is accessible to Document Intelligence service"""
        # Document Intelligence can access public URLs and Azure Blob Storage URLs
        return (url.startswith('https://') and 
                ('blob.core.windows.net' in url or 
                 'azure.com' in url or
                 not url.startswith('file://')))
    
    async def _cleanup_temp_directory(self, temp_dir: str):
        """Clean up temporary directory"""
        try:
            import shutil
            shutil.rmtree(temp_dir)
            logger.info(f"Cleaned up temporary directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp directory {temp_dir}: {e}")

class MSOfficeProcessingStrategy(IDocumentProcessor):
    """Strategy for processing Microsoft Office documents"""
    
    def __init__(
        self,
        conversion_service: IConversionService,
        pdf_strategy: PDFProcessingStrategy
    ):
        self.conversion_service = conversion_service
        self.pdf_strategy = pdf_strategy
    
    async def can_process(self, document: Document) -> bool:
        return document.document_type in [
            DocumentType.WORD, DocumentType.WORD_LEGACY,
            DocumentType.POWERPOINT, DocumentType.POWERPOINT_LEGACY
        ]
    
    async def process(self, document: Document, context: ProcessingContext) -> ExtractionResult:
        """Process MS Office document by converting to PDF first"""
        temp_dir = None
        try:
            # Create temporary directory
            temp_dir = tempfile.mkdtemp()
            
            # Download original document
            doc_content = await self.pdf_strategy.storage_service.download_file(document.url)
            
            # Save to temp file
            original_path = os.path.join(temp_dir, f"document.{document.document_type.value}")
            with open(original_path, 'wb') as f:
                f.write(doc_content)
            
            # Convert to PDF
            pdf_path = os.path.join(temp_dir, "converted.pdf")
            success = await self.conversion_service.convert_to_pdf(original_path, pdf_path)
            
            if not success:
                raise Exception("Failed to convert document to PDF")
            
            # Upload PDF to storage
            with open(pdf_path, 'rb') as f:
                pdf_content = f.read()
            
            pdf_storage_path = f"converted_pdfs/{document.metadata.document_name}.pdf"
            pdf_url = await self.pdf_strategy.storage_service.upload_file(pdf_content, pdf_storage_path)
            
            # Create PDF document and process it
            pdf_document = Document(
                url=pdf_url,
                document_type=DocumentType.PDF,
                metadata=document.metadata
            )
            
            # Process as PDF
            result = await self.pdf_strategy.process(pdf_document, context)
            result.metadata["original_type"] = document.document_type.value
            result.metadata["converted_pdf_url"] = pdf_url
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing MS Office document: {str(e)}")
            raise
        finally:
            if temp_dir and context.cleanup_temp_files:
                await self.pdf_strategy._cleanup_temp_directory(temp_dir)

class ImageProcessingStrategy(IDocumentProcessor):
    """Strategy for processing individual image documents"""
    
    def __init__(self, text_extraction_service: TextExtractionService):
        self.text_extraction_service = text_extraction_service
    
    async def can_process(self, document: Document) -> bool:
        return document.document_type == DocumentType.IMAGE
    
    async def process(self, document: Document, context: ProcessingContext) -> ExtractionResult:
        """Process single image document"""
        try:
            # Extract text from single image
            extracted_texts = await self.text_extraction_service.extract_from_images([document.url])
            
            return ExtractionResult(
                document_id=document.metadata.document_name,
                content=extracted_texts[0] if extracted_texts else "",
                page_count=1,
                metadata={"image_url": document.url}
            )
            
        except Exception as e:
            logger.error(f"Error processing image: {str(e)}")
            raise

class UnsupportedDocumentStrategy(IDocumentProcessor):
    """Fallback strategy for unsupported document types"""
    
    async def can_process(self, document: Document) -> bool:
        return True  # Always can "process" (by failing gracefully)
    
    async def process(self, document: Document, context: ProcessingContext) -> ExtractionResult:
        """Handle unsupported document types"""
        error_message = f"Document type {document.document_type.value} is not currently supported"
        logger.warning(error_message)
        
        return ExtractionResult(
            document_id=document.metadata.document_name,
            content="",
            errors=[error_message],
            metadata={"unsupported_type": document.document_type.value}
        ) 