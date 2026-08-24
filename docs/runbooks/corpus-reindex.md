# Runbook: corpus reindex

`corpus reindex` es dry-run por defecto. El modo `--execute` crea una nueva
generación STAGED, procesa batches fuera de la transacción y publica un swap
atómico solo cuando todos los vectores de `halfvec(2560)` son válidos. Este es
el índice operativo del modelo de embedding 4B.

```powershell
corpus reindex --document-id <UUID>
corpus reindex --document-id <UUID> --execute --run-id <opaque-id>
corpus reindex --document-id <UUID> --execute --resume --run-id <opaque-id>
```

Un fallo conserva la generación activa anterior. Cambiar modelo, dimensión,
normalización o chunking requiere reindexación completa. El perfil de embedding
0.6B usa una copia aislada `halfvec(1024)` y su propia base; nunca se debe
reutilizar ni mezclar con este índice operativo. No borrar generaciones activas
manualmente; usar el swap del servicio.
