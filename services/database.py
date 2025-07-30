import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Float, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from dataclasses import asdict

from services.ocr.entities import Document, DocumentMetadata, ExtractionResult, ProcessingStatus, DocumentType

logger = logging.getLogger(__name__)

# Nuevos enums para gestión de estados
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

# SQLAlchemy Base
Base = declarative_base()

class DocumentRecord(Base):
    """Modelo de base de datos para documentos procesados"""
    __tablename__ = "documents"
    
    # Identificadores únicos
    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(String(255), unique=True, nullable=False, index=True)
    
    # Información básica del documento
    document_name = Column(String(500), nullable=False)
    document_type = Column(String(50), nullable=False)
    original_url = Column(Text, nullable=False)
    
    # Metadatos de contexto
    request_id = Column(String(255), nullable=False, index=True)
    user_email = Column(String(255), nullable=False, index=True)
    context_id = Column(String(255), nullable=True, index=True)
    context_name = Column(String(500), nullable=True)
    attachment_id = Column(String(255), nullable=True)
    
    # Estados y procesamiento
    processing_status = Column(String(50), nullable=False, default=ProcessingStatus.PENDING.value)
    data_state = Column(String(50), nullable=False, default=DataState.BRONZE.value)
    process_stage = Column(String(50), nullable=False, default=ProcessStage.INGESTION.value)
    
    # Información de procesamiento
    confidence_score = Column(Float, nullable=True)
    page_count = Column(Integer, nullable=True)
    processing_time = Column(Float, nullable=True)
    content_length = Column(Integer, nullable=True)
    
    # Rutas de almacenamiento
    bronze_folder_path = Column(Text, nullable=True)
    original_document_url = Column(Text, nullable=True)
    extracted_content_url = Column(Text, nullable=True)
    figures_folder_url = Column(Text, nullable=True)
    
    # Metadatos adicionales y configuración
    extra_metadata = Column(JSON, nullable=True)
    processing_config = Column(JSON, nullable=True)
    ai_vision_enabled = Column(Boolean, default=True)
    
    # Calidad y errores
    quality_score = Column(Float, nullable=True)
    has_errors = Column(Boolean, default=False)
    error_details = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    processing_started_at = Column(DateTime, nullable=True)
    processing_completed_at = Column(DateTime, nullable=True)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertir el registro a diccionario incluyendo toda la metadata"""
        return {
            # Identificadores únicos
            'id': self.id,
            'document_id': self.document_id,
            
            # Información básica del documento
            'document_name': self.document_name,
            'document_type': self.document_type,
            'original_url': self.original_url,
            
            # Metadatos de contexto - CRÍTICOS para funcionamiento
            'request_id': self.request_id,
            'user_email': self.user_email,
            'context_id': self.context_id,
            'context_name': self.context_name,
            'attachment_id': self.attachment_id,
            
            # Estados y procesamiento
            'processing_status': self.processing_status,
            'data_state': self.data_state,
            'process_stage': self.process_stage,
            
            # Información de procesamiento
            'confidence_score': self.confidence_score,
            'page_count': self.page_count,
            'processing_time': self.processing_time,
            'content_length': self.content_length,
            
            # Rutas de almacenamiento
            'bronze_folder_path': self.bronze_folder_path,
            'original_document_url': self.original_document_url,
            'extracted_content_url': self.extracted_content_url,
            'figures_folder_url': self.figures_folder_url,
            
            # Metadatos adicionales y configuración - CRÍTICO
            'extra_metadata': self.extra_metadata,
            'processing_config': self.processing_config,
            'ai_vision_enabled': self.ai_vision_enabled,
            
            # Calidad y errores
            'quality_score': self.quality_score,
            'has_errors': self.has_errors,
            'error_details': self.error_details,
            
            # Timestamps
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'processing_started_at': self.processing_started_at.isoformat() if self.processing_started_at else None,
            'processing_completed_at': self.processing_completed_at.isoformat() if self.processing_completed_at else None
        }

class DocumentDatabase:
    """Servicio de base de datos para gestión de documentos"""
    
    def __init__(self, database_url: str = "sqlite:///./documents.db"):
        """
        Inicializar conexión a base de datos
        Args:
            database_url: URL de conexión (por defecto SQLite local)
        """
        self.database_url = database_url
        
        # Para SQLite sincrónico (más simple para empezar)
        if database_url.startswith("sqlite"):
            self.engine = create_engine(database_url, echo=False)
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        else:
            # Para bases de datos asíncronas (PostgreSQL, etc.)
            self.async_engine = create_async_engine(database_url, echo=False)
            self.AsyncSessionLocal = async_sessionmaker(
                autocommit=False, autoflush=False, bind=self.async_engine
            )
        
        # Crear tablas
        self.create_tables()
        logger.info(f"Database initialized with URL: {database_url}")
    
    def create_tables(self):
        """Crear tablas en la base de datos"""
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Error creating database tables: {str(e)}")
            raise
    
    def get_session(self) -> Session:
        """Obtener sesión de base de datos"""
        return self.SessionLocal()
    
    def create_document_record(self, document: Document, extraction_result: Optional[ExtractionResult] = None) -> DocumentRecord:
        """
        Crear registro de documento en base de datos
        
        Args:
            document: Entidad Document con metadatos
            extraction_result: Resultado de extracción (opcional)
        
        Returns:
            DocumentRecord creado
        """
        session = self.get_session()
        try:
            # Generar ID único si no existe
            document_id = f"{document.metadata.request_id}_{document.metadata.attachment_id}_{int(datetime.now().timestamp())}"
            
            record = DocumentRecord(
                document_id=document_id,
                document_name=document.metadata.document_name,
                document_type=document.document_type.value,
                original_url=document.url,
                request_id=document.metadata.request_id,
                user_email=document.metadata.user_email,
                context_id=document.metadata.context_id,
                context_name=document.metadata.context_name,
                attachment_id=document.metadata.attachment_id,
                processing_status=document.status.value,
                data_state=DataState.BRONZE.value,  # Siempre comienza en bronze
                process_stage=ProcessStage.INGESTION.value,
                extra_metadata=document.metadata.extra_metadata,
                processing_started_at=datetime.utcnow()
            )
            
            # Añadir información de extracción si está disponible
            if extraction_result:
                record.confidence_score = extraction_result.confidence_score
                record.page_count = extraction_result.page_count
                record.processing_time = extraction_result.processing_time
                record.content_length = len(extraction_result.content) if extraction_result.content else 0
                record.has_errors = bool(extraction_result.errors)
                record.error_details = {"errors": extraction_result.errors} if extraction_result.errors else None
            
            session.add(record)
            session.commit()
            session.refresh(record)
            
            logger.info(f"Created document record with ID: {record.document_id}")
            return record
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error creating document record: {str(e)}")
            raise
        finally:
            session.close()
    
    def update_document_status(self, document_id: str, status: ProcessingStatus, 
                             data_state: Optional[DataState] = None,
                             process_stage: Optional[ProcessStage] = None) -> Optional[DocumentRecord]:
        """
        Actualizar estado de documento
        
        Args:
            document_id: ID del documento
            status: Nuevo estado de procesamiento
            data_state: Nuevo estado de datos (opcional)
            process_stage: Nueva etapa de proceso (opcional)
        """
        session = self.get_session()
        try:
            record = session.query(DocumentRecord).filter(
                DocumentRecord.document_id == document_id
            ).first()
            
            if not record:
                logger.warning(f"Document record not found: {document_id}")
                return None
            
            # Actualizar campos
            record.processing_status = status.value
            record.updated_at = datetime.utcnow()
            
            if data_state:
                record.data_state = data_state.value
            
            if process_stage:
                record.process_stage = process_stage.value
            
            # Marcar como completado si está en estado COMPLETED
            if status == ProcessingStatus.COMPLETED:
                record.processing_completed_at = datetime.utcnow()
                if not process_stage:
                    record.process_stage = ProcessStage.READY.value
                # Mantener estado actual (BRONZE) - se actualizará en etapas posteriores
                # if not data_state:
                #     record.data_state = DataState.SILVER.value  # Promocionar a silver cuando se completa
            
            session.commit()
            session.refresh(record)
            
            logger.info(f"Updated document {document_id} status to {status.value}")
            return record
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating document status: {str(e)}")
            raise
        finally:
            session.close()
    
    def update_storage_paths(self, document_id: str, storage_paths: Dict[str, str]) -> Optional[DocumentRecord]:
        """
        Actualizar rutas de almacenamiento en Bronze
        
        Args:
            document_id: ID del documento
            storage_paths: Diccionario con rutas de almacenamiento
        """
        session = self.get_session()
        try:
            record = session.query(DocumentRecord).filter(
                DocumentRecord.document_id == document_id
            ).first()
            
            if not record:
                return None
            
            # Actualizar rutas de almacenamiento
            record.bronze_folder_path = storage_paths.get("base_folder")
            record.original_document_url = storage_paths.get("original_document")
            record.extracted_content_url = storage_paths.get("full_text")
            record.figures_folder_url = storage_paths.get("figures_folder")
            record.updated_at = datetime.utcnow()
            
            session.commit()
            session.refresh(record)
            
            logger.info(f"Updated storage paths for document {document_id}")
            return record
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating storage paths: {str(e)}")
            raise
        finally:
            session.close()
    
    def get_document_by_id(self, document_id: str) -> Optional[DocumentRecord]:
        """Obtener documento por ID"""
        session = self.get_session()
        try:
            return session.query(DocumentRecord).filter(
                DocumentRecord.document_id == document_id
            ).first()
        finally:
            session.close()
    
    def get_documents_by_user(self, user_email: str, limit: int = 100) -> List[DocumentRecord]:
        """Obtener documentos por usuario"""
        session = self.get_session()
        try:
            return session.query(DocumentRecord).filter(
                DocumentRecord.user_email == user_email
            ).order_by(DocumentRecord.created_at.desc()).limit(limit).all()
        finally:
            session.close()
    
    def get_documents_by_context(self, context_id: str, limit: int = 100) -> List[DocumentRecord]:
        """Obtener documentos por contexto"""
        session = self.get_session()
        try:
            return session.query(DocumentRecord).filter(
                DocumentRecord.context_id == context_id
            ).order_by(DocumentRecord.created_at.desc()).limit(limit).all()
        finally:
            session.close()
    
    def get_documents_by_state(self, data_state: DataState, limit: int = 100) -> List[DocumentRecord]:
        """Obtener documentos por estado de datos"""
        session = self.get_session()
        try:
            return session.query(DocumentRecord).filter(
                DocumentRecord.data_state == data_state.value
            ).order_by(DocumentRecord.created_at.desc()).limit(limit).all()
        finally:
            session.close()
    
    def update_document_record(self, document_id: str, updates: Dict[str, Any]) -> Optional[DocumentRecord]:
        """
        Actualizar un registro de documento de forma segura
        
        Args:
            document_id: ID del documento
            updates: Diccionario con campos a actualizar
            
        Returns:
            DocumentRecord actualizado o None si no se encuentra
        """
        session = self.get_session()
        try:
            record = session.query(DocumentRecord).filter(
                DocumentRecord.document_id == document_id
            ).first()
            
            if not record:
                return None
            
            # Aplicar actualizaciones
            for field, value in updates.items():
                if hasattr(record, field):
                    setattr(record, field, value)
            
            # Siempre actualizar timestamp
            record.updated_at = datetime.utcnow()
            
            session.commit()
            session.refresh(record)
            
            logger.info(f"Updated document record {document_id}")
            return record
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error updating document record: {str(e)}")
            raise
        finally:
            session.close()

    def get_processing_stats(self) -> Dict[str, Any]:
        """Obtener estadísticas de procesamiento"""
        session = self.get_session()
        try:
            total_docs = session.query(DocumentRecord).count()
            
            # Estadísticas por estado
            status_stats = {}
            for status in ProcessingStatus:
                count = session.query(DocumentRecord).filter(
                    DocumentRecord.processing_status == status.value
                ).count()
                status_stats[status.value] = count
            
            # Estadísticas por estado de datos
            data_state_stats = {}
            for state in DataState:
                count = session.query(DocumentRecord).filter(
                    DocumentRecord.data_state == state.value
                ).count()
                data_state_stats[state.value] = count
            
            return {
                "total_documents": total_docs,
                "by_processing_status": status_stats,
                "by_data_state": data_state_stats
            }
        finally:
            session.close() 