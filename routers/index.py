
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
from services.ocr.entities import ProcessingRequest, DocumentAttachment
from services.database import DataState, ProcessStage
from config.config import ENV_VARIABLES, logger

router = APIRouter(prefix="/api/v1")

# Initialize pipeline
pipeline = OCRPipeline(ENV_VARIABLES)

# Mount static files for local storage if using local storage
storage_config = pipeline.config_service.get_storage_config()
if storage_config['type'] == 'local':
    storage_path = storage_config['base_path']
    if os.path.exists(storage_path):
        router.mount("/files", StaticFiles(directory=storage_path), name="files")
        logger.info(f"Serving local files from: {storage_path}")

@router.get("/")
async def root():
    storage_info = {"storage_type": storage_config['type']}
    if storage_config['type'] == 'local':
        storage_info["storage_path"] = storage_config['base_path']
    return {
        "message": "Improved OCR Pipeline v2.0", 
        "status": "healthy",
        "storage": storage_info
    }

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        health_status = await pipeline.check_health()
        return health_status
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")

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

@router.post("/documents/{document_id}/promote")
async def promote_document_to_gold(
    document_id: str,
    enrichment_data: dict = None
):
    """Promover un documento al estado GOLD con datos de enriquecimiento opcionales"""
    try:
        success = await pipeline.document_manager.promote_to_gold(
            document_id, enrichment_data
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Document not found")
        
        return {
            "status": "success",
            "message": f"Document {document_id} promoted to GOLD state",
            "document_id": document_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error promoting document to GOLD: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error promoting document: {str(e)}")

@router.post("/process_document")
async def process_document(request: ProcessingRequest):
    """Process documents with improved architecture"""
    try:
        result = await pipeline.process_document(request)
        return result
    except Exception as e:
        logger.error(f"Error processing document: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Form("uploads")
):
    """Upload a file to local storage without processing"""
    try:
        # Validate file type
        allowed_extensions = {'.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.png', '.jpg', '.jpeg', '.mp4'}
        file_extension = os.path.splitext(file.filename)[1].lower()
        
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"File type {file_extension} not supported. Allowed: {allowed_extensions}"
            )
        
        # Create upload path with timestamp to avoid conflicts
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        upload_path = f"{folder}/{timestamp}_{file.filename}"
        
        # Read file content
        content = await file.read()
        
        # Upload to storage
        file_url = await pipeline.storage_service.upload_file(content, upload_path)
        
        logger.info(f"File uploaded successfully: {file_url}")
        
        return {
            "message": "File uploaded successfully",
            "filename": file.filename,
            "file_url": file_url,
            "upload_path": upload_path,
            "size_bytes": len(content),
            "file_type": file_extension,
            "timestamp": timestamp
        }
        
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")

@router.post("/upload_and_process")
async def upload_and_process(
    file: UploadFile = File(...),
    request_id: str = Form(...),
    user_email: str = Form(...),
    context_id: str = Form(None),
    context_name: str = Form(None),
    department: str = Form("upload"),
    priority: str = Form("normal")
):
    """Upload a local file and process it directly"""
    try:
        # Validate file type
        allowed_extensions = {'.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.png', '.jpg', '.jpeg', '.mp4'}
        file_extension = os.path.splitext(file.filename)[1].lower()
        
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400, 
                detail=f"File type {file_extension} not supported. Allowed: {allowed_extensions}"
            )
        
        # Create upload path
        upload_path = f"uploads/{request_id}_{file.filename}"
        
        # Read file content
        content = await file.read()
        
        # Upload to storage
        file_url = await pipeline.storage_service.upload_file(content, upload_path)
        
        logger.info(f"File uploaded successfully: {file_url}")
        
        # Create processing request
        processing_request = ProcessingRequest(
            request_id=request_id,
            user_email=user_email,
            context_id=context_id,
            context_name=context_name,
            attachments=[
                DocumentAttachment(
                    url=file_url,
                    file_type=file_extension.lstrip('.'),
                    name=file.filename,
                    attachment_id=f"upload_{uuid.uuid4().hex[:8]}",
                    size_bytes=len(content)
                )
            ],
            metadata={
                "department": department,
                "priority": priority,
                "source": "file_upload",
                "upload_timestamp": datetime.utcnow().isoformat()
            }
        )
        
        # Process the document
        result = await pipeline.process_document(processing_request)
        
        return {
            "upload_info": {
                "filename": file.filename,
                "file_url": file_url,
                "size_bytes": len(content),
                "file_type": file_extension
            },
            "processing_result": result
        }
        
    except Exception as e:
        logger.error(f"Error in upload and process: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload and processing failed: {str(e)}")

@router.get("/metrics")
async def get_metrics():
    """Get processing metrics and statistics"""
    return {
        "circuit_breaker_state": pipeline.circuit_breaker.state,
        "failure_count": pipeline.circuit_breaker.failure_count,
        "service_health": pipeline.health_check.get_overall_health()
    }

# Local storage specific endpoints (if needed in the future)
if storage_config['type'] == 'local':
    pass  # Reserved for local-only endpoints
# Universal bronze endpoints (work with both local and Azure storage)
@router.get("/browse")
async def browse_files(prefix: str = ""):
    """Browse storage files - works with both local and Azure storage"""
    try:
        if hasattr(pipeline.storage_service, 'list_files'):
            files = pipeline.storage_service.list_files(prefix)
            
            # Determine storage type and get additional info
            is_azure_storage = hasattr(pipeline.storage_service, 'container_name')
            storage_type = "azure" if is_azure_storage else "local"
            
            response = {
                "storage_type": storage_type,
                "prefix": prefix,
                "files": files,
                "total_files": len(files)
            }
            
            # Add type-specific information
            if not is_azure_storage:
                response["base_path"] = storage_config['base_path']
            else:
                response["container_name"] = pipeline.storage_service.container_name
            
            return response
        else:
            return {"error": "File browsing not supported for this storage type"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error browsing files: {str(e)}")

@router.get("/bronze")
async def browse_bronze_folders():
    """Browse bronze storage structure - works with both local and Azure storage"""
    try:
        if hasattr(pipeline.storage_service, 'list_files'):
            bronze_files = pipeline.storage_service.list_files("bronze")
            
            # Group files by bronze folder
            bronze_folders = {}
            for file_path in bronze_files:
                if file_path.startswith("bronze/"):
                    parts = file_path.split("/")
                    if len(parts) >= 2:
                        folder_name = parts[1]
                        if folder_name not in bronze_folders:
                            bronze_folders[folder_name] = []
                        bronze_folders[folder_name].append(file_path)
            
            # Determine storage type
            storage_type = "azure" if hasattr(pipeline.storage_service, 'container_name') else "local"
            
            return {
                "storage_type": storage_type,
                "bronze_folders": bronze_folders,
                "total_folders": len(bronze_folders),
                "total_files": len(bronze_files)
            }
        else:
            return {"error": "Bronze browsing not supported for this storage type"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error browsing bronze: {str(e)}")

@router.get("/bronze/documents")
async def list_bronze_documents():
    """List all documents in bronze state with organized data structure"""
    try:
        if not hasattr(pipeline.storage_service, 'list_files'):
            return {"error": "Bronze document listing not supported for this storage type"}
        
        # Get all bronze folders
        bronze_files = pipeline.storage_service.list_files("bronze")
        bronze_folders = set()
        
        # Extract unique folder names from file paths
        for file_path in bronze_files:
            if file_path.startswith("bronze/"):
                parts = file_path.split("/")
                if len(parts) >= 2:
                    bronze_folders.add(parts[1])
        
        documents = []
        
        for folder_name in bronze_folders:
            try:
                # Parse folder name structure: id_name_date_string
                parsed_info = parse_bronze_folder_name(folder_name)
                
                # Try to read manifest.json for additional metadata
                manifest_data = None
                try:
                    # Check if we're using local storage or Azure storage
                    if hasattr(pipeline.storage_service, 'get_local_path'):
                        # Local storage
                        manifest_path = pipeline.storage_service.get_local_path(f"bronze/{folder_name}/manifest.json")
                        if manifest_path.exists():
                            with open(manifest_path, 'r', encoding='utf-8') as f:
                                manifest_data = json.load(f)
                    elif hasattr(pipeline.storage_service, 'read_json_file'):
                        # Azure storage
                        try:
                            manifest_data = await pipeline.storage_service.read_json_file(f"bronze/{folder_name}/manifest.json")
                        except Exception:
                            # Manifest file doesn't exist or can't be read
                            pass
                except Exception as e:
                    logger.warning(f"Could not read manifest for {folder_name}: {str(e)}")
                
                # Build document info
                document_info = {
                    "folder_name": folder_name,
                    "parsed_structure": parsed_info,
                    "bronze_path": f"bronze/{folder_name}",
                    "status": "bronze"
                }
                
                # Add manifest data if available
                if manifest_data:
                    document_info["document_info"] = manifest_data.get("document_info", {})
                    document_info["bronze_structure"] = manifest_data.get("bronze_structure", {})
                    document_info["stored_artifacts"] = manifest_data.get("stored_artifacts", {})
                    
                    # Extract key information for easier access
                    doc_info = manifest_data.get("document_info", {})
                    document_info["summary"] = {
                        "document_name": doc_info.get("document_name", parsed_info.get("name", "unknown")),
                        "document_type": doc_info.get("document_type", "unknown"),
                        "user_email": doc_info.get("user_email", "unknown"),
                        "context_name": doc_info.get("context_name", ""),
                        "created_at": doc_info.get("created_at", ""),
                        "request_id": doc_info.get("request_id", parsed_info.get("id", "unknown"))
                    }
                    
                    # Count artifacts
                    artifacts = manifest_data.get("stored_artifacts", {})
                    figures = artifacts.get("figures", {})
                    document_info["artifacts_count"] = {
                        "total_figures": figures.get("total_figures", 0),
                        "has_original_document": bool(artifacts.get("original_document")),
                        "has_figure_analysis": bool(artifacts.get("figure_analysis"))
                    }
                else:
                    # Fallback to parsed info only
                    document_info["summary"] = {
                        "document_name": parsed_info.get("name", "unknown"),
                        "document_type": "unknown",
                        "user_email": "unknown",
                        "context_name": "",
                        "created_at": parsed_info.get("timestamp", ""),
                        "request_id": parsed_info.get("id", "unknown")
                    }
                    document_info["artifacts_count"] = {
                        "total_figures": 0,
                        "has_original_document": False,
                        "has_figure_analysis": False
                    }
                
                documents.append(document_info)
                
            except Exception as e:
                logger.warning(f"Error processing bronze folder {folder_name}: {str(e)}")
                # Add basic info even if parsing fails
                documents.append({
                    "folder_name": folder_name,
                    "bronze_path": f"bronze/{folder_name}",
                    "status": "bronze",
                    "error": f"Processing failed: {str(e)}",
                    "summary": {
                        "document_name": folder_name,
                        "document_type": "unknown",
                        "user_email": "unknown",
                        "context_name": "",
                        "created_at": "",
                        "request_id": "unknown"
                    }
                })
        
        # Sort documents by creation date (newest first)
        documents.sort(key=lambda x: x.get("summary", {}).get("created_at", ""), reverse=True)
        
        # Determine storage type for response
        storage_type = "azure" if hasattr(pipeline.storage_service, 'container_name') else "local"
        
        return {
            "status": "success",
            "storage_type": storage_type,
            "total_documents": len(documents),
            "documents": documents,
            "metadata": {
                "bronze_base_path": "bronze/",
                "structure_format": "id_name_date_string",
                "last_updated": datetime.utcnow().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"Error listing bronze documents: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error listing bronze documents: {str(e)}")

@router.get("/bronze/documents/{folder_name}")
async def get_bronze_document_details(folder_name: str):
    """Get detailed information about a specific bronze document"""
    try:
        if not hasattr(pipeline.storage_service, 'list_files'):
            return {"error": "Bronze document details not supported for this storage type"}
        
        # Check if folder exists
        bronze_files = pipeline.storage_service.list_files(f"bronze/{folder_name}")
        if not bronze_files:
            raise HTTPException(status_code=404, detail=f"Bronze document folder '{folder_name}' not found")
        
        # Parse folder name
        parsed_info = parse_bronze_folder_name(folder_name)
        
        # Read manifest.json
        manifest_data = None
        try:
            # Check if we're using local storage or Azure storage
            if hasattr(pipeline.storage_service, 'get_local_path'):
                # Local storage
                manifest_path = pipeline.storage_service.get_local_path(f"bronze/{folder_name}/manifest.json")
                if manifest_path.exists():
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        manifest_data = json.load(f)
            elif hasattr(pipeline.storage_service, 'read_json_file'):
                # Azure storage
                try:
                    manifest_data = await pipeline.storage_service.read_json_file(f"bronze/{folder_name}/manifest.json")
                except Exception:
                    # Manifest file doesn't exist or can't be read
                    pass
        except Exception as e:
            logger.warning(f"Could not read manifest for {folder_name}: {str(e)}")
        
        # Get all files in the bronze folder
        folder_files = [f for f in bronze_files if f.startswith(f"bronze/{folder_name}/")]
        
        # Organize files by type
        files_by_type = {
            "manifest": [],
            "raw": [],
            "figures": [],
            "content_pages": [],
            "extracted_content": [],
            "processing_logs": [],
            "other": []
        }
        
        # Determine storage type and base URL
        is_azure_storage = hasattr(pipeline.storage_service, 'container_name')
        storage_type = "azure" if is_azure_storage else "local"
        
        for file_path in folder_files:
            file_name = os.path.basename(file_path)
            
            # Generate appropriate URL based on storage type
            if is_azure_storage:
                file_url = pipeline.storage_service.get_blob_url(file_path)
            else:
                file_url = f"http://localhost:8000/files/{file_path}"
            
            file_info = {
                "filename": file_name,
                "path": file_path,
                "url": file_url
            }
            
            if file_name == "manifest.json":
                files_by_type["manifest"].append(file_info)
            elif "raw/" in file_path:
                files_by_type["raw"].append(file_info)
            elif "figures/" in file_path:
                files_by_type["figures"].append(file_info)
            elif "content_pages/" in file_path:
                files_by_type["content_pages"].append(file_info)
            elif "extracted_content/" in file_path:
                files_by_type["extracted_content"].append(file_info)
            elif "processing_logs/" in file_path:
                files_by_type["processing_logs"].append(file_info)
            else:
                files_by_type["other"].append(file_info)
        
        # Build response
        response = {
            "folder_name": folder_name,
            "parsed_structure": parsed_info,
            "bronze_path": f"bronze/{folder_name}",
            "status": "bronze",
            "storage_type": storage_type,
            "total_files": len(folder_files),
            "files_by_type": files_by_type,
            "files_count": {
                "manifest": len(files_by_type["manifest"]),
                "raw": len(files_by_type["raw"]),
                "figures": len(files_by_type["figures"]),
                "content_pages": len(files_by_type["content_pages"]),
                "extracted_content": len(files_by_type["extracted_content"]),
                "processing_logs": len(files_by_type["processing_logs"]),
                "other": len(files_by_type["other"])
            }
        }
        
        # Add manifest data if available
        if manifest_data:
            response["manifest_data"] = manifest_data
            
            # Add convenient summary
            doc_info = manifest_data.get("document_info", {})
            response["summary"] = {
                "document_name": doc_info.get("document_name", parsed_info.get("name", "unknown")),
                "document_type": doc_info.get("document_type", "unknown"),
                "user_email": doc_info.get("user_email", "unknown"),
                "context_name": doc_info.get("context_name", ""),
                "created_at": doc_info.get("created_at", ""),
                "request_id": doc_info.get("request_id", parsed_info.get("id", "unknown")),
                "original_url": doc_info.get("original_url", "")
            }
            
            # Add detailed artifacts information
            artifacts = manifest_data.get("stored_artifacts", {})
            figures = artifacts.get("figures", {})
            response["artifacts_details"] = {
                "original_document": artifacts.get("original_document"),
                "figure_analysis": artifacts.get("figure_analysis"),
                "figures": {
                    "total_figures": figures.get("total_figures", 0),
                    "figures_list": figures.get("figures", [])
                }
            }
        else:
            response["summary"] = {
                "document_name": parsed_info.get("name", "unknown"),
                "document_type": "unknown",
                "user_email": "unknown",
                "context_name": "",
                "created_at": parsed_info.get("timestamp", ""),
                "request_id": parsed_info.get("id", "unknown"),
                "original_url": ""
            }
            response["manifest_data"] = None
            response["artifacts_details"] = None
        
        response["metadata"] = {
            "structure_format": "id_name_date_string",
            "retrieved_at": datetime.utcnow().isoformat()
        }
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting bronze document details for {folder_name}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting document details: {str(e)}")


def parse_bronze_folder_name(folder_name: str) -> dict:
    """Parse bronze folder name with format: id_name_date_string"""
    try:
        # Split by underscore and try to identify parts
        parts = folder_name.split("_")
        
        if len(parts) < 3:
            # Not enough parts, return basic structure
            return {
                "id": parts[0] if parts else "unknown",
                "name": "_".join(parts[1:]) if len(parts) > 1 else "unknown",
                "timestamp": "",
                "date": "",
                "raw_name": folder_name
            }
        
        # Try to find timestamp pattern (YYYYMMDD_HHMMSS)
        timestamp_pattern = r"(\d{8}_\d{6})$"
        match = re.search(timestamp_pattern, folder_name)
        
        if match:
            timestamp = match.group(1)
            # Everything before the timestamp
            name_part = folder_name[:match.start()].rstrip("_")
            parts = name_part.split("_")
            
            return {
                "id": parts[0] if parts else "unknown",
                "name": "_".join(parts[1:]) if len(parts) > 1 else "unknown",
                "timestamp": timestamp,
                "date": timestamp.split("_")[0] if "_" in timestamp else timestamp[:8],
                "time": timestamp.split("_")[1] if "_" in timestamp else timestamp[9:],
                "raw_name": folder_name
            }
        else:
            # No clear timestamp pattern, use last two parts as date info
            return {
                "id": parts[0],
                "name": "_".join(parts[1:-2]) if len(parts) > 2 else "_".join(parts[1:]),
                "timestamp": "_".join(parts[-2:]) if len(parts) >= 2 else "",
                "date": parts[-2] if len(parts) >= 2 else "",
                "raw_name": folder_name
            }
            
    except Exception as e:
        logger.warning(f"Error parsing folder name {folder_name}: {str(e)}")
        return {
            "id": "unknown",
            "name": folder_name,
            "timestamp": "",
            "date": "",
            "raw_name": folder_name,
            "parse_error": str(e)
        }
