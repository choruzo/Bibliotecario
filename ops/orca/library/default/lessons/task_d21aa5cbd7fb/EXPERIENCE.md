---
task: task_d21aa5cbd7fb
run: run_bc7e29e5e432
date: 2026-11-13T08:25:11.3525069Z
domain: default
confidence: low
status: draft
---

## Cue

TODO: describe la situacion que dispara esta leccion (que reconoceria el worker antes de actuar).

## Lesson

TODO: indica la operacion a hacer, nombrando el componente del kit al que afecta.

## Evidence

- [escalation-deferred] 11/13/2026 07:41:08 actor=loop motivo: liveness  intento=1
- [escalation] 11/13/2026 07:41:11 actor=orca motivo: confirmada: liveness 
- [commit] 11/13/2026 08:20:40 actor=loop motivo: ab31cf9cf5a9f703658a851a110009aa7153df9e
- [integrated] 11/13/2026 08:22:04 actor=loop motivo: 9f00bf1f835edb9ab3686f7e5e0b62df6829a642
- [terminal-close] 11/13/2026 08:22:12 actor=cleanup motivo: cleanup
- [worktree-remove] 11/13/2026 08:22:45 actor=cleanup motivo: C:/Users/javie/orca/workspaces/Bibliotecario/h6-figure-generation-d21aa5
- [terminal-close] 11/13/2026 08:22:58 actor=loop motivo: settled
- [worker-report] # Reporte — task_d21aa5cbd7fb (h6-figure-generation) ## Resultado El modo `explain` genera ahora **una** figura declarativa opcional en la misma generación que la síntesis (cero llamadas extra al modelo). La figura se valida después de que el texto se mantiene (`validate_synthesis` + `verify_synthesis`) y antes de publicar: una figura válida se guarda en `Message.figures` (lista de uno) y viaja en el evento `done`; cualquier figura inválida se descarta con su motivo en `chat_outcome.figure_rejected` sin tocar el texto (`completed`), y si el texto cae a extracto la figura cae con él (`text_fallback`). El modo `answer` no cambia: su esquema cerrado sigue sin `figure` y un intento cae por `invalid_answer` (abstinencia). Los checks obligatorios pasan: gate `CHECK_OK`, 14 tests nuevos y 56 de no regresión (`test_explain.py` + `test_figures.py`, sin modificar).

