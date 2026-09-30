# H3 — Indexación y recuperación medible

La administración permite publicar una revisión aprobada, reindexarla e inspeccionar consultas en `/admin/retrieval`. El chat está implementado en [H4](../h4/README.md) y utiliza esta puerta de suficiencia.

## Publicación

1. Cargar, convertir y revisar el documento con H2.
2. Marcar la revisión vigente como revisada.
3. Pulsar **Publicar**. Se crea un trabajo persistente `index`.
4. El worker segmenta por bloques Markdown y conserva página, sección, líneas y origen manual/original. Los bloques que exceden el presupuesto se dividen, conservando el texto y sus localizadores; una tabla o bloque de código pequeño permanece íntegro. Conserva también los bloques HTML como texto inerte: cuando H2 no tiene mapa de origen, cita líneas de la revisión normalizada sin inventar una página. Antes de generar vectores comprueba conservación y orden de todo el texto no blanco.
5. Cada entrada tiene como máximo 900 bytes UTF-8, incluyendo hasta 180 bytes de contexto de encabezados. Se comprueba además el tokenizer real de llama.cpp con `search_document: ` y un máximo de 1.000 tokens, dejando margen en el contexto de 1.024. Un desbordamiento falla explícitamente.
6. Se generan embeddings Nomic de 768 dimensiones. La transacción final inserta todos los fragmentos, retira la versión anterior y activa la nueva. Los fallos, cancelaciones y leases obsoletos no escriben vectores parciales ni activan la revisión.

Una reindexación conserva el índice activo hasta el commit. Retirar un documento cambia inmediatamente su puntero de publicación. Una indexación pendiente no puede deshacer esa retirada: verifica el puntero y la revisión capturados al encolarse. Los archivos originales no cambian.

## Recuperación e inspección

- `POST /admin/retrieval/search`: `{ "query": "consulta", "limit": 10 }`; acepta un `document_id` opcional.
- Nomic recibe `search_query: `; también se valida su límite con `/tokenize`.
- PostgreSQL obtiene hasta 30 candidatos vectoriales por distancia coseno y 30 por búsqueda textual española (`websearch_to_tsquery`, índice GIN).
- Se fusionan mediante Reciprocal Rank Fusion, constante 60, sin duplicar IDs de fragmento. Los 30 primeros se envían a BGE mediante `/v1/rerank`, con contexto de encabezados.
- Ambos canales usan el mismo snapshot PostgreSQL y filtros de publicación, eliminación y visibilidad. Tras el reranker se comprueba de nuevo la vigencia. Si el corpus cambia durante la consulta, la decisión pasa a abstención.
- Las búsquedas usan distancia vectorial exacta para el corpus pequeño del MVP; no hay índice aproximado HNSW.
- La pantalla muestra fragmentos, citas, scores originales y fusionados, ranking, decisión, tiempos y enlace al original. Las trazas completas quedan en PostgreSQL, accesibles únicamente a administración.
- `GET /admin/retrieval/runs` y `/runs/{id}` permiten inspeccionar historial y errores.

Todas estas rutas requieren sesión administrativa; las operaciones POST requieren Origin y CSRF. La inspección llama al modelo local para evaluar ambigüedad y suficiencia, sin generar una respuesta documental.

## Suficiencia y evaluación

La política inicial es **abstenerse**. No se configura un umbral manual. `POST /admin/retrieval/calibrate` recibe un banco de al menos 24 trazas etiquetadas, con las cuatro clases de H0, y calcula la política a partir de las puntuaciones observadas. Rechaza trazas antiguas, filtradas o de otros modelos/corpus.

Cada caso contiene `id`, `run_id`, `kind`, `language`, `expected_documents` (IDs de la biblioteca), `expected_sections` y, para conversación, `conversation_id`. El comportamiento esperado deriva de la clase. El campo opcional `split: calibration | validation` permite reservar un banco nuevo completo para validación; si se utiliza, debe aparecer en todos los casos y no dividir una conversación. Sin ese campo se conserva la separación por IDs dentro de cada clase. Solo se habilita un umbral si no hay errores ni respuestas indebidas en ninguno de los dos grupos, responde al menos un positivo en ambos y los casos aceptados recuperan todos sus localizadores esperados en los diez primeros resultados.

Antes del umbral, `sufficiency.py` clasifica la pregunta sin mostrar documentos al modelo. Una pregunta ambigua produce una petición fija de aclaración, sin citas ni respuesta factual. Para preguntas claras, una segunda evaluación exige cobertura completa, ausencia de contradicciones y referencias a fragmentos recibidos. El servidor conserva sus pasajes originales; no pide al modelo que los copie. Fallos de proveedor, JSON inválido o referencias inexistentes producen abstención y bloquean la aprobación de la calibración. Estas evaluaciones usan temperatura cero.

La política está ligada a firmas del corpus activo y de la configuración de modelos/algoritmo. Cambiar versiones, retirar contenido o cambiar la configuración invalida su uso. H4 añade firmas sensibles a metadatos y calibración separada por ámbito `admin`/`usuario`; las consultas filtradas siguen sin calibración propia. Las firmas identifican configuración y revisiones, no detectan una sustitución de pesos que conserve exactamente el mismo nombre/URL: ese cambio requiere reindexar y recalibrar.

`GET /admin/retrieval/policy` devuelve la política vigente. La pantalla distingue abstención y aclaración. La firma de políticas incluye los prompts de suficiencia, temperatura y URL/nombre del modelo generativo, además de la configuración de recuperación. Cambiar esa evaluación invalida políticas sin obligar a regenerar los vectores. La semántica del juicio sigue dependiendo del modelo: referencias válidas no prueban por sí solas cobertura o ausencia de contradicciones.

### Evaluación de la biblioteca revisada

Tras publicar una única copia de cada fuente de H0 y revisarla:

```powershell
.venv/Scripts/python.exe scripts/h3/publish_catalog.py
.venv/Scripts/python.exe scripts/h3/calibrate_library.py --scope admin
.venv/Scripts/python.exe scripts/h3/calibrate_library.py --scope usuario
```

`publish_catalog.py` comprueba todos los hashes antes de cargar fuentes, reutiliza versiones coincidentes sin alterar documentos ajenos, verifica el original, la igualdad exacta del Markdown convertido, diagnósticos y localizadores, y marca revisada/publica cada fuente. Se ejecuta únicamente con autorización para esa publicación. Conflictos, cambios manuales o fallos detienen el proceso; los documentos ya publicados se conservan.

`calibrate_library.py` requiere una publicación única de cada fuente. Evalúa las 24 preguntas H0 como calibración y las 24 preguntas nuevas de `validation-v2.jsonl` como validación independiente (`--validation-bank` permite indicar otro banco). El intento con `validation-v1.jsonl` se conserva como rechazado en `attempt-v1-admin.json`; no se reutiliza para aprobar la versión posterior. Los seguimientos usan la misma reformulación de H4 con intención previa del usuario (`previous_questions`, máximo seis preguntas); no simulan respuestas previas como evidencia. Guarda trazas en PostgreSQL, informes privados en `.artifacts/h3/library-calibration-{scope}.json` e informes sin preguntas ni fragmentos en `evaluation/h3/library-calibration-{scope}.json`. Usa la cuenta local de H1 sin imprimir credenciales. No carga ni aprueba documentos. La calidad de las respuestas finales del chat se comprueba aparte.

La clasificación y suficiencia solicitan salida JSON restringida por esquema al proveedor, incluidas referencias limitadas a los fragmentos recibidos. La API vuelve a validar tipos, referencias y coherencia del resultado. Se registran categorías de error sin exponer detalles del proveedor; un fallo nunca se convierte en evidencia suficiente.

El cliente y proxy usan 60 segundos por petición; el chat mantiene 100 segundos por turno. Las decisiones estructuradas usan `BIB_SUFFICIENCY_REASONING_EFFORT=low`, configurable como `low`, `medium`, `high` o `disabled` si el proveedor no admite el parámetro. Presupuestos, esquemas, timeout y esfuerzo de razonamiento están ligados a la firma de política. Cambiarlos requiere recalibrar. Los tokens de razonamiento se incluyen en los límites de generación: una respuesta incompleta se rechaza aunque parezca JSON válido.

### Ensayo aislado reproducible

```powershell
docker compose cp docs api:/tmp/h3/docs
docker compose cp evaluation api:/tmp/h3/evaluation
docker compose cp scripts/h3/evaluate.py api:/tmp/evaluate_h3.py
docker compose exec -T api python /tmp/evaluate_h3.py
docker compose cp api:/tmp/h3-report.json .artifacts/h3/evaluation.json
docker compose cp api:/tmp/h3-traces.json .artifacts/h3/evaluation-traces.json
```

Antes de las copias: `docker compose exec -T api mkdir -p /tmp/h3`. El evaluador crea una base PostgreSQL temporal con todas las migraciones, comprueba SHA-256, indexa los 13 Markdown y usa los modelos reales. Al terminar elimina únicamente su base temporal. Los originales y publicaciones existentes no se modifican. Los fragmentos/trazas privados quedan fuera de Git en `.artifacts/`; el informe sin extractos está versionado en `evaluation/h3/results.json`.

Recall@5/10 cuenta localizadores distintos esperados (documentos y secciones); repetir fragmentos no aumenta cobertura. MRR@10 mide el primer documento/localizador esperado. nDCG@10 usa relevancia binaria de documento y sección dentro del conjunto de candidatos recuperados, y por tanto debe leerse junto a Recall. Se registran métricas por clase, idioma/formato del ensayo, decisiones, errores y latencias p50/p95/máximo por etapa. El corpus probado es Markdown español; no se extrapola a otros idiomas ni a PDF/DOCX cuya fidelidad sigue pendiente en H2.

Ver [resultados y límites del ensayo](validation.md).

## Validación técnica

```powershell
.venv/Scripts/python.exe -m pytest apps/api/tests -q -p no:cacheprovider
.venv/Scripts/python.exe scripts/h3/acceptance.py
cd apps/web
npm run typecheck
$env:BIB_E2E_CREDENTIALS = "D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/h1/admin-credentials.json"
$env:BIB_CHROME_PATH = "C:/Program Files/Google/Chrome/Application/chrome.exe"
npx playwright test tests/retrieval.spec.ts --config=playwright.compose.config.ts --output=../../.artifacts/h3/browser-tests --workers=1
```

En este Windows, pytest necesitó ejecutarse fuera del sandbox debido a permisos de directorios temporales. No se borraron los directorios inaccesibles heredados. El ensayo HTTP y el navegador crean documentos sintéticos que se dejan retirados, respetando el plazo de retención de H2.

La migración es `0004_h3`. `BIB_INDEX_TIMEOUT_SECONDS` limita cada intento de indexación (900 segundos por defecto); se mantienen los leases, renovación, cancelación y reintentos de H2. Los modelos deben ofrecer `/tokenize` además de embeddings/reranking. La dimensión H3 es fija en PostgreSQL (`vector(768)`).
