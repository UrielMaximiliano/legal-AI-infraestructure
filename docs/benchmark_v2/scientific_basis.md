# Base científica para Benchmark v2

## Alcance y reglas de interpretación

Este documento fija la base metodológica para evaluar generación con recuperación (RAG) y generación legal. Las métricas miden propiedades distintas: similitud con una referencia, relevancia, fidelidad al contexto, cobertura de claims, factualidad o calidad jurídica. Un valor alto en una dimensión no implica que la respuesta sea verdadera, jurídicamente correcta o segura. En particular, una respuesta puede ser muy similar a una referencia equivocada, o estar respaldada por un contexto que contiene una norma derogada.

La unidad estadística recomendada es el caso completo —misma pregunta, corpus/fecha de corte, contexto recuperado y referencia para todos los sistemas—. Se calculan primero los scores por caso y luego el promedio macro:

\[
  \bar s(M)=\frac{1}{n}\sum_{i=1}^{n}s_i(M).
\]

Los casos deben conservar `case_id`, jurisdicción, fecha de vigencia, fuente, versión del corpus, modelo evaluado, modelo evaluador, prompt, temperatura, tokens de entrada/salida y costo. En evaluaciones legales, el texto de autoridad debe ser recuperable por un identificador estable y una cita debe apuntar a un span verificable, no sólo a un documento amplio.

### Matriz de decisión

| Método | Qué mide | Datos necesarios | Uso de LLM | Costo dominante | Rol recomendado |
|---|---|---|---|---|---|
| BERTScore | Similaridad semántica candidato–referencia | Respuesta y una o más referencias | Encoder contextual, no juez generativo | Inferencia local del encoder | Señal secundaria de similitud |
| RAGAS | Faithfulness, answer relevance y context relevance sin gold answer | Pregunta, contexto y respuesta | Juez generativo + embeddings | Tokens de prompts y verificaciones | Diagnóstico rápido; calibrar con humanos |
| RAGChecker | Calidad y fallas de retriever/generator a nivel claim | Pregunta, chunks, respuesta y gold answer | Extractor y checker de entailment | Claims × referencias/chunks | Diagnóstico detallado con gold |
| ARES | Clasificación de relevancia/fidelidad/relevancia de respuesta | Corpus in-domain, ejemplos y validación humana | LLM para sintéticos; jueces finetuneados | Setup y anotación; inferencia barata | Ranking repetido de muchos sistemas |
| FActScore / SAFE | Porcentaje de hechos atómicos respaldados | Respuesta y fuente de conocimiento; SAFE agrega búsqueda | Extractor/verificador; SAFE usa agente + search | Verificación por claim y búsquedas | Factualidad; fuente debe ser autoritativa |
| Rúbrica legal | Corrección normativa, jurisdicción, citas, completitud y seguridad | Autoridad legal, gold claims y expertos | Puede asistir, no sustituir revisión | Anotación experta | Gate de calidad y liberación |

No se debe formar un promedio de estas métricas sin pre-registrar qué constructo representa cada una, sus pesos y cómo se trata una abstención. Para un benchmark científico, es preferible publicar el vector de métricas y un criterio de decisión separado.

## 1. BERTScore

**Fuente primaria:** [Zhang et al., “BERTScore: Evaluating Text Generation with BERT”, ICLR 2020 / arXiv:1904.09675](https://arxiv.org/abs/1904.09675).

### Definición y fórmula

Sea el candidato \(x=(x_1,\ldots,x_m)\), la referencia \(y=(y_1,\ldots,y_k)\), y sean \(h_i^x,h_j^y\) sus embeddings contextuales. La similitud token a token es:

\[
  S_{ij}=\cos(h_i^x,h_j^y).
\]

La versión sin ponderación IDF usa el mejor match de cada token:

\[
  P=\frac{1}{m}\sum_{i=1}^{m}\max_{j\leq k}S_{ij},\qquad
  R=\frac{1}{k}\sum_{j=1}^{k}\max_{i\leq m}S_{ij},
\]

\[
  F_1=\frac{2PR}{P+R}.
\]

Con IDF se reemplaza cada promedio por uno ponderado, usando, por ejemplo, \(w(t)=\log(N/df(t))\). Hay que informar encoder, capa, idioma, normalización/rescaling e IDF; cambiar cualquiera de esos elementos cambia la escala y puede cambiar el ranking.

### Aplicabilidad, límites y costo

- Es apropiado cuando existe una referencia razonable y se quiere tolerar paráfrasis, variación léxica y orden distinto. El paper estudió principalmente traducción e image captioning; la transferencia a español jurídico no es una garantía.
- Es una similitud, no una prueba de verdad ni de entailment. El paper muestra que puede asignar score alto a errores fácticos, como cambiar un día o una entidad. En derecho puede no detectar una negación, un número, una excepción, una fecha de vigencia o una autoridad incorrecta.
- El encoder no usa una llamada a un LLM generativo. La inferencia contextual es aproximadamente lineal en tokens para el encoder, más una matriz de similitudes \(O(mk)\) por par de textos. Con encoders BERT/RoBERTa estándar, la longitud máxima práctica es 512 sub-tokens; textos legales largos deben segmentarse con una regla fija y agregarse por caso, no truncarse silenciosamente.
- El costo monetario de API es cero si se ejecuta localmente; el costo real es GPU/CPU, memoria del modelo y tiempo. Registrar esos recursos y el número de ventanas para comparar configuraciones.

### Uso en Benchmark v2

Reportar \(P,R,F_1\) por caso, además de la referencia y la configuración del encoder. Usar BERTScore como evidencia de similitud superficial/semántica, nunca como sustituto de factualidad, cobertura de claims o validez jurídica.

## 2. RAGAS

**Fuente primaria:** [Es et al., “RAGAS: Automated Evaluation of Retrieval Augmented Generation”, EACL 2024](https://aclanthology.org/2024.eacl-demo.16/).

RAGAS fue propuesto como evaluación *reference-free* de un pipeline con pregunta \(q\), contexto recuperado \(c(q)\) y respuesta \(a_s(q)\). En el experimento original, los prompts usaron `gpt-3.5-turbo-16k` y answer relevance usó embeddings `text-embedding-ada-002`; esos nombres son parte del protocolo original, no una recomendación de proveedor actual.

### Fórmulas

**Faithfulness.** El juez descompone la respuesta en statements \(S(a_s(q))\) y decide para cada uno si está soportado por el contexto. Si \(V\subseteq S\) es el conjunto marcado como soportado:

\[
  F=\frac{|V|}{|S|}.
\]

Esto mide consistencia con el contexto, no verdad externa: si el contexto está equivocado, RAGAS puede otorgar un score alto.

**Answer relevance.** El juez genera \(n\) preguntas plausibles \(q_1,\ldots,q_n\) a partir de la respuesta, se embeben \(q\) y cada \(q_i\), y se promedian las similitudes coseno:

\[
  AR=\frac{1}{n}\sum_{i=1}^{n}
  \cos(e(q),e(q_i)).
\]

Answer relevance penaliza incompletitud y redundancia según las preguntas generadas, pero el paper aclara que no juzga factualidad.

**Context relevance.** El juez extrae \(S_{ext}\), las oraciones del contexto que considera cruciales para responder. Si \(N_{sent}(c)\) es el número de oraciones del contexto:

\[
  CR=\frac{|S_{ext}|}{N_{sent}(c)}.
\]

La métrica confunde parcialmente foco, segmentación de oraciones y cobertura; un contexto muy corto puede aumentar o disminuir el valor sin cambiar la evidencia útil.

### Aplicabilidad, límites y costo

- Útil cuando no hay respuesta gold, para iteración rápida del retriever y del prompt. No reemplaza la evaluación con gold en un dominio regulado.
- El juez puede fallar en descomposición, soporte, negación, números y lenguaje jurídico; el resultado depende del modelo, prompt, temperatura y formato de salida. El propio paper observó que context relevance era la dimensión más difícil, en especial con contextos largos.
- Es sensible a sesgos del juez, longitud y estilo. Faithfulness no distingue una autoridad correcta de una autoridad desactualizada, ni “cita presente” de “cita que realmente sostiene la proposición”.
- El costo crece linealmente con casos, oraciones y claims: extracción de statements, verificación, generación de preguntas y embeddings. Si el número de preguntas por respuesta es \(n\), una aproximación operacional es \(C\approx N(c_{extract}+|S|c_{verify}+n c_{question})+C_{embed}\), donde cada \(c\) incluye tokens de entrada/salida del proveedor. Fijar \(n\), prompts y reintentos; no reportar scores de ejecuciones con presupuestos diferentes como si fueran comparables.
- Si se usa un judge local, el costo API baja pero persisten costo de cómputo y sesgo de modelo. Si se cambia la implementación moderna de RAGAS, fijar versión y listar métricas exactas: las versiones posteriores agregan/renombran métricas.

### Uso en Benchmark v2

Reportar `faithfulness`, `answer_relevance` y `context_relevance` por caso, incluyendo el judge y prompts. Utilizar RAGAS como señal de diagnóstico; validar un subconjunto estratificado con revisión humana y verificar de forma independiente citas, números, jurisdicción y vigencia.

## 3. RAGChecker

**Fuente primaria:** [Ru et al., “RAGChecker: A Fine-grained Framework for Diagnosing Retrieval-Augmented Generation”, NeurIPS 2024 Datasets and Benchmarks / arXiv:2408.08067](https://arxiv.org/abs/2408.08067).

RAGChecker recibe \(q\), chunks recuperados \(\{chunk_j\}_{j=1}^{k}\), respuesta \(m\) y respuesta gold \(gt\). Un extractor transforma textos en claims y un checker determina si un claim es entailado por una referencia. Denotamos por \(c_i^m\) y \(c_i^{gt}\) los claims de respuesta y gold. Un chunk es relevante si contiene al menos un claim gold entailado; los conjuntos de chunks relevantes e irrelevantes son \(R\) e \(I\).

En las fórmulas, \(c\in X\) abrevia “el claim \(c\) es entailado por el texto o conjunto de chunks \(X\)”; no significa que un claim y un chunk sean el mismo tipo de objeto.

### Fórmulas de overall, retriever y generator

\[
  P_{claim}=\frac{|\{c_i^m:c_i^m\in gt\}|}{|\{c_i^m\}|},\qquad
  R_{claim}=\frac{|\{c_i^{gt}:c_i^{gt}\in m\}|}{|\{c_i^{gt}\}|},
\]

\[
  F1_{claim}=\frac{2P_{claim}R_{claim}}{P_{claim}+R_{claim}}.
\]

Para el retriever:

\[
  ClaimRecall=\frac{|\{c_i^{gt}:c_i^{gt}\in\{chunk_j\}\}|}{|\{c_i^{gt}\}|},
  \qquad ContextPrecision=\frac{|R|}{k}.
\]

Para el generator, con \(C_m=\{c_i^m\}\):

\[
  Faithfulness=\frac{|\{c\in C_m:c\in\{chunk_j\}\}|}{|C_m|},
\]

\[
  NS_R=\frac{|\{c\in C_m:c\notin gt\land c\in R\}|}{|C_m|},\quad
  NS_I=\frac{|\{c\in C_m:c\notin gt\land c\in I\}|}{|C_m|},
\]

\[
  Hallucination=\frac{|\{c\in C_m:c\notin gt\land c\notin\{chunk_j\}\}|}{|C_m|},
  \quad SelfKnowledge=\frac{|\{c\in C_m:c\in gt\land c\notin\{chunk_j\}\}|}{|C_m|},
\]

\[
  ContextUtilization=
  \frac{|\{c_i^{gt}:c_i^{gt}\in\{chunk_j\}\land c_i^{gt}\in m\}|}
       {|\{c_i^{gt}:c_i^{gt}\in\{chunk_j\}\}|}.
\]

Valores altos son deseables para precisión, recall, F1, claim recall, context precision, faithfulness y context utilization; valores bajos son deseables para noise sensitivity, hallucination y self-knowledge cuando el contrato exige depender sólo del contexto.

### Aplicabilidad, límites y costo

- Es apropiado para separar error de recuperación de error de generación y para respuestas largas; requiere gold answer y un extractor/checker de claims.
- La calidad del score depende de la granularidad de los claims, del entailment checker y de la definición de “correcto”. Un contexto erróneo puede soportar un claim incorrecto. Context precision es a nivel chunk; el propio paper advierte que el chunking impone un techo a la precisión a nivel claim.
- Si la respuesta o el gold está vacío, deben definirse casos de borde antes de ejecutar: denominador cero no es automáticamente cero. Reportar `N_claims` y proporción de abstenciones.
- El paper utilizó Llama 3 70B para extractor y checker en sus experimentos; la ejecución API o local es posible, pero cambiar esos modelos altera el instrumento. El costo es aproximadamente proporcional a claims × referencias/chunks, además de tokens de contexto; es más alto que una métrica vectorial.

### Uso en Benchmark v2

Usar `F1_claim` como overall sólo cuando exista gold legal validado. Publicar también `ClaimRecall`, `ContextPrecision`, `Faithfulness`, `Hallucination` y `ContextUtilization`; esos diagnósticos indican si una mejora proviene del retriever o del generator. Conservar el texto de claims y decisión de entailment para auditoría.

## 4. ARES

**Fuente primaria:** [Saad-Falcon et al., “ARES: An Automated Evaluation Framework for Retrieval-Augmented Generation Systems”, NAACL 2024](https://aclanthology.org/2024.naacl-long.20/).

La base estadística de PPI es [Angelopoulos et al., “Prediction-Powered Inference”, Science 2023 / arXiv:2301.09633](https://arxiv.org/abs/2301.09633).

ARES no es sólo un prompt de juez. (1) Genera triples sintéticos pregunta–pasaje–respuesta desde un corpus in-domain; (2) entrena tres clasificadores ligeros para context relevance, answer faithfulness y answer relevance; (3) usa un pequeño conjunto anotado y *prediction-powered inference* (PPI) para corregir/intervalar los scores sobre muchos ejemplos no anotados. El paper requiere un corpus in-domain, al menos aproximadamente 150 datapoints de validación humana y unos pocos ejemplos in-domain; en experimentos también usó FLAN-T5 XXL para sintéticos y DeBERTa-v3-Large como juez finetuneado.

### Fórmulas y salida

Para cada dimensión \(d\in\{CR,AF,AR\}\), el juez produce \(j_d(q,c,a)\in\{0,1\}\). El score directo es:

\[
  \hat\mu_d=\frac{1}{N}\sum_{i=1}^{N}j_d(q_i,c_i,a_i).
\]

PPI combina predicciones en un conjunto grande \(U\) y etiquetas humanas en un conjunto pequeño \(L\), estimando una corrección del sesgo del juez y un intervalo de confianza. Una forma didáctica del estimador rectificado es:

\[
  \hat\mu_{PPI,d}=\bar j_{d,U}+
  \left(\bar y_{d,L}-\bar j_{d,L}\right),
\]

donde \(y\) es la etiqueta humana y \(j\) la predicción del juez en los casos etiquetados. La implementación de ARES ajusta la rectificación y sus límites; por eso se deben usar su código/versión y reportar el intervalo, no sólo el punto medio.

### Aplicabilidad, límites y costo

- Es especialmente atractivo para comparar muchas variantes del mismo dominio: el costo de generar sintéticos, finetunear y anotar se amortiza; la inferencia posterior es barata y puede ejecutarse sin API externa.
- La calidad depende de sintéticos, negativos, calibración y similitud entre el dominio de validación y el benchmark. Un judge puede aprender artefactos del generador sintético. PPI no convierte etiquetas humanas escasas en cobertura jurídica completa.
- No se debe usar sin revalidar para otra jurisdicción, idioma, tipo de documento o cambio de corpus. En derecho, la validación debe cubrir explícitamente citas, fechas, excepciones y conflictos entre autoridades.
- Costo de setup: `C_sintético + C_finetune + C_humano(|L|)`. Costo marginal por sistema: inferencia de tres clasificadores sobre \(N\) triples y PPI; es mucho menor que anotar todos los outputs una vez preparado el juez. El paper reporta que usar cientos de anotaciones puede distinguir sistemas separados por pocos puntos, pero esos resultados no son una garantía fuera de sus dominios.

### Uso en Benchmark v2

ARES es adecuado si el benchmark se ejecutará repetidamente sobre un corpus estable. Guardar los sintéticos, splits, negativos, pesos del juez, conjunto humano, intervalo PPI y seed. Si sólo se tiene una corrida pequeña o una nueva jurisdicción legal, preferir claims + revisión experta antes que entrenar un judge sobre datos sintéticos insuficientes.

## 5. Claims, factualidad y atribución

### 5.1 FActScore

**Fuente primaria:** [Min et al., “FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation”, EMNLP 2023](https://aclanthology.org/2023.emnlp-main.741/).

FActScore define un hecho atómico como una afirmación corta que contiene una pieza de información. Para una respuesta \(y\), con hechos atómicos \(A_y\) y fuente confiable \(C\):

\[
  f(y)=\frac{1}{|A_y|}\sum_{a\in A_y}
  \mathbb{1}[a\text{ está respaldado por }C],
  \qquad
  FActScore(M)=\mathbb{E}_{x}[f(M(x))\mid M(x)\text{ responde}].
\]

El paper propone evaluación humana y un estimador automático que recupera pasajes y usa un LM evaluador. En su escenario de biografías/Wikipedia, reporta un error menor al 2% del estimador frente a humanos y estima que evaluar 6.500 generaciones manualmente costaría USD 26.000; son resultados de ese experimento, no precios universales.

**Límites.** FActScore es precisión, no recall: una respuesta corta o una abstención puede obtener score alto. Asume que el soporte es no debatible, que cada claim pesa igual y que la fuente no entra en conflicto consigo misma. En derecho, una fuente única no siempre basta: la vigencia, jerarquía, jurisdicción y excepciones deben ser parte del claim/etiqueta. Se recomienda agregar cobertura de claims gold y abstención como métricas separadas.

### 5.2 SAFE y F1@K

**Fuente primaria:** [Wei et al., “Long-form factuality in large language models”, 2024](https://arxiv.org/abs/2403.18802); [código oficial de LongFact/SAFE](https://github.com/google-deepmind/long-form-factuality).

SAFE usa un LLM para descomponer una respuesta, emite consultas a búsqueda y decide si cada hecho está soportado por resultados. Para hechos soportados \(S\), hechos totales \(A\) y una longitud deseada \(K\):

\[
  P=\frac{|S|}{|A|},\qquad
  R_K=\min\left(\frac{|S|}{K},1\right),\qquad
  F1@K=\frac{2P R_K}{P+R_K}.
\]

La idea de \(K\) es penalizar respuestas que son precisas pero demasiado cortas para la cantidad de hechos que el usuario necesita. SAFE requiere búsqueda y por eso puede ser costoso, no reproducible si cambian los resultados web y no es directamente apropiado cuando la verdad debe limitarse a un corpus legal cerrado. Para uso legal, reemplazar búsqueda general por fuentes autorizadas versionadas y guardar cada query, resultado, fecha y span.

El paper reporta 72% de acuerdo con anotadores crowdsourced sobre aproximadamente 16.000 hechos y más de 20 veces menor costo que humanos en su configuración. Es evidencia de viabilidad del agente evaluador, no una licencia para omitir expertos en casos de alto impacto.

### 5.3 Claim-level entailment y citas

**Fuente primaria complementaria:** [Hu et al., “RefChecker: Reference-based Fine-grained Hallucination Checker and Benchmark for Large Language Models”, EMNLP 2024](https://aclanthology.org/2024.emnlp-main.395/).

RefChecker representa claims como tripletas y los verifica contra una referencia en escenarios de contexto cero, ruidoso o preciso. La operación básica es binaria o ternaria por claim–referencia; una agregación útil para el benchmark es:

\[
  CitationPrecision=\frac{\#\text{citas que soportan el claim citado}}
                              {\#\text{citas verificables}},
  \qquad
  ClaimSupport=\frac{\#\text{claims soportados por autoridad}}
                             {\#\text{claims evaluados}}.
\]

Estas fórmulas son agregaciones operativas, no una nueva métrica de RefChecker. Separar `citation_precision` (la cita realmente sostiene el claim), `citation_recall` (los claims que requerían cita recibieron una) y `source_authority` (la fuente es admisible para jurisdicción y fecha). Una cita presente pero incorrecta debe ser un error de factualidad/citación, no un crédito de estilo.

### Costo y LLM de los evaluadores de factualidad

FActScore automatizado usa recuperación + LM evaluador; SAFE usa LLM + búsquedas iterativas; RefChecker/RAGChecker usan extractor y checker. El costo operativo puede expresarse como:

\[
  C_{total}=C_{LLM,in}+C_{LLM,out}+C_{search}+C_{embed}+C_{human}+C_{compute},
\]

con cada término desglosado por caso y por claim. Registrar precios y fecha del proveedor si hay API; no hardcodear precios que cambian. Los scores deben incluir intervalos o acuerdo humano, porque un juez que no distingue una norma derogada puede producir una falsa sensación de precisión.

## 6. Evaluación de generación legal

**Fuentes primarias:** [Guha et al., “LegalBench: A Collaboratively Built Benchmark for Measuring Legal Reasoning in Large Language Models”, NeurIPS 2023](https://papers.neurips.cc/paper_files/paper/2023/hash/89e44582fd28ddfea1ea4dcb0ebbf4b0-Abstract-Datasets_and_Benchmarks.html); [Fei et al., “LawBench: Benchmarking Legal Knowledge of Large Language Models”, EMNLP 2024](https://aclanthology.org/2024.emnlp-main.452/); [Li y Wu, “LegalEval-Q: A New Benchmark for The Quality Evaluation of LLM-Generated Legal Text”, 2025](https://arxiv.org/abs/2505.24826).

La generación legal no debe reducirse a ROUGE/BERTScore ni a un único juez. LegalBench fue construido colaborativamente con tareas diseñadas por profesionales y cubre distintos tipos de razonamiento; LawBench incluye tareas de conocimiento, comprensión, aplicación y generación; LegalEval-Q separa al menos claridad, coherencia y terminología. Estas fuentes justifican una evaluación multidimensional, pero sus resultados no son transferibles automáticamente entre jurisdicciones, idiomas, fechas de ley o géneros documentales.

### Rúbrica mínima por caso

1. **Corrección normativa/factual:** cada claim jurídico es consistente con la autoridad vigente, jurisdicción y fecha de corte. Medir `ClaimSupport`/FActScore sobre fuentes legales autorizadas y marcar separadamente conflicto, omisión y afirmación no verificable.
2. **Completitud:** definir un conjunto de claims/issues gold y medir recall; no premiar una respuesta que evita el punto difícil. Para claims gold, `Recall_claim` es `claims correctos cubiertos / claims gold`.
3. **Razonamiento y aplicación:** revisar si la norma se aplica a los hechos dados, si distingue regla, excepción y conclusión, y si no introduce hechos no proporcionados. Un score de similitud no cubre este criterio.
4. **Citas y trazabilidad:** cada claim material debe tener una autoridad y span que lo sostenga. Reportar precisión de cita, recall de cita, autoridad, vigencia y consistencia entre texto y referencia.
5. **Relevancia, claridad y formato:** la respuesta debe atender la pregunta, declarar supuestos, separar información de recomendación y respetar el formato contractual. Puede apoyarse en RAGAS `answer_relevance` y en una rúbrica humana; no inferir corrección desde fluidez.
6. **Seguridad y abstención:** detectar consejo categórico sin base, jurisdicción equivocada, datos personales expuestos y falta de advertencia cuando faltan hechos. Medir abstenciones correctas e incorrectas por separado.

La puntuación legal debe ser ordinal o binaria por criterio con anclajes y ejemplos; publicar el protocolo de anotación, capacitación, acuerdo inter-anotador y adjudicación. Usar un LLM como preanotador sólo después de calibrarlo contra expertos y auditar falsos negativos en claims críticos.

## 7. Comparación pareada e inferencia estadística

La comparación debe respetar que dos sistemas producen salida sobre los mismos casos. Si \(s_i^A\) y \(s_i^B\) son scores por caso:

\[
  d_i=s_i^A-s_i^B,\qquad
  \Delta=\frac{1}{n}\sum_i d_i=\bar s(A)-\bar s(B).
\]

No tratar las salidas de dos sistemas como muestras independientes: eso pierde el emparejamiento y puede subestimar la incertidumbre.

### 7.1 Paired bootstrap

**Fuente primaria:** [Koehn, “Statistical Significance Tests for Machine Translation Evaluation”, EMNLP 2004](https://aclanthology.org/W04-3250/).

El paired bootstrap re-muestrea índices de casos, manteniendo en cada réplica el par \((s_i^A,s_i^B)\). Para \(b=1,\ldots,B\), se muestrea con reemplazo \(I_b=(i_1,\ldots,i_n)\) y se calcula:

\[
  \Delta_b=\frac{1}{n}\sum_{r=1}^{n}
  \left(s_{i_r}^{A}-s_{i_r}^{B}\right).
\]

Un intervalo percentil bilateral al nivel \(1-\alpha\) es:

\[
  CI_{1-\alpha}=[Q_{\alpha/2}(\Delta_b),Q_{1-\alpha/2}(\Delta_b)].
\]

Para un test bilateral, documentar la convención exacta de p-valor (por ejemplo, proporción de réplicas que cruzan cero o la versión de prueba de bootstrap usada por la implementación) y la semilla. Reportar siempre \(\Delta\), CI, \(B\), unidad de remuestreo y p; no concluir sólo porque un intervalo “parece” más ancho. Usar al menos 10.000 réplicas para resultados publicados, salvo justificación.

**Límites.** El bootstrap independiente por sistema es incorrecto para una comparación pareada. Si hay varias preguntas por expediente, varias salidas por usuario o clusters por jurisdicción, remuestrear el cluster superior, no cada fila. Para métricas no descomponibles, recalcular la métrica sobre cada muestra y especificar esa elección.

### 7.2 Wilcoxon signed-rank

**Fuente primaria:** [Wilcoxon, “Individual Comparisons by Ranking Methods”, Biometrics Bulletin 1945, DOI 10.2307/3001968](https://doi.org/10.2307/3001968).

Se calcula sobre las diferencias pareadas \(d_i\). Se eliminan diferencias exactamente cero; se rankean \(|d_i|\) de menor a mayor, usando rango medio en empates. Si \(r_i\) es el rango:

\[
  W^+=\sum_{d_i>0}r_i,\qquad
  W^-=\sum_{d_i<0}r_i,\qquad
  T=\min(W^+,W^-).
\]

Para \(n\) pequeño usar distribución exacta si no hay empates problemáticos; para \(n\) grande, aproximación normal con corrección por continuidad y varianza ajustada por empates/ceros. El test contrasta una diferencia de localización/mediana bajo supuestos de simetría de las diferencias; no es un test de medias y no prueba equivalencia práctica.

Es útil como sensibilidad robusta a outliers y escalas no normales, pero scores discretos (por ejemplo, claims binarios o muchos ceros) reducen potencia y vuelven esenciales el manejo de empates y el tamaño efectivo. No usar Mann–Whitney/Wilcoxon rank-sum: los casos de Benchmark v2 son pareados.

### 7.3 Holm–Bonferroni

**Fuente primaria:** [Holm, “A Simple Sequentially Rejective Multiple Test Procedure”, Scandinavian Journal of Statistics 1979, DOI 10.2307/4615733](https://doi.org/10.2307/4615733).

Para una familia predefinida de \(m\) hipótesis y p-valores ordenados \(p_{(1)}\leq\cdots\leq p_{(m)}\), comparar secuencialmente:

\[
  p_{(i)}\leq\frac{\alpha}{m-i+1}.
\]

Se rechaza desde \(i=1\) hasta el primer incumplimiento; desde allí no se rechazan las restantes. Los p ajustados pueden expresarse como:

\[
  p^{Holm}_{(i)}=\max_{j\leq i}\{(m-j+1)p_{(j)}\},
\]

y luego se reordenan a la hipótesis original. Holm controla el family-wise error rate bajo dependencia arbitraria y suele ser menos conservador que Bonferroni simple.

Definir antes de mirar resultados la familia: por ejemplo, todas las comparaciones de sistemas para un endpoint primario, o todos los endpoints de una misma afirmación. No mezclar silenciosamente BERTScore, RAGAS, RAGChecker, factualidad y rúbrica humana en familias distintas. Ajustar p no corrige sesgo del juez, dependencia por expediente, múltiples seeds no declaradas ni un endpoint elegido post hoc.

### 7.4 Costo y uso de LLM

Paired bootstrap, Wilcoxon y Holm–Bonferroni no requieren un LLM ni llamadas de API. Su costo de cómputo es bajo frente a generar/verificar las respuestas; el bootstrap puede exigir hasta \(B\) recomputaciones de una métrica no descomponible. El costo científico relevante es fijar correctamente la unidad pareada, la familia de hipótesis y la semilla, no ahorrar esas operaciones a costa de una inferencia inválida.

## 8. Protocolo estadístico recomendado

1. Fijar un endpoint primario (por ejemplo, `F1_claim` o `ClaimSupport`) y endpoints diagnósticos antes de ejecutar.
2. Generar todas las salidas con los mismos casos, contexto, fecha de corpus y presupuesto de tokens por sistema.
3. Calcular scores por caso y publicar denominadores, claims, abstenciones y errores de parsing.
4. Reportar diferencia pareada \(\Delta\), intervalo paired bootstrap y tamaño de efecto; usar Wilcoxon signed-rank como análisis de sensibilidad cuando los scores sean ordinales/discretos.
5. Aplicar Holm–Bonferroni a la familia preespecificada de hipótesis y publicar p sin ajustar y ajustados.
6. Validar los jueces automáticos en un estrato humano que incluya casos fáciles, difíciles, negativos, citas incorrectas, fechas/jurisdicciones y abstenciones.
7. Reportar costo y latencia por caso junto a calidad. Una mejora estadísticamente significativa puede ser operacionalmente inviable o estar comprando más tokens, más recuperación o más revisión humana.

La conclusión debe ser acotada: “el sistema A obtuvo mayor score en el endpoint X bajo este corpus, jurisdicción, modelo evaluador y fecha”, no “A es más correcto” en general.

## Referencias primarias

- [BERTScore — Zhang et al. (ICLR 2020)](https://arxiv.org/abs/1904.09675).
- [RAGAS — Es et al. (EACL 2024)](https://aclanthology.org/2024.eacl-demo.16/).
- [RAGChecker — Ru et al. (NeurIPS 2024 / arXiv:2408.08067)](https://arxiv.org/abs/2408.08067).
- [ARES — Saad-Falcon et al. (NAACL 2024)](https://aclanthology.org/2024.naacl-long.20/).
- [Prediction-Powered Inference — Angelopoulos et al. (Science 2023)](https://arxiv.org/abs/2301.09633).
- [FActScore — Min et al. (EMNLP 2023)](https://aclanthology.org/2023.emnlp-main.741/).
- [SAFE/LongFact — Wei et al. (2024)](https://arxiv.org/abs/2403.18802).
- [RefChecker — Hu et al. (EMNLP 2024)](https://aclanthology.org/2024.emnlp-main.395/).
- [LegalBench — Guha et al. (NeurIPS 2023)](https://papers.neurips.cc/paper_files/paper/2023/hash/89e44582fd28ddfea1ea4dcb0ebbf4b0-Abstract-Datasets_and_Benchmarks.html).
- [LawBench — Fei et al. (EMNLP 2024)](https://aclanthology.org/2024.emnlp-main.452/).
- [LegalEval-Q — Li y Wu (2025)](https://arxiv.org/abs/2505.24826).
- [Paired bootstrap — Koehn (EMNLP 2004)](https://aclanthology.org/W04-3250/).
- [Wilcoxon signed-rank — Wilcoxon (1945)](https://doi.org/10.2307/3001968).
- [Holm–Bonferroni — Holm (1979)](https://doi.org/10.2307/4615733).
