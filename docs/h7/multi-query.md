# Recuperación multi-consulta (H7)

Fecha: 2026-11-13. Estado: implementada tras bandera `BIB_MULTI_QUERY`, **apagada por defecto** hasta completar la recalibración del umbral (ver más abajo).

## Problema

Una pregunta que necesita evidencia de dos documentos («abejas y fotosíntesis») se comporta como un solo aspecto: la consulta única se parece a uno de los dos temas, los pools vectorial y léxico devuelven pasajes de uno o dos documentos, y el rerank ordena por relevancia a la pregunta completa. El segundo aspecto queda fuera del `support` de `assess`, que responde `coverage_complete=false` con 4–10 pasajes del primer tema y el turno se abstiene. No es un fallo de cobertura de `assess`: llega a `assess` sin la evidencia que necesita.

## Diseño

`retrieve` gana un camino nuevo, activo solo con `settings.multi_query`:

1. **Descomposición** (`facets.decompose`): una llamada LLM con esquema cerrado `{"facets": ["consulta 1", "consulta 2"]}` (0–2 elementos, cada uno 3–120 caracteres, `additionalProperties: false`). Devuelve consultas de búsqueda autocontenidas, en español, una por aspecto. Nunca lanza: error de proveedor, timeout, JSON inválido o fuera de esquema devuelven `[]` y el turno sigue con la consulta única de hoy. Deduplica por texto normalizado (mayúsculas, acentos y espacios) y descarta facets que repiten o contienen la pregunta original: la original ya tiene su propio pool y un facet repetido solo lo engorda. Si la pregunta tiene un solo tema, el modelo devuelve `{"facets": []}` y el camino es el de hoy.
2. **Embeddings**: una única llamada `clients.embed([query, *facets], query=True)`. La descomposición se solapa con la preparación de la transacción y la firma de corpus (su llamada LLM arranca tras soltar la transacción de autenticación), así que no hay segunda llamada de embedding.
3. **Pools**: un `candidate_pools` por consulta (vector propio + su texto para la léxica), cada uno con su fusión RRF vectorial+léxica. **Unión por `chunk_id`**: se queda el mayor `rrf_score` y la unión de `channels`, etiquetados por consulta (`q0:vector`, `q1:text`, …) para conservar la procedencia de cada pool; un fragmento presente en dos pools se cuenta una vez. Orden final por `rrf_score` descendente.
4. **`expand_context` una vez** sobre la unión, con el presupuesto global de hoy (60 fragmentos / 36.000 bytes), sin duplicar chunks.
5. **Un solo rerank** con la consulta compuesta `query + " " + " ".join(facets)` (la original primero) sobre toda la unión.
6. **`assess` sin cambios**: recibe los candidatos ya ordenados y sigue juzgando la cobertura de la pregunta original (no la compuesta). Su tope interno de 60 fuentes sigue aplicando; la unión puede llegar a 90 (3 pools × 30) y `expand_context` sigue limitando el total.
7. **`results` como hoy**: los pasajes del `support` (máx. 10) si `assessment.action == answer`, si no todos los candidatos.

Diagnóstico en el resultado del run: `result["retrieval"] = {"facets": [...], "facet_error": "…"|None, "merged": n, "pools": [n1, n2, …]}`. Contiene consultas y contadores, nunca textos de pasajes ni secretos. Con la bandera apagada el resultado incluye la misma clave con `facets: []` y `facet_error: None`.

### Por qué el rerank es compuesto y no uno por aspecto

El coste del reranker crece con el número de parejas consulta-documento. Reranquear una vez por aspecto multiplicaría esa llamada por 3 (original + 2 facets) sobre ~30 documentos cada una, y obligaría a fundir tres listas de `rerank_score` sin una base común comparable. La nota de diseño de la tarea lo prohíbe explícitamente salvo medición («nunca añadir 3 reranks sin medir»). La alternativa elegida — un rerank con la consulta compuesta — mantiene **una** llamada y un único `rerank_score` comparable entre sí, a cambio de cambiar su significado: pasa a medir «relevancia al conjunto de aspectos», no a la pregunta.

### Traza por etapas

Cada resultado de `retrieve` (y con él cada `RetrievalRun`) incluye una clave `stages` con los contadores de cada etapa del pipeline. Se calcula **siempre**, con la bandera encendida o apagada, sobre las listas que el turno ya produjo: no re-filtra nada, no cambia ninguna decisión ni el orden o el contenido de `candidates`/`results`. Solo guarda contadores y hasta cinco identificadores de fragmento — ningún pasaje, título o secreto — así que el JSON del run no crece de forma apreciable.

| Contador | Significado |
|---|---|
| `pools` | Tamaño de cada pool fusionado por consulta (igual que `retrieval.pools`). |
| `merged` | Unión por `chunk_id`: candidatos únicos tras la fusión, antes de `expand_context`. |
| `post_rerank` | Candidatos que produce el rerank (la lista que recibe `assess`). |
| `assessed` | Candidatos entregados a la evaluación de suficiencia; `assess` aplica su tope interno de 60 fuentes sobre esa lista. |
| `support` | Soporte devuelto por el evaluador (`len(assessment.support)`). |
| `visible` | Candidatos que sobreviven al control de visibilidad posterior a la evaluación. |
| `dropped_invisible` | Cuántos descartó ese control: `assessed - visible` (nunca negativo). |
| `dropped_sample` | Hasta 5 `chunk_id` descartados, en el orden de los candidatos. |

Invariantes (validados por `stage_counts`, que falla con `ValueError` si se rompen): `visible <= assessed`, `dropped_invisible = assessed - visible`, `support <= assessed`, y la muestra descartada tiene exactamente `dropped_invisible` ids antes de truncarse a 5.

El ejemplo de la aceptación de H7 — 65 candidatos unidos y un run guardado con `candidates=0`, `results=0` — se lee así con la traza:

```json
"stages": {"pools": [30, 30, 30], "merged": 65, "post_rerank": 65,
           "assessed": 65, "support": 0, "visible": 0, "dropped_invisible": 65,
           "dropped_sample": ["…", "…", "…", "…", "…"]}
```

Aquí el filtro de visibilidad **vació la evidencia**: los 65 candidatos llegaron al evaluador (`assessed=65`) y ninguno sobrevivió al control posterior (`dropped_invisible=65`), con los cinco primeros ids a la vista para auditar qué documentos eran. En cambio, un `assessed=65` con `visible=65` y `support=0` sería lo contrario: el **evaluador** abstuvo y el filtro no descartó nada. Y un `post_rerank=0` con `merged>0` señala el reranker, no el filtro. La lectura decide el siguiente paso sin conjeturas: `dropped_invisible=assessed` → tarea sobre el control de visibilidad; `support=0` con `visible>0` → criterio de cobertura del evaluador.

## Regla de firma

`sufficiency.policy_signature` solo añade `DECOMPOSE_PROMPT`, `DECOMPOSE_MAX_TOKENS` y el esquema `Facets` al contrato **con la bandera encendida**. Con la bandera apagada el contrato es byte a byte el de H4: `policy_signature(settings)` devuelve exactamente el digest de `main` (golden test `test_policy_signature_stays_main_until_the_flag_turns_on`, con el digest literal capturado antes del cambio). Si un solo byte del contrato cambiara con la bandera apagada, el chat quedaría `uncalibrated` (fail-closed) sin que nadie hubiera recalibrado: el golden test existe para impedirlo.

Con la bandera encendida la firma cambia y las políticas existentes dejan de validar: es el comportamiento esperado y deseado — el umbral calibrado ya no describiría el score que se está usando.

## Dependencia explícita de la recalibración

**Encender la bandera sin recalibrar deja el chat en `uncalibrated`**: no hay política aprobada para la firma nueva. El `rerank_score` cambia de significado (relevancia al conjunto de aspectos), así que el umbral vigente, calibrado para la consulta única, deja de ser válido en cuanto hay facets. Antes de encender `BIB_MULTI_QUERY` por defecto hay que recalibrar con los bancos viejos y bancos nuevos siguiendo `h7-calibration-runbook.md` (paso del líder). Mientras la bandera esté apagada, la política calibrada y el comportamiento de producción no cambian: ni `decompose` se ejecuta ni la firma se mueve.

## Coste medido

Con los dobles de `test_multi_query.py` (retardo simulado de 20 ms por llamada de proveedor) y 2 facets:

| Fase | Bandera apagada | Bandera encendida (2 facets) |
|---|---|---|
| Llamadas de proveedor | 5 (`tokens`, `embed`, `rerank`, `intent`, `assess`) | 6 (`tokens`, `decompose`, `embed`, `rerank`, `intent`, `assess`) |
| `decompose_ms` | — | ~21,7 |
| `embedding_ms` | ~31,7 | ~30,6 |
| `search_ms` (pools+fusión) | ~1,0 | ~0,2 |
| `fusion_ms` (unión+contexto) | ~0,03 | ~0,04 |
| `reranking_ms` | ~30,0 | ~31,4 |
| `sufficiency_ms` | ~31,6 | ~32,4 |

Estructura del turno con 2 facets (orden y argumentos resumidos): `embedding_tokens("search_query: " + pregunta)` → `generate(DECOMPOSE_PROMPT, pregunta, max_tokens=500, schema=Facets)` → `embed([pregunta, facet1, facet2], query=True)` → `candidate_pools` ×3 (vector y texto propios de cada consulta) → `rerank(pregunta + " " + facet1 + " " + facet2, unión)` → `generate(intent, pregunta)` → `generate(assessment, pregunta, unión ordenada)`. Una sola llamada de embedding, un solo rerank y un solo assess en ambos caminos; el coste adicional es la llamada de descomposición (su latencia, ~la de cualquier generate) y un rerank sobre un pool mayor (hasta 90 documentos frente a 30; `assess` sigue limitado a 60).

## Rollback

Apagar la bandera: `BIB_MULTI_QUERY=false` (o simplemente retirarla; el defecto es `false`). El turno vuelve al camino de consulta única de H4 con el mismo resultado que hoy (verificado por test contra el camino degradado: candidatos, scores, canales, resultados y decisión idénticos), y la firma vuelve a ser la de `main` sin recalibrar nada.

## Pruebas

- `apps/api/tests/test_multi_query.py` (15): esquema cerrado y acotado; facets autocontenidas con dedup, descarte de repeticiones y tope de 2; `decompose` nunca lanza (error de proveedor, timeout, conexión, JSON inválido, fuera de esquema) y registra un código fijo; bandera apagada no invoca `decompose` y mantiene el camino de hoy; firma golden (apagada == `main`, encendida != `main`); 2 facets → una sola llamada de embed, tres pools con vectores propios, unión sin duplicados, un solo rerank con la consulta compuesta y un `expand_context`; fragmento compartido entre pools contado una vez con canales de ambos; `assess` recibe la unión ordenada con la pregunta original y conserva su tope de 60; fallo y crash de `decompose` degradan al camino de hoy con `facet_error` registrado; diagnóstico sin textos de pasajes; tabla de coste.
- `apps/api/tests/test_retrieval_stages.py` (16): helper `stage_counts` puro (65→0, 65→65, 30→28 con dos ids de muestra, truncado a 5, invariantes rotos rechazados) y trazas de `retrieve` con los dobles de `test_multi_query.py`: `stages` cuadra con `pools`, `merged`, `len(candidates)`, `len(results)` y `len(support)` del mismo resultado, con la bandera encendida y apagada; el control de visibilidad deja muestra de lo descartado en orden; turno vacío con todos los contadores a cero; traza sin pasajes ni títulos.
- Regresión: `test_h4.py`, `test_sufficiency.py`, `test_retrieval_context.py`, `test_domain_agnostic.py` sin cambios y en verde.


## Resultado de la activación (2026-11-13): rechazada, bandera apagada

| Paso | Resultado |
|---|---|
| Firma | `model_signature` 2899120c → 08750c2e; `corpus_signature` 54c394a7 sin cambio |
| Calibración | aprobada en `admin` y `usuario` (`empirical_holdout_pass`, holdout tp 57 / fp 0 / tn 22, `improper_answer_rate 0.0`) |
| Regresión coloquial | 13/13; p50 10,5 s; fase `facets` 13 llamadas, 781 ms |
| Regresión agnóstica | **34/40**: los cuatro fallos históricos (`T002`, `T008`, `U002`, `U003`) más `A002` (`calibrated_score`) y `T003` (abstención del evaluador) |
| Banco de concepto | 9/12, 0 indebidas, 0 cifras sin respaldo; los tres fallos son `expected_answer` abstenidos |
| Multi-documento | 4 casos con dos o más documentos citados (`A001`, `A002`, `A004`, `A005`); el criterio era 5 |
| Preguntas objetivo | abejas+fotosíntesis y Revolución **abstienen** en `explain` y en `answer`, con facets generados (2 y 1) y pool unido de 65 y 38 |

**Decisión: rechazada.** Dos fallos nuevos en el banco agnóstico son una regresión
funcional y las preguntas objetivo siguen absteniendo. La bandera vuelve a `0`, la
calibración no se commitea y los artefactos de política vuelven a su estado aprobado.
La política del intento v1 queda en la base de datos como historia, inalcanzable con
la bandera apagada.

**Causas, separadas por lo que está medido.** (1) `A002` cae por `calibrated_score`:
con facets el rerank compuesto bajó el score por debajo del umbral de una pregunta que
antes pasaba. Es un efecto real del rerank con la consulta concatenada. (2) Las
preguntas objetivo **no** caen por score: la traza muestra
`assessment={action: abstain, coverage_complete: false, support: []}` con
`decision.reason=evidence_assessed`, que es el **evaluador** diciendo que no cubre; y
el mismo patrón aparece con `BIB_MULTI_QUERY=0`. La pregunta de abejas+fotosíntesis,
tal como está redactada, pide una relación causal que el corpus no afirma. (3) La traza
guardada muestra `merged=65` y `candidates=0`, lo que es incompatible con que `assess`
haya recibido fuentes; el único punto que vacía la lista es el control de visibilidad
posterior a la evaluación, que no registra cuántos descartó. Queda como incógnita
abierta, no como causa atribuida al multi-query.

**Qué se conserva.** La descomposición (`facets.py`), la unión por `chunk_id`, el
diagnóstico `retrieval` y el golden de firma. La v2 (`h7-multi-query-v2.md`) queda
**aparcada**: no ataca ninguna de las dos causas medidas. Antes hay que instrumentar
las etapas (`h7-retrieval-trace.md`) y, según lo que salga, decidir entre el control de
visibilidad, el criterio de cobertura o responder por facet.

**No hay regresión introducida por H7 en las preguntas objetivo**: fallan igual con la
bandera apagada.