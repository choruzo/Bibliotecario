# Validacion de H5

Fecha: 2026-09-30. Entorno: Windows, Python 3.12, Next.js 16.3.7,
Docker Compose y PostgreSQL 17 con pgvector.

| Comprobacion | Resultado |
|---|---|
| Suite API H1–H5 | 100 pruebas pasadas; 0 fallos |
| Playwright sobre web compilada, escritorio y movil | 10 pruebas pasadas; 0 omitidas |
| TypeScript y build Docker API/web | Correctos |
| Migraciones desde base PostgreSQL vacia | `0001_h1` → `0006_h5`, correctas |
| `alembic check`, base aislada y despliegue local | Sin nuevas operaciones |
| Salud Compose | API, worker, web, PostgreSQL y LiteLLM saludables |
| Checks reales de dependencias | PostgreSQL, generacion, embeddings y reranker disponibles |
| Configuracion API/worker | Firmas actuales, sin reinicios pendientes |
| Revision visual movil | Sin desbordamiento de pagina |
| `git diff --check` | Sin errores |

## Flujos comprobados

La aceptacion `scripts/h5/postgres_acceptance.py` crea una base PostgreSQL
aislada y almacenamiento temporal, aplica todas las migraciones y bootstrap,
y publica dos documentos sinteticos. Comprueba:

- filtrado real de JSON por categoria, etiqueta exacta y visibilidad;
- reindexacion selectiva, fallo permanente simulado, nuevo trabajo de reintento
  y finalizacion al 100%, conservando la version activa;
- reindexacion de toda esa biblioteca aislada;
- rechazo de confirmacion antigua tras retirar una version;
- persistencia y recarga de configuracion, auditoria y exportaciones JSON;
- ausencia de operaciones de migracion pendientes.

Los clientes de modelos de esta aceptacion son deterministas. Usa la cola,
leases, conversion, segmentacion y finalizacion de indices de la aplicacion;
no mide calidad del modelo ni rendimiento de una reindexacion masiva.
La base y sus documentos se eliminan al terminar. El corpus privado del
despliegue local no se reindexo para validar H5.

Las ocho pruebas de H5 cubren ademas roles/CSRF, rechazo de claves y URLs con
credenciales, conflictos de configuracion, deteccion del worker desactualizado
tras reiniciar solo la API, clasificacion publicada sin alterar la revision
historica, invalidacion de la firma del corpus, seleccion invalida sin efectos
parciales y procedencia de respuestas.

Playwright comprueba en ambos tamaños la seleccion y confirmacion de lotes,
guardado de configuracion, auditoria y enlaces de las fuentes con respuestas
simuladas. Dos casos acceden realmente al Compose compilado, autentican al
administrador, consultan configuracion/heartbeat y descargan diagnosticos a
traves del proxy. Los otros seis casos verifican la regresion de autenticacion,
estado de servicios y redireccion del usuario sin rol administrador.

## Limites y avisos

Se mantiene la politica conservadora de H3/H4. Esta validacion administrativa
no aprueba calibraciones ni cambia la puerta de evidencia.
Los lotes tienen un limite de 1000 documentos. Los nuevos valores de proveedor
requieren reiniciar API y worker, y un cambio de modelos requiere reindexar
y recalibrar segun las firmas afectadas.

Pytest emitio un aviso de deprecacion Starlette/httpx. Alembic emitio el aviso
de reflexion del tipo `vector`; termino sin operaciones pendientes. Los primeros
intentos locales de pytest/Playwright quedaron bloqueados por permisos de
temporales/procesos; las ejecuciones finales usaron un contexto permitido y
Chrome ya instalado, y completaron las suites.

Evidencia local ignorada por Git: `.artifacts/h5/api-tests.xml`,
`.artifacts/h5/live-status.json` y capturas de Playwright en
`.artifacts/h1/browser-tests`. Cambios de H5 pendientes de commit en `main`.
