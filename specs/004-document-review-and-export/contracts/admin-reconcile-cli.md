# Contrato CLI — `document-exports reconcile`

## Invocación

```text
document-exports reconcile [--actor ACTOR] [--run-id UUID] [--execute]
  [--case-file-id UUID] [--draft-id UUID] [--format DOCX|PDF]
  [--incident-type TYPE] [--older-than DURATION_OR_UTC]
```

- `--actor` es obligatorio, se valida como identidad textual auditable
  (trim, 1–100 caracteres, letras Unicode, números, espacios, `.`, `-`, `_`,
  `@`). No autentica ni autoriza.
- Si no se proporciona `--run-id`, el comando genera un UUID y lo devuelve.
- `--execute` es la única habilitación de eliminación. Sin él el comando es
  dry-run y no borra archivos ni filas; sí registra una auditoría de la
  corrida.
- Los filtros se combinan con AND. `--incident-type` acepta
  `TEMPORARY_FILE`, `ORPHAN_FILE`, `FAILED_ATTEMPT`, `MISSING_FILE`,
  `CORRUPT_FILE` e `INCOMPLETE_DB`.
- `--older-than` acepta una duración ISO-8601 simple (`P24H`, `P7D`) o una
  fecha UTC RFC3339; el cálculo se hace contra `created_at`/detección UTC.

## Incidencias y acciones

| Incidencia | Detección | Acción posible |
|---|---|---|
| `TEMPORARY_FILE` | temporal aleatorio en root, edad ≥24 h | borrar solo con `--execute` |
| `ORPHAN_FILE` | archivo bajo layout sin fila DB; la primera detección persiste `ORPHAN_DETECTED` y se esperan ≥7 días desde su `created_at` | borrar solo con `--execute` |
| `FAILED_ATTEMPT` | attempt `FAILED` con edad ≥180 días | borrar metadata del attempt, nunca el export fallido |
| `MISSING_FILE` | export descargable sin archivo | registrar y omitir |
| `CORRUPT_FILE` | hash/MIME/estructura inconsistente | registrar y omitir; exige regeneración |
| `INCOMPLETE_DB` | estado DB pendiente de reconciliación o SUCCEEDED sin export válido | registrar y omitir |

Siempre se omiten:

- el último `GENERATED` válido de cualquier `(draft_id, format)`;
- el attempt con mayor `attempt_number` de cada `document_export`, para
  conservar la monotonía del contador aunque se eliminen fallos antiguos;
- cualquier archivo asociado a un export con attempt `PROCESSING` activo;
- registros sin archivo, archivos corruptos y metadata de
  `document_exports` fallidos;
- candidatos cuya resolución canónica/symlink check no sea segura.

## Salida JSON

```json
{
  "run_id": "uuid",
  "mode": "dry-run",
  "filters": {
    "case_file_id": null,
    "draft_id": null,
    "format": null,
    "incident_type": null,
    "older_than": "2026-07-27T00:00:00Z"
  },
  "candidates": 3,
  "deleted": 0,
  "omitted": 2,
  "conflicts": 1,
  "errors": 0,
  "items": [
    {
      "incident_type": "ORPHAN_FILE",
      "resource_type": "artifact",
      "resource_id": "fingerprint-or-uuid",
      "action": "would_delete",
      "reason": "no database record"
    }
  ]
}
```

La salida nunca incluye ruta absoluta, `storage_path`, nombre personal,
contenido, excepción ni stack trace. Los IDs de archivo sin fila se
representan mediante un fingerprint estable.

## Idempotencia y auditoría

- El servicio calcula `filters_hash` de los filtros normalizados, modo y
  actor.
- El primer uso de `run_id` persiste un evento `RECONCILIATION_RUN` con
  filtros, resultado y actor.
- El mismo `run_id` y el mismo hash devuelve exactamente el resumen guardado,
  sin repetir eliminaciones.
- El mismo `run_id` con filtros, actor o modo distintos devuelve
  `CLEANUP_CONFLICT` y código de salida 2.
- Cada candidato/audit action registra actor, timestamp UTC, recurso opaco,
  acción, resultado y razón. Los errores individuales no abortan toda la
  corrida, salvo error de conexión a base de datos.

## Códigos de salida

| Código | Significado |
|---:|---|
| 0 | corrida válida; puede incluir omisiones |
| 2 | argumentos inválidos o `CLEANUP_CONFLICT` |
| 3 | uno o más errores de filesystem/DB durante `--execute` |
| 4 | configuración/storage root no disponible |
