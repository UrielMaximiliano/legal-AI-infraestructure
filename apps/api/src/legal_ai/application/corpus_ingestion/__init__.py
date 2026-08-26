"""Pipeline de ingesta de corpus 005.

API pública estable: :class:`CorpusIngestionService`,
:class:`CorpusIngestionConfiguration` y el alias histórico
``CorpusIngestion``. La implementación vive en submódulos enfocados:

- ``configuration``: configuración declarativa y validación.
- ``preparation``: normalización + metadatos + chunking (sin DB).
- ``dry_run``: análisis local, deduplicación y reporte sin UoW.
- ``staging``: persistencia staged de documentos/chunks/batches.
- ``embedding_batches``: transiciones y persistencia de batches.
- ``finalization``: activación de generaciones y cierre del run.
"""

from legal_ai.application.corpus_ingestion.configuration import (
    CorpusIngestionConfiguration,
)
from legal_ai.application.corpus_ingestion.service import CorpusIngestionService

CorpusIngestion = CorpusIngestionService

__all__ = [
    "CorpusIngestion",
    "CorpusIngestionConfiguration",
    "CorpusIngestionService",
]
