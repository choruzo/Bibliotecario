# H1: esqueleto ejecutable y persistencia

API FastAPI, web Next.js y worker comparten PostgreSQL/pgvector y el almacen de documentos del host. El worker mantiene un heartbeat persistente y termina ordenadamente; la adquisicion y conversion de trabajos pertenece a H2. No hay cuentas ni contrasenas de usuario predeterminadas.

## Instalacion limpia

Requisitos: Docker con motor Linux activo, Compose 2.24.4 o posterior y los tres servicios llama.cpp accesibles desde los contenedores. Python solo se necesita en el host para los scripts de configuracion y comprobacion.

Desde la raiz del repositorio:

```powershell
python scripts/h1/init_env.py
docker compose config --quiet
docker compose up --build -d
docker compose exec api python -m bibliotecario.cli bootstrap-admin --username administrador
```

El bootstrap solicita y confirma la contrasena por entrada oculta (minimo 12 caracteres). No la pase en argumentos ni variables. Repetir el bootstrap rechaza la operacion si ya existe un administrador. `create-user --username lector --role usuario` permite crear otras cuentas desde la misma consola local de confianza.

Como alternativa para una primera instalacion local, `python scripts/h1/bootstrap_local.py` crea `administrador` con contrasena aleatoria en `.artifacts/h1/admin-credentials.json`, excluido de Git, y la envia al contenedor por stdin. No sobrescribe cuentas ni archivos de credenciales existentes.

Abra http://localhost:3000 e inicie sesion. Administracion permite comprobar base de datos, generacion a traves de LiteLLM, embeddings y reranker. Biblioteca presenta el estado vacio; carga y chat documental llegaran en H2 y H4.

```powershell
python scripts/h1/smoke.py --username administrador
docker compose ps --all
docker compose logs api worker
```

El smoke devuelve 0 cuando los cuatro checks estan disponibles y 1 ante un fallo. La comprobacion genera una peticion minima a cada modelo; no se ejecuta periodicamente en segundo plano.

Ensayo reproducible de esquema, migracion idempotente, bind mount, sesion, auditoria y persistencia tras reiniciar solo los servicios de este proyecto:

```powershell
python scripts/h1/acceptance.py --credentials .artifacts/h1/admin-credentials.json --restart
python scripts/h1/check_model_errors.py --credentials .artifacts/h1/admin-credentials.json
```

La segunda prueba usa APIs efimeras dentro del contenedor para simular una URL inaccesible por modelo y verificar HTTP 503 con resultados independientes. No detiene los modelos del host. Los informes omiten secretos y se guardan en `.artifacts/h1/`.

## Configuracion

`init_env.py` crea `.env` con secretos aleatorios para PostgreSQL y LiteLLM, y se niega a sobrescribirlo. Por defecto los datos se guardan en `bibliotecario-data/` del repositorio, ignorado por Git. Puede elegir otra ruta con `--data-dir`. En Windows use una ruta absoluta con `/`. Si edita manualmente la contrasena de PostgreSQL, use caracteres seguros para una URL (el generador utiliza hexadecimal).

- PostgreSQL: `${BIB_DATA_DIR}/postgres`, base `bibliotecario`, extension `vector` y revision Alembic `0001_h1`.
- Archivos: `${BIB_DATA_DIR}/documents/{originals,normalized}`. `storage-init` prepara solo estos directorios para UID 10001; no recorre ni modifica archivos existentes.
- Migraciones: servicio de una sola ejecucion, antes de API y worker. Nunca se usa `create_all` en despliegues.
- Puertos: solo web y API se publican en loopback; PostgreSQL y LiteLLM permanecen en la red interna.
- Modelos: las URLs, claves, nombres, dimensiones y timeout son variables. Generacion usa LiteLLM; los otros dos modelos usan los endpoints directos de llama.cpp.
- Linux: `host.docker.internal` se resuelve con `host-gateway`. Los servidores del host deben escuchar en una interfaz alcanzable desde Docker; `127.0.0.1` puede no bastar.
- Cambiar el puerto web exige ajustar `BIB_PUBLIC_ORIGIN` al origen real, incluido el puerto. La web reenvia `/api` desde el servidor, sin exponer secretos ni necesitar CORS.

El alias publico de generacion es `bibliotecario-generation`; si lo cambia, actualice tambien `config/h1/litellm.yaml`. `LLAMA_GENERATION_MODEL` incluye el prefijo de proveedor `openai/` esperado por LiteLLM.

## Perfiles

Desarrollo con recarga del codigo y frontend:

```powershell
docker compose -f compose.yaml -f compose.dev.yaml up --build -d
```

Produccion con cookies seguras y validacion de HTTPS:

```powershell
# En .env: BIB_PUBLIC_ORIGIN=https://biblioteca.example
docker compose -f compose.yaml -f compose.production.yaml up --build -d
```

Produccion necesita un proxy TLS externo que llegue al puerto web de loopback y preserve el origen publico. La API no publica puerto en este perfil. No publique esta instalacion directamente en Internet; el endurecimiento y limites adicionales pertenecen a H7.

## Autenticacion y observabilidad

Las contrasenas se guardan con Argon2id. Las sesiones son persistentes, con expiracion absoluta, token aleatorio cuyo SHA-256 es lo unico guardado en PostgreSQL, cookie HttpOnly/SameSite=Strict y revocacion al cerrar sesion. Login valida Origin; logout requiere ademas un token CSRF. Ambos roles pueden acceder a su identidad, pero solo admin puede sondear dependencias.

`/health/live` indica proceso vivo. `/health/ready` comprueba PostgreSQL, extension y revision; no depende de modelos, para que una caida de llama.cpp permita iniciar sesion y diagnosticarla. `/health/dependencies` requiere admin y devuelve 200 o 503 con cuatro resultados independientes, errores clasificados y latencias de los modelos. El health del worker verifica la antiguedad de su heartbeat.

Los logs de aplicacion son JSON con un UUID de correlacion devuelto en `X-Request-ID`. Se registran plantilla de ruta, metodo, estado y duracion. No se registran cuerpos, cookies, consultas, contrasenas, claves ni respuestas de proveedores. Los errores de validacion tampoco devuelven los valores enviados. Login, logout y creacion de cuentas generan eventos de auditoria.

## Pruebas

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r apps/api/requirements.lock -e './apps/api[test]' -r requirements-h0.txt
.venv/Scripts/python.exe -m pytest apps/api/tests -q
.venv/Scripts/python.exe -m unittest discover -s tests -v
cd apps/web
npm ci
npm run build
npm test
```

Las pruebas unitarias usan SQLite solo para contratos de autenticacion y mocks HTTP para respuestas de proveedores. No certifican PostgreSQL, pgvector ni conectividad de contenedores. La aceptacion requiere el smoke sobre Compose real y comprobar que una sesion y los registros se conservan despues de reiniciar API y PostgreSQL.

Playwright verifica acceso, errores, permisos y logout en escritorio y movil con respuestas HTTP simuladas. Use `npx playwright install chromium` o `BIB_CHROME_PATH` con la ruta de un Chrome local. Las capturas quedan en `.artifacts/h1/browser-tests/`.

`tests/compose.spec.ts` contiene el ensayo de navegador real. Por defecto se omite; para ejecutarlo con Compose activo, defina `BIB_E2E_CREDENTIALS` con la ruta absoluta del archivo local de cuenta y ejecute `npm test -- tests/compose.spec.ts`. `BIB_E2E_ORIGIN` permite cambiar el origen de despliegue. No genera trazas con contrasenas.

`python scripts/h1/probe_clients.py` comprueba los tres contratos directamente contra los modelos del host. Para probar LiteLLM externo, indique `--llm-url` y `--llm-model`; una clave propia se lee de `BIB_LLM_API_KEY`. El sondeo directo no acredita la ruta de red de Compose.

Las dependencias Python y npm se bloquean en `requirements.lock` y `package-lock.json`. El empaquetado de imagenes por digest, exportacion y ensayo offline completo corresponden a H6.
