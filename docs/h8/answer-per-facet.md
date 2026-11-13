# Responder por facetas (H8)

Fecha: 2026-11-13. Estado: implementada tras la bandera `BIB_ANSWER_PER_FACET`, **apagada por defecto**.

## Problema

Medido en H7: con 60 candidatos delante y 0 descartes, el evaluador de cobertura dice `coverage_complete=false` para preguntas que reparten su evidencia entre dos documentos (ocurre también con la pregunta reformulada y con `BIB_MULTI_QUERY=0`). La recuperación entrega; el filtro no descarta: el límite es el criterio de cobertura sobre una pregunta de dos partes. Producto confirma que es un caso de uso real y que la abstención no sirve. Decisión cerrada: **responder por facetas**, sin relajar `assess`.

## Disparador

Solo en la ruta `mode="explain"` de `chat.py`, **antes de recuperar** y solo con `settings.answer_per_facet` encendida:

1. `contextual_query` produce la consulta del turno (reescritura y traducción de siempre, sin cambios).
2. `plan_facets` llama a `facets.plan_parts(clients, query, diagnostics)` (0-2 partes, nunca lanza). `plan_parts` divide la pregunta en **hasta dos partes autocontenidas tal y como las escribiría el usuario**: una parte puede ser un **fragmento literal de la pregunta** y se conserva tal cual, porque esta ruta **no recupera la pregunta original** — a diferencia de multi-query, aquí la cláusula repetida es una de las dos respuestas. `plan_parts` no añade temas que la pregunta no tenga (una pregunta de un solo tema devuelve `[]` — el hueco medido: «¿Cómo polinizan las abejas las flores?» se partía en mecanismo + anatomía) y solo descarta duplicados **entre** las dos partes.
3. **Solo con exactamente 2 partes no vacías y distintas** se entra en la ruta por facetas. Con 0 o 1 parte, o con fallo, el turno sigue por el camino `explain` normal y `chat_outcome.facet_plan` registra `"not_two"` (tema único) o `"plan_failed"` (proveedor, timeout o JSON inválido).

### `plan_parts` frente a `decompose`: dos contratos, no una bandera

`facets.py` tiene ahora dos funciones con dos prompts y dos reglas de deduplicación, y `decompose` queda **byte-idéntico** (multi-query depende de él y hay un golden que lo prueba):

| | `decompose` (multi-query, H7) | `plan_parts` (facetas, H8) |
|---|---|---|
| Qué genera | consultas de **búsqueda** por aspecto | las **partes de la pregunta** como las escribiría el usuario |
| Parte que repite la pregunta | **se descarta**: en multi-query la pregunta original ya tiene su propio pool, y repetirla solo lo engorda | **se conserva**: en la ruta por facetas la pregunta original no se recupera, así que la cláusula literal es una sub-consulta válida — descartarla pierde una de las dos respuestas (medido en la aceptación: 003/006/008 producían dos facetas correctas y el dedup dejaba una → `not_two` → abstención) |
| Tema único | `[]` | `[]`, y el prompt prohíbe añadir temas que la pregunta no mencione |
| Duplicados | contra la pregunta original y entre facetas | solo entre las dos partes |
| Fallos (proveedor, timeout, JSON) | `[]` + código fijo en `diagnostics["error"]` | `[]` + código fijo en `diagnostics["error"]` |

La tentación de meter un booleano en `decompose` se evita con dos funciones y dos prompts: ningún parámetro nuevo cruza la frontera entre multi-query y facetas.

La bandera es **independiente de `multi_query`**: esta ruta no toca `retrieval.py` ni depende de `BIB_MULTI_QUERY`. Con `mode="answer"` o con la bandera apagada no se llama a `plan_parts` ni se escribe ninguna clave nueva: ambos caminos quedan byte a byte idénticos.

## La faceta es un turno normal

Cada faceta se responde con el camino `explain` que ya existe, de principio a fin:

- **Retrieval propio**: `retrieve(...)` con la **consulta de la faceta**, en su propia sesión, dentro del mismo turno. Las dos retrievals se lanzan **concurrentes** con `asyncio.gather` (una tarea por faceta): los tramos ligados al modelo (embed, rerank, intent, assessment) de ambas se solapan y las sesiones no comparten transacción. `chat_outcome.facet_concurrency` deja constancia (`"concurrent"`); `chat_latency.facets_retrieval_ms` mide el conjunto y cada parte guarda su `latency` propia.
- **Decisión propia, idéntica a la de hoy**: el `assessment.action == "answer"` de esa faceta y el umbral de la política vigente, tal y como `evidence_decision` ya los aplica dentro de `retrieve`. Una faceta es una pregunta independiente y se juzga como tal; si una faceta abstiene, no se genera nada para ella.
- **Generación propia** con `EXPLAIN_SYSTEM` y `synthesis_schema(fuentes_de_la_faceta)`: el `enum` del esquema de cada faceta contiene **solo los marcadores de su tramo**. La pregunta original (campo `question`), las preferencias de la conversación y la consulta de la faceta (campo `query`) viajan en cada prompt.
- **Verificación propia**: una auditoría por frase contra la unión de las citas de esa frase (`verify_synthesis`), como en cualquier turno `explain`.

## Renumeración global de citas

El punto más delicado: un id repetido entre facetas rompería los chips de la web y la validación de fuentes. `citation()` recibe el desplazamiento acumulado: la faceta A numera `C1..Cn` y la faceta B continúa en `Cn+1..Cm`. El mensaje publicado lleva **un único `sources`** (unión de las facetas que responden, sin ids repetidos y sin huecos entre tramos) y la web actual pinta todos los chips sin cambios. El `enum` de cada faceta solo admite sus propios marcadores, así que una faceta no puede citar pasajes de la otra.

No se deduplican pasajes entre facetas: cada faceta es un turno normal y si las dos recuperan el mismo fragmento, cada una lo cita con su propio marcador.

## Composición determinista

Sin llamada al modelo (`compose_facets` es una función pura):

```
La pregunta tiene dos partes; respondo cada una con su evidencia.

<bloque de la faceta A: markdown de explain>

---

<bloque de la faceta B: markdown de explain>

_Esta composición no afirma ninguna relación entre las dos partes: resume la evidencia de cada una por separado._
```

- **La frase de cierre es fija y literal, y se emite una sola vez.** Está redactada sobre la composición, no sobre el corpus: afirmar «la relación no está en los documentos» sería una negación que el sistema no puede probar (y el corpus podría contenerla fuera de los pasajes recuperados). Por eso el cierre describe lo que la respuesta hace —resumir cada parte por separado— y nunca lo que los documentos contienen o dejan de contener.
- **Una faceta abstiene** (`partial_facets`): se publica el bloque de la que responde y, en lugar del otro bloque, la línea `No encuentro evidencia documental suficiente para la segunda parte: <consulta de la faceta>.` — con la consulta de la faceta sin evidencia, para que el usuario sepa a qué parte falta. El cierre se mantiene. `status="completed"`, `reason="partial_facets"`.
- **Ambas abstienen** (`facets_uncovered`): `status="abstained"` y el mensaje es la abstención genérica de siempre más ` La pregunta tiene dos partes; puedes preguntarlas por separado.` La abstención genérica no se toca.
- `corpus_changed` (ver abajo): abstención genérica plana, sin la pista de dos partes — la composición falló por un motivo técnico y sugerir preguntar por separado sería engañoso.

## Fallbacks por faceta

Una síntesis rechazada cae al extracto literal verificado **solo en su faceta** (`synthesis_fallback` sobre las fuentes de esa faceta): la faceta A puede publicar extractos mientras la B publica prosa auditada, sin arrastrarse mutuamente. El motivo queda en `chat_outcome.fallbacks` como `{"part": 0|1, "reason": ..., "detail": ...}` y en `chat_outcome.parts[i].reason == "grounded_extract"`.

## Publicación y revalidación

Antes de publicar se aplica la comprobación de siempre a **todos** los pasajes de **ambas** facetas (contenido del chunk, revisión, versión activa, visibilidad) y `corpus_signature` debe coincidir con la almacenada. La ruta guarda una única firma de corpus calculada sobre las dos retrievals: si las dos facetas vieron estados de corpus distintos, `result["corpus_signature"]` es `None` y la comprobación de publicación abstiene siempre. En ambos casos: `abstained`/`corpus_changed` y **ninguna fuente publicada**.

## Traza

Un único `RetrievalRun` por turno (`run.query` es la consulta contextual de la pregunta completa):

- `result.parts`: una entrada por faceta con `{"query", "stages", "decision", "assessment", "candidates", "results", "corpus_signature", "latency"}` — la misma estructura de etapas de H7 (`stages`), sin retrazar nada.
- `result.decision`: resumen `{"action": "answer"|"abstain", "reason": "facets_composed"|"partial_facets"|"facets_uncovered"}`.
- `result.chat_outcome`: `facet_plan="two"`, `facet_concurrency`, y `parts` con consulta, estado (`completed`/`abstained`, el mismo vocabulario de `status` del mensaje y del banco), motivo, nº de citas y nº de documentos de cada faceta.
- `result.chat_latency`: `plan_ms`, `facets_retrieval_ms`, `facet{i}_generation_ms`, `facet{i}_verification_ms` y `total_ms` — la generación y la verificación se miden **por faceta**, no agregadas. `plan_ms` es la planificación de `plan_parts`; la clave `decompose_ms` sigue siendo de multi-query (`retrieval.py`), que no corre en esta ruta.
- Sin figuras en esta ruta (v1): el bloque por faceta no pide figura y `chat_outcome` no incluye claves de figura (`figure_hint` solo se escribe en el camino explain de un turno).

## Coste

Por turno con dos facetas que responden: 1 planificación (`plan_parts`) + 2 retrievals completas (cada una: embed, rerank, intent, assessment) + 2 generaciones + 1 verificación por frase (hasta 14 por faceta). Las dos evaluaciones de cobertura son la parte cara; la concurrencia solapa sus tramos de modelo. El tope de producto es p50 ≤ 25 s: si secuencial no cabría, concurrente con dos sesiones es el modo por defecto de esta implementación. No se recorta la verificación; si aun así no cupiera, se medirá y se decidirá con datos.

## Regla de firma

`policy_signature` **no cambia**: no se añade nada. La política gobierna cómo se juzga una pregunta, y aquí cada sub-pregunta pasa exactamente por el mismo `assess` y el mismo umbral que pasaría si el usuario la escribiera por separado; el digest de `main` sigue validando con la bandera encendida o apagada. Si algún día la decisión de una faceta dejara de ser la de una pregunta independiente (por ejemplo, un umbral distinto o un assess facetal), habría que añadir ese contrato a la firma y recalibrar.

## Fuera de alcance (v1)

`assess`, `retrieval.py`, el umbral, el modelo, la web, las figuras y `mode="answer"` quedan intactos; ni más de dos facetas, ni recalibración, ni cambios en la abstención genérica. En `facets.py` solo se añade `plan_parts` con su `PLAN_PROMPT`: `decompose` queda byte-idéntico para multi-query. Las consultas de faceta las genera el modelo y no se reescriben ni se reintentan: quedan registradas en la traza (`parts[i].query`).
