---
task: task_7832bedbdc99
run: run_bc7e29e5e432
date: 2026-11-13T08:25:08.5362755Z
domain: default
confidence: low
status: draft
---

## Cue

TODO: describe la situacion que dispara esta leccion (que reconoceria el worker antes de actuar).

## Lesson

TODO: indica la operacion a hacer, nombrando el componente del kit al que afecta.

## Evidence

- [commit] 11/13/2026 07:29:51 actor=loop motivo: 5547890b832f65222a005a754f5247276f5127b4
- [integrated] 11/13/2026 07:33:13 actor=loop motivo: 83440b611e8d23027a2222245c662aed900faa7f
- [terminal-close] 11/13/2026 07:33:20 actor=cleanup motivo: cleanup
- [worktree-remove] 11/13/2026 07:33:51 actor=cleanup motivo: C:/Users/javie/orca/workspaces/Bibliotecario/h6-figures-contract-7832be
- [terminal-close] 11/13/2026 07:34:09 actor=loop motivo: settled
- [terminal-close] 11/13/2026 07:50:38 actor=loop motivo: settled
- [worker-report] # Reporte — task_7832bedbdc99 (contrato de figuras declarativas, API) ## Resultado Existe el contrato de figuras declarativas cerrado: `figures.py` define los cuatro tipos (table, timeline, bars, steps) con modelos pydantic `extra="forbid"` en todos los niveles y `validate_figure(payload, source_ids, allowed_numbers)` que devuelve `(figura saneada, None)` o `(None, motivo)` con los nueve motivos exigidos. `numbers()` y `NUMBER_WORDS` se movieron byte a byte de `chat.py` a `textnums.py` con re-export (mismo docstring, mismos casos; test de paridad incluido). `Message.figures` persiste como JSON NOT NULL con `server_default='[]'` vía migración reversible `0007_h6`, `message_json` devuelve `figures` (`[]` si es `None`), y `main.py` y `scripts/h5/postgres_acceptance.py` esperan la revisión `0007_h6`. Los 33 tests nuevos y el gate completo pasan; sin cambios en `apps/web`, `evaluation/` ni en el esquema de generación.

