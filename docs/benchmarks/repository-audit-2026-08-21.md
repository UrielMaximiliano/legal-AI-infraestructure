# Auditoría y limpieza del repositorio — 2026-08-21

La auditoría se ejecutó con dos agentes Codex administrados por Orca, ambos en
modo estrictamente read-only. No tocaron el servidor, el corpus, los
embeddings, los resultados ni el código durante la inspección.

## Resultado

- Rama: `005-corpus-ingestion-and-semantic-retrieval`.
- HEAD: `2117c21`.
- No había cambios tracked antes de esta pasada; sí había tooling local sin
  versionar (`.deepsec`, `.opencode`, `.agents`, `.claude` y
  `skills-lock.json`).
- El contrato vigente de producción es 4B/`halfvec(2560)`. La evidencia G2
  histórica de 1024 no describe ese contrato y queda fuera de la autoridad del
  runtime.
- Este checkout está en la rama 005 y no contiene la implementación 006 ni los
  outputs operativos del benchmark final; por eso esta pasada deja el protocolo
  listo, pero no declara una corrida de generación como reproducida.
- Los resultados del benchmark 004, las evidencias G1-G4 y los lockfiles se
  conservaron.

## Limpieza realizada

Se eliminaron únicamente artefactos regenerables y sin proceso activo:

- `.deepsec/node_modules/` (~848 MB).
- `.opencode/node_modules/` (~53 MB).
- `.claude/` (directorio vacío/junction local).
- caches de Python, pytest, mypy y Ruff, `htmlcov`, `.coverage` y
  `tools/__pycache__` (~39 MB).

Se conservaron deliberadamente `.deepsec` (configuración, README y evidencia de
seguridad), `.opencode` (configuración), `.agents` (skill local),
`skills-lock.json`, `.env`, el entorno `.venv`, el código, tests, migraciones,
fixtures, prompts, PDFs y todos los resultados. Los dos `node_modules` quedan
ignorados en `.gitignore` y pueden reinstalarse con el gestor correspondiente.

## Riesgos abiertos antes del benchmark

1. Los artefactos de insumo y resultados de los 1.000 casos no están en este
   checkout; deben apuntar a una ruta externa versionada por manifiesto.
2. El proxy PDF automático no es una métrica jurídica; para decidir producción
   hace falta gold humano.
3. Los índices 2560 y 1024 deben seguir siendo bases separadas.
4. No debe presentarse la evidencia histórica G2/1024 como validación del
   índice operativo 4B/2560.
5. Antes del benchmark final hay que ejecutar desde la rama que contenga la
   implementación RAG vigente y registrar su commit en el manifiesto.

La guía operativa consolidada está en
[benchmark-protocol.md](benchmark-protocol.md). Antes de ejecutar una nueva
corrida, completar [run-manifest.example.yml](run-manifest.example.yml) y
pasar el checklist de cierre.
