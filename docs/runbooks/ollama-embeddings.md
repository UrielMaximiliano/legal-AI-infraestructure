# Runbook: Ollama embeddings

La aplicaciÃ³n usa `qwen3-embedding:0.6b`, `vector(1024)` y `/api/embed`. Un
endpoint remoto debe ser HTTPS y requiere Bearer. HTTP solo es vÃ¡lido para
localhost, `127.0.0.1` o `host.docker.internal` documentado.

El probe G1-B se ejecuta desde Docker/local y no se cierra con localhost, fake
ni mocks. El reporte nunca contiene tokens, Authorization ni vectores completos.
Un 401/403 requiere revisar el token; un 404 en `/api/embed` indica que la ruta
Funnel/Nginx no expone el contrato y mantiene G1-B bloqueado.
