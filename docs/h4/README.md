# H4 — Chat fundamentado con memoria pedagógica

`/chat` permite crear, listar, renombrar y continuar conversaciones privadas del usuario autenticado, guardar preferencias pedagógicas y navegar desde cada marcador `[C1]` hasta el fragmento exacto y el original de su versión. API y web usan las mismas cookies, Origin y CSRF de H1. El original se descarga como contenido inerte; los mensajes y fragmentos se muestran como texto, sin ejecutar Markdown/HTML documental.

## Flujo de un turno

1. Una actualización condicional adquiere un lease de conversación de 125 segundos. Un segundo turno simultáneo recibe 409. Se guardan pregunta y respuesta pendiente antes de consultar modelos.
2. Para seguimientos, LiteLLM reformula una consulta autónoma a partir de los últimos seis mensajes y de un resumen extractivo acumulado de preguntas anteriores. El resumen está limitado a 4.000 caracteres; conserva intención del usuario, sin convertir respuestas anteriores en evidencia. Las referencias recientes y preferencias quedan persistidas.
3. Cada pregunta ejecuta recuperación híbrida y reranking de H3. Las trazas quedan disponibles solo para administración. La política distingue ámbitos `admin` y `usuario`; no reutiliza la calibración administrativa para usuarios.
4. Se clasifica la claridad de la consulta sin mostrar fuentes al modelo y después se comprueban cobertura y contradicciones de los fragmentos. Una pregunta ambigua pide aclaración sin generar hechos ni citas; se guarda como `abstained` con motivo `clarification_required`. Las preguntas claras requieren además una política aprobada para los modelos, corpus y ámbito vigentes y superar su umbral. Cualquier fallo de evaluación conserva la abstención. La reformulación y evaluación pueden llamar al modelo antes de esta decisión, sin responder a la pregunta.
5. Con evidencia suficiente, LiteLLM genera JSON mediante streaming: una explicación por cada pasaje seleccionado, todos en orden (el esquema lo impone con `prefixItems`); no hay explicación general sin cita. Se validan IDs, fragmentos literales, citas usadas y cifras. Después se verifica cada explicación frente a su pasaje, una llamada por afirmación en paralelo. Si el verificador rechaza alguna o hay cifras sin respaldo, se publican los extractos literales (`grounded_extract`); un JSON inválido o una cita falsa producen abstención. Ver `docs/h3/general-explanation.md`.
6. Antes del commit se comprueban otra vez publicación, versión, revisión, permisos y firma del corpus. La retirada durante la generación invalida la respuesta. Documento y versión se bloquean durante la publicación final.
7. Solo el contenido validado se envía al navegador. El protocolo NDJSON transmite `status`, `delta`, `done` o `error`; los tokens sin validar permanecen en el servidor. La sección **Explicación general** tiene estilo diferenciado. El turno completo tiene un timeout de 100 segundos.

Un error de proveedor conserva la pregunta y marca la respuesta interrumpida. Una desconexión libera el lease; tras un cierre abrupto del proceso, el siguiente turno recupera el lease caducado y marca la respuesta anterior interrumpida. Reiniciar no elimina conversaciones, resúmenes ni fuentes almacenadas. La retirada conserva la trazabilidad histórica; la eliminación impide descargar el original.

La comprobación semántica por modelo reduce el riesgo de explicaciones sin respaldo, pero no demuestra lógicamente su fidelidad. La validación de pasajes/IDs es determinista. La evaluación adversarial y el endurecimiento de este verificador continúan en H7.

## API

- `GET/POST /chat/conversations`.
- `GET/PATCH /chat/conversations/{id}`; PATCH acepta `title` y `preferences`.
- `POST /chat/conversations/{id}/messages`: `{ "content": "pregunta" }`, respuesta NDJSON.
- `GET /chat/messages/{id}/sources/{citation_id}/original`: fuente de una respuesta de la conversación propia, con comprobación de permisos.

No se entregan candidatos descartados, puntuaciones ni trazas completas al usuario. Las fuentes de las respuestas son snapshots de la versión citada, con SHA-256 original y normalizado.

## Calibración por ámbito

La inspección administrativa incorpora un selector de ámbito. `POST /admin/retrieval/search` admite `scope: "admin" | "usuario"`; `GET /admin/retrieval/policy?scope=usuario` consulta su política. `POST /admin/retrieval/calibrate` acepta el mismo `scope` y exige que todas las trazas correspondan a él. Mantiene los mínimos de clases, separación calibración/validación y rechazo conservador de H3.

La firma del corpus incorpora también los metadatos publicados: cambiar visibilidad invalida las políticas anteriores. La firma de suficiencia incorpora prompts, parámetros y modelo generativo; las políticas anteriores requieren recalibración. Las preguntas claras permanecen en abstención hasta superar el banco de evaluación de su ámbito. La calibración actual se registra en `evaluation/h3/library-calibration-{scope}.json`; el informe inicial rechazado se conserva como antecedente.

## Operación y pruebas

La migración aditiva es `0005_h4`. Actualizar con `docker compose up -d --build api worker web`, conservando los mounts de datos.

```powershell
.venv/Scripts/python.exe -m pytest apps/api/tests -q -p no:cacheprovider
cd apps/web
npm run typecheck
$env:BIB_CHROME_PATH = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
npx playwright test tests/chat.spec.ts tests/workspace.spec.ts --config=playwright.compose.config.ts --workers=1
```

El ensayo HTTP usa las credenciales locales de H1 sin imprimirlas y crea una conversación sintética, sin alterar documentos ni calibraciones:

```powershell
.venv/Scripts/python.exe scripts/h4/acceptance.py
docker compose restart api web
.venv/Scripts/python.exe scripts/h4/acceptance.py --verify-restart
docker compose cp scripts/h4/probe_generation.py api:/tmp/probe_h4.py
docker compose exec -T api python /tmp/probe_h4.py
```

La última prueba verifica streaming y verificación semántica reales con una fuente sintética, separada de la biblioteca. Ver [validación](validation.md).
