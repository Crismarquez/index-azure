import asyncio
import logging
import os
import json
from pathlib import Path
from typing import List
import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import asdict

from services.interfaces import IStorageService
from services.ocr.entities import Document, ExtractionResult


import aiohttp

from azure.storage.blob import BlobServiceClient

from .interfaces import IStorageService

logger = logging.getLogger(__name__)

class AzureBlobStorageAdapter(IStorageService):
    """Adapter for Azure Blob Storage"""
    
    def __init__(self, connection_string: str, container_name: str):
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        self.container_client = self.blob_service_client.get_container_client(container_name)
        self.container_name = container_name
    
    async def upload_file(self, content: bytes, path: str) -> str:
        """Upload file content and return URL"""
        try:
            blob_client = self.container_client.get_blob_client(path)
            await asyncio.to_thread(blob_client.upload_blob, content, overwrite=True)
            
            # Return the blob URL
            return blob_client.url
            
        except Exception as e:
            logger.error(f"Error uploading file to {path}: {str(e)}")
            raise
    
    async def download_file(self, url: str) -> bytes:
        """Download file content from URL"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    return await response.read()
                    
        except Exception as e:
            logger.error(f"Error downloading file from {url}: {str(e)}")
            raise
    
    async def delete_file(self, path: str) -> bool:
        """Delete file from storage"""
        try:
            blob_client = self.container_client.get_blob_client(path)
            await asyncio.to_thread(blob_client.delete_blob)
            return True
            
        except Exception as e:
            logger.error(f"Error deleting file {path}: {str(e)}")
            return False

class LocalFileStorageAdapter(IStorageService):
    """Adapter for local file system storage"""
    
    def __init__(self, base_path: str = "./storage", base_url: str = "http://localhost:8000/files"):
        self.base_path = Path(base_path).resolve()
        self.base_url = base_url.rstrip('/')
        
        # Create base directory if it doesn't exist
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Local storage initialized at: {self.base_path}")
    
    async def upload_file(self, content: bytes, path: str) -> str:
        """Save file to local filesystem and return URL"""
        try:
            # Remove leading slash if present
            path = path.lstrip('/')
            file_path = self.base_path / path
            
            # Create directories if they don't exist
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file content
            await asyncio.to_thread(file_path.write_bytes, content)
            
            # Return file URL for local access
            relative_path = path.replace('\\', '/')
            file_url = f"{self.base_url}/{relative_path}"
            
            logger.info(f"Stored file locally at: {file_path}")
            return file_url
            
        except Exception as e:
            logger.error(f"Error uploading file to {path}: {str(e)}")
            raise
    
    async def download_file(self, url: str) -> bytes:
        """Download file content from URL or local path"""
        try:
            # Handle local file URLs
            if url.startswith(self.base_url):
                # Extract relative path from URL
                relative_path = url.replace(self.base_url + '/', '')
                file_path = self.base_path / relative_path
                
                if file_path.exists():
                    return await asyncio.to_thread(file_path.read_bytes)
                else:
                    raise FileNotFoundError(f"Local file not found: {file_path}")
            
            # Handle absolute local paths
            elif url.startswith('file://') or os.path.isabs(url):
                file_path = Path(url.replace('file://', ''))
                if file_path.exists():
                    return await asyncio.to_thread(file_path.read_bytes)
                else:
                    raise FileNotFoundError(f"File not found: {file_path}")
            
            # Handle remote URLs
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        response.raise_for_status()
                        return await response.read()
                        
        except Exception as e:
            logger.error(f"Error downloading file from {url}: {str(e)}")
            raise
    
    async def delete_file(self, path: str) -> bool:
        """Delete file from local storage"""
        try:
            # Remove leading slash if present
            path = path.lstrip('/')
            file_path = self.base_path / path
            
            if file_path.exists():
                await asyncio.to_thread(file_path.unlink)
                logger.info(f"Deleted local file: {file_path}")
                return True
            else:
                logger.warning(f"File not found for deletion: {file_path}")
                return False
                
        except Exception as e:
            logger.error(f"Error deleting file {path}: {str(e)}")
            return False
    
    def get_local_path(self, storage_path: str) -> Path:
        """Get the actual local file path for a storage path"""
        return self.base_path / storage_path.lstrip('/')
    
    def list_files(self, prefix: str = "") -> List[str]:
        """List all files with optional prefix filter"""
        try:
            search_path = self.base_path / prefix.lstrip('/') if prefix else self.base_path
            
            if search_path.is_file():
                return [str(search_path.relative_to(self.base_path))]
            
            files = []
            if search_path.exists() and search_path.is_dir():
                for file_path in search_path.rglob('*'):
                    if file_path.is_file():
                        relative_path = file_path.relative_to(self.base_path)
                        files.append(str(relative_path).replace('\\', '/'))
            
            return sorted(files)
            
        except Exception as e:
            logger.error(f"Error listing files with prefix {prefix}: {str(e)}")
            return []

class BronzeStorageService:
    """Service to manage bronze layer storage structure for OCR processing results"""
    
    def __init__(self, storage_service: IStorageService, base_path: str = "bronze"):
        self.storage_service = storage_service
        self.base_path = base_path
    
    def _get_document_folder_name(self, document: Document) -> str:
        """Generate unique folder name for document processing session"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        request_id = document.metadata.request_id or "no_request"
        document_name = self._sanitize_filename(document.metadata.document_name or "unknown_document")
        
        return f"{request_id}_{document_name}_{timestamp}"
    
    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename[:50]  # Limit length
    
    def get_bronze_paths(self, document: Document) -> Dict[str, str]:
        """Get all bronze storage paths for a document"""
        folder_name = self._get_document_folder_name(document)
        base_folder = f"{self.base_path}/{folder_name}"
        
        return {
            "base_folder": base_folder,
            "raw_folder": f"{base_folder}/raw",
            "extracted_content_folder": f"{base_folder}/extracted_content",
            "figures_folder": f"{base_folder}/figures",
            "processing_logs_folder": f"{base_folder}/processing_logs",
            "quality_assessment_folder": f"{base_folder}/quality_assessment",
            
            # Specific file paths
            "original_document": f"{base_folder}/raw/original_document.pdf",
            "full_text": f"{base_folder}/extracted_content/full_text.md",
            "metadata": f"{base_folder}/extracted_content/metadata.json",
            "extraction_result": f"{base_folder}/extracted_content/extraction_result.json",
            "figure_analysis": f"{base_folder}/figures/figure_analysis.json",
            "processing_log": f"{base_folder}/processing_logs/processing_log.json",
            "quality_report": f"{base_folder}/quality_assessment/quality_report.json"
        }
    
    async def store_original_document(self, document: Document, content: bytes, paths: Dict[str, str]) -> str:
        """Store the original document in bronze/raw folder"""
        try:
            original_path = paths["original_document"]
            url = await self.storage_service.upload_file(content, original_path)
            logger.info(f"Stored original document at: {original_path}")
            return url
        except Exception as e:
            logger.error(f"Error storing original document: {str(e)}")
            raise
    
    async def store_extraction_result(self, extraction_result: ExtractionResult, paths: Dict[str, str]) -> Dict[str, str]:
        """Store all extraction results in bronze structure"""
        stored_urls = {}
        
        try:
            # Store full text content
            full_text_content = extraction_result.content.encode('utf-8')
            stored_urls["full_text"] = await self.storage_service.upload_file(
                full_text_content, paths["full_text"]
            )
            
            # Store extraction result as JSON
            extraction_data = {
                "document_id": extraction_result.document_id,
                "confidence_score": extraction_result.confidence_score,
                "page_count": extraction_result.page_count,
                "processing_time": extraction_result.processing_time,
                "errors": extraction_result.errors,
                "content_length": len(extraction_result.content),
                "extraction_timestamp": datetime.now().isoformat()
            }
            
            extraction_json = json.dumps(extraction_data, indent=2).encode('utf-8')
            stored_urls["extraction_result"] = await self.storage_service.upload_file(
                extraction_json, paths["extraction_result"]
            )
            
            # Store metadata
            metadata_json = json.dumps(extraction_result.metadata or {}, indent=2).encode('utf-8')
            stored_urls["metadata"] = await self.storage_service.upload_file(
                metadata_json, paths["metadata"]
            )
            
            logger.info(f"Stored extraction results in bronze structure")
            return stored_urls
            
        except Exception as e:
            logger.error(f"Error storing extraction results: {str(e)}")
            raise
    
    async def store_figures(self, figures_data: List[Dict[str, Any]], figure_contents: List[bytes], paths: Dict[str, str]) -> Dict[str, Any]:
        """Store extracted figures and their analysis in bronze structure"""
        stored_figures = []
        
        try:
            # Store individual figure files
            for i, (figure_data, figure_content) in enumerate(zip(figures_data, figure_contents)):
                figure_filename = f"figure_{i+1}.png"
                figure_path = f"{paths['figures_folder']}/{figure_filename}"
                
                figure_url = await self.storage_service.upload_file(figure_content, figure_path)
                
                stored_figures.append({
                    "figure_id": f"figure_{i+1}",
                    "filename": figure_filename,
                    "storage_path": figure_path,
                    "url": figure_url,
                    "analysis": figure_data.get("analysis", ""),
                    "caption": figure_data.get("caption", ""),
                    "bounding_regions": figure_data.get("bounding_regions", [])
                })
            
            # Store figure analysis summary
            figure_analysis = {
                "total_figures": len(stored_figures),
                "figures": stored_figures,
                "processing_timestamp": datetime.now().isoformat()
            }
            
            analysis_json = json.dumps(figure_analysis, indent=2).encode('utf-8')
            await self.storage_service.upload_file(analysis_json, paths["figure_analysis"])
            
            logger.info(f"Stored {len(stored_figures)} figures in bronze structure")
            return figure_analysis
            
        except Exception as e:
            logger.error(f"Error storing figures: {str(e)}")
            raise
    
    async def store_processing_logs(self, processing_data: Dict[str, Any], paths: Dict[str, str]) -> str:
        """Store processing logs and statistics"""
        try:
            log_data = {
                "processing_start": processing_data.get("start_time"),
                "processing_end": processing_data.get("end_time"),
                "processing_duration": processing_data.get("duration"),
                "ai_vision_enabled": processing_data.get("ai_vision_enabled", False),
                "figures_detected": processing_data.get("figures_detected", 0),
                "figures_analyzed": processing_data.get("figures_analyzed", 0),
                "figures_skipped": processing_data.get("figures_skipped", 0),
                "thresholds_applied": processing_data.get("thresholds_applied", {}),
                "errors": processing_data.get("errors", []),
                "warnings": processing_data.get("warnings", []),
                "service_versions": processing_data.get("service_versions", {}),
                "log_timestamp": datetime.now().isoformat()
            }
            
            log_json = json.dumps(log_data, indent=2).encode('utf-8')
            url = await self.storage_service.upload_file(log_json, paths["processing_log"])
            
            logger.info(f"Stored processing logs in bronze structure")
            return url
            
        except Exception as e:
            logger.error(f"Error storing processing logs: {str(e)}")
            raise
    
    async def store_quality_assessment(self, quality_data: Dict[str, Any], paths: Dict[str, str]) -> str:
        """Store quality assessment results"""
        try:
            quality_report = {
                "quality_score": quality_data.get("quality_score"),
                "is_quality_ok": quality_data.get("is_quality_ok", True),
                "quality_suggestions": quality_data.get("quality_suggestions", []),
                "confidence_metrics": quality_data.get("confidence_metrics", {}),
                "validation_checks": quality_data.get("validation_checks", {}),
                "assessment_timestamp": datetime.now().isoformat()
            }
            
            quality_json = json.dumps(quality_report, indent=2).encode('utf-8')
            url = await self.storage_service.upload_file(quality_json, paths["quality_report"])
            
            logger.info(f"Stored quality assessment in bronze structure")
            return url
            
        except Exception as e:
            logger.error(f"Error storing quality assessment: {str(e)}")
            raise
    
    async def create_bronze_manifest(self, document: Document, all_stored_urls: Dict[str, Any], paths: Dict[str, str]) -> str:
        """Create a manifest file with all stored artifacts for this document"""
        try:
            manifest = {
                "document_info": {
                    "document_name": document.metadata.document_name,
                    "request_id": document.metadata.request_id,
                    "user_email": document.metadata.user_email,
                    "context_id": document.metadata.context_id,
                    "context_name": document.metadata.context_name,
                    "attachment_id": document.metadata.attachment_id,
                    "document_type": document.document_type.value,
                    "original_url": document.url,
                    "created_at": document.metadata.created_at.isoformat() if document.metadata.created_at else None,
                    "extra_metadata": document.metadata.extra_metadata
                },
                "bronze_structure": {
                    "base_folder": paths["base_folder"],
                    "created_timestamp": datetime.now().isoformat()
                },
                "stored_artifacts": all_stored_urls,
                "folder_structure": {
                    "raw": "Original document files",
                    "extracted_content": "OCR text extraction results and metadata",
                    "figures": "Extracted figures and AI vision analysis",
                    "processing_logs": "Processing statistics and logs",
                    "quality_assessment": "Quality validation results"
                }
            }
            
            manifest_path = f"{paths['base_folder']}/manifest.json"
            manifest_json = json.dumps(manifest, indent=2).encode('utf-8')
            manifest_url = await self.storage_service.upload_file(manifest_json, manifest_path)
            
            logger.info(f"Created bronze manifest at: {manifest_path}")
            return manifest_url
            
        except Exception as e:
            logger.error(f"Error creating bronze manifest: {str(e)}")
            raise 