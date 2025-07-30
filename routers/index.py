
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
