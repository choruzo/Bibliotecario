# Traspaso para la siguiente sesión (RAG Bibliotecario)

Redactado el 2026-10-01 para pegarlo como *prompt* inicial de una sesión limpia de Claude Code.
Último commit de referencia: `f75b681 fix: pin images by digest and migrate generation to Gemma 4` (prioridad 1 hecha; ver `docs/h3/model-pinning-gemma.md`).

## Encargo

Seguir mejorando el RAG para que funcione bien con documentos de **cualquier dominio**, no solo con el corpus técnico interno. Trabaja por prioridades (sección «Plan»), valida cada cambio con datos reales y no solo con pruebas unitarias, y documenta cada iteración en `docs/h3/<tema>.md`. Antes de hacer commit y push a `main`, valida que no hay regresiones (sección «Validación obligatoria»). Responde siempre en español.

## Contexto mínimo del sistema

- **Stack**: FastAPI (`apps/api/bibliotecario`), Next.js (`apps/web`), PostgreSQL con pgvector y un *worker*, todo en Docker Compose (`compose.yaml`). Los modelos son locales y corren en el host:
  - generación: Gemma 4 12B NVFP4 (`gemma-4-12b-it`) en vLLM, contenedor `gemma4-12b-vllm` en `:8080`, lanzado con `G:\models\launch-gemma4-12b-vllm.ps1 -Detach` (incluye `--reasoning-parser gemma4`), a través de litellm. Razonamiento desactivado (`BIB_SUFFICIENCY_REASONING_EFFORT=disabled`): con él cada evaluación tarda 70-130 s;
  - embeddings: nomic-embed-text-v1.5, 768 dimensiones, en `:8081`;
  - reranker: bge-reranker-v2-m3 en `:8082`.
- **Flujo de una pregunta** (`chat.py` → `retrieval.py` → `sufficiency.py`):
  1. Reformulación: `contextual_query`. En el primer turno es determinista (`normalize_query`); en los seguimientos usa el LLM con `last_user_question` y controles (`missing_terms`, `needs_context`, `adds_context` en `query.py`), con hasta 3 intentos.
  2. Búsqueda híbrida: vector + `websearch_to_tsquery` con OR (`lexical_query`), fusión RRF, ampliación de contexto (60 fragmentos / 36.000 bytes) y reranker.
  3. `assess`: salvaguardas deterministas (`requires_specific_context`, incluida la de referentes sin sujeto), clasificación de intención (primero la pregunta sola y después con títulos y apartados) y evaluación de cobertura con JSON estructurado que selecciona `support`.
  4. `evidence_decision`: busca una política calibrada exacta o heredada (`find_policy`) y compara la puntuación del reranker con el umbral.
  5. Generación con un esquema que empareja cada cita con su pasaje literal.
  6. `validate_answer`: citas exactas, cifras presentes en los pasajes (`numbers`) y cobertura de todos los pasajes.
  7. `verify_grounding` con el LLM. Si se rechaza (`grounding_rejected`, `incomplete_answer` o `unsupported_number`), se recurre a `extractive_answer` con los extractos literales.
  8. Antes de publicar se comprueban de nuevo la vigencia y los permisos.
- **Calibración**: `scripts/h3/calibrate_library.py`, con los bancos `evaluation/h3/colloquial-calibration-v1.jsonl` (32 casos) y `colloquial-validation-v1.jsonl` (31). Con Gemma tarda unos 6 minutos por ámbito (`admin` y `usuario`) y los ámbitos deben ejecutarse **en secuencia**, porque el LLM es único.
  - Cualquier cambio en *prompts*, en `VERSION` o en las constantes del contrato que se incluyen en `policy_signature` invalida las políticas: hay que recalibrar o el chat se abstiene con `uncalibrated`.
  - Si un caso falla por `provider_timeout`, quítalo del *checkpoint* `.artifacts/retrieval-fix/calibration-progress-<scope>.json` y relanza con `--resume`; así solo se reevalúa ese caso.
- **Estado actual** (políticas aprobadas):

  | Ámbito | Umbral | Validación |
  | --- | ---: | --- |
  | admin | −1,2895 | 46/46 positivos, 0 indebidas, 17/17 negativos (técnico + agnóstico) |
  | usuario | −1,2895 | 46/46 positivos, 0 indebidas, 17/17 negativos (técnico + agnóstico) |

  Aceptación de chat: `scripts/h4/colloquial_acceptance.py`, 13 de 13; `scripts/h4/agnostic_acceptance.py`, 62 de 64. Último cambio: `docs/h3/chunk-grouping.md`. Detalle anterior en `docs/h3/domain-agnostic-pdf-fix.md`; los informes anteriores, en `docs/h3/calibration-fix.md` y `docs/h3/colloquial-retrieval-fix.md`.
- **Biblioteca publicada**: 13 documentos técnicos internos (H0) y los 17 PDF del corpus agnóstico (catálogo `evaluation/h3/agnostic_corpus_catalog.json`; la abeja es `89f7cc5a-4436-4e3b-be85-f44d13c01886`, versión 2). Calibrar siempre con los cuatro bancos y los dos catálogos (comando en `docs/h3/agnostic-evaluation.md`).

## Corpus agnóstico descargado (no publicado todavía)

Está en `.artifacts/agnostic-corpus/`, carpeta ignorada por Git. Todos son de licencia abierta: Wikipedia es CC BY-SA, el BOE es público y arXiv permite el uso académico. El archivo `baseline.json` recoge la conversión actual de cada uno. Las columnas «Tablas rec.», «Texto rec.» y «Pérdida» indican cuántas páginas tienen tablas reconstruidas, texto recuperado o pérdida residual:

| Archivo | Dominio | Págs. | Tablas | Tablas rec. | Texto rec. | Pérdida | Fragmentos |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| wiki-Apis_mellifera.pdf | biología (ya publicado) | 11 | 4 | 2 | 3 | 0 | 169 |
| wiki-Sistema_solar.pdf | astronomía | 15 | 6 | 0 | 7 | 1 | 263 |
| wiki-Diabetes_mellitus.pdf | medicina | 30 | 2 | 0 | 5 | 0 | 483 |
| wiki-Tabla_periódica_de_los_elementos.pdf | química | 33 | 14 | 1 | 12 | 2 | 448 |
| wiki-Copa_Mundial_de_Fútbol.pdf | deporte (muchas tablas) | 37 | 30 | 13 | 13 | 2 | 560 |
| wiki-Impuesto_sobre_la_renta_…España.pdf | fiscalidad | 26 | 2 | 0 | 0 | 0 | 335 |
| wiki-Revolución_francesa.pdf | historia | 40 | 1 | 0 | 10 | 2 | 498 |
| wiki-Fotosíntesis.pdf | biología vegetal | 22 | 1 | 0 | 2 | 0 | 232 |
| wiki-Dieta_mediterránea.pdf | nutrición | 8 | 1 | 0 | 2 | 1 | 92 |
| wiki-Python.pdf | informática | 24 | 8 | 0 | 5 | 2 | 284 |
| wiki-Inflación.pdf | economía | 11 | 3 | 0 | 5 | 0 | 197 |
| wiki-Volcán.pdf | geología | 18 | 0 | 0 | 0 | 0 | 208 |
| wiki-Café.pdf | agroalimentación | 47 | 4 | 2 | 6 | 1 | 605 |
| boe-constitucion-1978.pdf | derecho (texto consolidado) | 39 | 0 | 0 | 1 | 0 | 725 |
| boe-ley-propiedad-horizontal.pdf | derecho | 20 | 0 | 0 | 0 | 0 | 350 |
| arxiv-attention-is-all-you-need-en.pdf | IA, inglés, 2 columnas | 15 | 6 | 1 | 8 | 3 | 325 |
| arxiv-bert-en.pdf | IA, inglés, 2 columnas | 16 | 19 | 2 | 16 | **12** | 435 |

`bee_chat_check.py`, en la misma carpeta, es el script de comprobación de la abeja. `republish` sube una nueva versión del PDF, la revisa y la publica; `chat` lanza 6 preguntas y comprueba el estado, las cifras citadas y el sujeto conservado. Sirve de plantilla para el arnés general (prioridad 2).

**Hallazgos de esa conversión que aún no están corregidos:**
- ~~Los fragmentos son minúsculos~~: corregido por la prioridad 3.
- Los PDF de arXiv a dos columnas pierden texto y ecuaciones en muchas páginas.
- La conversión es lenta: hasta 64 s para 37 páginas, en parte porque `recover_pdf_page` llama a `find_tables` en todas las páginas.

## Plan, por prioridad

Cada punto incluye su criterio de aceptación. No pases al siguiente sin medir el anterior.

1. ~~**Fijar versiones de imágenes.**~~ Hecho en `f75b681`. En `.env` y `compose.yaml`, `LITELLM_IMAGE` usa la etiqueta móvil `ghcr.io/berriai/litellm:main-stable`; al volver a descargarla pasó a la versión 1.103.2 y el modelo empezó a devolver los seguimientos sin reformular. Fíjala por versión o *digest*, y haz lo mismo con `pgvector/pgvector`.
   - *Aceptación*: `docker compose config` muestra *digests* o versiones exactas y la aceptación coloquial sigue en 13 de 13.
2. ~~**Banco de evaluación agnóstico y arnés reproducible.**~~ Hecho; ver `docs/h3/agnostic-evaluation.md`. Corpus publicado (`AGN-001`…`AGN-017`, `scripts/h4/publish_agnostic.py`), bancos `agnostic-{calibration,validation}-v1.jsonl`, calibración combinada aprobada en ambos ámbitos (umbral −1,2932, 0 indebidas) y `scripts/h4/agnostic_acceptance.py` 61/64 (fallos: translingüe de la reina y dos irrespondibles personales que piden aclaración). La prioridad 8 quedó medida: con la política heredada, 61/64 y 0 indebidas.
   - Publica los PDF anteriores mediante la API: `POST /admin/documents` y después revisar y publicar, como en `bee_chat_check.py republish`.
   - Crea `evaluation/h3/agnostic-calibration-v1.jsonl` y `agnostic-validation-v1.jsonl`, con unos 30 casos cada uno: respondibles (incluidos datos de tablas), irrespondibles y con premisa falsa, ambiguos, seguimientos («¿Y …?», «¿Cuánto…?», «en ese documento…»), preguntas en inglés en primer turno y preguntas coloquiales sí/no.
   - Ningún grupo conversacional debe repartirse entre los dos bancos. Respeta los mínimos de H0 por clase (answerable 10, unanswerable 5, ambiguous 3, conversation 6) en cada banco.
   - Extiende `calibrate_library.py` para combinar varios bancos, o crea un script nuevo. Hoy exige que las 13 fuentes H0 estén publicadas y mapea `expected_documents` desde `evaluation/h0/corpus_catalog.json`; hará falta un catálogo para el corpus agnóstico.
   - Convierte `bee_chat_check.py` en `scripts/h4/agnostic_acceptance.py`. Para cada respuesta debe comprobar: estado esperado, que cada cita coincida literalmente con su pasaje, que las cifras de la respuesta aparezcan en los pasajes (`bibliotecario.chat.numbers`), que se conserve el sujeto en los seguimientos y que el SHA-256 del original coincida.
   - *Aceptación*: calibración aprobada en los dos ámbitos con el banco técnico y el agnóstico, 0 respuestas indebidas y resultados por dominio en un informe.
3. ~~**Agrupar bloques pequeños al trocear**~~ Hecho; ver `docs/h3/chunk-grouping.md`. 3852 fragmentos de 624 B de media (antes 7658 de 347), recall@10/nDCG técnico 0,879/0,750 (antes 0,838/0,744), agnóstico 62/64. Pendiente: `EVAL-A006` se abstiene ahora (falso negativo seguro). (`chunking.py`) Une bloques consecutivos del mismo `section_path` hasta el presupuesto y conserva todos los localizadores (`provenance`) de los bloques unidos. Mantén la comprobación de cobertura de `build_index` y la regla de cortes de `break_point`. Plantéate subir `CHUNK_BYTES` (el embedding admite hasta 1000 tokens con su prefijo; compruébalo con `embedding_tokens`).
   - *Aceptación*: tamaño medio de fragmento mayor de 500 bytes, ningún corte a mitad de palabra ni de enlace, y recall10/nDCG del banco técnico iguales o mejores. Requiere reindexar (`POST /admin/operations/reindex` con `confirmation: "REINDEXAR"`) y recalibrar.
4. **Eliminar o restringir la «explicación general».** Es por donde más se cuela contenido no respaldado (p. ej., «la larva recibe alimento especializado»). Además, muchas respuestas acaban en `grounded_extract`, que es seguro pero muy literal (6 de 8 en la aceptación). Mide antes y después qué proporción de respuestas queda como `grounded` frente a `grounded_extract`, y por qué motivo.
   - *Aceptación*: más respuestas `grounded`, 0 cifras no respaldadas y 0 regresiones en la aceptación.
5. **Reducir llamadas al LLM.** Fusiona la intención y la suficiencia en una sola llamada estructurada, y no reformules cuando `needs_context` sea falso y no haya historial relevante. Las latencias por fase están en `result.latency` de cada `RetrievalRun`.
   - *Aceptación*: p50/p95 de latencia del chat medidos antes y después, y la misma calidad en los bancos.
6. **Conversión PDF.** Compara `pymupdf_layout`, que la propia librería recomienda en sus avisos, o el modo no *legacy* de pymupdf4llm frente a la recuperación heurística actual. Usa el corpus agnóstico, sobre todo arXiv, el Mundial y la tabla periódica. Mide la cobertura de palabras por página, las tablas correctas y el tiempo de conversión. Limita `find_tables` a las páginas con pérdida detectada.
   - *Aceptación*: menos páginas con `pdf_text_loss`, tablas con correspondencia correcta entre fila y columna y conversión más rápida.
7. **Primeras preguntas en otro idioma.** «How long does a queen bee live?» se abstenía en primer turno porque no se traduce; con la agrupación de fragmentos ya se responde, pero el comportamiento translingüe sigue dependiendo de la pregunta. Valora traducir o normalizar en el primer turno solo cuando el idioma no sea español, y añade estos casos a los bancos.
8. **Política heredada.** Mide en la práctica si heredar el umbral al publicar documentos nuevos introduce respuestas indebidas: publica el corpus agnóstico con la política heredada y pasa el banco agnóstico antes de recalibrar.

## Validación obligatoria antes de commit y push

1. Pruebas del API:

   ```bash
   cd apps/api && ../../.venv/Scripts/python.exe -m pytest -q --basetemp=<scratchpad>/pytest -p no:cacheprovider
   ```

   Hoy pasan 120. El `--basetemp` hace falta porque el sandbox impide crear temporales en el directorio por defecto.
2. Pruebas de la raíz: `.venv/Scripts/python.exe -m pytest -q tests` (pasan 4).
3. Web: `cd apps/web && npx tsc --noEmit` y Playwright. El navegador de Playwright no está instalado; usa el Chrome del sistema:

   ```bash
   BIB_CHROME_PATH="C:/Program Files/Google/Chrome/Application/chrome.exe" npx playwright test tests/documents.spec.ts tests/retrieval.spec.ts tests/chat.spec.ts tests/operations.spec.ts tests/workspace.spec.ts tests/accessibility.spec.ts
   ```

   Hoy pasan 18 y se omiten 6, los del modo Compose.
4. Despliegue: `docker compose up -d --build api worker web`, y espera a que el estado sea *healthy*.
5. Si cambia la firma de política, recalibra los dos ámbitos en secuencia; si cambia el troceado, reindexa primero.
6. Aceptación de chat: `.venv/Scripts/python.exe scripts/h4/colloquial_acceptance.py` debe dar 13 de 13, más el arnés agnóstico cuando exista.
7. Actualiza `docs/h3/<tema>.md` con los resultados reales, incluidos los fallos y las repeticiones operativas.

## Avisos del entorno (Windows)

- Docker Desktop guarda su disco en `F:\DockerData` (`CustomWslDistroDir`). F: tiene unos 111 GB; si se llena, el motor pasa a solo lectura y no arranca. Revisa `docker system df` y el espacio libre de F: si los *builds* fallan con «read-only file system».
- Los datos persistentes (PostgreSQL y documentos) están en `BIB_DATA_DIR=D:/Archivos/Javier/Proyectos/Bibliotecario/bibliotecario-data`, montados como *bind mounts*. Sobreviven a un reinicio del disco de Docker.
- Los contenedores `api` y `worker` son de solo lectura; solo `/tmp` admite escritura. Para depurar dentro del contenedor, usa `docker compose exec -T api python - < script.py`.
- PostgreSQL no publica su puerto. Para consultar: `docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "..."'`. La columna `result` de `retrieval_runs` es `json`, no `jsonb`.
- Las credenciales de administrador para los scripts están en `.artifacts/h1/admin-credentials.json`. La API se usa a través de la web, en `http://localhost:3000/api`, con la cabecera `Origin` y `X-CSRF-Token` (se obtiene de `/auth/me`).
- `docs/*.md` está en `.gitignore`, porque ahí vive el corpus interno; la documentación versionada va en `docs/h*/`. Nunca subas a Git `.artifacts/` ni el corpus.
- No envíes el correo del usuario a servicios externos (por ejemplo, en el User-Agent de una descarga).
- Usa el directorio *scratchpad* para los temporales. El shell es PowerShell, con Bash (Git Bash) también disponible.
