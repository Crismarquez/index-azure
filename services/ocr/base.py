import time
import os
from typing import List, Optional, Dict, Any

from services.interfaces import (
    IDocumentProcessor, IOCRService, IVisionService, 
    IStorageService, IConversionService, IConfigurationService, IErrorHandler
)
from services.ocr.entities import Document, ExtractionResult, ProcessingContext, ProcessingStatus, DocumentMetadata, ProcessingRequest
from services.data import BronzeStorageService

from config.config import logger

class DocumentOrchestrationService:
    """Main orchestrator for document processing"""
    
    def __init__(
        self,
        processors: List[IDocumentProcessor],
        error_handler: IErrorHandler,
        config_service: IConfigurationService
    ):
        self.processors = processors
        self.error_handler = error_handler
        self.config_service = config_service
        
    async def process_document(self, document: Document) -> ExtractionResult:
        """Main entry point for document processing"""
        start_time = time.perf_counter()
        context = ProcessingContext(**self.config_service.get_ocr_config())
        
        # Add AI Vision thresholds to context
        context.ai_vision_thresholds = self.config_service.get_ai_vision_thresholds()
        
        try:
            # Find appropriate processor
            processor = await self._find_processor(document)
            if not processor:
                raise ValueError(f"No processor found for document type: {document.document_type}")
            
            # Update status
            document.status = ProcessingStatus.PROCESSING
            logger.info(f"Processing document {document.metadata.document_name} with {processor.__class__.__name__}")
            
            # Log AI Vision configuration
            if context.ai_vision_thresholds:
                enabled = context.ai_vision_thresholds.get('enabled', True)
                logger.info(f"AI Vision analysis: {'enabled' if enabled else 'disabled'}")
                if enabled:
                    max_figures = context.ai_vision_thresholds.get('max_figures_per_document', 'unlimited')
                    min_size = context.ai_vision_thresholds.get('min_figure_size', 0.01)
                    logger.info(f"AI Vision thresholds: max_figures={max_figures}, min_size={min_size}")
            
            # Process document
            result = await processor.process(document, context)
            result.processing_time = time.perf_counter() - start_time
            
            document.status = ProcessingStatus.COMPLETED
            logger.info(f"Successfully processed document in {result.processing_time:.2f} seconds")
            
            return result
            
        except Exception as e:
            document.status = ProcessingStatus.FAILED
            should_retry = await self.error_handler.handle_error(e, {
                "document": document,
                "processor": processor.__class__.__name__ if 'processor' in locals() else None
            })
            
            if should_retry:
                logger.info("Retrying document processing...")
                return await self.process_document(document)
            
            raise
    
    async def _find_processor(self, document: Document) -> Optional[IDocumentProcessor]:
        """Find the appropriate processor for the document"""
        for processor in self.processors:
            if await processor.can_process(document):
                return processor
        return None

class TextExtractionService:
    """Service for coordinating text extraction from different sources"""
    
    def __init__(
        self,
        ocr_service: IOCRService,
        vision_service: IVisionService,
        storage_service: IStorageService
    ):
        self.ocr_service = ocr_service
        self.vision_service = vision_service
        self.storage_service = storage_service
        self.bronze_storage = BronzeStorageService(storage_service)
    
    async def extract_from_pdf(self, pdf_url: str, pdf_path: str = None, use_ai_vision: bool = True, ai_vision_thresholds: Dict[str, Any] = None, document: Document = None) -> Dict[str, Any]:
        """Extract text from complete PDF and handle figures when detected with bronze storage"""
        start_time = time.perf_counter()
        processing_data = {
            "start_time": start_time,
            "ai_vision_enabled": use_ai_vision,
            "thresholds_applied": ai_vision_thresholds or {},
            "errors": [],
            "warnings": []
        }
        
        # Get bronze storage paths if document is provided
        bronze_paths = None
        if document:
            bronze_paths = self.bronze_storage.get_bronze_paths(document)
            logger.info(f"Using bronze storage structure: {bronze_paths['base_folder']}")
        
        try:
            # Process the complete PDF with Document Intelligence
            logger.info("Processing complete PDF with Document Intelligence")
            pdf_result = await self.ocr_service.extract_text_from_pdf(pdf_url)
            
            extracted_content = pdf_result.get('content', '')
            figures_info = pdf_result.get('figures', [])
            has_figures = pdf_result.get('has_figures', False)
            pages = pdf_result.get('pages', [])
            
            figure_descriptions = []
            figure_urls = []
            figure_analysis_decisions = []
            figure_contents = []  # Store figure binary content for bronze storage
            
            # Check if AI Vision is enabled and configured
            if ai_vision_thresholds and not ai_vision_thresholds.get('enabled', True):
                use_ai_vision = False
                logger.info("AI Vision analysis disabled by configuration")
            
            # If figures are detected and AI vision is enabled, apply thresholds and extract relevant figures
            if has_figures and use_ai_vision and pdf_path and figures_info:
                logger.info(f"Found {len(figures_info)} figures, applying thresholds for selective analysis")
                
                # Default thresholds if none provided
                if ai_vision_thresholds is None:
                    ai_vision_thresholds = {
                        'min_figure_size': 0.01,
                        'excluded_keywords': ['logo', 'signature', 'watermark'],
                        'max_figures_per_document': 10,
                        'enabled': True
                    }
                
                # Create temporary directory for figure extraction
                import tempfile
                temp_figures_dir = tempfile.mkdtemp()
                
                try:
                    # Filter figures based on thresholds
                    figures_to_analyze = []
                    for figure_info in figures_info:
                        # Apply threshold analysis
                        decision = self.ocr_service.should_analyze_figure_with_ai_vision(
                            figure_info, ai_vision_thresholds
                        )
                        figure_analysis_decisions.append(decision)
                        
                        if decision['should_analyze']:
                            figures_to_analyze.append(figure_info)
                            logger.info(f"Figure {figure_info.get('id')} will be analyzed: {', '.join(decision['reasons'])}")
                        else:
                            logger.info(f"Figure {figure_info.get('id')} skipped: {', '.join(decision['reasons'])}")
                    
                    if figures_to_analyze:
                        # Extract only the figures that passed the threshold check
                        figure_paths = await self.ocr_service.extract_figures_from_pdf(
                            pdf_path, figures_to_analyze, temp_figures_dir, pages
                        )
                        
                        # Process each extracted figure with AI vision
                        for i, figure_path in enumerate(figure_paths):
                            try:
                                # Read figure content for storage
                                with open(figure_path, 'rb') as f:
                                    figure_content = f.read()
                                    figure_contents.append(figure_content)
                                
                                # Upload figure to storage (legacy path for immediate access)
                                storage_path = f"extracted_figures/{os.path.basename(pdf_path)}/figure_{i+1}.png"
                                figure_url = await self.storage_service.upload_file(figure_content, storage_path)
                                figure_urls.append(figure_url)
                                
                                # Get AI description of the figure
                                if self.vision_service.storage_type == 'local':
                                    figure_description = await self.vision_service.describe_image(
                                        figure_path, 
                                        self._get_figure_analysis_prompt()
                                    )
                                else:   
                                    figure_description = await self.vision_service.describe_image(
                                        figure_url, 
                                        self._get_figure_analysis_prompt()
                                    )
                                figure_descriptions.append(figure_description)
                                
                                # Store figure data for bronze storage
                                figures_to_analyze[i]["analysis"] = figure_description
                                
                                logger.info(f"Successfully analyzed figure {i+1} with AI Vision")
                                
                            except Exception as e:
                                error_msg = f"Error processing figure {i+1}: {str(e)}"
                                logger.error(error_msg)
                                processing_data["errors"].append(error_msg)
                                figure_descriptions.append(f"[Error processing figure {i+1}]")
                    else:
                        logger.info("No figures met the criteria for AI Vision analysis")
                    
                finally:
                    # Cleanup temporary files
                    import shutil
                    try:
                        shutil.rmtree(temp_figures_dir)
                    except Exception as e:
                        logger.warning(f"Failed to cleanup temp directory: {e}")
            
            # Combine the main document content with figure descriptions
            if figure_descriptions:
                figure_section = "\n\n## EXTRACTED FIGURES AND CHARTS:\n\n"
                for i, description in enumerate(figure_descriptions):
                    figure_section += f"### Figure {i+1}:\n{description}\n\n"
                extracted_content += figure_section
            
            # Update processing data
            processing_data.update({
                "end_time": time.perf_counter(),
                "duration": time.perf_counter() - start_time,
                "figures_detected": len(figures_info),
                "figures_analyzed": len(figure_descriptions),
                "figures_skipped": len(figures_info) - len(figure_descriptions) if figures_info else 0
            })
            
            # Store results in bronze structure if document is provided
            bronze_urls = {}
            if document and bronze_paths:
                try:
                    # Store original document if we have access to pdf content
                    if pdf_path and os.path.exists(pdf_path):
                        with open(pdf_path, 'rb') as f:
                            pdf_content = f.read()
                        bronze_urls["original_document"] = await self.bronze_storage.store_original_document(
                            document, pdf_content, bronze_paths
                        )
                    
                    # Store figures in bronze structure
                    if figure_contents and figures_to_analyze:
                        bronze_urls["figures"] = await self.bronze_storage.store_figures(
                            figures_to_analyze, figure_contents, bronze_paths
                        )
                    
                    # Store processing logs
                    bronze_urls["processing_logs"] = await self.bronze_storage.store_processing_logs(
                        processing_data, bronze_paths
                    )
                    
                    logger.info("Successfully stored results in bronze structure")
                    
                except Exception as e:
                    error_msg = f"Error storing to bronze structure: {str(e)}"
                    logger.warning(error_msg)
                    processing_data["warnings"].append(error_msg)
            
            return {
                'content': extracted_content,
                'figures_count': len(figures_info),
                'figures_analyzed': len(figure_descriptions),
                'figures_skipped': len(figures_info) - len(figure_descriptions) if figures_info else 0,
                'figures_descriptions': figure_descriptions,
                'figures_urls': figure_urls,
                'figure_analysis_decisions': figure_analysis_decisions,
                'has_figures': has_figures,
                'ai_vision_enabled': use_ai_vision,
                'thresholds_applied': ai_vision_thresholds,
                'confidence': pdf_result.get('confidence'),
                'metadata': pdf_result,
                'bronze_storage_urls': bronze_urls,
                'bronze_base_folder': bronze_paths["base_folder"] if bronze_paths else None,
                'processing_data': processing_data
            }
            
        except Exception as e:
            error_msg = f"Error extracting from PDF: {str(e)}"
            logger.error(error_msg)
            processing_data["errors"].append(error_msg)
            processing_data["end_time"] = time.perf_counter()
            processing_data["duration"] = time.perf_counter() - start_time
            
            # Try to store error logs in bronze structure if possible
            if document and bronze_paths:
                try:
                    await self.bronze_storage.store_processing_logs(processing_data, bronze_paths)
                except Exception as log_error:
                    logger.warning(f"Could not store error logs to bronze: {str(log_error)}")
            
            raise
    
    async def extract_from_images(self, image_urls: List[str], use_ai_vision: bool = True) -> List[str]:
        """Extract text from a list of images"""
        results = []
        
        for i, image_url in enumerate(image_urls):
            try:
                # First try OCR
                ocr_result = await self.ocr_service.extract_text_with_layout(image_url)
                
                # If OCR detects figures/charts and AI vision is available, use enhanced extraction
                if use_ai_vision and self._has_complex_content(ocr_result):
                    logger.info(f"Using AI vision for complex content in image {i+1}")
                    enhanced_content = await self.vision_service.describe_image(
                        image_url, 
                        self._get_vision_prompt()
                    )
                    results.append(enhanced_content)
                else:
                    results.append(ocr_result.get('content', ''))
                    
            except Exception as e:
                logger.error(f"Error processing image {i+1}: {str(e)}")
                results.append(f"[Error processing page {i+1}]")
        
        return results
    
    def _has_complex_content(self, ocr_result: Dict[str, Any]) -> bool:
        """Determine if OCR result contains complex content requiring AI vision"""
        return 'figures' in ocr_result or 'tables' in ocr_result
    
    def _get_vision_prompt(self) -> str:
        """Get the prompt for AI vision processing"""
        return """
        Extract all text, tables, and describe any charts/diagrams in markdown format.
        Focus on preserving the exact original text and structure.
        For charts/graphs, convert data into readable markdown tables.
        """

    def _get_figure_analysis_prompt(self) -> str:
        """Get the prompt for analyzing extracted figures"""
        return """
        Analyze this figure/chart/diagram and provide a detailed description in markdown format.
        Include:
        1. Type of figure (chart, diagram, graph, etc.)
        2. Main content and data presented
        3. Key insights or trends visible
        4. Any text or labels present
        5. Convert any data into readable format (tables if applicable)
        
        Be comprehensive and preserve all important information from the figure.
        """

class QualityAssuranceService:
    """Service for quality checks and validation"""
    
    def __init__(self):
        self.min_confidence = 0.7
        self.min_content_length = 10
    
    async def validate_extraction_result(self, result: ExtractionResult) -> bool:
        """Validate the quality of extraction results"""
        issues = []
        
        # Check content length
        if len(result.content.strip()) < self.min_content_length:
            issues.append("Content too short")
        
        # Check confidence score
        if result.confidence_score and result.confidence_score < self.min_confidence:
            issues.append(f"Low confidence score: {result.confidence_score}")
        
        # Check for common OCR errors
        error_indicators = ['###', '???', 'ﾃ�', '▪▪▪']
        if any(indicator in result.content for indicator in error_indicators):
            issues.append("Potential OCR artifacts detected")
        
        if issues:
            result.errors.extend(issues)
            logger.warning(f"Quality issues found: {issues}")
            return False
        
        return True
    
    async def suggest_improvements(self, result: ExtractionResult) -> List[str]:
        """Suggest improvements for poor quality results"""
        suggestions = []
        
        if result.confidence_score and result.confidence_score < self.min_confidence:
            suggestions.append("Consider using higher resolution images")
            suggestions.append("Try preprocessing images (noise reduction, contrast enhancement)")
        
        if len(result.content.strip()) < self.min_content_length:
            suggestions.append("Verify source document quality")
            suggestions.append("Check if document contains actual text content")
        
        return suggestions 