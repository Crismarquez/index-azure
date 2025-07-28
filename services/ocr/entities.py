from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime

class DocumentType(Enum):
    PDF = "pdf"
    WORD = "docx"
    WORD_LEGACY = "doc"
    POWERPOINT = "pptx"
    POWERPOINT_LEGACY = "ppt"
    EXCEL = "xlsx"
    IMAGE = "image"
    VIDEO = "mp4"

class ProcessingStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class DocumentMetadata:
    """Rich metadata for documents - generalized for any use case"""
    request_id: str  # Generic identifier (was engagement_id)
    user_email: str
    document_name: str
    context_id: Optional[str] = None  # Generic context (was deal_id) 
    context_name: Optional[str] = None  # Generic context name (was deal_name)
    attachment_id: Optional[str] = None  # Changed to string for flexibility
    content_type: Optional[str] = None
    file_size: Optional[int] = None
    created_at: datetime = None
    # Additional metadata can be stored here
    extra_metadata: Optional[Dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()

@dataclass
class Document:
    """Core document entity"""
    url: str
    document_type: DocumentType
    metadata: DocumentMetadata
    status: ProcessingStatus = ProcessingStatus.PENDING
    
    def __post_init__(self):
        # Auto-detect document type from URL if not provided
        if isinstance(self.document_type, str):
            try:
                self.document_type = DocumentType(self.document_type.lower())
            except ValueError:
                raise ValueError(f"Unsupported document type: {self.document_type}")

@dataclass
class ExtractionResult:
    """Result of OCR processing"""
    document_id: str
    content: str
    confidence_score: Optional[float] = None
    page_count: Optional[int] = None
    processing_time: Optional[float] = None
    metadata: Dict[str, Any] = None
    errors: List[str] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.errors is None:
            self.errors = []

@dataclass
class ProcessingContext:
    """Context for processing operations"""
    temp_directory: Optional[str] = None
    max_pages: Optional[int] = None
    quality_settings: Dict[str, Any] = None
    retry_attempts: int = 3
    timeout_seconds: int = 300
    cleanup_temp_files: bool = True
    ai_vision_thresholds: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.quality_settings is None:
            self.quality_settings = {"zoom": 5, "dpi": 300} 

# Generic schemas for document processing (replacing HubSpot-specific schemas)
@dataclass
class DocumentAttachment:
    """Generic document attachment that can be used in any context"""
    url: str
    file_type: str  # File extension or MIME type
    name: str
    attachment_id: str
    size_bytes: Optional[int] = None
    upload_date: Optional[str] = None

@dataclass  
class ProcessingRequest:
    """Generic processing request that can be used for any document processing scenario"""
    request_id: str  # Generic identifier (could be engagement_id, task_id, etc.)
    user_email: str
    context_id: Optional[str] = None  # Generic context (could be deal_id, project_id, etc.)
    context_name: Optional[str] = None  # Generic context name (could be deal_name, project_name, etc.)
    attachments: List[DocumentAttachment] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)  # For additional context-specific data
    
    def __post_init__(self):
        """Validate the processing request"""
        if not self.attachments:
            raise ValueError("At least one attachment is required")
        if not self.request_id:
            raise ValueError("request_id is required")
        if not self.user_email:
            raise ValueError("user_email is required") 