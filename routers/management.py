from datetime import datetime
import uuid
import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from services.ocr.engineering import OCRPipeline
from services.database import DataState
from config.config import ENV_VARIABLES, logger

router = APIRouter(prefix="/api/v1", tags=["management"])

# Initialize pipeline
pipeline = OCRPipeline(ENV_VARIABLES)

# Mount static files for local storage if using local storage
storage_config = pipeline.config_service.get_storage_config()
if storage_config['type'] == 'local':
    storage_path = storage_config['base_path']
    if os.path.exists(storage_path):
        router.mount("/files", StaticFiles(directory=storage_path), name="files")
        logger.info(f"Serving local files from: {storage_path}")

# Nuevos endpoints para gestión de documentos

@router.get("/documents/stats")
async def get_processing_stats():
    """Obtener estadísticas de procesamiento de documentos"""
    try:
        stats = pipeline.document_manager.get_processing_statistics()
        return {
            "status": "success",
            "data": stats
        }
    except Exception as e:
        logger.error(f"Error getting processing stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting stats: {str(e)}")

@router.get("/documents/user/{user_email}")
async def get_user_documents(
    user_email: str,
    limit: int = Query(50, description="Número máximo de documentos a retornar")
):
    """Obtener documentos de un usuario específico"""
    try:
        documents = pipeline.document_manager.get_user_documents(user_email, limit)
        return {
            "status": "success",
            "user_email": user_email,
            "count": len(documents),
            "documents": documents
        }
    except Exception as e:
        logger.error(f"Error getting user documents: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting user documents: {str(e)}")

@router.get("/documents/bronze")
async def get_bronze_documents(
    limit: int = Query(100, description="Número máximo de documentos a retornar"),
    user_email: str = Query(None, description="Filtrar por email de usuario (opcional)"),
    context_id: str = Query(None, description="Filtrar por ID de contexto (opcional)"),
    include_storage_info: bool = Query(False, description="Incluir información de almacenamiento")
):
    """Obtener documentos en estado Bronze (datos brutos procesados)"""
    try:
        if user_email:
            # Si se especifica usuario, filtrar por usuario y estado bronze
            all_user_docs = pipeline.document_manager.get_user_documents(user_email, limit * 2)
            documents = [doc for doc in all_user_docs if doc.get('data_state') == 'bronze'][:limit]
        elif context_id:
            # Si se especifica contexto, filtrar por contexto y estado bronze
            all_context_docs = pipeline.document_manager.database.get_documents_by_context(context_id, limit * 2)
            documents = [doc.to_dict() for doc in all_context_docs if doc.data_state == 'bronze'][:limit]
        else:
            # Obtener todos los documentos en estado bronze
            documents = pipeline.document_manager.get_documents_by_state(DataState.BRONZE, limit)
        
        # Añadir información de almacenamiento si se solicita
        if include_storage_info:
            for doc in documents:
                if doc.get('bronze_folder_path'):
                    doc['storage_info'] = {
                        'bronze_folder': doc.get('bronze_folder_path'),
                        'original_document_url': doc.get('original_document_url'),
                        'extracted_content_url': doc.get('extracted_content_url'),
                        'figures_folder_url': doc.get('figures_folder_url')
                    }
        
        return {
            "status": "success",
            "data_state": "bronze",
            "description": "Documentos con datos brutos procesados",
            "count": len(documents),
            "filters": {
                "user_email": user_email,
                "context_id": context_id,
                "limit": limit,
                "include_storage_info": include_storage_info
            },
            "documents": documents
        }
    except Exception as e:
        logger.error(f"Error getting bronze documents: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting bronze documents: {str(e)}")

@router.get("/documents/bronze/{document_id}/storage")
async def get_bronze_document_storage(document_id: str):
    """Obtener información detallada del almacenamiento Bronze de un documento específico"""
    try:
        # Obtener información del documento
        document_info = pipeline.document_manager.get_document_info(document_id)
        
        if not document_info:
            raise HTTPException(status_code=404, detail="Document not found")
        
        if document_info.get('data_state') != 'bronze':
            raise HTTPException(
                status_code=400, 
                detail=f"Document is not in bronze state. Current state: {document_info.get('data_state')}"
            )
        
        # Construir información de almacenamiento
        bronze_folder = document_info.get('bronze_folder_path')
        if not bronze_folder:
            raise HTTPException(status_code=404, detail="Bronze storage information not available")
        
        storage_structure = {
            "document_id": document_id,
            "bronze_folder": bronze_folder,
            "storage_urls": {
                "original_document": document_info.get('original_document_url'),
                "extracted_content": document_info.get('extracted_content_url'),
                "figures_folder": document_info.get('figures_folder_url')
            },
            "folder_structure": {
                "base_folder": bronze_folder,
                "raw_folder": f"{bronze_folder}/raw",
                "extracted_content_folder": f"{bronze_folder}/extracted_content",
                "content_pages_folder": f"{bronze_folder}/content_pages",
                "figures_folder": f"{bronze_folder}/figures",
                "processing_logs_folder": f"{bronze_folder}/processing_logs",
                "quality_assessment_folder": f"{bronze_folder}/quality_assessment"
            },
            "expected_files": {
                "manifest": f"{bronze_folder}/manifest.json",
                "original_document": f"{bronze_folder}/raw/original_document.pdf",
                "full_text": f"{bronze_folder}/extracted_content/full_text.md",
                "metadata": f"{bronze_folder}/extracted_content/metadata.json",
                "extraction_result": f"{bronze_folder}/extracted_content/extraction_result.json",
                "figure_analysis": f"{bronze_folder}/figures/figure_analysis.json",
                "processing_log": f"{bronze_folder}/processing_logs/processing_log.json",
                "quality_report": f"{bronze_folder}/quality_assessment/quality_report.json"
            }
        }
        
        return {
            "status": "success",
            "document_info": {
                "document_id": document_id,
                "document_name": document_info.get('document_name'),
                "data_state": document_info.get('data_state'),
                "created_at": document_info.get('created_at')
            },
            "bronze_storage": storage_structure
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting bronze storage info: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting bronze storage info: {str(e)}")

@router.get("/documents/bronze/summary")
async def get_bronze_documents_summary():
    """Obtener resumen de documentos en estado Bronze"""
    try:
        # Obtener todos los documentos bronze
        bronze_documents = pipeline.document_manager.get_documents_by_state(DataState.BRONZE, limit=1000)
        
        # Calcular estadísticas
        total_count = len(bronze_documents)
        
        # Agrupar por usuario
        users_count = {}
        for doc in bronze_documents:
            user = doc.get('user_email', 'unknown')
            users_count[user] = users_count.get(user, 0) + 1
        
        # Agrupar por tipo de documento
        doc_types = {}
        for doc in bronze_documents:
            doc_type = doc.get('document_type', 'unknown')
            doc_types[doc_type] = doc_types.get(doc_type, 0) + 1
        
        # Documentos recientes (últimos 7 días)
        from datetime import datetime, timedelta
        recent_cutoff = datetime.now() - timedelta(days=7)
        recent_docs = []
        
        for doc in bronze_documents:
            created_at_str = doc.get('created_at')
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                    if created_at >= recent_cutoff:
                        recent_docs.append(doc)
                except:
                    pass
        
        return {
            "status": "success",
            "data_state": "bronze",
            "summary": {
                "total_documents": total_count,
                "recent_documents_7_days": len(recent_docs),
                "unique_users": len(users_count),
                "documents_by_user": users_count,
                "documents_by_type": doc_types
            },
            "recent_documents": recent_docs[:10]  # Últimos 10 documentos recientes
        }
        
    except Exception as e:
        logger.error(f"Error getting bronze documents summary: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting bronze documents summary: {str(e)}")

@router.get("/documents/state/{state}")
async def get_documents_by_state(
    state: str,
    limit: int = Query(100, description="Número máximo de documentos a retornar")
):
    """Obtener documentos por estado de datos (bronze, silver, gold)"""
    try:
        # Validar estado
        try:
            data_state = DataState(state.lower())
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid state. Valid states: {[s.value for s in DataState]}"
            )
        
        documents = pipeline.document_manager.get_documents_by_state(data_state, limit)
        return {
            "status": "success",
            "data_state": state,
            "count": len(documents),
            "documents": documents
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting documents by state: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting documents by state: {str(e)}")

@router.get("/documents/{document_id}")
async def get_document_info(document_id: str):
    """Obtener información detallada de un documento específico"""
    try:
        document_info = pipeline.document_manager.get_document_info(document_id)
        
        if not document_info:
            raise HTTPException(status_code=404, detail="Document not found")
        
        return {
            "status": "success",
            "document": document_info
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document info: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting document info: {str(e)}")