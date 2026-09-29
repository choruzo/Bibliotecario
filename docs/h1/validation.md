# Validacion local de H1

Fecha: 2026-09-29. Entorno: Windows, Python 3.12.12, Node 22.20.0, Chrome local.

## Comprobaciones realizadas

- API: 23 pruebas pytest aprobadas (roles, Argon2id, bootstrap sin sobrescritura, sesiones persistentes y expiracion, desactivacion, origen, CSRF, revocacion, auditoria, correlacion y contratos de modelos).
- H0: 4 pruebas unittest aprobadas.
- Web: compilacion de produccion Next.js y TypeScript aprobadas.
- Interfaz: 6 pruebas Playwright aprobadas en escritorio y movil, con respuestas HTTP simuladas. Capturas revisadas en `.artifacts/h1/browser-tests/`.
- Compose: configuracion base y variantes de desarrollo y produccion validadas con `config --quiet`.
- Alembic: `upgrade head --sql` genera la extension vector, las cinco tablas, roles y revision `0001_h1`.
- Modelos reales del host: `probe_clients.py` informa disponibles generacion, embeddings y reranker. Este sondeo llama directamente a los tres puertos de llama.cpp.
- Secretos de despliegue generados localmente en `.env`, ignorado por Git. Cuenta inicial `administrador` creada mediante bootstrap; su contrasena aleatoria esta en `.artifacts/h1/admin-credentials.json`, fuera de Git. No se han publicado cambios en Git.

Starlette emite una advertencia de deprecacion por el transporte httpx del TestClient; las 23 pruebas terminan correctamente.

## Ensayo real de Docker Compose

- Motor Docker 29.7.2; imagenes API y web construidas correctamente.
- PostgreSQL/pgvector 0.8.2 y revision `0001_h1` instalados. Reaplicar `alembic upgrade head` no modifica el esquema ni los registros.
- Preparacion del bind mount aprobada; API sin privilegios puede escribir y leer un archivo visible desde el host. El archivo temporal del ensayo se elimina al finalizar.
- API, PostgreSQL, worker, web y LiteLLM saludables. `migrate` y `storage-init` terminan con exit 0.
- Login real con cookie, health administrativo y logout aprobados a traves del proxy Next.js.
- Los cuatro checks informan `available`: base de datos, generacion mediante LiteLLM -> llama.cpp, embedding y reranker directos.
- Reinicio de PostgreSQL, API y worker: conserva la misma sesion, usuarios, auditoria y archivo del volumen. Logout revoca la sesion.
- Tres escenarios de fallo de conexion, uno por modelo, en APIs temporales dentro del contenedor: HTTP 503 y `connection_error` en el check afectado; los otros tres siguen disponibles. Los procesos llama.cpp del host permanecen activos.
- Dos pruebas Playwright reales aprobadas (escritorio y movil): login, cuatro checks, recarga manteniendo sesion y logout. Capturas en `.artifacts/h1/browser-compose/`; las trazas estan desactivadas para no almacenar credenciales.

Evidencia estructurada local: `.artifacts/h1/compose-acceptance.json` y `.artifacts/h1/model-errors.json`.

El primer arranque detecto una carrera en el health de PostgreSQL: el socket Unix del servidor temporal de inicializacion podia responder antes del servidor TCP. Se corrigio usando `pg_isready -h 127.0.0.1`; el siguiente arranque y las migraciones terminaron correctamente.

H1 cumple su criterio de aceptacion en este entorno de desarrollo. La instalacion offline y los ensayos del perfil de produccion con un proxy TLS pertenecen a hitos posteriores.
