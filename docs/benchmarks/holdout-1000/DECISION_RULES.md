# Reglas de decisión

1. Excluir corridas parciales o con joins inválidos.
2. Priorizar Accuracy factual E2E; no usar el promedio condicional para rankear.
3. Tratar como equivalentes las candidatas cuyo IC95% pareado del delta incluya
   cero.
4. Entre candidatas equivalentes, preferir mayor Precision material y 100% de
   outputs válidos; latencia y VRAM solo desempatan.
5. No fijar producción hasta confirmar los ocho campos y TP/FP/FN con revisión
   humana.

Con la evidencia automática actual, C15 es la candidata por semejanza factual.
C05 es un control útil para una política más adversa a invenciones materiales,
porque tiene mayor Precision entre las corridas 100% exitosas, aunque menor
Accuracy factual. C19 representa el mejor punto del embedding 0.6B.
