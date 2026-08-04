# Investigación técnica — 004-document-review-and-export

**Fecha:** 2026-08-03
**Estado:** A10 integrado; planificación cerrada
**Fuentes funcionales:** `spec.md`, `checklists/requirements.md`, los artefactos
de 003 y la constitución/principios del repositorio.

## 1. Evidencia del repositorio

La implementación actual es un backend Python 3.12 organizado como una
arquitectura hexagonal ligera:

- FastAPI y Pydantic v2 en `apps/api/src/legal_ai/api` y `schemas`.
- Servicios de aplicación en `application/`.
- Modelos de dominio en `domain/`.
- Puertos en `ports/` y adaptadores SQLAlchemy async en
  `adapters/database/`.
- `UnitOfWork` abre una `AsyncSession`, concentra los repositorios y hace
  `commit`/`rollback` explícitos.
- Alembic usa revisiones numéricas (`001`, `002`, `003`) y PostgreSQL 16 con
  pgvector se ejecuta desde `compose.yaml`.
- Las rutas de 003 instancian `UnitOfWork` por solicitud y registran sus
  routers en `api/router.py`.
- Los tests se separan en `unit`, `integration` y `contract`, con pytest-
  asyncio, cobertura mínima de 85 %, Ruff y mypy estricto.

El lock actual contiene FastAPI, SQLAlchemy, asyncpg, Alembic, httpx y las
herramientas de test, pero no contiene `python-docx`, WeasyPrint, un renderer
headless de PDF ni una librería de sanitización HTML. La propuesta de este
plan agrega solo los adaptadores de rendering necesarios y mantiene las
validaciones de HTML y MIME basadas en una allowlist y la biblioteca estándar.

## 2. Hallazgos de compatibilidad con 003

### Estado del borrador

El código existente conserva los nombres de enum en español
(`DraftStatus.APROBADO`, valor serializado `aprobado`), mientras que la
especificación normativa usa `APPROVED` como nombre conceptual. 004 no agrega
un estado `FINALIZED` ni cambia valores persistidos. El servicio de
finalización usará el miembro/valor aprobado existente; si se necesita un
nombre inglés en el código público, se añadirá únicamente un alias compatible
que no cree un valor nuevo ni altere la máquina de estados.

### Envelope de errores

004 reutiliza o extiende el serializer público existente de 003 y no crea un
serializer público separado. El contrato exacto conserva el objeto anidado
`error` con `code`, `message`, `details`, `request_id` y `timestamp`:

```json
{
  "error": {
    "code": "EXPORT_FILE_CORRUPTED",
    "message": "The exported file failed integrity validation.",
    "details": {},
    "request_id": "...",
    "timestamp": "2026-08-03T21:00:00Z"
  }
}
```

`timestamp` es obligatorio, generado por el servidor en UTC, RFC 3339 y con
sufijo `Z`. Los tests contractuales fijan ese envelope y prueban no regresión
de 003; mensajes y detalles permanecen sanitizados.

### Límites binarios

Las validaciones operan sobre bytes: contenido editable y `final_snapshot`
2 MiB (2.097.152 bytes), preview HTML 5 MiB (5.242.880 bytes), DOCX persistido
20 MiB (20.971.520 bytes), PDF persistido 30 MiB (31.457.280 bytes) y DOCX
descomprimido 50 MiB (52.428.800 bytes). Los tests cubren el límite exacto,
el límite + 1 byte y contenido UTF-8 multibyte. Los artefactos documentales de
003 conservan su límite histórico de 100 KiB; 004 eleva únicamente el límite
efectivo de runtime a 2 MiB (2.097.152 bytes) mediante la tarea de compatibilidad.

### Revisión existente

No se encontraron clases, tablas, repositorios ni rutas de revisión en el
árbol actual. Por tanto, `document_reviews`, `review_comments`,
`review_events`, sus servicios y endpoints son nuevos en 004. Se reutilizan
la sesión de base de datos, los patrones de optimistic locking, paginación y
el middleware de `request_id` de los incrementos anteriores.

## 3. Decisiones de rendering

### DOCX: `python-docx`

**Decisión:** añadir `python-docx` como adaptador DOCX detrás de
`DocxRenderer`; fijar la versión elegida en el lock de dependencias y validar
la versión en el arranque/test de renderer.

La documentación oficial muestra que la biblioteca permite configurar
secciones, orientación y márgenes, estilos, encabezados/pies y guardar el
documento a una ruta o stream:

- [Working with Sections](https://python-docx.readthedocs.io/en/latest/user/sections.html)
- [Working with Documents](https://python-docx.readthedocs.io/en/latest/user/documents.html)
- [Working with Headers and Footers](https://python-docx.readthedocs.io/en/latest/user/hdrftr.html)

El adaptador escribirá a un temporal provisto por storage, configurará el
layout institucional y no conservará metadatos personales innecesarios. La
validación ZIP posterior no confía en que la biblioteca haya producido un
archivo correcto.

### PDF: WeasyPrint como primer adaptador headless

**Decisión:** añadir WeasyPrint como implementación inicial de `PdfRenderer`.
Recibe exclusivamente el HTML canónico producido por
`CanonicalHtmlRenderer`; no lee el DOCX y no invoca Ollama, red, RAG ni
servicios externos.

La documentación oficial describe la conversión HTML/CSS a PDF y permite
inyectar un `url_fetcher`; el adaptador usará uno que rechace toda URL remota
o archivo externo. También documenta que el runtime Linux requiere Pango y
dependencias nativas, por lo que el Dockerfile deberá instalarlas y el health
check deberá reportar disponibilidad del renderer.

- [WeasyPrint API reference](https://doc.courtbouillon.org/weasyprint/stable/api_reference.html)
- [WeasyPrint first steps and platform dependencies](https://doc.courtbouillon.org/weasyprint/v68.0/first_steps.html)
- [WeasyPrint security note for untrusted HTML/CSS](https://doc.courtbouillon.org/weasyprint/v53.4/first_steps.html)

El protocolo permite reemplazar WeasyPrint por otro renderer sin tocar
servicios, storage o endpoints. En Windows se soportan los mismos contratos y
test doubles; la integración nativa se ejecuta en el contenedor Linux o WSL,
porque las dependencias GTK/Pango de WeasyPrint no forman parte del runtime
Windows base del repositorio.

### HTML y sanitización

No se agrega `bleach`, `nh3` ni un parser HTML de terceros. El renderer
canónico no acepta HTML arbitrario: construye un documento a partir de un
snapshot estructurado, escapa todo texto con la biblioteca estándar y solo
emite etiquetas de una allowlist fija. Así se cumplen scripts/iframes/URLs
remotas bloqueados sin sumar una dependencia que duplicaría el parser. Si una
futura especificación permite markup editable, deberá introducir un puerto de
sanitización independiente y una revisión de seguridad.

### MIME e integridad

No se agrega `python-magic`: el MIME admitido se deriva de la combinación
formato/extensión y se verifica con la firma y estructura del archivo. DOCX se
valida como ZIP OOXML y PDF por encabezado/EOF. SHA-256 se calcula en streaming
con `hashlib` al crear y antes de descargar. Esta combinación evita confiar en
un MIME enviado por el cliente o en una detección dependiente de librerías
nativas.

## 4. Decisiones de ejecución

- La respuesta inicial de crear/reintentar/regenerar es `202` después de Tx1.
  Tx1 inserta PENDING y confirma en la misma transacción las transiciones a
  `GENERATING`/`PROCESSING`; no existe una transacción intermedia. Se programa
  una `BackgroundTasks` local del proceso web para ejecutar el pipeline fuera
  de PostgreSQL. No es una cola durable, no agrega Redis ni scheduler y se
  puede invocar directamente en tests.
- Tras el `202`, un fallo de renderer/validación/timeout se persiste como
  `FAILED` en export y attempt y se consulta por metadata/attempts; no se
  transforma en una respuesta HTTP tardía. Los 500/504/503 síncronos solo
  aplican antes de aceptar/programar el recurso.
- La asignación de versión y la comprobación de una generación activa se
  serializan tomando primero el lock corto del draft y aplicando índices
  únicos parciales como segunda barrera.
- `review_events` también registra finalización, exportación, integridad y
  reconciliación. No se crea una tabla de jobs ni una tabla de run IDs: la
  auditoría de la corrida guarda el hash de filtros y el resumen JSON para
  hacer idempotente `run_id`.

## 5. Decisiones operativas

- `EXPORT_STORAGE_ROOT` apunta al volumen privado de la API. El layout es
  relativo y solo usa UUIDs, formato y `export_version`; el `draft_version`
  identifica el contenido fuente, pero no el contador del artefacto.
- Docker crea el directorio y el volumen con el usuario no root `appuser`.
  Los permisos 0700/0600 se aplican cuando el sistema operativo los soporta;
  las pruebas Windows verifican el rechazo de traversal y symlinks aunque el
  sistema de archivos no exponga bits POSIX.
- El comando administrativo se publica como entry point Python
  `document-exports`, con el subcomando `reconcile`; usa `argparse` y JSON de
  stdout. `--execute` es obligatorio para borrar.
- Los límites, timeouts y ventanas de retención se cargan desde una sección
  tipada `ExportConfig`; los tests inyectan valores pequeños y un root
  temporal.

### Benchmarks informativos A8

Se recomienda un runner stdlib separado de pytest para evitar agregar
`pytest-benchmark` y para mantener los benchmarks fuera del CI estándar. El
runner usa 10 warm-up, 50 iteraciones secuenciales y p95 por rango cercano
`ceil(0.95 * N)` en el entorno Docker Linux de referencia. El dataset
`004-benchmark-v1` fija los casos de revisión, preview, aceptación `202`,
descarga y reconcile dry-run; cada resultado conserva dataset/hash, commit,
lockfile, entorno, muestras, p95 y umbral.

Los umbrales son informativos: 300 ms para revisión, 2.000 ms para preview de
100 KiB, 500 ms hasta aceptar `202`, 1.500 ms para validar/consumir un archivo
de 1 MiB (1.048.576 bytes) y 3.000 ms para reconcile dry-run. La aceptación usa un fake después
de Tx1 y no mide la generación DOCX/PDF. Una superación del umbral o una
regresión superior al 10% del baseline genera alerta estructurada, pero no
falla el comando ni el CI estándar.

### Aislamiento y cancelación de renderers A9

La generación DOCX/PDF se ejecuta en un proceso hijo independiente por
operación, iniciado con `multiprocessing.get_context("spawn")`. El límite de
30 s para DOCX y 60 s para PDF se aplica al hijo, que recibe únicamente datos
serializables y una ruta temporal segura. No se pasan sesiones DB, objetos ORM,
request context ni rutas internas expuestas.

Cuando vence el timeout, el ejecutor solicita terminación, espera una gracia
breve, fuerza `kill` si el hijo sigue activo, ejecuta `join`, elimina los
temporales y registra `GENERATION_TIMEOUT`. El hijo no se reutiliza, no se deja
un proceso zombi, no se mantiene una transacción DB abierta y ningún artefacto
producido después del deadline puede publicarse. Los puertos de renderer y los
test doubles permanecen reemplazables. La cancelación cooperativa sola no se
considera suficiente para librerías bloqueantes como WeasyPrint o
`python-docx`.

### Rechazo de Range en descarga A10

004 no implementa descargas parciales. Si la solicitud incluye `Range`, la
ruta responde antes de abrir el archivo con `416 Range Not Satisfiable`, código
estable `RANGE_NOT_SUPPORTED`, envelope JSON uniforme con `request_id`,
`timestamp` y
`Accept-Ranges: none`. No inicia streaming, no lee el archivo completo y no
devuelve `Content-Range` para un recurso parcial inexistente. Esta semántica
evita que clientes o proxies interpreten ambiguamente un `200` completo como
respuesta a una solicitud parcial.

## 6. Alternativas rechazadas

| Alternativa | Motivo de rechazo |
|---|---|
| LibreOffice o DOCX→PDF | contradice el pipeline PDF decidido y agrega un binario no necesario |
| Playwright/Chromium como primera implementación | mayor imagen y mantenimiento; no se necesita JavaScript para el HTML canónico |
| Redis/Celery/cola durable | fuera de alcance; 004 exige dos transacciones cortas y sin scheduler/colas |
| S3/Blob/CDN | almacenamiento cloud fuera de alcance; el volumen local es la fuente de artefactos del MVP |
| Guardar HTML | HTML es preview/intermedio efímero, no un `DocumentExport` |
| Persistir solo la ruta o solo el hash | no permite regenerar desde el snapshot ni auditar el artefacto; se conservan metadatos DB y hash |
| Cambiar el enum de drafts a una nueva máquina | rompería 003; finalización es metadato write-once con estado aprobado |

## 7. Resultado de la investigación

A1–A10 y la compatibilidad del límite heredado de 003 están integrados en los
artefactos del incremento. No quedan decisiones funcionales abiertas en esta
ronda. Las decisiones de implementación cerradas incluyen las verificaciones
normales de instalación, paquetes nativos, permisos del volumen, procesos
hijos `spawn` por operación, rechazo temprano de Range y fakes deterministas.
