# H5 — Operacion administrativa completa

Implementado y validado. Resultados del ensayo: [validation.md](validation.md).

La administracion se distribuye entre `/admin` (modelos y base de datos),
`/admin/documents`, `/admin/jobs`, `/admin/retrieval` y `/admin/operations`.
Solo el rol `admin` accede a estas rutas. Las mutaciones requieren sesion,
origen permitido y CSRF.

## Documentos y trabajos

Documentos permite filtrar por titulo, categoria, etiqueta exacta, visibilidad
y estado de la ultima version. Los filtros se aplican antes de paginar.
Los metadatos de borradores se editan en la revision normalizada.
Una version publicada permite actualizar categoria, etiquetas y visibilidad
desde **Clasificacion publicada**, sin cambiar el texto ni la revision
normalizada historica. La operacion comprueba los metadatos esperados,
se audita e invalida la firma del corpus y sus calibraciones anteriores.
La visibilidad afecta inmediatamente a futuras recuperaciones y al acceso
al original; no borra mensajes ya guardados.

Trabajos permite filtrar por estado, tipo e identificador de documento,
inspeccionar eventos, cancelar conversion/indexacion y reintentar trabajos
fallidos o cancelados. Un reintento es un trabajo nuevo enlazado al anterior.
En un lote, su progreso pasa a seguir el nuevo trabajo. Un fallo de reindexacion
mantiene activa la version publicada hasta que el indice nuevo se complete.

Para retirar contenido, abrir el documento y usar **Retirar version publicada**.
La recuperacion excluye esa version inmediatamente. La eliminacion sigue
requiriendo confirmacion del titulo y cumplimiento de la retencion.

## Reindexacion

En **Operacion → Reindexacion**, seleccionar documentos publicados o
previsualizar toda la biblioteca. La previsualizacion enumera titulo, version
y revision. Escribir `REINDEXAR` y confirmar encola todos los trabajos en una
transaccion; una seleccion cambiada o con trabajos activos se rechaza.
Los lotes sobreviven a reinicios y muestran progreso, finalizados y fallidos.
Los trabajos se recuperan desde la pagina Trabajos.

Cada operacion admite hasta 1000 documentos; para bibliotecas mayores hay que
seleccionar varios lotes. Se muestran los 50 lotes mas recientes. Las versiones
retiradas o sin revision aprobada no se incluyen. La nueva indexacion no
aprueba una politica de evidencia: sigue siendo necesaria la calibracion de H3.

## Configuracion

**Operacion → Configuracion** muestra URL y modelo de generacion via LiteLLM,
embeddings y reranker, esfuerzo de razonamiento y timeouts de modelos,
conversion e indexacion. Embeddings conserva el contrato de 768 dimensiones.
Solo estos campos se persisten; no se aceptan claves, credenciales en URLs,
query strings ni parametros privados. Las claves siguen en variables de entorno.

El guardado comprueba una revision para evitar sobrescribir cambios concurrentes.
Los valores guardados se aplican al arrancar cada proceso. Despues de guardar:

```powershell
docker compose restart api worker
```

La pantalla compara valores activos y guardados y la firma del heartbeat del
worker; un reinicio de solo la API no oculta el worker desactualizado.
Los procesos hijos reciben la configuracion publica del worker que los lanza.
Los cambios de modelos invalidan las firmas correspondientes de indices y
politicas: reindexar y recalibrar antes de permitir respuestas documentales.
La URL de generacion debe seguir apuntando a la pasarela LiteLLM prevista.

## Auditoria, respuestas y exportacion

**Operacion → Auditoria** permite filtrar por accion, actor, objeto y resultado;
cada registro conserva fecha e identificador de correlacion.
**Fuentes de respuestas** muestra la conversacion, traza de recuperacion,
documento, version, revision y SHA-256 original guardados con cada respuesta.
Los enlaces permiten consultar las versiones y descargar el original citado.
Una eliminacion controlada puede hacer que el original ya no este disponible;
la respuesta conserva su procedencia historica.

**Exportaciones** descarga JSON de diagnosticos (configuracion publica,
heartbeat y estado del worker, hasta 1000 trabajos recientes) y de evaluaciones
registradas en `evidence_policies` (ambito, firmas, metricas y casos).
Las exportaciones se auditan. No incluyen variables de entorno, claves,
contraseñas, cookies ni la URL de PostgreSQL. Los resultados de evaluacion
pueden contener identificadores de fuentes internas: conservarlos localmente.
Los informes de scripts que solo existen en `.artifacts/` siguen disponibles
en ese directorio; la interfaz exporta las evaluaciones persistidas.

## Instalacion y validacion

Migracion aditiva `0006_h5`: `app_settings`, `reindex_batches` y firma de
configuracion del worker. Se mantiene el campo calculado PostgreSQL
`chunks.search_vector` y su GIN, gestionados por H3; Alembic los excluye de
la comparacion contra el ORM portable para no proponer su eliminacion.

```powershell
docker compose build api web
docker compose up -d api worker web
.venv/Scripts/python.exe -m pytest apps/api/tests -q -p no:cacheprovider --basetemp=.artifacts/h5/pytest
```

La aceptacion PostgreSQL crea una base de nombre aleatorio `bib_h5_*`, aplica
todas las migraciones desde cero, usa solo documentos sinteticos y proveedores
deterministas, y elimina esa base y su almacenamiento al terminar. Requiere
permiso `CREATEDB` en la instancia de pruebas de Compose:

```powershell
docker compose run --rm -T --no-deps -v "${PWD}/scripts/h5:/checks:ro" api python /checks/postgres_acceptance.py
```

Pruebas de navegador usando Chrome instalado y el despliegue compilado:

```powershell
cd apps/web
$env:BIB_CHROME_PATH = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
$env:BIB_E2E_CREDENTIALS = '../../.artifacts/h1/admin-credentials.json'
npx playwright test tests/operations.spec.ts --config=playwright.compose.config.ts
```

Los artefactos de navegador quedan en `.artifacts/h1/browser-tests` segun la
configuracion existente. Las pruebas simuladas cubren la confirmacion,
configuracion y fuentes; las de Compose comprueban acceso real y descarga a
traves del proxy. No ejecutan reindexaciones masivas del corpus privado.
