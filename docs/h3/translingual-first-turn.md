# Primer turno translingüe: traducción determinista al español

Fecha: 2026-11-10. Sucede a `agnostic-evaluation.md` en el punto pendiente de las
preguntas en inglés sobre documentos en español. No recalibra ni cambia el corpus.

## Problema

La consulta de recuperación se busca con `websearch_to_tsquery('spanish', …)` y
con embeddings sobre un corpus casi enteramente español. Una primera pregunta
como «How long does a queen bee live?» conservaba su idioma y competía en peores
condiciones: la pregunta translingüe `AGN-VAL-A016` se abstenía aunque su
equivalente española se respondía.

## Decisión

Traducir al español **solo la consulta de recuperación** del primer turno (o de
una pregunta autónoma que abre tema) cuando la pregunta no esté en español. El
mensaje del usuario, el historial y el texto que ve el usuario conservan su
idioma original. Los seguimientos no se traducen: pasan por
`chat.contextual_query` con historial y por la reformulación existente.

## Detección de idioma

`apps/api/bibliotecario/language.py` implementa `detect_language(text)` sin
llamar a ningún modelo:

- puntúa palabras funcionales características de `es`, `en`, `fr`, `de`, `it` y
  `pt`; las compartidas por varios idiomas pesan menos;
- añade rasgos ortográficos: `¿¡` y `ñ` en español, `ãõ`, `ç`, `nh`, `lh` y
  `ção` en portugués, apóstrofos y `œ` en francés, `ß` y diéresis en alemán,
  `zione`/`gli`/`che` en italiano;
- usa las formas acentuadas exactas (`qué`, `cómo`, `são`, `où`, `für`, `è`…)
  porque su forma sin tilde suele ser compartida (`como` es español y portugués);
- ante empate o señal insuficiente devuelve `es`. Es la opción conservadora: un
  falso negativo deja la consulta sin traducir; un falso positivo añadiría una
  llamada innecesaria.

La tabla de `apps/api/tests/test_translingual.py` cubre 21 frases cortas, entre
ellas preguntas españolas con siglas y títulos extranjeros («¿Qué dice BERT sobre
attention?», «¿Cómo configuro SSH en el switch Cisco?»), que siguen siendo `es`.

## Traducción y coste

`chat.first_turn_query` llama una sola vez a `language.translate_to_spanish` si
`detect_language != "es"` y `Settings.translate_first_turn` está activo (por
defecto sí; se desactiva con `BIB_TRANSLATE_FIRST_TURN=false`). El prompt pide
solo la traducción, conserva nombres propios, siglas, versiones y cifras, y usa
`temperature=0`; la salida está limitada a 600 tokens y se valida contra salidas
vacías, demasiado largas o que sean una negativa del modelo.

- Es **una llamada extra por turno traducido**, no por turno. Un primer turno en
  español y cualquier seguimiento no la hacen.
- El presupuesto de aceptación es +1,5 s en p50. Para acotar la cola, la llamada
  tiene un timeout configurable (`BIB_TRANSLATION_TIMEOUT_SECONDS`, 8 s por
  defecto). Si falla, tarda o devuelve una traducción inservible, se usa la
  consulta original y el `RetrievalRun` guarda el diagnóstico
  `translation_failed`; el turno sigue su curso por las puertas de ambigüedad y
  evidencia.
- La fase se registra como `translation` en `llm.trace`/`llm.phases` y su tiempo
  en `result.latency.translation_ms` (también en `chat_latency.translation_ms`).
  `result.translation` resume idioma detectado, estado y error.
- La generación recibe la pregunta original y el `SYSTEM` pide responder en su
  idioma, aunque la consulta de recuperación esté en español. Las constantes de
  abstención, aclaración y estado siguen en español; esta tarea no las
  localiza.

## Casos añadidos

Banco agnóstico de validación (`evaluation/h3/agnostic-validation-v1.jsonl`),
todos en primer turno y sin tocar los grupos conversacionales:

| id | idioma | tipo | documento/sección |
| --- | --- | --- | --- |
| `AGN-VAL-T001` | fr | answerable | `AGN-001` / Abeja reina |
| `AGN-VAL-T002` | de | answerable | `AGN-002` / Objetos del sistema solar |
| `AGN-VAL-T003` | it | answerable | `AGN-010` / Tipos de datos |
| `AGN-VAL-T004` | en | answerable | `AGN-003` / Diagnóstico |
| `AGN-VAL-T005` | fr | answerable | `AGN-013` / Arábica |
| `AGN-VAL-T006` | de | answerable | `AGN-004` / Bloques |
| `AGN-VAL-T007` | en | unanswerable | fuera del corpus (temporal) |
| `AGN-VAL-T008` | de | unanswerable | fuera del corpus (personal) |

El banco pasa de 32 a 40 casos (22 answerable, 8 unanswerable, 3 ambiguous y 7
conversation). Se mantienen los mínimos de H0 y la unicidad de ids.

Banco coloquial de validación (`evaluation/h3/colloquial-validation-v1.jsonl`):

| id | idioma | documento |
| --- | --- | --- |
| `COL-validation-T001` | en | `DOC-007` (Cisco) |
| `COL-validation-T002` | fr | `DOC-005` (Git) |

Pasa de 31 a 33 casos. Son casos independientes: no se ha partido ningún grupo
conversacional.

## Reproducir

```powershell
# Detección, traducción, fallback y traza
$env:PYTHONPATH = (Resolve-Path .\apps\api).Path
.venv/Scripts/python.exe -m pytest apps/api/tests/test_translingual.py -q

# Contratos de los bancos
.venv/Scripts/python.exe -m unittest discover -s tests -v

# Puerta completa
pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .
```

Para comprobar a mano que los bancos siguen siendo JSONL válido:

```powershell
.venv/Scripts/python.exe -c "import json,pathlib; [print(p, len([json.loads(l) for l in pathlib.Path(p).read_text(encoding='utf-8').splitlines()])) for p in ['evaluation/h3/agnostic-validation-v1.jsonl','evaluation/h3/colloquial-validation-v1.jsonl']]"
```

## Firma de política y calibración pendiente

`TRANSLATION_PROMPT`, `TRANSLATION_MAX_TOKENS`, `settings.translate_first_turn` y
`settings.translation_timeout_seconds` entran en `policy_signature`. **El cambio
invalida las políticas aprobadas** (umbral −1,2895 en `admin` y `usuario`). No se
recalibra en esta tarea; debe hacerse con la pila viva después del Run:

```powershell
.venv/Scripts/python.exe scripts/h3/calibrate_library.py --scope admin `
  --calibration-bank evaluation/h3/colloquial-calibration-v1.jsonl evaluation/h3/agnostic-calibration-v1.jsonl `
  --validation-bank evaluation/h3/colloquial-validation-v1.jsonl evaluation/h3/agnostic-validation-v1.jsonl `
  --catalog evaluation/h0/corpus_catalog.json evaluation/h3/agnostic_corpus_catalog.json
# después, igual con --scope usuario
```

Hasta recalibrar, `find_policy` no encontrará una política con la firma nueva y
el chat se abstendrá con `uncalibrated`; es el comportamiento fail-closed
esperado, no una regresión de recuperación.

## Validación en vivo (2026-11-11)

Pila completa (`docker compose up -d --build api worker web`), Gemma 4 12B en
vLLM y embeddings/reranker con la configuración de GPU. Calibración con los
cuatro bancos y los dos catálogos: firma `2899120c395d`, umbral **−1,28946**,
aprobada en `admin` y `usuario` (`empirical_holdout_pass`).

| Prueba | Antes | Ahora |
| --- | --- | --- |
| Aceptación coloquial | 13/13 | **13/13** |
| Aceptación agnóstica | 62/64 | **36/40**, 0 indebidas, 0 cifras sin respaldo |
| p50/p95 agnóstica | 8,0/13,1 s | **8,0/13,8 s** |
| Fase `translation` | — | 10 llamadas, 476 ms de media (374 ms en la coloquial) |

Los casos translingües añadidos responden con citas en el idioma de la pregunta
(`T001` fr, `T003` it, `T004` en, `T005` fr, `T006` de) y el irrespondible
`T007` se abstiene. **`AGN-VAL-T002` (de, «Wie groß ist der Durchmesser des
Ganymed?») se abstiene con `calibrated_score`** aunque su equivalente francesa
responde: la puntuación del reranker para la consulta traducida queda por debajo
del umbral. Son 5 de 6 respondibles, el mínimo acordado.

Pendiente conocido: `AGN-VAL-U002`, `U003` y `T008` (preguntas personales) piden
aclaración en vez de abstenerse con `evidence_assessed`; es el mismo
comportamiento que antes de esta tarea y el arnés lo cuenta como fallo de clase.
No hubo `translation_failed` en ninguna de las 73 consultas de las dos
aceptaciones. La coloquial mantiene 13/13, con un p95 de 44 s por
`cisco-install`, que acaba en `grounded_extract` tras rechazar el verificador.

