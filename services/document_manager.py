import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from services.database import DocumentDatabase, DataState, ProcessStage
from services.ocr.entities import Document, ExtractionResult, ProcessingStatus
from services.data import BronzeStorageService
from services.interfaces import IStorageService

logger = logging.getLogger(__name__)

class DocumentManager:
    """
    Gestor de alto nivel para documentos que integra:
    - Base de datos para tracking y gestión
    - Almacenamiento Bronze para archivos
    - Estados y etapas de procesamiento
    """
    
    def __init__(self, 
                 database: DocumentDatabase,
                 storage_service: IStorageService,
                 bronze_base_path: str = "bronze"):
        self.database = database
        self.storage_service = storage_service
        self.bronze_storage = BronzeStorageService(storage_service, bronze_base_path)
        
        logger.info("DocumentManager initialized")
    
    async def register_document(self, document: Document) -> str:
        """
        Registrar un nuevo documento en el sistema
        
        Args:
            document: Entidad Document con metadatos
            
        Returns:
            document_id: ID único del documento registrado
        """
        try:
            # Crear registro en base de datos
            record = self.database.create_document_record(document)
            
            # Actualizar el document_id en la entidad
            document.document_id = record.document_id
            
            logger.info(f"Document registered with ID: {record.document_id}")
            return record.document_id
            
        except Exception as e:
            logger.error(f"Error registering document: {str(e)}")
            raise
    
    async def update_processing_status(self, 
                                     document_id: str, 
                                     status: ProcessingStatus,
                                     stage: Optional[ProcessStage] = None) -> bool:
        """
        Actualizar estado de procesamiento de un documento
        
        Args:
            document_id: ID del documento
            status: Nuevo estado de procesamiento
            stage: Nueva etapa de proceso (opcional)
            
        Returns:
            True si se actualizó correctamente
        """
        try:
            # Determinar stage automáticamente si no se proporciona
            if not stage:
                if status == ProcessingStatus.PROCESSING:
                    stage = ProcessStage.EXTRACTION
                elif status == ProcessingStatus.COMPLETED:
                    stage = ProcessStage.READY
                elif status == ProcessingStatus.FAILED:
                    stage = ProcessStage.VALIDATION  # Para revisión
            
            record = self.database.update_document_status(
                document_id=document_id,
                status=status,
                process_stage=stage
            )
            
            if record:
                logger.info(f"Updated processing status for {document_id}: {status.value}")
                return True
            else:
                logger.warning(f"Document not found for status update: {document_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating processing status: {str(e)}")
            raise
    
    async def store_extraction_result(self, 
                                    document: Document, 
                                    extraction_result: ExtractionResult,
                                    original_content: bytes) -> Dict[str, str]:
        """
        Almacenar resultado completo de extracción (BD + archivos)
        
        Args:
            document: Entidad Document
            extraction_result: Resultado de extracción
            original_content: Contenido original del documento
            
        Returns:
            Diccionario con URLs de almacenamiento
        """
        try:
            # 1. Obtener rutas de almacenamiento Bronze
            bronze_paths = self.bronze_storage.get_bronze_paths(document)
            
            # 2. Almacenar documento original
            original_url = await self.bronze_storage.store_original_document(
                document, original_content, bronze_paths
            )
            
            # 3. Almacenar resultado de extracción
            stored_urls = await self.bronze_storage.store_extraction_result(
                extraction_result, bronze_paths
            )
            
            # 4. Crear manifest
            all_stored_data = {
                "original_document": original_url,
                **stored_urls
            }
            
            manifest_url = await self.bronze_storage.create_bronze_manifest(
                document, all_stored_data, bronze_paths
            )
            
            # 5. Actualizar base de datos con rutas de almacenamiento
            self.database.update_storage_paths(document.document_id, bronze_paths)
            
            # 6. Actualizar información de extracción en BD
            extraction_updates = {
                'confidence_score': extraction_result.confidence_score,
                'page_count': extraction_result.page_count,
                'processing_time': extraction_result.processing_time,
                'content_length': len(extraction_result.content) if extraction_result.content else 0,
                'has_errors': bool(extraction_result.errors),
                'error_details': {"errors": extraction_result.errors} if extraction_result.errors else None,
                'quality_score': extraction_result.quality_score,
                'ai_vision_enabled': extraction_result.ai_vision_enabled
            }
            
            updated_record = self.database.update_document_record(document.document_id, extraction_updates)
            if not updated_record:
                logger.warning(f"Could not update extraction info for document {document.document_id}")
            
            # 7. Mantener en BRONZE - se actualizará en etapas posteriores
            # await self.update_data_state(document.document_id, DataState.SILVER)
            
            logger.info(f"Stored complete extraction result for document {document.document_id}")
            
            return {
                "manifest_url": manifest_url,
                "bronze_folder": bronze_paths["base_folder"],
                **all_stored_data
            }
            
        except Exception as e:
            logger.error(f"Error storing extraction result: {str(e)}")
            raise
    
    async def update_data_state(self, 
                              document_id: str, 
                              data_state: DataState) -> bool:
        """
        Actualizar estado de datos (Bronze -> Silver -> Gold)
        
        Args:
            document_id: ID del documento
            data_state: Nuevo estado de datos
            
        Returns:
            True si se actualizó correctamente
        """
        try:
            record = self.database.update_document_status(
                document_id=document_id,
                status=ProcessingStatus.COMPLETED,  # Mantener status actual
                data_state=data_state
            )
            
            if record:
                logger.info(f"Updated data state for {document_id}: {data_state.value}")
                return True
            else:
                logger.warning(f"Document not found for data state update: {document_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating data state: {str(e)}")
            raise
    
    def get_document_info(self, document_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtener información completa de un documento
        
        Args:
            document_id: ID del documento
            
        Returns:
            Diccionario con información del documento o None si no existe
        """
        try:
            record = self.database.get_document_by_id(document_id)
            return record.to_dict() if record else None
            
        except Exception as e:
            logger.error(f"Error getting document info: {str(e)}")
            return None
    
    def get_user_documents(self, user_email: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Obtener documentos de un usuario
        
        Args:
            user_email: Email del usuario
            limit: Número máximo de documentos
            
        Returns:
            Lista de documentos del usuario
        """
        try:
            records = self.database.get_documents_by_user(user_email, limit)
            return [record.to_dict() for record in records]
            
        except Exception as e:
            logger.error(f"Error getting user documents: {str(e)}")
            return []
    
    def get_documents_by_state(self, data_state: DataState, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Obtener documentos por estado de datos
        
        Args:
            data_state: Estado de datos (BRONZE, SILVER, GOLD)
            limit: Número máximo de documentos
            
        Returns:
            Lista de documentos en el estado especificado
        """
        try:
            records = self.database.get_documents_by_state(data_state, limit)
            return [record.to_dict() for record in records]
            
        except Exception as e:
            logger.error(f"Error getting documents by state: {str(e)}")
            return []
    
    def get_processing_statistics(self) -> Dict[str, Any]:
        """
        Obtener estadísticas de procesamiento
        
        Returns:
            Diccionario con estadísticas del sistema
        """
        try:
            return self.database.get_processing_stats()
            
        except Exception as e:
            logger.error(f"Error getting processing statistics: {str(e)}")
            return {}
    
    async def promote_to_gold(self, document_id: str, 
                            enrichment_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Promover documento a estado GOLD (datos enriquecidos para análisis)
        
        Args:
            document_id: ID del documento
            enrichment_data: Datos adicionales de enriquecimiento
            
        Returns:
            True si se promovió correctamente
        """
        try:
            # Actualizar estado a GOLD
            success = await self.update_data_state(document_id, DataState.GOLD)
            
            if success and enrichment_data:
                # Almacenar datos de enriquecimiento si se proporcionan
                current_record = self.database.get_document_by_id(document_id)
                if current_record:
                    # Merge enrichment data with existing extra_metadata
                    current_metadata = current_record.extra_metadata or {}
                    current_metadata.update({
                        "gold_promotion_date": datetime.utcnow().isoformat(),
                        "enrichment_data": enrichment_data
                    })
                    
                    enrichment_updates = {
                        'extra_metadata': current_metadata
                    }
                    
                    self.database.update_document_record(document_id, enrichment_updates)
            
            if success:
                logger.info(f"Promoted document {document_id} to GOLD state")
            
            return success
            
        except Exception as e:
            logger.error(f"Error promoting document to GOLD: {str(e)}")
            raise 