# Runbook: corpus reindex

`corpus reindex` es dry-run por defecto. El modo `--execute` crea una nueva
generaciÃ³n STAGED, procesa batches fuera de la transacciÃ³n y publica un swap
atÃ³mico solo cuando todos los vectores 1024 son vÃ¡lidos.

```powershell
corpus reindex --document-id <UUID>
corpus reindex --document-id <UUID> --execute --run-id <opaque-id>
corpus reindex --document-id <UUID> --execute --resume --run-id <opaque-id>
```

Un fallo conserva la generaciÃ³n activa anterior. Cambiar modelo, dimensiÃ³n,
normalizaciÃ³n o chunking requiere reindexaciÃ³n completa. No borrar generaciones
activas manualmente; usar el swap del servicio.
