# Topología de datos de IMI LEG

## Decisión

IMI LEG tendrá dos bases nuevas y aisladas:

| Base | Responsabilidad | Vector | Fuente de verdad |
| --- | --- | --- | --- |
| `imi_leg_core` | Better Auth, empleados, expedientes, templates, documentos, revisiones, numeración y exportaciones | No | IMI LEG |
| `imi_disposiciones_rag` | Corpus oficial de disposiciones, versiones de fuentes, chunks, embeddings, retrieval y auditoría RAG | `halfvec(1024)` | Legal AI RAG |

La base `legal_ai` existente se conserva como legado para el RAG de decretos.
No se migra ni se mezcla con ninguna de las dos bases nuevas.

## Tercera forma normal

La parte transaccional evita dependencias transitivas y grupos repetidos:

- los catálogos (`document_types`, `case_types`, estados, roles, organismos,
  unidades y cargos) tienen tablas propias;
- las variables declaradas por una plantilla se almacenan una por fila en
  `imi.template_variables`, no como un array de la plantilla;
- los valores ingresados se relacionan con la versión de documento y la
  variable en `imi.document_variable_values`;
- los documentos, sus versiones, citas, revisiones, comentarios, intentos y
  exportaciones tienen relaciones separadas;
- la numeración oficial usa una secuencia por tipo y año, y una relación propia
  con restricción única por secuencia y número;
- el corpus separa identidad de fuente (`corpus_documents`), versión de
  contenido, asignación a conjuntos de evaluación y chunk vectorial;
- filtros de retrieval son columnas y claves de catálogo, no un JSON libre.

Los únicos JSONB son snapshots estructurados inmutables, valores de una
variable tipada, contenido de salida validado y resúmenes de auditoría. No se
usan para ocultar entidades o relaciones que la aplicación necesite consultar.

## Límite entre bases

PostgreSQL no puede imponer una FK entre `imi_leg_core` y
`imi_disposiciones_rag`. Por eso el límite usa IDs externos explícitos:
`core_operation_id`, `core_document_id`, `core_document_version_id` y
`rag_run_id`. El BFF/API debe propagar esos IDs y registrar el `request_id` en
ambos lados. La consistencia entre bases se verifica en la capa de servicio y
mediante auditoría, nunca con joins cross-database.

## Archivos de bootstrap

- Core: `infra/database/imi-core/init/001_schema.sql`
- RAG de disposiciones: `infra/database/imi-disposiciones-rag/init/001_schema.sql`
- Compose aislado: `compose.imi-leg.yaml`

El compose legado no se reemplaza. Para crear únicamente las bases nuevas en
un entorno vacío:

```powershell
docker compose -f compose.imi-leg.yaml up -d
docker compose -f compose.imi-leg.yaml ps
```

Conexiones locales por defecto:

```text
core:          postgresql://imi_leg_core:<secret>@127.0.0.1:55434/imi_leg_core
disposiciones: postgresql://imi_disposiciones_rag:<secret>@127.0.0.1:55435/imi_disposiciones_rag
legado:        postgresql://legal_ai:<secret>@127.0.0.1:5432/legal_ai
```

Los scripts de `/docker-entrypoint-initdb.d` solo se ejecutan al inicializar
un volumen vacío. No usar `docker compose down -v` sobre el servidor actual.
En un servidor con datos, se debe crear un proyecto/volúmenes nuevos y validar
los conteos antes de cargar corpus.

## Orden de integración

1. Levantar las dos bases nuevas y ejecutar la validación del contrato.
2. Ejecutar Better Auth sobre el schema `auth` de `imi_leg_core`.
3. Migrar los repositorios transaccionales de IMI LEG al core.
4. Configurar el adaptador de retrieval para leer únicamente
   `rag.eligible_disposition_chunks`.
5. Cargar y evaluar el corpus de disposiciones; no importar el corpus actual
   de decretos.
6. Recién después publicar el endpoint privado para que el frontend lo use.

El compose aislado levanta un segundo proceso `imi-leg-api` en
`127.0.0.1:8001`, con `LEGAL_AI_RUNTIME_PROFILE=imi_leg_06b`. El proceso legacy
conserva `127.0.0.1:8000`; ambos pueden coexistir sin compartir sesiones ni
repositorios. El endpoint público privado debe enrutar `/legal-ai` al puerto
8001 cuando se habilite IMI LEG.

## AWS y Ollama on-premise

En AWS se conserva el mismo límite lógico. La base core y la base vectorial de
disposiciones deben tener endpoints/credenciales separados. Ollama puede
seguir on-premise detrás de una red privada, VPN o túnel saliente; nunca debe
exponerse directamente a Internet. La API de generación solo debe acceder a
Ollama mediante el endpoint privado configurado y con timeout, autenticación y
logs sin prompts ni documentos.
