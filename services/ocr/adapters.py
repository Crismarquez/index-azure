import asyncio
import subprocess
import tempfile
import mimetypes
import os
import logging
from typing import Dict, Any, List
import aiohttp
import pickle
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import pathname2url
import base64
import re


from openai import AsyncAzureOpenAI

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
import fitz

from services.interfaces import IOCRService, IVisionService, IStorageService, IConversionService, IConfigurationService

logger = logging.getLogger(__name__)

class AzureDocumentIntelligenceAdapter(IOCRService):
    """Adapter for Azure Document Intelligence (Form Recognizer)"""
    
    def __init__(self, endpoint: str, api_key: str, storage_type: str = 'azure', local_storage_path: str = None):
        self.client = DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(api_key)
        )
        self.storage_type = storage_type
        self.local_storage_path = Path(local_storage_path) if local_storage_path else None
    
    def _is_local_file_url(self, url: str) -> bool:
        """Check if URL points to a local file"""
        return (self.storage_type == 'local' and 
                (url.startswith('http://localhost') or 
                 url.startswith('file://') or 
                 Path(url).is_absolute()))
    
    def _get_local_file_path(self, url: str) -> Path:
        """Convert URL to local file path"""
        if url.startswith('http://localhost'):
            # Extract relative path from localhost URL
            # Example: http://localhost:8000/files/uploads/file.pdf -> uploads/file.pdf
            relative_path = url.split('/files/')[-1]
            return self.local_storage_path / relative_path
        elif url.startswith('file://'):
            return Path(url.replace('file://', ''))
        elif Path(url).is_absolute():
            return Path(url)
        else:
            raise ValueError(f"Cannot determine local path for URL: {url}")
    
    def _analyze_document_from_file(self, file_path: Path, model: str, output_format: str, features: List[str]):
        """Analyze document from local file"""
        # Determine content type based on file extension
        extension = file_path.suffix.lower()
        content_type_map = {
            '.pdf': 'application/pdf',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.bmp': 'image/bmp',
            '.tiff': 'image/tiff',
            '.tif': 'image/tiff'
        }
        
        content_type = content_type_map.get(extension, 'application/octet-stream')

        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf‑8")

        poller = self.client.begin_analyze_document(
            model_id=model,
            body={"base64Source": b64},   # JSON mapping also goes in “body”
            features=features,
            output_content_format=output_format,
        )
        return poller

    async def extract_text_from_image(self, image_url: str, options: Dict[str, Any] = None) -> str:
        """Extract plain text from image"""
        result = await self.extract_text_with_layout(image_url, options)
        return result.get('content', '')
    
    async def extract_text_with_layout(self, image_url: str, options: Dict[str, Any] = None) -> Dict[str, Any]:
        """Extract text with layout information from image or PDF"""
        try:
            # Default options
            if options is None:
                options = {}
            
            model = options.get('model', 'prebuilt-layout')
            features = options.get('features', ['ocrHighResolution'])
            output_format = options.get('output_format', 'markdown')
            
            # Determine if we should use local file or URL
            if self._is_local_file_url(image_url):
                # Use local file for Document Intelligence
                local_path = self._get_local_file_path(image_url)
                
                if not local_path.exists():
                    raise FileNotFoundError(f"Local file not found: {local_path}")
                
                logger.info(f"Using local file for Document Intelligence: {local_path}")
                
                # Read file content and analyze
                poller = await asyncio.to_thread(
                    lambda: self._analyze_document_from_file(
                        local_path, model, output_format, features
                    )
                )
            else:
                # Use URL for Document Intelligence (Azure Storage)
                logger.info(f"Using URL for Document Intelligence: {image_url}")
                poller = await asyncio.to_thread(
                    lambda: self.client.begin_analyze_document(
                        model,
                        body={"urlSource": image_url},
                        output_content_format=output_format,
                        features=features,
                    )
                )
            
            # Get result
            result = await asyncio.to_thread(lambda: poller.result())

                        # Get full markdown content
            full_md = result.content

            # Get page markdown content
            page_mds = []
            for page in result.pages:
                span = page.spans[0]
                start, length = span['offset'], span['length']
                content = full_md[start : start + length]
                # use regex to delete if <figure> is in content, just delete inside <figure> and </figure>
                pattern = re.compile(r'(<figure>).*?(</figure>)', re.DOTALL)
                content = pattern.sub(r'\1\2', content)

                page_mds.append({
                    "page_number": page.page_number,
                    "content": content,
                    "unit": page.unit,
                    "width": page.width,
                    "height": page.height
                })
            
            # Extract metadata
            has_figures = hasattr(result, 'figures') and result.figures
            has_tables = hasattr(result, 'tables') and result.tables
            
            return {
                "pages": page_mds,
                'content': result.content if hasattr(result, 'content') else '',
                'figures': has_figures,
                'tables': has_tables,
                'confidence': getattr(result, 'confidence', None),
                'raw_result': result
            }
            
        except Exception as e:
            logger.error(f"Error in Azure Document Intelligence: {str(e)}")
            raise

    async def extract_text_from_pdf(self, pdf_url: str, options: Dict[str, Any] = None) -> Dict[str, Any]:
        """Extract text and detect figures from complete PDF using Document Intelligence"""
        try:
            # Default options for PDF processing
            if options is None:
                options = {}
            
            model = options.get('model', 'prebuilt-layout')
            features = options.get('features', ['ocrHighResolution'])
            output_format = options.get('output_format', 'markdown')
            
            # Determine if we should use local file or URL
            if self._is_local_file_url(pdf_url):
                # Use local file for Document Intelligence
                local_path = self._get_local_file_path(pdf_url)
                
                if not local_path.exists():
                    raise FileNotFoundError(f"Local PDF file not found: {local_path}")
                
                logger.info(f"Using local PDF file for Document Intelligence: {local_path}")
                
                # Read file content and analyze
                poller = await asyncio.to_thread(
                    lambda: self._analyze_document_from_file(
                        local_path, model, output_format, features
                    )
                )
            else:
                # Use URL for Document Intelligence (Azure Storage)
                logger.info(f"Using URL for Document Intelligence: {pdf_url}")
                poller = await asyncio.to_thread(
                    lambda: self.client.begin_analyze_document(
                        model,
                        body={"urlSource": pdf_url},
                        output_content_format=output_format,
                        features=features,
                    )
                )
            
            # Get result
            result = await asyncio.to_thread(lambda: poller.result())

            # Get full markdown content
            full_md = result.content

            # Get page markdown content
            page_mds = []
            for page in result.pages:
                span = page.spans[0]
                start, length = span['offset'], span['length']
                content = full_md[start : start + length]
                # use regex to delete if <figure> is in content, just delete inside <figure> and </figure>
                pattern = re.compile(r'(<figure>).*?(</figure>)', re.DOTALL)
                content = pattern.sub(r'\1\2', content)

                page_mds.append({
                    "page_number": page.page_number,
                    "content": content,
                    "unit": page.unit,
                    "width": page.width,
                    "height": page.height
                })
            
            # Process figures information
            figures_info = []
            if hasattr(result, 'figures') and result.figures:
                for i, figure in enumerate(result.figures):
                    figure_info = {
                        'id': f"figure_{i+1}",
                        'caption': getattr(figure, 'caption', {}).get('content', '') if hasattr(figure, 'caption') else '',
                        'bounding_regions': []
                    }
                    
                    # Extract bounding box information for figure cropping
                    if hasattr(figure, 'bounding_regions'):
                        for region in figure.bounding_regions:
                            if hasattr(region, 'polygon') and hasattr(region, 'page_number'):
                                figure_info['bounding_regions'].append({
                                    'page_number': region.page_number,
                                    'polygon': region.polygon
                                })
                    
                    figures_info.append(figure_info)
            
            # Process tables information
            tables_info = []
            if hasattr(result, 'tables') and result.tables:
                for i, table in enumerate(result.tables):
                    caption_obj = getattr(table, 'caption', None)
                    caption_text = caption_obj.get('content', '') if isinstance(caption_obj, dict) else ''
                    
                    table_info = {
                        'id': f"table_{i+1}",
                        'row_count': getattr(table, 'row_count', 0),
                        'column_count': getattr(table, 'column_count', 0),
                        'caption': caption_text
                    }
                    tables_info.append(table_info)
            
            return {
                "pages": page_mds,
                'content': result.content if hasattr(result, 'content') else '',
                'figures': figures_info,
                'tables': tables_info,
                'has_figures': len(figures_info) > 0,
                'has_tables': len(tables_info) > 0,
                'confidence': getattr(result, 'confidence', None),
                'raw_result': result
            }
            
        except Exception as e:
            logger.error(f"Error processing PDF with Document Intelligence: {str(e)}")
            raise

    async def extract_figures_from_pdf(self, pdf_path: str, figures_info: List[Dict[str, Any]], output_dir: str, pages: List[Dict[str, Any]]) -> List[str]:
        """Extract specific figures from PDF based on Document Intelligence detection"""
        try:
            def extract_figures_sync():
                import fitz  # PyMuPDF
                
                pdf_document = fitz.open(pdf_path)
                figure_paths = []
                
                for figure_info in figures_info:
                    figure_id = figure_info['id']
                    
                    for region in figure_info['bounding_regions']:
                        page_number = region['page_number'] - 1  # Convert to 0-based index
                        # get page inch from pages
                        assert pages[page_number]['unit'] == 'inch', "Se espera unit='inch' en page_meta"
                        page_inch_width = pages[page_number]['width']
                        page_inch_height = pages[page_number]['height']


                        polygon_raw = region['polygon']
                        if polygon_raw and len(polygon_raw) % 2 == 0:
                            polygon = [
                                {'x': polygon_raw[i], 'y': polygon_raw[i + 1]}
                                for i in range(0, len(polygon_raw), 2)
                            ]
                        else:
                            polygon = []

                        
                        if page_number < pdf_document.page_count:
                            page = pdf_document.load_page(page_number)

                            # Convert from relative coordinates to page coordinates
                            page_rect = page.rect
                            sx = page_rect.width / page_inch_width
                            sy = page_rect.height / page_inch_height

                            # Convert polygon to rect (simplified - takes bounding box)
                            x_coords = [p['x'] * sx for p in polygon]
                            y_coords = [p['y'] * sy for p in polygon]
                            
                            
                            x_min, x_max = min(x_coords), max(x_coords)
                            y_min, y_max = min(y_coords), max(y_coords)

                            # Create clip rect
                            clip_rect = fitz.Rect(x_min, y_min, x_max, y_max)
                            
                            # Extract the figure region with high resolution
                            mat = fitz.Matrix(3, 3)  # 3x zoom for better quality
                            pix = page.get_pixmap(matrix=mat, clip=clip_rect)
                            
                            # Save the figure
                            figure_filename = f"{figure_id}_page_{page_number + 1}.png"
                            figure_path = os.path.join(output_dir, figure_filename)
                            pix.save(figure_path)
                            figure_paths.append(figure_path)
                
                pdf_document.close()
                return figure_paths
            
            return await asyncio.to_thread(extract_figures_sync)
            
        except Exception as e:
            logger.error(f"Error extracting figures from PDF: {str(e)}")
            raise

    def should_analyze_figure_with_ai_vision(self, figure_info: Dict[str, Any], thresholds: Dict[str, Any]) -> Dict[str, Any]:
        """
        Determine if a figure should be analyzed with AI Vision based on configurable thresholds
        
        Args:
            figure_info: Information about the detected figure
            thresholds: Configuration thresholds for AI Vision analysis
            
        Returns:
            Dict with decision and reasoning
        """
        reasons = []
        should_analyze = True
        
        # 1. Size threshold - check minimum figure size
        min_size = thresholds.get('min_figure_size', 0.01)  # Default 1% of page
        if figure_info.get('bounding_regions'):
            for region in figure_info['bounding_regions']:
                polygon_raw = region.get('polygon', [])
                if polygon_raw and len(polygon_raw) % 2 == 0:
                    polygon = [
                        {'x': polygon_raw[i], 'y': polygon_raw[i + 1]}
                        for i in range(0, len(polygon_raw), 2)
                    ]
                else:
                    polygon = []

                if polygon:
                    # Calculate figure area (simplified as bounding box area)
                    x_coords = [p.get('x', 0) for p in polygon]
                    y_coords = [p.get('y', 0) for p in polygon]
                    
                    width = max(x_coords) - min(x_coords)
                    height = max(y_coords) - min(y_coords)
                    area = width * height
                    
                    if area < min_size:
                        should_analyze = False
                        reasons.append(f"Figure too small (area: {area:.3f} < threshold: {min_size})")
                        break
                    else:
                        reasons.append(f"Size check passed (area: {area:.3f})")
        
        # 2. Caption threshold - analyze based on caption relevance
        min_caption_length = thresholds.get('min_caption_length', 0)
        caption = figure_info.get('caption', '')
        if min_caption_length > 0 and len(caption) < min_caption_length:
            should_analyze = False
            reasons.append(f"Caption too short ({len(caption)} chars < {min_caption_length})")
        elif caption:
            reasons.append(f"Caption available ({len(caption)} chars)")
        
        # 3. Keywords filter - only analyze figures with specific keywords in caption
        required_keywords = thresholds.get('required_keywords', [])
        excluded_keywords = thresholds.get('excluded_keywords', ['logo', 'signature', 'watermark'])
        
        if caption:
            caption_lower = caption.lower()
            
            # Check excluded keywords
            for excluded in excluded_keywords:
                if excluded.lower() in caption_lower:
                    should_analyze = False
                    reasons.append(f"Contains excluded keyword: '{excluded}'")
                    break
            
            # Check required keywords (if specified)
            if required_keywords and should_analyze:
                has_required = any(keyword.lower() in caption_lower for keyword in required_keywords)
                if not has_required:
                    should_analyze = False
                    reasons.append(f"Missing required keywords: {required_keywords}")
                else:
                    reasons.append("Contains required keywords")
        
        # 4. Figure type filtering based on common patterns
        figure_types_to_analyze = thresholds.get('analyze_figure_types', ['chart', 'graph', 'diagram', 'table'])
        figure_types_to_skip = thresholds.get('skip_figure_types', ['logo', 'signature', 'header', 'footer'])
        
        if caption:
            caption_lower = caption.lower()
            
            # Check if should skip based on type
            for skip_type in figure_types_to_skip:
                if skip_type.lower() in caption_lower:
                    should_analyze = False
                    reasons.append(f"Figure type to skip: '{skip_type}'")
                    break
            
            # Check if should analyze based on type
            if should_analyze and figure_types_to_analyze:
                should_analyze_type = any(fig_type.lower() in caption_lower for fig_type in figure_types_to_analyze)
                if should_analyze_type:
                    reasons.append("Figure type marked for analysis")
        
        # 5. Maximum figures per document limit
        max_figures_per_doc = thresholds.get('max_figures_per_document', None)
        figure_index = int(figure_info.get('id', 'figure_0').split('_')[-1])
        if max_figures_per_doc and figure_index > max_figures_per_doc:
            should_analyze = False
            reasons.append(f"Exceeds max figures limit ({figure_index} > {max_figures_per_doc})")
        
        return {
            'should_analyze': should_analyze,
            'reasons': reasons,
            'figure_id': figure_info.get('id'),
            'caption': caption,
            'thresholds_applied': list(thresholds.keys())
        }

class OpenAIVisionAdapter(IVisionService):
    """Adapter for OpenAI Vision API"""
    
    def __init__(self, api_key: str, endpoint: str, deployment_name: str, storage_type: str = 'azure'):
        self.api_key = api_key
        self.endpoint = endpoint
        self.deployment_name = deployment_name
        self.storage_type = storage_type

        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")


        self.client = AsyncAzureOpenAI(
            azure_endpoint=f"https://{self.endpoint}.openai.azure.com/",
            azure_ad_token_provider=token_provider,
            azure_deployment=self.deployment_name,
            api_version="2025-04-01-preview"  # versión soportada con visión
        )

    def _local_image_to_data_url(self, image_path: str) -> str:
        mime_type, _ = mimetypes.guess_type(image_path)
        if mime_type is None:
            mime_type = "application/octet-stream"
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime_type};base64,{b64}"

    async def describe_image(self, image: str, prompt: str) -> str:
        """
        Describe image.

        :param image: if storage_type=="url", pass URL; if "local", pass filesystem path.
        :param prompt: textual prompt to accompany the image.
        """
        # Prepare content
        if self.storage_type == "local":
            img_url = self._local_image_to_data_url(image)
        else:
            img_url = image

        message = {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": img_url}}
            ]
        }

        # Retry logic
        for attempt in range(3):
            try:
                resp = await self.client.chat.completions.create(
                    model=self.deployment_name,
                    messages=[message],
                    max_tokens=300
                )
                return resp.choices[0].message.content
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(30)
                else:
                    raise

class LibreOfficeAdapter(IConversionService):
    """Adapter for LibreOffice document conversion"""
    
    async def convert_to_pdf(self, source_path: str, target_path: str) -> bool:
        """Convert document to PDF using LibreOffice"""
        try:
            def convert_sync():
                # Create user profile directory
                user_profile_dir = os.path.join(os.path.dirname(target_path), "userprofile")
                os.makedirs(user_profile_dir, exist_ok=True)
                
                cmd = [
                    'soffice',
                    '--headless',
                    f'-env:UserInstallation=file://{user_profile_dir}',
                    '--convert-to', 'pdf',
                    '--outdir', os.path.dirname(target_path),
                    source_path
                ]
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env={'HOME': os.path.dirname(target_path), 'PATH': os.environ.get('PATH', '')}
                )
                
                stdout, stderr = process.communicate(timeout=60)
                
                if process.returncode != 0:
                    raise Exception(f"LibreOffice conversion failed: {stderr.decode()}")
                
                return True
            
            return await asyncio.to_thread(convert_sync)
            
        except Exception as e:
            logger.error(f"Error converting document: {str(e)}")
            return False
    
    async def pdf_to_images(self, pdf_path: str, output_dir: str, quality_settings: Dict[str, Any]) -> List[str]:
        """Convert PDF pages to images"""
        try:
            def convert_sync():
                zoom = quality_settings.get('zoom', 5)
                mat = fitz.Matrix(zoom, zoom)
                
                pdf_document = fitz.open(pdf_path)
                image_paths = []
                
                for page_num in range(pdf_document.page_count):
                    page = pdf_document.load_page(page_num)
                    image = page.get_pixmap(matrix=mat)
                    
                    image_path = os.path.join(output_dir, f"page_{page_num}.jpeg")
                    image.save(image_path)
                    image_paths.append(image_path)
                
                pdf_document.close()
                return image_paths
            
            return await asyncio.to_thread(convert_sync)
            
        except Exception as e:
            logger.error(f"Error converting PDF to images: {str(e)}")
            raise

class EnvironmentConfigurationService(IConfigurationService):
    """Configuration service using environment variables"""
    
    def __init__(self, env_variables: Dict[str, str]):
        self.env_variables = env_variables
    
    def get_ocr_config(self) -> Dict[str, Any]:
        return {
            'max_pages': int(self.env_variables.get('MAX_PAGES', '100')),
            'timeout_seconds': int(self.env_variables.get('OCR_TIMEOUT', '300')),
            'quality_settings': {
                'zoom': int(self.env_variables.get('PDF_ZOOM', '5')),
                'dpi': int(self.env_variables.get('IMAGE_DPI', '300'))
            },
            'cleanup_temp_files': self.env_variables.get('CLEANUP_TEMP', 'true').lower() == 'true'
        }
    
    def get_storage_config(self) -> Dict[str, Any]:
        storage_type = self.env_variables.get('STORAGE_TYPE', 'azure').lower()
        
        if storage_type == 'local':
            return {
                'type': 'local',
                'base_path': self.env_variables.get('LOCAL_STORAGE_PATH', './storage'),
                'base_url': self.env_variables.get('LOCAL_STORAGE_URL', 'http://localhost:8000/files')
            }
        else:
            return {
                'type': 'azure',
                'connection_string': self.env_variables['AZURE_STORAGE_CONNECTION_STRING'],
                'container_name': self.env_variables['AZURE_STORAGE_CONTAINER']
            }
    
    def get_ai_config(self) -> Dict[str, Any]:
        return {
            'openai_endpoint': self.env_variables['AZURE_OPENAI_SERVICE'],
            'openai_key': self.env_variables['AZURE_OPENAI_API_KEY'],
            'openai_deployment': self.env_variables['AZURE_OPENAI_DEPLOYMENT_NAME'],
            'form_recognizer_endpoint': self.env_variables['AZURE_FORM_RECOGNIZER_ENDPOINT'],
            'form_recognizer_key': self.env_variables['AZURE_FORM_RECOGNIZER_KEY']
        }

    def get_ai_vision_thresholds(self) -> Dict[str, Any]:
        """Get configurable thresholds for AI Vision figure analysis"""
        return {
            # Minimum figure size (as fraction of page area, 0.0-1.0)
            'min_figure_size': float(self.env_variables.get('AI_VISION_MIN_FIGURE_SIZE', '0.01')),
            
            # Minimum caption length to consider analysis
            'min_caption_length': int(self.env_variables.get('AI_VISION_MIN_CAPTION_LENGTH', '0')),
            
            # Maximum figures to analyze per document (cost control)
            'max_figures_per_document': int(self.env_variables.get('AI_VISION_MAX_FIGURES_PER_DOC', '10')) if self.env_variables.get('AI_VISION_MAX_FIGURES_PER_DOC') else None,
            
            # Keywords that must be present in caption (comma-separated)
            'required_keywords': [kw.strip() for kw in self.env_variables.get('AI_VISION_REQUIRED_KEYWORDS', '').split(',') if kw.strip()],
            
            # Keywords that exclude from analysis (comma-separated)  
            'excluded_keywords': [kw.strip() for kw in self.env_variables.get('AI_VISION_EXCLUDED_KEYWORDS', 'logo,signature,watermark,header,footer').split(',') if kw.strip()],
            
            # Figure types to analyze (comma-separated)
            'analyze_figure_types': [ft.strip() for ft in self.env_variables.get('AI_VISION_ANALYZE_TYPES', 'chart,graph,diagram,table,figure').split(',') if ft.strip()],
            
            # Figure types to skip (comma-separated)
            'skip_figure_types': [ft.strip() for ft in self.env_variables.get('AI_VISION_SKIP_TYPES', 'logo,signature,header,footer,watermark').split(',') if ft.strip()],
            
            # Enable/disable AI Vision analysis entirely
            'enabled': self.env_variables.get('AI_VISION_ENABLED', 'true').lower() == 'true'
        } 