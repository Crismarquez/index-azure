from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from services.ocr.entities import Document, ExtractionResult, ProcessingContext

class IDocumentProcessor(ABC):
    """Interface for document processing strategies"""
    
    @abstractmethod
    async def can_process(self, document: Document) -> bool:
        """Check if this processor can handle the document type"""
        pass
    
    @abstractmethod
    async def process(self, document: Document, context: ProcessingContext) -> ExtractionResult:
        """Process the document and extract text"""
        pass

class IOCRService(ABC):
    """Interface for OCR services"""
    
    @abstractmethod
    async def extract_text_from_image(self, image_url: str, options: Dict[str, Any] = None) -> str:
        """Extract text from a single image"""
        pass
    
    @abstractmethod
    async def extract_text_with_layout(self, image_url: str, options: Dict[str, Any] = None) -> Dict[str, Any]:
        """Extract text with layout information"""
        pass

    @abstractmethod
    async def extract_text_from_pdf(self, pdf_url: str, options: Dict[str, Any] = None) -> Dict[str, Any]:
        """Extract text and detect figures from complete PDF using Document Intelligence"""
        pass

    @abstractmethod
    async def extract_figures_from_pdf(self, pdf_path: str, figures_info: List[Dict[str, Any]], output_dir: str) -> List[str]:
        """Extract specific figures from PDF based on Document Intelligence detection"""
        pass

class IVisionService(ABC):
    """Interface for AI vision services"""
    
    @abstractmethod
    async def describe_image(self, image_url: str, prompt: str) -> str:
        """Generate description for complex images with charts/diagrams"""
        pass

class IStorageService(ABC):
    """Interface for storage operations"""
    
    @abstractmethod
    async def upload_file(self, content: bytes, path: str) -> str:
        """Upload file and return URL"""
        pass
    
    @abstractmethod
    async def download_file(self, url: str) -> bytes:
        """Download file content"""
        pass
    
    @abstractmethod
    async def delete_file(self, path: str) -> bool:
        """Delete file"""
        pass
    
    @abstractmethod
    def list_files(self, prefix: str = "") -> List[str]:
        """List all files with optional prefix filter"""
        pass

class IConversionService(ABC):
    """Interface for document conversion"""
    
    @abstractmethod
    async def convert_to_pdf(self, source_path: str, target_path: str) -> bool:
        """Convert document to PDF"""
        pass
    
    @abstractmethod
    async def pdf_to_images(self, pdf_path: str, output_dir: str, quality_settings: Dict[str, Any]) -> List[str]:
        """Convert PDF pages to images"""
        pass

class IConfigurationService(ABC):
    """Interface for configuration management"""
    
    @abstractmethod
    def get_ocr_config(self) -> Dict[str, Any]:
        """Get OCR service configuration"""
        pass
    
    @abstractmethod
    def get_storage_config(self) -> Dict[str, Any]:
        """Get storage configuration"""
        pass
    
    @abstractmethod
    def get_ai_config(self) -> Dict[str, Any]:
        """Get AI services configuration"""
        pass

    @abstractmethod
    def get_ai_vision_thresholds(self) -> Dict[str, Any]:
        """Get configurable thresholds for AI Vision figure analysis"""
        pass

class IErrorHandler(ABC):
    """Interface for error handling"""
    
    @abstractmethod
    async def handle_error(self, error: Exception, context: Dict[str, Any]) -> bool:
        """Handle errors with retry logic and logging"""
        pass
    
    @abstractmethod
    def should_retry(self, error: Exception, attempt: int) -> bool:
        """Determine if operation should be retried"""
        pass 