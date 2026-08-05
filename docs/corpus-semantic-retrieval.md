# Corpus ingestion and semantic retrieval (005)

El incremento implementa lectores `.txt`, `.json` y `.html`, normalizaciÃ³n
versionada, chunking jurÃ­dico, persistencia PostgreSQL/pgvector, ingesta
dry-run/execute, reindexaciÃ³n, bÃºsqueda exacta y health/readiness.

La bÃºsqueda exige tipo, subtipo y jurisdicciÃ³n y consulta `REVIEWED` por defecto.
La auditorÃ­a `semantic_search_runs` se persiste antes de responder; si no puede
escribirse, la API devuelve 503 sin resultados parciales. No se implementa RAG
generativo, BM25, re-ranking, HNSW por defecto, MCP, OCR, scraping, Google Drive,
PDF ni frontend.

MÃ©tricas de evaluaciÃ³n: Precision@3/5, Recall@3/5, MRR, utilidad jurÃ­dica humana
1â€“5, relevancia legal y latencias p50/p95/mÃ¡xima. Los resultados G3 son
informativos y no inventan umbrales.
