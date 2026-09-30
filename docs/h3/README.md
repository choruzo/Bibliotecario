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

Todas estas rutas requieren sesión administrativa; las operaciones POST requieren Origin y CSRF. No se llama al modelo generativo.

## Suficiencia y evaluación

La política inicial es **abstenerse**. No se configura un umbral manual. `POST /admin/retrieval/calibrate` recibe un banco de al menos 24 trazas etiquetadas, con las cuatro clases de H0, y calcula la política a partir de las puntuaciones observadas. Rechaza trazas antiguas, filtradas o de otros modelos/corpus.

Cada caso contiene `id`, `run_id`, `kind`, `language`, `expected_documents` (IDs de la biblioteca), `expected_sections` y, para conversación, `conversation_id`. El comportamiento esperado deriva de la clase. Se separan calibración y validación por IDs dentro de cada clase, manteniendo los grupos conversacionales juntos. Solo se habilita un umbral si no produce respuestas indebidas en ninguno de los dos grupos, responde al menos un positivo en ambos y los casos aceptados recuperan todos sus localizadores esperados en los diez primeros resultados.

La política está ligada a firmas del corpus activo y de la configuración de modelos/algoritmo. Cambiar versiones, retirar contenido o cambiar la configuración invalida su uso. H4 añade firmas sensibles a metadatos y calibración separada por ámbito `admin`/`usuario`; las consultas filtradas siguen sin calibración propia. Las firmas identifican configuración y revisiones, no detectan una sustitución de pesos que conserve exactamente el mismo nombre/URL: ese cambio requiere reindexar y recalibrar.

`GET /admin/retrieval/policy` devuelve la política vigente. La pantalla indica si falta calibración. Los casos ambiguos permanecen en abstención; pedir aclaración y reformular seguimientos forma parte de H4. Se mide esa limitación explícitamente.

### Evaluación de la biblioteca revisada

Tras publicar una única copia de cada fuente de H0 y revisarla:

```powershell
.venv/Scripts/python.exe scripts/h3/calibrate_library.py
```

El script comprueba los hashes originales contra el catálogo y ejecuta las 24 consultas mediante la API. Guarda las trazas en PostgreSQL y el informe privado en `.artifacts/h3/library-calibration.json`. Usa la cuenta local de `.artifacts/h1/admin-credentials.json`, sin imprimir credenciales. No carga ni aprueba documentos.

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
