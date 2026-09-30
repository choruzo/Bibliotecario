# Validación de H3

Ensayo local realizado entre el 29 y el 30 de septiembre de 2026 (Europe/Madrid), en Windows y Docker Compose. PostgreSQL/pgvector, Nomic y BGE reales; ninguna llamada al generador. El informe sin extractos está en [`evaluation/h3/results.json`](../../evaluation/h3/results.json). Las trazas completas privadas y capturas permanecen en `.artifacts/h3/`.

## Resultado funcional

- 13 fuentes Markdown verificadas por SHA-256; 1.448 fragmentos con embeddings de 768 dimensiones.
- Conservación y orden de todo el texto no blanco comprobados en las 13 fuentes. Se corrigió la omisión de bloques HTML presentes en una fuente: se conservan como texto inerte con localizadores de la revisión normalizada.
- Publicación y sustitución transaccionales, sin vectores parciales. Reindexar mantiene el índice anterior hasta el commit.
- Cancelación, reintentos, revisión obsoleta, lease obsoleto y retirada durante reindexación cubiertos por pruebas.
- Prueba HTTP con worker real: publicación, recuperación por ambos canales, traza persistente, sustitución, reindexación y exclusión tras retirada, todas correctas.
- Pantalla de inspección probada en Chrome de escritorio y móvil: publicación del documento concreto, búsqueda, puntuaciones, original, IDs de cita y retirada; sin desbordamiento horizontal.
- API, web, worker, PostgreSQL y LiteLLM quedaron `healthy`. La migración activa es `0004_h3`.

## Recuperación

Banco: 24 consultas, 10 respondibles, 5 no respondibles, 3 ambiguas y 6 turnos conversacionales. Cero errores de ejecución. Los seguimientos se consultan tal como están escritos: no se implementa aún la reformulación contextual de H4.

| Clase | Recall@5 | Recall@10 | MRR@10 | nDCG@10 |
|---|---:|---:|---:|---:|
| Respondibles | 0,7833 | 0,9067 | 0,9143 | 0,7013 |
| Conversación, consultas sin reformular | 0,6111 | 0,6111 | 0,4722 | 0,4985 |

Recall cuenta documentos y secciones esperadas distintas; MRR considera el primer documento/localizador esperado. nDCG usa relevancia binaria de documento/sección en el conjunto de candidatos: no reemplaza la medición de cobertura del corpus. Las métricas de consultas ambiguas se conservan como diagnóstico, no como prueba de que deban responderse.

Cobertura incompleta en `EVAL-A007`, `EVAL-A009`, `EVAL-C001-T3`, `EVAL-C002-T2` y `EVAL-C002-T3`. Los dos primeros justifican mejorar segmentación/recuperación; los turnos de seguimiento también dependen del contexto aún pendiente en H4.

## Suficiencia: umbral rechazado

La separación conserva cada conversación en un único grupo: 13 casos de calibración y 11 de validación. El candidato empírico **2,052673** es una puntuación del reranker, no una probabilidad. En calibración admite 3 positivos sin falsos positivos, pero en validación admite **0 positivos y una consulta ambigua (`EVAL-M002`)**. Por tanto, **no se aprueba ni se activa**.

La política efectiva sigue siendo abstenerse: 0 respuestas indebidas en las 5 preguntas no respondibles; cobertura de respuesta efectiva 0/16 casos respondibles/conversacionales. La exactitud binaria global es 8/24 = 0,3333 y F1 de responder es 0. Las 3 consultas ambiguas se abstienen; exactitud de pedir aclaración 0/3, porque ese comportamiento aún no está implementado. Estas cifras son una limitación explícita, no una aprobación de suficiencia.

H3 deja el buscador medible y la calibración reproducible, pero **queda pendiente obtener una política de suficiencia validada** antes de habilitar respuestas documentales en H4. No se ajustó el umbral al conjunto de validación para ocultar su fallo.

## Latencia de la última ejecución

Milisegundos, 24 consultas en el entorno local. Otras pruebas compartieron los servicios durante el ensayo; no es un benchmark de capacidad ni un SLA.

| Etapa | p50 | p95 | Máximo |
|---|---:|---:|---:|
| Tokenizer y embedding de consulta | 50,99 | 110,82 | 196,30 |
| Búsqueda PostgreSQL | 21,97 | 28,26 | 35,50 |
| Fusión y materialización | 57,78 | 70,95 | 122,89 |
| Reranking | 185,30 | 223,48 | 261,72 |

## Pruebas

- API H1–H3: **56 pasadas**, con una advertencia heredada de deprecación de Starlette/httpx.
- `npm run typecheck`: correcto.
- Build de API y web en Docker, incluido `next build`: correcto.
- Aceptación HTTP final: correcta.
- Playwright final contra Compose: **2 pasadas**, escritorio y móvil.
- `git diff --check`: correcto.

Pytest requirió ejecución fuera del sandbox por permisos de sus directorios temporales. El servidor de desarrollo de Next.js excedió el timeout inicial de Playwright; la configuración `playwright.compose.config.ts` prueba la aplicación compilada sin arrancarlo. Una prueba de navegador inicial confundía la publicación de otro documento con la del suyo; ahora espera el estado del documento concreto y verifica que su fuente desaparece aunque existan otras publicaciones.

Los documentos sintéticos se dejan retirados para respetar la retención de H2. La evaluación del corpus usó una base temporal eliminada al terminar y un almacén temporal dentro del contenedor; no publicó ni editó las fuentes de la biblioteca actual. Los informes y las trazas se exportaron antes de terminar. El cambio previo en `.gitignore` se preservó.

La evaluación cubre únicamente Markdown español. La fidelidad de variantes PDF/DOCX sigue pendiente en H2; no se declara medida su recuperación. La abstención segura y las métricas quedan disponibles, pero este banco pequeño no demuestra suficiencia general ni resuelve ambigüedad o seguimiento conversacional.

## Revalidación con H4 — 2026-09-30

Se repitió el ensayo con los 13 documentos reales de `docs/`, verificando todos sus hashes contra H0, PostgreSQL vacío con la cadena completa de migraciones hasta `0005_h4`, Nomic y BGE reales. Se corrigió el esquema histórico de `evidence_policies` en `0004_h3`: importar el ORM vigente incluía anticipadamente `scope` y hacía fallar la migración H4 en instalaciones nuevas. Las migraciones desde cero y la indexación posterior pasaron.

Resultado: **13 documentos, 1.448 fragmentos, 24 consultas y cero errores**. Recall@10 respondible **0,9067**, MRR@10 **0,9143**; Recall@10 conversacional sin reformular **0,6111**. El umbral candidato **2,052673** vuelve a rechazarse: validación contiene **0 positivos aceptados y 1 respuesta indebida**, correspondiente a `EVAL-M002`, que es ambigua. La abstención segura permanece vigente. No se ajustó la política para forzar su aprobación.

El informe sin consultas ni fragmentos está en [`evaluation/h3/revalidation-h4.json`](../../evaluation/h3/revalidation-h4.json). Las trazas privadas se conservan en `.artifacts/h4/h3-real-docs-traces.json`. La base temporal se eliminó al finalizar. Esta prueba conserva los seguimientos originales del banco H3; no mide la reformulación contextual de H4.

En ese ensayo inicial la biblioteca activa tenía nueve documentos y ninguna de las 13 fuentes del catálogo estaba publicada. `scripts/h3/calibrate_library.py` rechazó el preflight porque requiere una única publicación de cada fuente. No se cargaron ni aprobaron documentos de producción ni se modificó su política durante ese ensayo: la calibración pertenece exclusivamente al corpus temporal y al ámbito administrativo. La corrección posterior de suficiencia y la evaluación de la biblioteca publicada se documentan en `docs/h3/calibration-fix.md`.
