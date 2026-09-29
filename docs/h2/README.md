# H2: pipeline documental y administracion

H2 permite cargar PDF textual, DOCX, Markdown y TXT, revisar su conversion y conservar versiones y revisiones inmutables. No indexa ni publica: una aprobacion conserva `requiere_revision` y registra `reviewed_at`; H3 construira y activara el indice.

## Uso local

```powershell
docker compose up --build -d
```

Abrir `http://localhost:3000/admin/documents` con el administrador creado en H1. La cuenta y su contrasena aleatoria siguen en `.artifacts/h1/admin-credentials.json`, fuera de Git; no se modifican al actualizar H2.

La pagina Documentos permite cargar, sustituir, editar Markdown y metadatos, consultar revisiones y procedencia, descargar el original, aprobar y eliminar con confirmacion del titulo. Trabajos muestra progreso, intentos, diagnosticos y eventos; permite cancelar conversiones o crear un nuevo trabajo de reintento. El historial del trabajo terminal permanece intacto. Los cuadros de confirmacion mantienen el foco y se cierran con Escape.

## Garantias

- Carga solo administrativa con sesion, Origin, CSRF e idempotencia. Nombres, extension, MIME, contenido, UTF-8, estructura XML/ZIP y limites se comprueban antes de crear la version. PDF cifrados, rutas de archivo peligrosas, macros DOCX y archivos corruptos se rechazan.
- Originales y cada revision normalizada se guardan bajo identificadores internos, con SHA-256. Una edicion no sobrescribe el original ni el Markdown anterior. Cada revision incluye una instantanea de metadatos y numero monotono.
- Una sustitucion agrega una version al mismo documento. Las mutaciones del borrador se serializan con la sustitucion y la eliminacion.
- La cola PostgreSQL usa `FOR UPDATE SKIP LOCKED`, propietario, lease y generacion. Un resultado tardio no se confirma; un lease vencido se recupera tras reiniciar. Tres intentos automaticos como maximo; el reintento manual crea un trabajo nuevo vinculado al anterior.
- Conversion en proceso hijo con timeout y cancelacion. La persistencia del resultado exige propiedad vigente y estado no cancelado. El heartbeat del worker es independiente de la conversion.
- Los PDF conservan pagina y seccion; DOCX conserva seccion, no paginas inventadas. Los mapas identifican lineas del Markdown normalizado. Bloques editados o ambiguos pierden la pagina original y se marcan `manual`.
- La vista previa omite HTML e imagenes, y no descarga imagenes remotas. Los originales se sirven como adjuntos, no como HTML.
- Retirar desactiva la version publicada. Eliminar exige titulo exacto, ausencia de trabajos y version activa, y retencion cumplida. Las versiones alguna vez publicadas requieren 90 dias desde la retirada; los borradores nunca publicados pueden eliminarse tras acabar/cancelar sus trabajos. Queda una tumba sin contenido ni metadatos personales y la auditoria.

## Limites y configuracion

Por defecto: carga 100 MiB, DOCX expandido 250 MiB, PDF 1000 paginas, Markdown normalizado 20 MiB, conversion 180 segundos, lease 30 segundos. Las opciones se documentan en `.env.example` y `bibliotecario/config.py`.

El progreso representa etapas y renovaciones del trabajo, no un contador exacto de paginas. No hay OCR automatico: paginas sin texto generan `possible_ocr_page_N`, y un documento vacio no se puede aprobar. Imagenes, ciertos encabezados/pies, numeracion y tablas complejas pueden requerir correccion manual; se conservan diagnosticos y el original descargable. No se garantiza fidelidad visual de cualquier PDF.

No se han implementado cuotas globales, antivirus, limpieza de archivos huerfanos tras corte entre filesystem y transaccion, ni indexacion. Las escrituras fallidas ordinarias limpian sus propios archivos; un corte abrupto puede dejar archivos sin referencia, nunca contenido publicado. Estos asuntos se deben cerrar antes del despliegue de produccion (H6/H7).

## Validacion reproducible

```powershell
.venv/Scripts/python.exe -m pytest apps/api/tests -q
.venv/Scripts/python.exe scripts/h2/evaluate_conversion.py
.venv/Scripts/python.exe scripts/h2/acceptance.py
$env:BIB_E2E_CREDENTIALS = "$PWD/.artifacts/h1/admin-credentials.json"
$env:BIB_CHROME_PATH = "C:/Program Files/Google/Chrome/Application/chrome.exe"
Set-Location apps/web
npx playwright test --output=../../.artifacts/h2/browser-tests --workers=1
```

La aceptacion real crea y elimina exclusivamente documentos sinteticos. Detiene y arranca solo el worker de este Compose para probar recuperacion; ejecutar sin otros trabajos de ingesta en curso. No toca los contenedores de modelos. La matriz usa los originales privados de `docs/` y variantes de H0, verifica sus hashes y no los carga en la base de datos. Informes y capturas quedan en `.artifacts/h2/`, ignorado por Git.

Ver [resultados y diferencias de extraccion](validation.md).
