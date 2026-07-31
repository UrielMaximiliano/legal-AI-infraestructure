# Especificación: Base Local y Verificación de Dependencias

**ID de Especificación**: `001-local-base-dependencies`
**Creada**: 2026-07-31
**Estado**: Borrador
**Entrada**: Descripción del usuario: "Base local y verificación de dependencias del asistente jurídico"

## Resumen Ejecutivo

Esta especificación define el entorno local mínimo ejecutable para el proyecto
legal-AI-infraestructure. El primer incremento verifica que la aplicación pueda
iniciar correctamente, responder mediante HTTP, conectarse a PostgreSQL con
pgvector, alcanzar el endpoint configurable de Ollama e informar el estado de
cada dependencia individualmente. Todo el alcance se limita a la validación
local del desarrollo. No se incluye RAG, embeddings, corpus, generación
jurídica, frontend, Redis, Kubernetes, Terraform ni Helm.

## Declaración del Problema

### Estado Actual

El repositorio del proyecto existe con una constitución y principios IaC, pero
no hay código de aplicación, ni base de datos, ni API, ni forma de verificar
que las dependencias de infraestructura sean alcanzables y estén configuradas
correctamente.

### Estado Deseado

Un desarrollador puede ejecutar un comando documentado, iniciar PostgreSQL y la
API localmente mediante Docker Compose, y recibir respuestas estructuradas que
confirman que cada dependencia está disponible o identifican la falla específica.
Esto valida la base técnica antes de construir cualquier funcionalidad de IA.

### Impacto del Negocio

Sin esta base, los incrementos posteriores (ingesta, embeddings, recuperación,
generación) no pueden desarrollarse ni probarse de manera confiable. Establecer
la verificabilidad local temprano previene fallos compuestos en fases futuras.

## Escenarios de Usuario y Pruebas

### Historia de Usuario Principal

Como desarrollador del proyecto,
quiero levantar la aplicación y sus dependencias locales con un comando documentado,
para comprobar que la API, PostgreSQL, pgvector y Ollama están disponibles
antes de implementar funcionalidades de inteligencia artificial.

### Contrato de Health Checks

El sistema expone tres endpoints de salud claramente diferenciados:

**GET /health/live**

Indica únicamente que el proceso HTTP está activo. No consulta PostgreSQL,
pgvector ni Ollama. Debe responder HTTP 200 mientras el proceso pueda atender
solicitudes. Una dependencia externa caída no debe modificar este resultado.

Respuesta conceptual:

```json
{
  "status": "ok",
  "service": "legal-ai-api",
  "version": "0.1.0"
}
```

**GET /health/ready**

Indica si la aplicación está preparada para atender operaciones funcionales.
Debe verificar PostgreSQL, pgvector y la configuración mínima obligatoria.
Ollama debe evaluarse también, pero el resultado debe distinguir entre no
preparado y degradado. PostgreSQL inaccesible o pgvector ausente implican
HTTP 503. Configuración inválida imprescindible implica HTTP 503. Ollama no
disponible implica inicialmente HTTP 503 porque las futuras funciones
principales dependerán del modelo. La respuesta debe identificar el estado
general sin revelar secretos.

Estados generales permitidos:

- `ready`: PostgreSQL, pgvector y Ollama disponibles.
- `degraded`: Reservado para capacidades futuras donde una dependencia opcional
  pueda fallar sin impedir la operación principal.
- `not_ready`: PostgreSQL inaccesible, pgvector ausente, configuración
  obligatoria inválida u Ollama no disponible.

**GET /health/dependencies**

Ejecuta y muestra el diagnóstico individual de PostgreSQL, pgvector y Ollama.
Debe responder HTTP 200 cuando la operación de diagnóstico pudo ejecutarse,
aunque alguna dependencia esté caída. Solo debe responder HTTP 500 ante un
error interno no controlado del propio diagnóstico. Cada dependencia debe
incluir: `status`, `latency_ms` cuando corresponda, `error_code` sanitizado
cuando exista, y mensaje técnico breve sin secretos.

Estados individuales permitidos:

- `ok`
- `unavailable`
- `timeout`
- `misconfigured`
- `invalid_response`
- `missing`

La ausencia de pgvector debe representarse como `"status": "missing"`.

No se utilizará el endpoint genérico `GET /health` para evitar ambigüedad
entre liveness y readiness.

### Escenarios de Aceptación

**Escenario 1 — Todas las dependencias disponibles**

Dado que la API está iniciada,
y PostgreSQL está disponible,
y pgvector está habilitado,
y Ollama responde,
cuando el operador consulta el estado de dependencias,
entonces recibe un estado general correcto,
y cada dependencia aparece disponible.

**Escenario 2 — Ollama no disponible**

Dado que la API y PostgreSQL están disponibles,
y Ollama no responde antes del timeout,
cuando el operador consulta el endpoint de dependencias,
entonces la API sigue respondiendo,
Ollama aparece como no disponible o timeout,
y no se expone un stack trace.

**Escenario 3 — PostgreSQL no disponible**

Dado que la API logra iniciar,
y PostgreSQL no está disponible,
cuando se consulta `/health/live`,
entonces `/health/live` informa que el proceso está vivo,
cuando se consulta `/health/ready`,
entonces informa HTTP 503 con estado `not_ready`,
y el diagnóstico identifica PostgreSQL como dependencia fallida.

**Escenario 4 — pgvector ausente**

Dado que PostgreSQL está disponible,
pero la extensión pgvector no está habilitada,
cuando se consulta `/health/ready`,
entonces la aplicación retorna HTTP 503 con estado `not_ready`,
y el diagnóstico diferencia este caso de una caída de PostgreSQL
mostrando `"status": "missing"`.

**Escenario 5 — Configuración de Ollama inválida**

Dado que `OLLAMA_BASE_URL` no está configurada o es inválida,
cuando inicia la aplicación o se consulta el diagnóstico,
entonces el error se informa claramente con `error_code` estable,
sin revelar secretos,
y sin provocar una excepción no controlada.

**Escenario 6 — Reinicio local**

Dado que el entorno local fue iniciado y PostgreSQL contiene datos de prueba,
cuando se detienen y vuelven a iniciar los contenedores sin eliminar volúmenes,
entonces los datos permanecen disponibles.

**Escenario 7 — Eliminación explícita de datos**

Dado que existen datos locales,
cuando el desarrollador utiliza el procedimiento documentado de limpieza destructiva,
entonces los datos locales se eliminan,
y el procedimiento requiere una acción explícita diferente del apagado normal.

**Escenario 8 — Pruebas sin Ollama real**

Dado un entorno de pruebas automatizadas,
cuando se ejecutan las pruebas unitarias,
entonces pueden completarse utilizando un sustituto del cliente de Ollama,
sin depender del endpoint compartido.

## Requisitos Funcionales

### RF-001 — Health del Proceso

El sistema DEBE exponer el endpoint `GET /health/live` que indica si el
proceso de la API está ejecutándose. Este endpoint NO DEBE depender de
PostgreSQL ni de Ollama. Una dependencia externa caída NO DEBE hacer que
este endpoint informe que el proceso está muerto.

### RF-002 — Readiness

El sistema DEBE exponer el endpoint `GET /health/ready` que indica si la
aplicación está preparada para atender operaciones que requieren sus
dependencias obligatorias. La respuesta DEBE distinguir entre: `ready`,
`degraded`, `not_ready`. Para este incremento, `degraded` queda reservado
para capacidades futuras.

### RF-003 — Estado de PostgreSQL

El sistema DEBE comprobar la conectividad con PostgreSQL mediante una
operación liviana y segura. DEBE informar al menos: estado, tiempo de
respuesta en milisegundos, tipo de error sanitizado cuando no esté disponible.
NO DEBE devolver contraseñas, cadenas de conexión completas ni información
sensible.

### RF-004 — Estado de pgvector

El sistema DEBE comprobar que la extensión pgvector se encuentre habilitada
en la base configurada. DEBE diferenciar: PostgreSQL inaccesible, PostgreSQL
accesible pero pgvector ausente (mostrando `"status": "missing"`), PostgreSQL
y pgvector disponibles. La verificación DEBE consultar PostgreSQL y confirmar
que la extensión vector está instalada.

### RF-005 — Estado de Ollama

El sistema DEBE comprobar que el endpoint configurado de Ollama sea accesible.
La comprobación DEBE utilizar una operación liviana (como consultar información
del servicio o modelos disponibles) y NO DEBE ejecutar generación ni embeddings.
DEBE informar: disponible, no disponible, timeout, respuesta inválida, error
de configuración. NO DEBE exponer datos sensibles del endpoint ni detalles
internos innecesarios. No se fija un endpoint interno concreto de Ollama;
eso corresponde al plan técnico según la API disponible.

### RF-006 — Estado Agregado de Dependencias

El sistema DEBE ofrecer el endpoint `GET /health/dependencies` con una
respuesta estructurada que contenga como mínimo: estado general, estado de
PostgreSQL, estado de pgvector, estado de Ollama, fecha y hora de la
comprobación en UTC ISO 8601, duración de cada comprobación en milisegundos,
e `identificador de correlación` de la solicitud.

Ejemplo conceptual:

```json
{
  "status": "ok",
  "timestamp": "2026-07-31T15:30:00Z",
  "request_id": "abc-123",
  "dependencies": {
    "postgres": {
      "status": "ok",
      "latency_ms": 12
    },
    "pgvector": {
      "status": "ok"
    },
    "ollama": {
      "status": "ok",
      "latency_ms": 35
    }
  }
}
```

### RF-007 — Configuración

La aplicación DEBE poder configurarse mediante variables de entorno. DEBE
existir un archivo de ejemplo (`.env.example`) que documente las variables
requeridas sin incluir valores secretos reales. Como mínimo deben
contemplarse: entorno de ejecución, host y puerto de la API, configuración
de PostgreSQL, endpoint de Ollama, timeout de Ollama, nivel de logging,
versión de build.

El timeout de Ollama se configura mediante `OLLAMA_TIMEOUT_SECONDS` con
valor por defecto de 5 segundos. Restricciones: valor mayor que 0, valor
máximo permitido de 30 segundos para health checks, configuración inválida
detectada mediante validación.

### RF-008 — Inicio Local Reproducible

Un desarrollador DEBE poder iniciar las dependencias locales y la API
siguiendo instrucciones documentadas. El procedimiento NO DEBE requerir
Kubernetes. PostgreSQL DEBE persistir sus datos durante reinicios normales
del entorno local.

El procedimiento debe distinguir tres pasos identificables:
1. Iniciar PostgreSQL.
2. Ejecutar migraciones.
3. Iniciar la API.

El entorno puede ofrecer un comando simplificado que ejecute esos pasos
en orden, pero las acciones deben seguir siendo identificables.

### RF-009 — Cierre y Limpieza

Debe documentarse cómo: detener el entorno, reiniciarlo, consultar logs,
eliminar únicamente contenedores, eliminar también los datos locales de
forma explícita. La eliminación de datos no debe formar parte del comando
de detención normal.

### RF-010 — Manejo de Dependencias Degradadas

Si PostgreSQL u Ollama están caídos: la API DEBE continuar iniciando cuando
sea técnicamente posible, el endpoint de salud del proceso DEBE responder,
readiness DEBE indicar que el sistema no está preparado o está degradado,
el endpoint de dependencias DEBE identificar el componente fallido, los
stack traces NO DEBEN mostrarse al cliente.

### RF-011 — Cierre Ordenado

La aplicación DEBE cerrar conexiones y recursos de manera ordenada al
detenerse.

### RF-012 — Información de Versión

La API DEBE poder informar una versión de aplicación o identificador de
build configurable, sin revelar información sensible del entorno. Si el
nombre o versión de build no están configurados, DEBE informarse un valor
por defecto o indicador de "no configurado".

### RF-013 — Migraciones Versionadas

La aplicación DEBE utilizar migraciones versionadas desde el comienzomediante
una herramienta de migraciones. La primera migración debe contemplar
únicamente la preparación técnica mínima de la base: habilitar la extensión
vector mediante `CREATE EXTENSION IF NOT EXISTS vector` y permitir verificar
que la migración fue aplicada. No debe crear tablas de documentos, chunks,
embeddings, usuarios, auditoría ni borradores.

La migración DEBE ejecutarse de forma explícita y documentada. NO DEBE
ejecutarse automáticamente de manera silenciosa cada vez que inicia la API.

## Requisitos No Funcionales

### Seguridad (RNF-001)

- NO registrar contraseñas.
- NO devolver cadenas de conexión completas.
- NO registrar secretos.
- NO incluir archivos `.env` reales en Git.
- NO enviar información jurídica ni personal a Ollama en esta capacidad.
- NO exponer PostgreSQL públicamente.
- NO exponer Ollama directamente mediante la API.
- NO exponer `OLLAMA_BASE_URL`, `DATABASE_URL`, hostnames internos
  completos, credenciales ni stack traces en ningún endpoint.

### Privacidad (RNF-002)

Esta capacidad NO DEBE procesar documentos jurídicos ni datos personales
reales. Los health checks se consideran endpoints operativos y no procesan
información jurídica.

### Rendimiento (RNF-003)

Las comprobaciones de salud deben ser livianas. Cada dependencia DEBE tener
timeout independiente. El endpoint NO DEBE quedar bloqueado indefinidamente
por una dependencia caída. No deben implementarse reintentos en health checks;
los reintentos se evaluarán posteriormente para operaciones reales de
embeddings o generación.

### Resiliencia (RNF-004)

Los errores de PostgreSQL y Ollama deben gestionarse de manera independiente.
El fallo de una dependencia NO DEBE ocultar el estado de las restantes.

### Observabilidad Mínima (RNF-005)

Los logs deben ser estructurados o consistentes. Cada solicitud DEBE poder
correlacionarse mediante un `request_id` o `correlation_id`. Los errores
DEBEN registrar contexto técnico suficiente sin incluir secretos.

### Mantenibilidad (RNF-006)

Las comprobaciones de dependencias deben estar separadas detrás de
componentes reemplazables. La lógica de health checks NO DEBE quedar
acoplada directamente a los controladores HTTP.

### Testabilidad (RNF-007)

Las comprobaciones de PostgreSQL y Ollama deben poder sustituirse por dobles
de prueba. La mayoría de las pruebas NO DEBE depender de un Ollama real.

### Compatibilidad (RNF-008)

El desarrollo principal debe funcionar en Windows con PowerShell y Docker
Desktop o un motor Docker compatible. Los contenedores deben poder ejecutarse
posteriormente en Linux.

### Reproducibilidad (RNF-009)

Las dependencias deben fijarse mediante versiones o archivos de lock. La
imagen utilizada para PostgreSQL debe incluir o soportar pgvector de manera
reproducible.

## Reglas de Negocio

### RB-001

El endpoint de salud del proceso (`/health/live`) y el endpoint de readiness
(`/health/ready`) representan conceptos diferentes y NO DEBEN fusionarse.

### RB-002

Ollama se considera una dependencia externa. El proyecto no administra
modelos ni la infraestructura de Ollama.

### RB-003

La ausencia de Ollama DEBE mostrarse como dependencia no disponible, no
como error no controlado de la aplicación.

### RB-004

La ausencia de pgvector DEBE considerarse un error de preparación del
entorno.

### RB-005

Las respuestas de diagnóstico deben estar diseñadas para operadores, pero
NO DEBEN revelar secretos.

### RB-006

Redis no se incorporará hasta que una capacidad posterior demuestre su
necesidad.

### RB-007

PostgreSQL es una dependencia obligatoria.

### RB-008

pgvector es una dependencia obligatoria.

### RB-009

Ollama es una dependencia obligatoria para readiness, aunque no se utilice
todavía para generar contenido.

### RB-010

No se agregará autenticación en esta capacidad.

### RB-011

Las latencias deben expresarse en milisegundos.

### RB-012

La fecha y hora de diagnóstico debe expresarse en UTC usando ISO 8601.

### RB-013

Cada respuesta DEBE incluir `request_id` o `correlation_id`.

### RB-014

Las respuestas de error deben usar códigos estables, no depender
únicamente del texto del mensaje.

## Objetivos de Nivel de Servicio (SLOs)

- El endpoint `/health/live` responde dentro de 1 segundo independientemente
  del estado de las dependencias.
- Las comprobaciones de dependencias se completan dentro del timeout
  configurado (por defecto: 5 segundos por dependencia).
- El endpoint `/health/dependencies` responde dentro de 2x el timeout
  individual más largo.
- Cero datos sensibles expuestos en cualquier respuesta de salud o diagnóstico.

## Criterios de Éxito

### Validación Funcional

- [ ] El proyecto puede iniciarse localmente siguiendo el README
- [ ] El proceso de API expone `/health/live`
- [ ] `/health/live` responde HTTP 200 independientemente de dependencias
- [ ] `/health/ready` refleja correctamente las dependencias obligatorias
- [ ] `/health/ready` retorna HTTP 503 cuando alguna dependencia falla
- [ ] `/health/dependencies` muestra el diagnóstico individual de cada dependencia
- [ ] PostgreSQL se comprueba de manera real
- [ ] pgvector se comprueba de manera real
- [ ] Ollama se comprueba mediante su endpoint configurado
- [ ] Los errores se presentan de forma estructurada con códigos estables
- [ ] No se exponen secretos en ningún endpoint
- [ ] Cada respuesta incluye `request_id`

### Validación de Pruebas

- [ ] Existen pruebas automatizadas de los escenarios principales
- [ ] Las pruebas pueden completarse sin un Ollama real
- [ ] Las comprobaciones de PostgreSQL son sustituibles con dobles

### Validación Operativa

- [ ] Los datos de PostgreSQL sobreviven a reinicios normales
- [ ] No se ha incorporado funcionalidad fuera del alcance
- [ ] La documentación cubre inicio, parada, reinicio, logs y limpieza
- [ ] Las migraciones se ejecutan de forma explícita y documentada
- [ ] La primera migración habilita la extensión vector

## Casos Límite

- PostgreSQL responde, pero la consulta de pgvector falla.
- Ollama responde HTTP, pero devuelve un formato no reconocido.
- Ollama responde después del timeout.
- `OLLAMA_BASE_URL` contiene un esquema no permitido.
- El timeout configurado es cero, negativo, no numérico o superior al máximo.
- La base está disponible, pero la migración inicial no fue aplicada.
- Dos comprobaciones se ejecutan concurrentemente.
- El cliente cancela la solicitud durante el diagnóstico.
- El nombre o versión de build no están configurados.
- Una dependencia devuelve un error con información sensible; esa
  información debe sanitizarse.

## Supuestos

- Docker y Docker Compose están disponibles en la máquina del desarrollador.
- Existe una imagen de PostgreSQL con soporte pgvector que puede utilizarse
  (ej. `pgvector/pgvector` o una imagen personalizada).
- Ollama es accesible en un endpoint configurable (local o remoto).
- No se utilizan proveedores cloud; toda la infraestructura es on-premise.
- La constitución del proyecto y los principios IaC son los documentos
  rectores.
- Las migraciones se ejecutan de forma explícita antes de iniciar la API.

## Alcance Excluido

- Carga de documentos y corpus jurídico
- Parsing jurídico y chunking
- Embeddings y búsqueda semántica
- RAG y generación de decretos
- Prompts jurídicos
- Redis
- Colas y workers funcionales
- Frontend
- Autenticación de usuarios
- Exportación PDF o DOCX
- Fine-tuning
- MCP (Model Context Protocol)
- Agentes autónomos
- Kubernetes
- Terraform
- Helm
- CI/CD completo
- Observabilidad avanzada (Prometheus, Grafana, Loki)

## Dependencias

- Constitución del proyecto (`.specify/memory/constitution.md`)
- Principios IaC (`.specify/memory/principles.md`)
- Motor de contenedores (Docker Desktop o compatible) en la máquina de
  desarrollo
- Endpoint de Ollama accesible (opcional para pruebas reales)

## Notas

- Este es el primer incremento de una secuencia de desarrollo planificada
  de 11 fases definida en la constitución del proyecto (Principio XIX).
- Redis se excluye explícitamente según RB-006 y Principio XX (Simplicidad).
- Ollama se trata como dependencia externa según Principio XII (Dependencia
  de Ollama) y no debe ser administrado por Terraform ni Helm.
- La especificación evita deliberadamente prescribir librerías o frameworks
  específicos más allá de los ya fijados en la constitución (Python, FastAPI,
  Pydantic, PostgreSQL con pgvector).

## Clarificaciones

### Sesión 2026-07-31

- Q: ¿Cuántos endpoints de health check debe exponer el sistema? → A: Tres endpoints distintos: `/health/live`, `/health/ready`, `/health/dependencies`.
- Q: ¿Cuál es el timeout por defecto de Ollama? → A: 5 segundos, configurable mediante `OLLAMA_TIMEOUT_SECONDS`, máximo 30 segundos.
- Q: ¿Se incluyen migraciones desde el primer incremento? → A: Sí, se incluye Alembic con una primera migración que habilita la extensión vector.
- Q: ¿En qué idioma deben redactarse los artefactos? → A: Español para documentación funcional; inglés para nombres técnicos, endpoints y código.
- Q: ¿Cuáles son las dependencias obligatorias para readiness? → A: PostgreSQL, pgvector y Ollama son todas obligatorias para este incremento.
