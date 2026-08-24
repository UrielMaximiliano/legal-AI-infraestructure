# Validación jurídica humana pendiente

La evaluación automática selecciona candidatas; la decisión final requiere
comparar el output con su PDF por ocho campos: organismo, objeto,
persona/cargo, dependencia, fecha/plazo/vigencia, normas, artículos y datos
críticos.

Cada campo recibe 1 (correcto), 0,5 (parcial) o 0 (incorrecto/ausente). Los
hechos atómicos se marcan TP, FP o FN. Dos revisores deben evaluar una muestra
estratificada común, medir acuerdo y resolver desacuerdos antes de abrir el
resto de la muestra.

Muestra mínima sugerida: C15, C19, C05 y una línea base 4B; 100 documentos
estratificados por organismo, tipo de acto y longitud. La configuración solo se
promueve si mantiene la mejor Accuracy jurídica, no aumenta FP materiales y
conserva 100% de outputs válidos.
