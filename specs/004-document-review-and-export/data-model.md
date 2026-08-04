# Modelo de datos — 004-document-review-and-export

## Alcance

Este modelo extiende `document_drafts` de 003 y agrega la revisión humana,
los eventos append-only, los artefactos persistidos y sus intentos de
procesamiento. PostgreSQL sigue siendo la fuente de verdad. HTML no tiene
tabla ni archivo persistido.

## Enums de dominio

Los enums nuevos se implementan como `StrEnum` en
`apps/api/src/legal_ai/domain/enums.py` y se persisten como `VARCHAR` con
checks de allowlist, siguiendo 003.

| Enum | Valores |
|---|---|
| `ReviewStatus` | `OPEN`, `SUBMITTED`, `CHANGES_REQUESTED`, `APPROVED`, `CLOSED` |
| `CommentSeverity` | `INFO`, `SUGGESTION`, `WARNING`, `BLOCKING` |
| `CommentStatus` | `OPEN`, `RESOLVED`, `DISMISSED` |
| `ExportFormat` | `DOCX`, `PDF` |
| `ExportStatus` | `PENDING`, `GENERATING`, `GENERATED`, `FAILED`, `SUPERSEDED` |
| `ExportAttemptStatus` | `PENDING`, `PROCESSING`, `SUCCEEDED`, `FAILED` |

`DraftStatus` no recibe un estado nuevo. El gate de aprobación usa el miembro
`APROBADO` existente de 003 (el nombre conceptual de la especificación es
`APPROVED`).

## `DocumentDraft` extendido

Se mantienen todos los campos de 003 y se agregan:

| Campo | Tipo Python/SQL | Reglas |
|---|---|---|
| `finalized_by` | `str \| None` / `VARCHAR(100)` | Nulo antes de finalizar; actor textual validado, trim, 1–100 caracteres |
| `finalized_at` | `datetime \| None` / `TIMESTAMPTZ` | UTC; write-once |
| `finalization_notes` | `str \| None` / `TEXT` | Nulo o no vacío; máximo 2.000 caracteres |
| `final_snapshot` | `dict \| None` / `JSONB` | Nulo antes de finalizar; máximo 2 MiB (2.097.152 bytes) serializado, medido en bytes UTF-8 |
| `final_snapshot_sha256` | `str \| None` / `CHAR(64)` | SHA-256 del JSON canónico UTF-8 |

Invariantes:

1. `finalized_at`, `finalized_by`, `final_snapshot` y
   `final_snapshot_sha256` aparecen juntos; las notas pueden ser nulas.
2. `finalized_at IS NULL` implica que ningún campo de finalización está
   escrito. La actualización condicional incluye `finalized_at IS NULL` y
   `version = expected_version`.
3. `finalized_at IS NOT NULL` implica estado aprobado, revisión aprobada y
   cerrada, y bloqueo de edición, transición, rechazo, aprobación o
   regeneración del draft.
4. La finalización incrementa `document_drafts.version` exactamente una vez.
5. `final_snapshot` se serializa con `sort_keys=True` y separadores compactos
   antes de calcular el hash. No se vuelve a construir desde datos vivos.

En los contratos y servicios de 004, `draft_version` nombra el valor de
contenido respaldado por `document_drafts.version`; no existe una segunda
columna para esa versión. `expected_version` protege ese valor cuando la
operación muta el draft.

### Forma canónica de `final_snapshot`

```json
{
  "schema_version": 1,
  "draft_id": "uuid",
  "source_draft_version": 3,
  "finalized_version": 4,
  "source_content_sha256": "64-hex",
  "document": {
    "title": "string",
    "institutional_header": "string",
    "visto": ["string"],
    "considerando": ["string"],
    "por_ello": "string",
    "articles": [{"number": 1, "text": "string"}],
    "signatures": [{"label": "string", "name": "string?"}],
    "locale": "es-AR"
  },
  "source_text": "approved text"
}
```

El builder conserva el texto aprobado y solo estructura marcadores
reconocibles; nunca completa hechos, autoridades o artículos faltantes. Las
propiedades obligatorias de DOCX se validan antes de persistir un artefacto.

## `document_reviews`

```sql
document_reviews (
    id UUID PRIMARY KEY,
    draft_id UUID NOT NULL REFERENCES document_drafts(id),
    draft_version INTEGER NOT NULL,
    review_snapshot JSONB NOT NULL,
    review_snapshot_sha256 CHAR(64) NOT NULL,
    status VARCHAR(24) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    opened_by VARCHAR(100) NOT NULL,
    submitted_by VARCHAR(100),
    decided_by VARCHAR(100),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at TIMESTAMPTZ,
    decided_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_review_draft_version UNIQUE (draft_id, draft_version)
)
```

`review_snapshot` se construye al abrir la revisión desde la versión exacta del
draft y se serializa con JSON canónico (`sort_keys=True`, separadores compactos)
antes de calcular `review_snapshot_sha256`. Ambos campos son write-once. Los
anclajes y todas las transiciones de review se validan contra este snapshot;
una edición posterior del draft no lo modifica.

Los actores de revisión se almacenan en sus campos reales (`opened_by`,
`submitted_by`, `decided_by`, `author` y `actor`) como strings textuales
auditables de 1–100 caracteres, sin FK ni unicidad, porque 004 no implementa
autenticación. `finalized_by` y `exported_by` siguen las mismas reglas. Ningún
actor aparece en paths o `file_name`; `request_id` conserva únicamente
trazabilidad técnica. No se introduce un identificador alternativo de actor. No se usan para autorización
y la representación debe permitir una futura sustitución por
`authenticated_subject_id` sin romper el contrato actual. La revisión se
vincula a una versión concreta y no se reutiliza para otra.

`approve` persiste la decisión humana, `decided_at` y `closed_at` en la misma
transacción; el evento conserva que la revisión pasó por `APPROVED` y quedó
cerrada. Así el endpoint de finalización tiene un gate verificable aun cuando
no existe un endpoint público de cierre separado.

## `review_comments`

```sql
review_comments (
    id UUID PRIMARY KEY,
    review_id UUID NOT NULL REFERENCES document_reviews(id),
    parent_comment_id UUID REFERENCES review_comments(id),
    draft_version INTEGER NOT NULL,
    author VARCHAR(100) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'OPEN',
    body TEXT NOT NULL,
    anchor JSONB,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_by VARCHAR(100),
    resolved_at TIMESTAMPTZ
)
```

Reglas:

- `body` tiene entre 1 y 10.000 caracteres después de validar el request.
- `draft_version` debe ser igual a la versión de la revisión.
- `parent_comment_id`, si existe, pertenece a la misma revisión y no puede
  formar ciclos.
- `anchor` es nulo para comentarios generales. Para un anclaje contiene
  `draft_version`, `kind`, `section` o `start/end`, y un hash del texto
  anclado; los offsets deben estar dentro del snapshot de la revisión.
- El texto original, autor y anclaje nunca se sobrescriben. Solo cambian
  `status`, `version`, `resolved_by` y `resolved_at`.
- No existe endpoint DELETE ni borrado físico.

## `review_events`

Tabla append-only para revisión, finalización, exportación, integridad y
reconciliación:

```sql
review_events (
    id UUID PRIMARY KEY,
    review_id UUID REFERENCES document_reviews(id),
    draft_id UUID REFERENCES document_drafts(id),
    export_id UUID REFERENCES document_exports(id),
    attempt_id UUID REFERENCES export_attempts(id) ON DELETE SET NULL,
    resource_type VARCHAR(32) NOT NULL,
    resource_id VARCHAR(128),
    event_type VARCHAR(64) NOT NULL,
    actor VARCHAR(100),
    request_id VARCHAR(128),
    run_id UUID,
    draft_version INTEGER,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

La implementación de la migración crea las tablas referenciadas antes de
`review_events`; el evento nunca se actualiza ni elimina desde la aplicación.
`resource_id` es texto opaco para admitir UUIDs de recursos persistidos y el
fingerprint SHA-256 de un identificador relativo cuando el recurso huérfano no
tiene UUID; nunca contiene la ruta absoluta ni un nombre con PII.
`summary` solo contiene códigos, tamaños, hashes, estados y razones
minimizadas.
Los eventos originados por HTTP incluyen `request_id`; los eventos del comando
administrativo pueden dejarlo nulo y deben incluir `run_id` como identificador
de trazabilidad de la corrida.
Existe un índice único parcial sobre `run_id` para eventos
`RECONCILIATION_RUN` no nulos. Las carreras se resuelven leyendo el evento
ganador y comparando su hash de filtros antes de devolver replay o
`CLEANUP_CONFLICT`.

## `review_operation_requests`

Tabla de idempotencia para las mutaciones de review. La infraestructura de
generación de 003 no ofrece scope por operación/recurso ni replay de respuesta,
por lo que 004 mantiene esta tabla separada:

```sql
review_operation_requests (
    id UUID PRIMARY KEY,
    operation VARCHAR(64) NOT NULL,
    resource_id UUID NOT NULL,
    idempotency_key VARCHAR(100) NOT NULL,
    request_hash CHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    response_status INTEGER,
    response_payload JSONB,
    error_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    request_id VARCHAR(128) NOT NULL,
    CONSTRAINT uq_review_operation_request
      UNIQUE (operation, resource_id, idempotency_key)
)
```

`status` solo admite `PROCESSING`, `SUCCEEDED` y `FAILED`. El payload de
respuesta se limita a campos contractuales sanitizados y nunca contiene el
snapshot, el cuerpo completo del documento, paths internos ni excepciones. Una
solicitud dentro de la ventana de 24 horas usa hash y status para replay,
conflicto u operación activa. Una fila expirada se reutiliza bajo lock como una
nueva ventana; no se reproduce su respuesta anterior.

## `document_exports`

```sql
document_exports (
    id UUID PRIMARY KEY,
    draft_id UUID NOT NULL REFERENCES document_drafts(id),
    draft_version INTEGER NOT NULL,
    review_id UUID NOT NULL REFERENCES document_reviews(id),
    export_version INTEGER NOT NULL,
    parent_export_id UUID REFERENCES document_exports(id),
    format VARCHAR(8) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    storage_path VARCHAR(500),
    file_name VARCHAR(120) NOT NULL,
    content_sha256 CHAR(64),
    source_snapshot_sha256 CHAR(64) NOT NULL,
    renderer_name VARCHAR(100),
    renderer_version VARCHAR(100),
    exported_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    error_code VARCHAR(64),
    error_message TEXT,
    CONSTRAINT uq_export_draft_format_version
      UNIQUE (draft_id, format, export_version)
)
```

Invariantes:

- `format` solo es `DOCX` o `PDF`; `HTML` nunca crea esta fila.
- `export_version` empieza en 1 por combinación `draft_id + format` y la
  regeneración usa `max(export_version)+1` bajo lock del draft.
- `storage_path` solo se completa después del rename atómico y es siempre
  relativo a `EXPORT_STORAGE_ROOT`.
- `content_sha256` es obligatorio para `GENERATED` y `SUPERSEDED`.
- `GENERATED` y `SUPERSEDED` son descargables; `PENDING`, `GENERATING` y
  `FAILED` no lo son.
- Una fila `FAILED` se conserva indefinidamente como metadata. Un retry usa
  la misma fila y crea un nuevo `ExportAttempt`.
- `parent_export_id` solo se usa en regeneración; el origen no se modifica
  hasta el éxito de la nueva fila.

Índices y checks:

- índice por `(draft_id, format, status)`;
- índice por `parent_export_id`;
- índice estable para listados `(draft_id, created_at DESC, id DESC)`;
- índice único parcial `(draft_id, format)` donde `status IN
  ('PENDING','GENERATING')`;
- checks de formato, estado, versión positiva, nombre/path de límites y hash
  de 64 hexadecimales.

## `export_attempts`

```sql
export_attempts (
    id UUID PRIMARY KEY,
    export_id UUID NOT NULL REFERENCES document_exports(id),
    draft_id UUID NOT NULL REFERENCES document_drafts(id),
    format VARCHAR(8) NOT NULL,
    idempotency_key VARCHAR(100) NOT NULL,
    request_hash CHAR(64) NOT NULL,
    attempt_number INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_code VARCHAR(64),
    error_message TEXT,
    request_id VARCHAR(128) NOT NULL,
    exported_by VARCHAR(100) NOT NULL,
    CONSTRAINT uq_export_attempt_number UNIQUE (export_id, attempt_number)
)
```

Reglas:

- `idempotency_key` tiene 16–100 caracteres seguros; la validación de
  caracteres se hace antes de insertar y se refuerza con check ASCII para
 evitar separadores/path/control characters.

`PENDING` es el valor de inserción; Tx1 lo transforma a `GENERATING` en el
export y a `PROCESSING` en el attempt antes del commit. No existe una Tx
intermedia para marcar estados activos; Tx2 es la única transacción posterior
y marca éxito o fallo.
- El índice único parcial `(exported_by, idempotency_key)` con predicado
  `status IN ('PENDING','PROCESSING')` permite un único intento activo. Los
  `FAILED` coexisten y conservan el mismo key/hash.
- `attempt_number` es 1 para la creación y aumenta por cada retry del mismo
  `export_id`; una regeneración crea otro export y comienza en 1.
- `request_id` nunca participa en el hash idempotente.
- `error_message` solo contiene un mensaje sanitizado; no se guardan paths,
  stack traces, excepciones de librerías, secretos ni contenido documental.
- Los fallos se retienen al menos 180 días; el cleanup manual puede retirar
  intentos fallidos más antiguos cuando ninguna regla de auditoría los
  requiera.

Índices adicionales: `(draft_id, format, created_at DESC, id DESC)`,
`status`, y `(exported_by, idempotency_key, created_at DESC)`.

## Relaciones

```text
document_drafts 1 ──< document_reviews 1 ──< review_comments
review_operation_requests (scope operation + resource + key; no document FK)
document_reviews 1 ──< review_events
document_drafts 1 ──< document_exports 1 ──< export_attempts
document_exports 1 ──< document_exports (parent_export_id)
document_exports ──< review_events
```

La combinación `(draft_id, draft_version)` identifica la unidad revisable; la
combinación `(draft_id, format, export_version)` identifica un artefacto
inmutable.
La combinación `(exported_by, idempotency_key, request_hash)` identifica una
solicitud idempotente dentro de la ventana de 24 horas.

## Reglas de mutabilidad

| Recurso | Mutable | Inmutable |
|---|---|---|
| Draft no finalizado | contenido, estado y `document_drafts.version` según 003 | `context_snapshot` y `context_hash` |
| Draft finalizado | solo lecturas y preview | contenido, estado jurídico, metadata y snapshot final |
| Review | status/version mediante transición optimista | identidad de versión, timestamps de apertura y eventos |
| Comment | status/resolución | body, autor, anclaje, parent |
| ReviewEvent | ninguna | toda la fila |
| DocumentExport | status de pipeline y error; `GENERATED`→`SUPERSEDED` | contenido, `export_version`, formato, hash, snapshot fuente, path confirmado |
| ExportAttempt | estado de procesamiento y resultado | key, request_hash, actor, número y timestamps históricos |

## Migración y compatibilidad

La revisión Alembic será `004` y dependerá exactamente de `003`. Los campos
nuevos de `document_drafts` se agregan nulos, sin backfill y sin alterar filas
existentes. La creación respeta las dependencias de FK: altera drafts, crea
`document_exports` con la columna `review_id` y FK diferida, crea
`export_attempts`, crea `document_reviews`/`review_comments`, crea
`review_operation_requests`, añade la FK de `review_id`, crea `review_events`
(que referencia a todas las tablas) y luego índices/checks.
El downgrade quita primero esa FK diferida y revierte las tablas en orden
inverso; exige respaldo/mantenimiento porque elimina datos de 004.
