# Benchmarks de generación jurídica

Esta carpeta documenta cómo ejecutar y evaluar las corridas de generación sobre
el holdout de 1.000 decretos. El objetivo es comparar la fidelidad del output
contra el PDF de referencia, manteniendo constantes los datos de entrada y
variando una configuración por vez.

## Fuentes de verdad

- **Entrada:** el mismo conjunto versionado de 1.000 prompts y sus PDFs de
  referencia. El PDF de holdout no se indexa ni se embebe.
- **Salida:** un `case-NNNN.json` por prompt, dentro de una carpeta de corrida.
- **Configuración:** un `config.yml` o `manifest.json` inmutable por corrida,
  con modelo, dimensiones, contexto Ollama, contexto RAG, `top_k`,
  `minimum_score`, seed, endpoint y versión de código.
- **Evaluación:** resultados generados por las herramientas de `tools/` y sus
  hashes. No se mezclan casos de corridas distintas.

La clave de unión es `case_number` más el nombre/hash del PDF de referencia.
Un archivo faltante, duplicado o con hash distinto invalida la comparación de
ese caso; nunca se convierte en un cero silencioso.

## Índices y modelos

El índice operativo de 4B usa `qwen3-embedding:4b-q4_K_M` y
`halfvec(2560)`. El perfil 0.6B usa una base e índice aislados con
`halfvec(1024)`. Los vectores de 1024 no se pueden consultar contra la tabla
operativa de 2560 ni mezclarse en una misma corrida.

## Evaluación en una frase

Primero se calcula una **pre-evaluación automática PDF-proxy** para filtrar
configuraciones. Solo una anotación humana de campos y hechos atómicos puede
producir Accuracy, Precision, Recall y F1 jurídicos aptos para decidir
producción.

El procedimiento reproducible y el criterio de decisión están en
[benchmark-protocol.md](benchmark-protocol.md).

## Evaluación consolidada del holdout

La evaluación vigente de las 19 corridas —18 configuraciones únicas— está en
[holdout-1000/README.md](holdout-1000/README.md). Conserva el catálogo de
parámetros, el manifiesto de los 1.000 prompts/PDFs, resultados CSV/JSON y la
metodología exacta. El reporte ejecutivo usa la métrica extremo a extremo:
outputs fallidos o ausentes puntúan cero.
