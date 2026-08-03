# Quickstart: Validación del Incremento 003

## Prerrequisitos

- Docker Compose funcionando (incremento 001 y 002 completados)
- PostgreSQL con pgvector
- Ollama accesible (local o remoto via OLLAMA_BASE_URL)
- API FastAPI corriendo en puerto configurado

## 1. Migración

```bash
# Ejecutar migración 003
docker compose exec api alembic upgrade head

# Verificar revisión actual
docker compose exec api alembic current
# Esperado: 003 (head)
```

## 2. Crear Plantilla

```bash
curl -X POST http://localhost:8000/api/v1/templates \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Designación Transitoria",
    "document_type": "RESOLUCION",
    "organ_emisor": "Instituto Municipal de Industria",
    "normativa": "Ley 1234/56",
    "description": "Plantilla para designación transitoria de personal",
    "body_template": "RESOLUCIÓN NÚMERO {{variables.numero_resolucion}}\n\nEn la ciudad de ..., a los ... días del mes de ... del año ..., siendo las ... horas,\n\nVISTO: La normativa vigente sobre designaciones,\n\nCONSIDERANDO:\n\n1. Que {{employee.first_name}} {{employee.last_name}} desempeña funciones en {{employee.department}},\n2. Que resulta necesario designar transitoriamente a {{designation.position_name}} en {{designation.organizational_unit}},\n\nPOR ELLO:\n\nSE RESUELVE:\n\nArtículo 1°: Designar a {{employee.first_name}} {{employee.last_name}} (CUIL: {{employee.cuil}}) como {{designation.position_name}} por el período que indique la normativa.\n\nArtículo 2°: La presente resolución entrará en vigor a partir de su dictación.\n\nFirma: {{designation.appointing_authority}}",
    "variables": [
      {"name": "numero_resolucion", "label": "Número de Resolución", "type": "text", "required": true},
      {"name": "fecha_resolucion", "label": "Fecha de Resolución", "type": "date", "required": false}
    ]
  }'
```

## 3. Crear Datos de Designación

```bash
curl -X POST http://localhost:8000/api/v1/case-files/{case_file_id}/designation \
  -H "Content-Type: application/json" \
  -d '{
    "position_name": "Asesor Legal Transitorio",
    "organizational_unit": "Dirección de Asuntos Legales",
    "start_date": "2026-08-01",
    "legal_basis": "Art. 45 de la Ley 1234/56",
    "appointing_authority": "Director General",
    "salary_category": "Categoría B",
    "work_schedule": "Full-time"
  }'
```

## 4. Generar Borrador

```bash
curl -X POST http://localhost:8000/api/v1/drafts/generate \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-key-001" \
  -d '{
    "template_id": "{template_id}",
    "case_file_id": "{case_file_id}",
    "variables": {
      "numero_resolucion": "RES-2026-001",
      "fecha_resolucion": "2026-08-01"
    }
  }'
```

**Esperado**: 201 con DraftResponse (status=GENERADO, content generado por Ollama)

**Si Ollama no está disponible**: 503 con error OLLAMA_UNAVAILABLE, no se crea borrador

## 5. Editar Borrador

```bash
curl -X PATCH http://localhost:8000/api/v1/drafts/{draft_id}/content \
  -H "Content-Type: application/json" \
  -d '{
    "content": "# RESOLUCIÓN NÚMERO RES-2026-001\n\n...",
    "expected_version": 1
  }'
```

## 6. Enviar a Revisión

```bash
curl -X POST http://localhost:8000/api/v1/drafts/{draft_id}/transitions \
  -H "Content-Type: application/json" \
  -d '{
    "action": "SEND_TO_REVIEW",
    "expected_version": 2
  }'
```

## 7. Aprobar Borrador

```bash
curl -X POST http://localhost:8000/api/v1/drafts/{draft_id}/transitions \
  -H "Content-Type: application/json" \
  -d '{
    "action": "APPROVE",
    "observations": "Documento revisado y aprobado",
    "expected_version": 3
  }'
```

## 8. Regenerar Borrador

```bash
curl -X POST http://localhost:8000/api/v1/drafts/{draft_id}/regenerate \
  -H "Content-Type: application/json" \
  -d '{
    "observations": "Agregar mención a la normativa actualizada",
    "expected_version": 3
  }'
```

**Esperado**: 201 con nuevo DraftResponse, borrador anterior pasa a SUPERSEDED

## 9. Verificar Historial

```bash
curl http://localhost:8000/api/v1/drafts/{draft_id}/history
```

## 10. Verificar Intentos de Generación

```bash
curl http://localhost:8000/api/v1/generation-attempts/{attempt_id}
```

## 11. Tests

```bash
# Unitarios
docker compose exec api pytest tests/unit/ -v

# Integración
docker compose exec api pytest tests/integration/ -v

# Contractuales
docker compose exec api pytest tests/contract/ -v

# Cobertura
docker compose exec api pytest --cov=legal_ai --cov-report=term-missing

# Regresión (todos los tests)
docker compose exec api pytest
```

## 12. Validación de Backward Compatibility

```bash
# Verificar que endpoints existentes funcionan
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/api/v1/employees
curl http://localhost:8000/api/v1/case-files

# Verificar que los 245 tests existentes pasan
docker compose exec api pytest --tb=short
```

## 13. Validación de Errores

```bash
# Plantilla inexistente
curl http://localhost:8000/api/v1/templates/00000000-0000-0000-0000-000000000000
# Esperado: 404 DOCUMENT_TEMPLATE_NOT_FOUND

# Borrador inexistente
curl http://localhost:8000/api/v1/drafts/00000000-0000-0000-0000-000000000000
# Esperado: 404 DRAFT_NOT_FOUND

# Transición inválida
curl -X POST http://localhost:8000/api/v1/drafts/{draft_id}/transitions \
  -d '{"action": "APPROVE", "expected_version": 1}'
# Esperado: 409 INVALID_DRAFT_TRANSITION (si el borrador no está en EN_REVISION)
```
