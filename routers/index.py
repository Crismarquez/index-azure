
from datetime import datetime
import uuid
import json
import os

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from services.ocr.engineering import OCRPipeline
from services.ocr.entities import ProcessingRequest, DocumentAttachment
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

# Add local storage browsing endpoint if using local storage
if storage_config['type'] == 'local':
    @router.get("/browse")
    async def browse_files(prefix: str = ""):
        """Browse local storage files"""
        try:
            if hasattr(pipeline.storage_service, 'list_files'):
                files = pipeline.storage_service.list_files(prefix)
                return {
                    "storage_type": "local",
                    "base_path": storage_config['base_path'],
                    "prefix": prefix,
                    "files": files,
                    "total_files": len(files)
                }
            else:
                return {"error": "File browsing not supported for this storage type"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error browsing files: {str(e)}")
    
    @router.get("/bronze")
    async def browse_bronze_folders():
        """Browse bronze storage structure"""
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
                
                return {
                    "storage_type": "local",
                    "bronze_folders": bronze_folders,
                    "total_folders": len(bronze_folders),
                    "total_files": len(bronze_files)
                }
            else:
                return {"error": "Bronze browsing not supported for this storage type"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error browsing bronze: {str(e)}")
