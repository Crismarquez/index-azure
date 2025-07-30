# OCR Document Processing System

Sistema avanzado de procesamiento OCR con Azure AI que incluye gestión de documentos en base de datos con estados Bronze, Silver y Gold.

## 🆕 Nuevas Funcionalidades - Base de Datos

### Estados de Datos
- **Bronze**: Datos brutos, recién procesados
- **Silver**: Datos limpios y estructurados  
- **Gold**: Datos enriquecidos listos para análisis

### Campos de Gestión
- `state`: Estado de los datos (bronze/silver/gold)
- `status_process`: Estado del procesamiento (pending/processing/completed/failed)
- `process_stage`: Etapa específica del proceso (ingestion/extraction/transformation/etc.)

## 🚀 Configuración Rápida

### 1. Configurar Variables de Entorno

Copia `env.template` a `.env` y configura:

```bash
# Database Configuration
DATABASE_TYPE=sqlite
DATABASE_URL=sqlite:///./database/documents.db

# Azure Configuration (requerido)
AZURE_FORM_RECOGNIZER_ENDPOINT=tu_endpoint
AZURE_FORM_RECOGNIZER_KEY=tu_key
AZURE_OPENAI_SERVICE=tu_servicio
AZURE_OPENAI_API_KEY=tu_api_key
AZURE_OPENAI_DEPLOYMENT_NAME=tu_deployment
```

### 2. Instalar Dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar Base de Datos

```bash
# Ejecutar script de configuración
python scripts/setup_database.py

# O inicializar solo la base de datos
python database/init_db.py
```

### 4. Iniciar el Servidor

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 📊 API Endpoints

### Procesamiento de Documentos

```bash
# Procesar documento
POST /api/v1/process_document
```

### Gestión de Documentos

```bash
# Estadísticas generales
GET /api/v1/documents/stats

# Documentos por usuario
GET /api/v1/documents/user/{email}

# Documentos por estado
GET /api/v1/documents/state/{bronze|silver|gold}

# Información de documento específico
GET /api/v1/documents/{document_id}

# Promover documento a Gold
POST /api/v1/documents/{document_id}/promote
```

### 🥉 Endpoints Específicos para Bronze

```bash
# Consultar documentos en estado Bronze
GET /api/v1/documents/bronze

# Consultar documentos Bronze con filtros
GET /api/v1/documents/bronze?user_email={email}&limit=50&include_storage_info=true

# Información de almacenamiento Bronze de un documento
GET /api/v1/documents/bronze/{document_id}/storage

# Resumen de documentos Bronze
GET /api/v1/documents/bronze/summary
```

### Ejemplos de Uso

```bash
# Ver estadísticas generales
curl http://localhost:8000/api/v1/documents/stats

# Ver todos los documentos Bronze
curl http://localhost:8000/api/v1/documents/bronze

# Ver documentos Bronze de un usuario específico
curl "http://localhost:8000/api/v1/documents/bronze?user_email=usuario@email.com"

# Ver documentos Bronze con información de almacenamiento
curl "http://localhost:8000/api/v1/documents/bronze?include_storage_info=true&limit=20"

# Ver información de almacenamiento Bronze de un documento
curl http://localhost:8000/api/v1/documents/bronze/DOC123/storage

# Ver resumen de documentos Bronze
curl http://localhost:8000/api/v1/documents/bronze/summary

# Ver documentos de un usuario
curl http://localhost:8000/api/v1/documents/user/usuario@email.com

# Promover documento a estado Gold
curl -X POST http://localhost:8000/api/v1/documents/DOC123/promote \
     -H "Content-Type: application/json" \
     -d '{"enrichment_data": {"analysis": "completed"}}'
```

### 📊 Ejemplos de Respuestas

#### Consulta de documentos Bronze:
```json
{
  "status": "success",
  "data_state": "bronze",
  "description": "Documentos con datos brutos procesados",
  "count": 25,
  "filters": {
    "user_email": null,
    "context_id": null,
    "limit": 100,
    "include_storage_info": false
  },
  "documents": [...]
}
```

#### Información de almacenamiento Bronze:
```json
{
  "status": "success",
  "document_info": {
    "document_id": "REQ123_ATT456_1703123456",
    "document_name": "mi_documento.pdf",
    "data_state": "bronze",
    "created_at": "2023-12-20T15:30:56"
  },
  "bronze_storage": {
    "document_id": "REQ123_ATT456_1703123456",
    "bronze_folder": "bronze/REQ123_mi_documento_20231220_153056",
    "storage_urls": {
      "original_document": "http://localhost:8000/files/bronze/.../original_document.pdf",
      "extracted_content": "http://localhost:8000/files/bronze/.../full_text.md"
    },
    "folder_structure": {
      "base_folder": "bronze/REQ123_mi_documento_20231220_153056",
      "raw_folder": "bronze/REQ123_mi_documento_20231220_153056/raw",
      "extracted_content_folder": "bronze/.../extracted_content",
      "figures_folder": "bronze/.../figures"
    },
    "expected_files": {
      "manifest": "bronze/.../manifest.json",
      "original_document": "bronze/.../raw/original_document.pdf",
      "full_text": "bronze/.../extracted_content/full_text.md"
    }
  }
}
```

#### Resumen de documentos Bronze:
```json
{
  "status": "success",
  "data_state": "bronze",
  "summary": {
    "total_documents": 150,
    "recent_documents_7_days": 25,
    "unique_users": 12,
    "documents_by_user": {
      "usuario1@email.com": 45,
      "usuario2@email.com": 30
    },
    "documents_by_type": {
      "pdf": 120,
      "docx": 25,
      "image": 5
    }
  },
  "recent_documents": [...]
}
```

## 🗄️ Estructura de Base de Datos

### Tabla `documents`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | Integer | ID auto-incremental |
| `document_id` | String | ID único del documento |
| `document_name` | String | Nombre del documento |
| `processing_status` | String | Estado: pending/processing/completed/failed |
| `data_state` | String | Estado de datos: bronze/silver/gold |
| `process_stage` | String | Etapa: ingestion/extraction/transformation/etc. |
| `user_email` | String | Email del usuario |
| `confidence_score` | Float | Puntuación de confianza OCR |
| `page_count` | Integer | Número de páginas |
| `processing_time` | Float | Tiempo de procesamiento |
| `bronze_folder_path` | String | Ruta del almacenamiento bronze |
| `created_at` | DateTime | Fecha de creación |
| `updated_at` | DateTime | Fecha de actualización |

## 🏗️ Arquitectura

### Flujo de Procesamiento

1. **Registro**: Documento se registra en BD con estado `bronze/ingestion`
2. **Procesamiento**: Estado cambia a `processing/extraction`
3. **Almacenamiento**: Archivos se guardan en estructura Bronze
4. **Finalización**: Estado cambia a `completed/ready` y `silver`
5. **Enriquecimiento**: Opcionalmente se puede promover a `gold`

### Servicios Principales

- **DocumentDatabase**: Operaciones de base de datos
- **DocumentManager**: Gestión de alto nivel (BD + archivos)
- **BronzeStorageService**: Almacenamiento de archivos
- **OCRPipeline**: Pipeline de procesamiento OCR

## 📁 Estructura de Archivos Bronze

```
bronze/
├── {document_id}/
│   ├── manifest.json              # Manifiesto general
│   ├── raw/
│   │   └── original_document.pdf  # Documento original
│   ├── extracted_content/
│   │   ├── full_text.md           # Texto extraído
│   │   ├── metadata.json          # Metadatos
│   │   └── extraction_result.json # Resultado completo
│   ├── content_pages/
│   │   ├── page_1.json            # Contenido por página
│   │   └── page_2.json
│   ├── figures/
│   │   ├── figure_1.png           # Figuras extraídas
│   │   └── figure_analysis.json   # Análisis de figuras
│   ├── processing_logs/
│   │   └── processing_log.json    # Logs de procesamiento
│   └── quality_assessment/
│       └── quality_report.json    # Reporte de calidad
```

## 🔍 Consultas Avanzadas

### Python SDK

```python
from services.document_manager import DocumentManager
from services.database import DocumentDatabase, DataState

# Inicializar
db = DocumentDatabase()
manager = DocumentManager(db, storage_service)

# Consultar documentos
bronze_docs = manager.get_documents_by_state(DataState.BRONZE)
user_docs = manager.get_user_documents("usuario@email.com")
stats = manager.get_processing_statistics()

# Promover documento
await manager.promote_to_gold("doc_id", {"enrichment": "data"})
```

## 🛠️ Configuración Avanzada

### Base de Datos PostgreSQL

```bash
# En .env
DATABASE_URL=postgresql://user:password@localhost/documents_db
```

### Base de Datos MySQL

```bash
# En .env  
DATABASE_URL=mysql://user:password@localhost/documents_db
```

## 🔧 Mantenimiento

### Respaldo de Base de Datos

```bash
# SQLite
cp database/documents.db backup/documents_$(date +%Y%m%d).db

# PostgreSQL
pg_dump documents_db > backup/documents_$(date +%Y%m%d).sql
```

### Limpieza de Datos

```python
# Eliminar documentos antiguos
from datetime import datetime, timedelta
from services.database import DocumentDatabase

db = DocumentDatabase()
cutoff_date = datetime.now() - timedelta(days=90)

# Implementar lógica de limpieza según necesidades
```

## 📈 Monitoreo

### Métricas Disponibles

- Total de documentos procesados
- Distribución por estados (Bronze/Silver/Gold)
- Tiempo promedio de procesamiento
- Tasa de éxito/fallo
- Documentos por usuario

### Dashboard de Estadísticas

```bash
curl http://localhost:8000/api/v1/documents/stats
```

Respuesta:
```json
{
  "total_documents": 150,
  "by_processing_status": {
    "completed": 145,
    "failed": 3,
    "processing": 2
  },
  "by_data_state": {
    "bronze": 50,
    "silver": 80,
    "gold": 20
  }
}
```

## 🤝 Contribuir

1. Fork el proyecto
2. Crea una rama para tu feature
3. Commit tus cambios
4. Push a la rama
5. Abre un Pull Request

## 📝 Licencia

Este proyecto está bajo la licencia MIT. 