# Contrato de integración IMI LEG ↔ Legal AI

Este documento fija el límite entre el BFF de IMI LEG y el backend legal. Legal
AI es la fuente de verdad de documentos, versiones, revisión, finalización y
exportaciones. El navegador no debe llamar directamente a FastAPI.

## Flujo canónico

```text
IMI LEG autenticado
  → Route Handler/BFF
  → FastAPI privada
  → PostgreSQL/pgvector + Ollama
```

El BFF obtiene los tipos desde `/openapi.json`, conserva las claves de
idempotencia en `sessionStorage` y construye el actor desde la sesión. No debe
reenviar un actor elegido por el navegador.

## Documentos

- `POST /api/v1/drafts` crea un documento manual estructurado.
- `GET /api/v1/drafts/{draft_id}/document` devuelve el documento actual y su
  versión.
- `PATCH /api/v1/drafts/{draft_id}/document` guarda cambios con
  `expected_version`; un conflicto `409` nunca se resuelve sobrescribiendo en
  silencio.
- `POST /api/v1/rag/drafts/generate/stream` genera el mismo documento
  estructurado mediante IA. El endpoint JSON
  `/api/v1/rag/drafts/generate` permanece disponible para compatibilidad.
- `GET /api/v1/drafts` lista borradores globalmente con paginación y filtros de
  texto, tipo y expediente.

Los tipos `disposicion` y `decreto` se derivan de la plantilla. El RAG deriva
el subtipo del expediente, usa jurisdicción `corrientes` y restringe la
recuperación a documentos `REVIEWED`, chunks `ACTIVE` y `INDEX_90`.

Cada edición crea una fila en `draft_document_versions`. La salida inicial de
IA se guarda como `AI_GENERATED`; la redacción manual como `MANUAL`; y cada
autoguardado humano como `HUMAN_EDIT`. Los borradores de texto antiguos se
pueden leer mediante el adaptador de compatibilidad, pero no se convierten
silenciosamente en una versión histórica.

## Revisión y finalización

La generación deja el borrador en `generado`. No abre una revisión. La UI debe
crear la revisión únicamente cuando la persona elige “Iniciar revisión”; esa
operación fotografía la versión actual. Mientras la revisión está `OPEN` o
`SUBMITTED`, el autoguardado responde `409`. “Solicitar cambios” libera la
edición y la siguiente revisión crea una fotografía nueva.

`POST /api/v1/drafts/{draft_id}/finalize` requiere:

```json
{
  "expected_version": 4,
  "finalized_by": "actor-de-la-sesion",
  "official_number": 123,
  "issued_on": "2026-08-26",
  "finalization_notes": "Opcional"
}
```

El número se reserva en PostgreSQL con unicidad transaccional por
`document_type + number + year`; el borrador conserva además esos metadatos
para lectura rápida. El snapshot final se construye desde la fotografía
estructurada revisada. PDF y DOCX se solicitan después y nunca se generan en
el navegador.

## SSE de generación

La respuesta es `text/event-stream` y emite únicamente:

- `started`: incluye `request_id`.
- `progress`: fases `queued`, `retrieving`, `generating` y `validating`.
- `complete`: incluye el documento estructurado validado, sus citas y el
  `rag_run_id`.
- `error`: incluye código sanitizado, mensaje, `request_id` y `retryable`.
- `cancelled`: confirma cancelación sin crear un draft.

Hay un heartbeat cada 15 segundos. No se envía texto parcial: el documento
aparece únicamente después de validar esquema y citas. Desde la reserva del
run, todos los eventos incluyen `rag_run_id`. Para cancelar se usa
`DELETE /api/v1/rag/runs/{run_id}`; la cancelación es cooperativa y deja el
intento en estado terminal. Un reinicio cierra los runs no terminales con
`RAG_GENERATION_INTERRUPTED`; sus claves se pueden reintentar de forma segura.

## Errores y compatibilidad

El backend conserva su envelope JSON con `request_id`; el BFF lo normaliza a
`{code, message, requestId, details, retryable}`. Debe tratar explícitamente
`409`, `422`, `503` y `504`. `409` representa conflicto de versión,
idempotencia, bloqueo de revisión o numeración duplicada; no es permiso para
perder cambios locales.

Las variables del BFF son server-only: `LEGAL_AI_BASE_URL`,
`LEGAL_AI_SERVICE_TOKEN` y sus timeouts. FastAPI permanece detrás de red
privada o túnel; no se expone públicamente. Cuando `LEGAL_AI_SERVICE_TOKEN`
está configurado en la API, el BFF debe enviarlo como `Authorization: Bearer`
en cada llamada `/api/v1/*`; el navegador nunca lo recibe.

La operación histórica del benchmark se documenta con precisión: Orca fue
utilizado para aislamiento/orquestación de pods y worktrees; OpenCode se
ejecutó directamente debido al fallo de permisos del launcher.
