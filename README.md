# Pipeline de Procesamiento de Documentos OCR

Sistema de procesamiento de documentos con OCR generalizado que puede ser usado en múltiples escenarios, no limitado a un CRM específico.

## 🚀 Características

- **Procesamiento multi-formato**: PDF, Word, Excel, PowerPoint, imágenes
- **Extracción inteligente**: Texto, tablas, figuras e imágenes  
- **Análisis de calidad**: Validación automática y sugerencias de mejora
- **Storage flexible**: Soporte para almacenamiento local y Azure Blob Storage
- **Arquitectura limpia**: Principios SOLID, extensible y mantenible
- **Generic API**: No atado a ningún CRM específico

## 📋 Endpoints

### `POST /process_document`

Procesa documentos de cualquier contexto (CRM, gestión de proyectos, etc.).

#### Input

```json
{
  "request_id": "req_12345",
  "user_email": "user@company.com",
  "context_id": "project_789",
  "context_name": "Proyecto Alpha",
  "attachments": [
    {
      "url": "https://example.com/document.pdf",
      "file_type": "pdf",
      "name": "Contract_v2.pdf",
      "attachment_id": "att_001",
      "size_bytes": 1024000,
      "upload_date": "2024-01-15T10:30:00Z"
    }
  ],
  "metadata": {
    "department": "legal",
    "priority": "high",
    "custom_field": "value"
  }
}
```

#### Campos

| Campo | Descripción | Requerido |
|-------|-------------|-----------|
| `request_id` | Identificador único de la solicitud | ✅ |
| `user_email` | Email del usuario que realiza la solicitud | ✅ |
| `context_id` | ID del contexto (proyecto, deal, etc.) | ❌ |
| `context_name` | Nombre del contexto | ❌ |
| `attachments` | Lista de documentos a procesar | ✅ |
| `metadata` | Metadatos adicionales específicos del uso | ❌ |

#### Campos de Attachment

| Campo | Descripción | Requerido |
|-------|-------------|-----------|
| `url` | URL del documento a procesar | ✅ |
| `file_type` | Tipo de archivo (pdf, docx, xlsx, etc.) | ✅ |
| `name` | Nombre del archivo | ✅ |
| `attachment_id` | ID único del attachment | ✅ |
| `size_bytes` | Tamaño en bytes | ❌ |
| `upload_date` | Fecha de carga | ❌ |

#### Response

```json
{
  "results": [
    {
      "document_name": "Contract_v2.pdf",
      "status": "completed",
      "extracted_text": "...",
      "figures": [...],
      "quality": {
        "quality_score": 0.95,
        "is_quality_ok": true
      },
      "bronze_structure": {
        "manifest_url": "...",
        "raw_document_url": "...",
        "extracted_content_url": "...",
        "figures_folder_url": "..."
      }
    }
  ]
}
```

## 🔧 Ejemplos de Uso

### CRM (HubSpot, Salesforce, etc.)

```json
{
  "request_id": "engagement_12345",
  "user_email": "sales@company.com",
  "context_id": "deal_789",
  "context_name": "Acme Corp Deal",
  "attachments": [...],
  "metadata": {
    "crm_type": "hubspot",
    "deal_stage": "negotiation"
  }
}
```

### Gestión de Proyectos

```json
{
  "request_id": "task_67890",
  "user_email": "pm@company.com", 
  "context_id": "project_alpha",
  "context_name": "Website Redesign",
  "attachments": [...],
  "metadata": {
    "project_phase": "design",
    "team": "frontend"
  }
}
```

### Legal/Compliance

```json
{
  "request_id": "review_54321",
  "user_email": "legal@company.com",
  "context_id": "contract_456",
  "context_name": "Vendor Agreement Review",
  "attachments": [...],
  "metadata": {
    "department": "legal",
    "document_type": "contract",
    "urgency": "high"
  }
}
```

### HR/Recruiting

```json
{
  "request_id": "application_98765",
  "user_email": "hr@company.com",
  "context_id": "position_123",
  "context_name": "Senior Developer Position",
  "attachments": [...],
  "metadata": {
    "application_stage": "initial_review",
    "position_level": "senior"
  }
}
```

## 🏗️ Instalación

Ver [INSTALLATION.md](INSTALLATION.md) para instrucciones detalladas.

## 📁 Estructura Bronze

El sistema organiza automáticamente todos los artefactos procesados en una estructura bronze. Ver [BRONZE_STRUCTURE_README.md](BRONZE_STRUCTURE_README.md) para más detalles.

## 🔍 Health Check

```bash
GET /health
```

```json
{
  "status": "healthy",
  "services": {
    "storage": "ok",
    "ocr": "ok", 
    "ai_vision": "ok"
  }
}
```

## 🚀 Inicio Rápido

```bash
# 1. Configurar variables de entorno
cp env.template .env
# Editar .env con tus credenciales

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Ejecutar
uvicorn main_improved:app --reload

# 4. Probar
curl -X POST http://localhost:8000/process_document \
  -H "Content-Type: application/json" \
  -d @example_request.json
``` 