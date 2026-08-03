# Error Catalog - Increment 003

## Estructura de respuesta de error

```python
class ErrorResponse(BaseModel):
    code: str        # Código de error (ej: DOCUMENT_TEMPLATE_NOT_FOUND)
    message: str     # Descripción legible en español
    details: dict | None = None  # Detalles adicionales opcionales
```

```json
{
  "code": "DOCUMENT_TEMPLATE_NOT_FOUND",
  "message": "Plantilla no encontrada",
  "details": {
    "template_id": "uuid"
  }
}
```

## Catálogo completo de errores

| Código | HTTP | Descripción | Capa |
|--------|------|-------------|------|
| DOCUMENT_TEMPLATE_NOT_FOUND | 404 | Plantilla no encontrada | Service |
| DOCUMENT_TEMPLATE_NAME_EXISTS | 409 | Nombre de plantilla ya registrado | Repository |
| DOCUMENT_TEMPLATE_INACTIVE | 409 | Plantilla desactivada, no puede generar borradores | Service |
| DOCUMENT_TEMPLATE_CONFLICT | 409 | Conflicto de versión al actualizar plantilla | Repository |
| CASE_FILE_NOT_FOUND | 404 | Expediente no encontrado | Service |
| DESIGNATION_DATA_NOT_FOUND | 404 | Datos de designación no encontrados | Repository |
| DESIGNATION_DATA_INCOMPLETE | 422 | Datos de designación incompletos para generación | Service |
| CASE_FILE_TYPE_INCOMPATIBLE | 409 | Tipo de expediente incompatible con la operación | Service |
| DRAFT_NOT_FOUND | 404 | Borrador no encontrado | Repository |
| INVALID_DRAFT_TRANSITION | 409 | Transición de estado no válida | Service |
| DRAFT_ALREADY_APPROVED | 409 | Borrador ya fue aprobado | Service |
| GENERATION_IN_PROGRESS | 409 | Ya existe una generación en curso para este expediente | Repository |
| GENERATION_FAILED | 502 | Error en la generación del documento | Service |
| OLLAMA_UNAVAILABLE | 503 | Servicio Ollama no disponible | Client |
| OLLAMA_TIMEOUT | 504 | Timeout en la respuesta de Ollama | Client |
| CONCURRENT_MODIFICATION | 409 | Conflicto de concurrencia, versión desactualizada | Repository |
| VALIDATION_ERROR | 422 | Error de validación en campos del request | Pydantic |
| DATABASE_ERROR | 500 | Error interno de base de datos | SQLAlchemy |
| MISSING_REQUIRED_VARIABLES | 422 | Variables requeridas faltantes en el request | Service |
| CONTENT_TOO_LARGE | 422 | Contenido del borrador excede el límite permitido | Service |
| CONTEXT_BUILD_FAILED | 500 | Error al construir el contexto para generación | Service |
| IDEMPOTENCY_KEY_MISMATCH | 409 | Idempotency-Key no coincide con request previo | Repository |

## Descripciones detalladas

### DOCUMENT_TEMPLATE_NOT_FOUND (404)

La plantilla de documento solicitada no existe en el sistema.

**Capa**: Service  
**Trigger**: GET/PATCH/DELETE con UUID inexistente  
**Resolución**: Verificar que el UUID sea correcto y que la plantilla no haya sido eliminada.

---

### DOCUMENT_TEMPLATE_NAME_EXISTS (409)

Ya existe una plantilla activa con el mismo nombre.

**Capa**: Repository  
**Trigger**: POST/PATCH con nombre duplicado  
**Resolución**: Usar un nombre diferente o desactivar la plantilla existente.

---

### DOCUMENT_TEMPLATE_INACTIVE (409)

La plantilla está desactivada y no puede usarse para generar borradores.

**Capa**: Service  
**Trigger**: POST /drafts/generate con template_id de plantilla inactiva  
**Resolución**: Reactivar la plantilla o usar una plantilla activa.

---

### DOCUMENT_TEMPLATE_CONFLICT (409)

Conflicto de versión al intentar modificar la plantilla.

**Capa**: Repository  
**Trigger**: Operación concurrente sobre la misma plantilla  
**Resolución**: Re-leer la plantilla y reintentar con la versión actual.

---

### CASE_FILE_NOT_FOUND (404)

El expediente solicitado no existe en el sistema.

**Capa**: Service  
**Trigger**: GET/PATCH/DELETE con UUID inexistente  
**Resolución**: Verificar que el UUID sea correcto. Reutilizado del incremento 002.

---

### DESIGNATION_DATA_NOT_FOUND (404)

No existen datos de designación registrados para el expediente.

**Capa**: Repository  
**Trigger**: GET de designación cuando no existe  
**Resolución**: Crear datos de designación con POST.

---

### DESIGNATION_DATA_INCOMPLETE (422)

Los datos de designación están incompletos para generar el documento.

**Capa**: Service  
**Trigger**: POST /drafts/generate sin campos obligatorios en designación  
**Resolución**: Completar los campos faltantes en la designación.

---

### CASE_FILE_TYPE_INCOMPATIBLE (409)

El tipo de expediente no es compatible con la operación solicitada.

**Capa**: Service  
**Trigger**: Crear designación en expediente de tipo incompatible  
**Resolución**: Verificar el tipo de expediente y usar la operación adecuada.

---

### DRAFT_NOT_FOUND (404)

El borrador solicitado no existe en el sistema.

**Capa**: Repository  
**Trigger**: GET/PATCH/POST con UUID inexistente  
**Resolución**: Verificar que el UUID sea correcto.

---

### INVALID_DRAFT_TRANSITION (409)

La transición de estado solicitada no es válida desde el estado actual.

**Capa**: Service  
**Trigger**: POST /transitions con acción inválida  
**Resolución**: Consultar la matriz de transiciones válidas.

---

### DRAFT_ALREADY_APPROVED (409)

El borrador ya fue aprobado y no puede ser aprobado nuevamente.

**Capa**: Service  
**Trigger**: POST /transitions con action=approve sobre borrador aprobado  
**Resolución**: Finalizar el borrador o regenerar uno nuevo.

---

### GENERATION_IN_PROGRESS (409)

Ya existe una generación en curso para este expediente.

**Capa**: Repository  
**Trigger**: POST /drafts/generate cuando hay generación activa  
**Resolución**: Esperar a que la generación actual finalize.

---

### GENERATION_FAILED (502)

Error en la generación del documento por parte del modelo de lenguaje.

**Capa**: Service  
**Trigger**: Error en la llamada a Ollama  
**Resolución**: Verificar logs de generación, reintentar o contactar soporte.

---

### OLLAMA_UNAVAILABLE (503)

El servicio Ollama no está disponible o no responde.

**Capa**: Client  
**Trigger**: Intento de conexión fallido  
**Resolución**: Verificar que Ollama esté ejecutándose y accesible.

---

### OLLAMA_TIMEOUT (504)

La respuesta de Ollama excedió el tiempo límite.

**Capa**: Client  
**Trigger**: Timeout en la llamada a Ollama  
**Resolución**: Verificar carga del servidor, reducir complejidad del prompt.

---

### CONCURRENT_MODIFICATION (409)

Conflicto de concurrencia: otro usuario modificó el recurso.

**Capa**: Repository  
**Trigger**: expected_version no coincide con versión actual  
**Resolución**: Re-leer el recurso y reintentar con la versión actual.

---

### VALIDATION_ERROR (422)

Error de validación en los campos del request.

**Capa**: Pydantic  
**Trigger**: Campos faltantes, tipo incorrecto, formato inválido  
**Resolución**: Corregir los campos según el schema esperado.

---

### DATABASE_ERROR (500)

Error interno de base de datos.

**Capa**: SQLAlchemy  
**Trigger**: Excepción no manejada en queries  
**Resolución**: Contactar soporte técnico, verificar logs de BD.

---

### MISSING_REQUIRED_VARIABLES (422)

Variables requeridas faltantes en el request de generación.

**Capa**: Service  
**Trigger**: POST /drafts/generate sin variables obligatorias  
**Resolución**: Incluir todas las variables requeridas por la plantilla.

---

### CONTENT_TOO_LARGE (422)

El contenido del borrador excede el límite permitido (50KB).

**Capa**: Service  
**Trigger**: PATCH /drafts/{id}/content con contenido excesivo  
**Resolución**: Reducir el tamaño del contenido.

---

### CONTEXT_BUILD_FAILED (500)

Error al construir el contexto para la generación del documento.

**Capa**: Service  
**Trigger**: Error al ensamblar template + designation + variables  
**Resolución**: Verificar integridad de datos, contactar soporte técnico.

---

### IDEMPOTENCY_KEY_MISMATCH (409)

La Idempotency-Key no coincide con el request previo para la misma key.

**Capa**: Repository  
**Trigger**: POST /drafts/generate con key previa pero payload diferente  
**Resolución**: Usar una nueva Idempotency-Key o enviar el mismo payload.
