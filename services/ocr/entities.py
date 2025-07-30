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

# Nuevos enums para gestión de estados avanzada
class DataState(Enum):
    """Estado de los datos en la arquitectura de capas"""
    BRONZE = "bronze"      # Datos brutos, sin procesar
    SILVER = "silver"      # Datos limpios y estructurados
    GOLD = "gold"          # Datos agregados y listos para análisis

class ProcessStage(Enum):
    """Etapa del proceso de datos"""
    INGESTION = "ingestion"         # Carga inicial
    EXTRACTION = "extraction"       # Extracción OCR/IA
    TRANSFORMATION = "transformation" # Limpieza y transformación
    ENRICHMENT = "enrichment"       # Enriquecimiento con metadatos
    VALIDATION = "validation"       # Validación de calidad
    READY = "ready"                # Listo para consumo

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
    """Core document entity with extended state management"""
    url: str
    document_type: DocumentType
    metadata: DocumentMetadata
    status: ProcessingStatus = ProcessingStatus.PENDING
    # Nuevos campos para gestión de estados
    data_state: DataState = DataState.BRONZE
    process_stage: ProcessStage = ProcessStage.INGESTION
    # Campo para ID único en base de datos
    document_id: Optional[str] = None
    
    def __post_init__(self):
        # Auto-detect document type from URL if not provided
        if isinstance(self.document_type, str):
            try:
                self.document_type = DocumentType(self.document_type.lower())
            except ValueError:
                raise ValueError(f"Unsupported document type: {self.document_type}")
        
        # Generar ID único si no se proporciona
        if not self.document_id:
            timestamp = int(datetime.now().timestamp())
            self.document_id = f"{self.metadata.request_id}_{self.metadata.attachment_id}_{timestamp}"

@dataclass
class ExtractionResult:
    """Result of OCR processing with enhanced metadata"""
    document_id: str
    content: str
    pages: List[Dict[str, Any]] = None
    confidence_score: Optional[float] = None
    page_count: Optional[int] = None
    processing_time: Optional[float] = None
    metadata: Dict[str, Any] = None
    errors: List[str] = None
    # Nuevos campos para gestión de resultados
    quality_score: Optional[float] = None
    figures_detected: Optional[int] = None
    ai_vision_enabled: bool = True
    storage_paths: Optional[Dict[str, str]] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.errors is None:
            self.errors = []
        if self.storage_paths is None:
            self.storage_paths = {}

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