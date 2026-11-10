# Reporte · task_ac91e49ebd62

## Resultado

Se añadió detección determinista de idioma (`es`, `en`, `fr`, `de`, `it`, `pt`, con `es` por defecto) y una traducción al español de la consulta de recuperación solo en el primer turno o pregunta autónoma no española. La traducción es una única llamada al LLM con salida corta, timeout configurable, traza propia (`translation` en `llm`, `translation_ms` en `result.latency`) y vuelta segura al original con el diagnóstico `translation_failed`. Se añadieron 8 casos translingües al banco agnóstico de validación, 2 al coloquial, un test nuevo y la documentación; la puerta de calidad termina en `CHECK_OK`.

## Archivos

- `apps/api/bibliotecario/language.py` — nuevo: detección por stopwords/ortografía, prompt y llamada de traducción, limpieza y timeout.
- `apps/api/bibliotecario/chat.py` — `first_turn_query` con traducción opcional, diagnóstico, traza de latencia y fase; instrucción de responder en el idioma de la pregunta.
- `apps/api/bibliotecario/config.py` — `translate_first_turn` (por defecto activo) y `translation_timeout_seconds` (8 s), ambos con prefijo `BIB_`.
- `apps/api/bibliotecario/retrieval.py` — la inspección `/admin/retrieval/search` usa la misma traducción y registra su traza.
- `apps/api/bibliotecario/sufficiency.py` — prompt y ajustes de traducción incluidos en `policy_signature`.
- `apps/api/tests/test_translingual.py` — nuevo: 21 frases de detección, no traducción en español/seguimientos, fallo y timeout con fallback, y llegada del texto traducido a `retrieve` con traza en el `RetrievalRun`.
- `evaluation/h3/agnostic-validation-v1.jsonl` — 8 casos translingües (`AGN-VAL-T001`…`T008`); 40 casos en total.
- `evaluation/h3/colloquial-validation-v1.jsonl` — 2 casos translingües (`COL-validation-T001/T002`); 33 casos en total.
- `docs/h3/translingual-first-turn.md` — nuevo: método, detección, coste, casos, reproducción y pendiente de medición.
- `docs/h3/agnostic-evaluation.md` y `docs/h3/colloquial-retrieval-fix.md` — nota de que los recuentos históricos corresponden a los bancos originales.
- `report.md` — este informe.

## Checks

| Check | Comando | Resultado |
|---|---|---|
| Tests nuevos | `PYTHONPATH=<worktree>/apps/api .venv/Scripts/python.exe -m pytest apps/api/tests/test_translingual.py -q` | PASS (29 passed) |
| Suite API | incluida en `check.ps1` | PASS (161 passed, 1 skipped) |
| Contratos de bancos | `.venv/Scripts/python.exe -m unittest discover -s tests -v` | PASS en `test_agnostic_banks`; los dos tests H0 se omiten en la puerta por falta de `docs/*.md` en el worktree |
| Validación de bancos | `python -c` de parseo y unicidad | PASS: agnóstico 40 ids únicos, coloquial 33 ids únicos, grupos conversacionales intactos |
| Puerta completa | `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .` | PASS (`CHECK_OK`) |

## Decisiones

- **Detección determinista y conservadora.** Stopwords con peso extra para palabras exclusivas, rasgos ortográficos y formas acentuadas exactas. Los empates y las frases sin señal vuelven a `es`; las preguntas españolas con siglas o títulos ingleses («BERT», «SSH», «Cisco») siguen detectándose como español.
- **Una sola llamada extra por turno traducido.** Solo se aplica en la rama de primer turno/pregunta autónoma y con `translate_first_turn` activo. Un turno español, un seguimiento o el ajuste desactivado no llaman al modelo. La llamada usa `temperature=0`, `reasoning_effort=disabled`, 600 tokens y timeout de 8 s.
- **La consulta original manda.** El mensaje guardado, el historial y el `question` de generación conservan el texto del usuario; solo cambia `query` para recuperación. El `SYSTEM` de generación pide responder en el idioma de la pregunta original.
- **Traza y fallback.** El éxito queda como fase `translation` en `llm.phases` y `result.latency.translation_ms`; el fallo o timeout conserva la consulta original y añade `translation_failed` a `result.diagnostics`.
- **Firma de política invalidada.** `TRANSLATION_PROMPT`, `TRANSLATION_MAX_TOKENS`, `translate_first_turn` y `translation_timeout_seconds` entran en `policy_signature`. Las políticas aprobadas con umbral −1,2895 dejan de valer y el chat se abstendrá con `uncalibrated` hasta recalibrar. **No se recalibra en esta tarea**; los comandos quedan en `docs/h3/translingual-first-turn.md`.
- **Bancos.** Se usaron documentos y secciones ya presentes en los bancos y catálogos (`AGN-001/002/003/004/010/013`, `DOC-005/007`). No se partió ningún grupo conversacional y los ids son únicos.

## Riesgos / pendientes

- La aceptación en vivo no se ejecutó: falta recalibrar y pasar los bancos con la pila real. Queda medir p50/p95 de la traducción, el porcentaje de `translation_failed` y si el p50 total respeta +1,5 s.
- Los resúmenes históricos `evaluation/h3/agnostic-acceptance-*.json` fijan el SHA-256 del banco anterior; quedan obsoletos hasta repetir la aceptación con el banco de 40 casos.
- La traducción añade una llamada solo en turnos translingües; en el peor caso el timeout de 8 s puede superar el presupuesto p50, aunque el turno no se bloquea.
- Las constantes de abstención, aclaración y los mensajes de estado siguen en español; la instrucción de idioma cubre la respuesta factual generada.
- No se tocó `compose.yaml` (fuera de alcance). `BIB_TRANSLATE_FIRST_TURN`/`BIB_TRANSLATION_TIMEOUT_SECONDS` se leen del entorno del proceso; para inyectarlos en el contenedor habría que mapearlos explícitamente en la configuración de Compose.

## Commit

Commit `feat(api): translate non-Spanish first turns to Spanish` en la rama del
worktree. No se hizo push ni merge; `.orca-task/` queda sin versionar.
