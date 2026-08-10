# Runbook: Ollama embeddings

La aplicaciÃ³n usa `qwen3-embedding:4b-q4_K_M`, `halfvec(2560)` y `/api/embed`. Un
endpoint remoto debe ser HTTPS y requiere Bearer. HTTP solo es vÃ¡lido para
localhost, `127.0.0.1` o `host.docker.internal` documentado.

El probe G1-B se ejecuta desde Docker/local y no se cierra con localhost, fake
ni mocks. El reporte nunca contiene tokens, Authorization ni vectores completos.
Un 401/403 requiere revisar el token; un 404 en el perfil configurado indica que
la ruta Funnel/Nginx no lo expone y mantiene G1-B abierto.

El perfil nativo `/api/embed` acepta batches. El proxy externo documentado usa
`/api/embeddings`, procesado secuencialmente por prompt; se selecciona mediante
`OLLAMA_EMBEDDING_ENDPOINT` y no existe fallback implícito. El probe validado
desde Docker/local obtuvo HTTP 200, 2560 dimensiones, estabilidad y
compatibilidad documento/query sin registrar token ni vectores.

Para convivencia en GPU con `qwen3.6:35b`, la API fija
`OLLAMA_EMBEDDING_CONTEXT_LENGTH=2048` y envía
`options.num_ctx=2048` en cada llamada nativa a `/api/embed`. Esto desacopla el
contexto del embedding del `OLLAMA_CONTEXT_LENGTH=32768` global usado por el
modelo generativo y evita que el embedding reserve VRAM innecesaria. Cambiar
este valor requiere un benchmark explícito de calidad, latencia y residencia;
no existe ajuste automático ni fallback silencioso.
