---
task: task_4bedbef3b21a
run: run_6c32899d3c9c
date: 2026-11-13T16:36:51.4527498Z
domain: default
confidence: low
status: draft
---

## Cue

TODO: describe la situacion que dispara esta leccion (que reconoceria el worker antes de actuar).

## Lesson

TODO: indica la operacion a hacer, nombrando el componente del kit al que afecta.

## Evidence

- [escalation-deferred] 11/13/2026 15:51:39 actor=loop motivo: liveness  intento=1
- [escalation] 11/13/2026 15:51:55 actor=orca motivo: confirmada: liveness 
- [escalation-ignored] 11/13/2026 16:10:05 actor=loop motivo: msg_stop espureo: sesion del worker activa (liveness= activity=)
- [escalation-ignored] 11/13/2026 16:23:03 actor=loop motivo: msg_stop espureo: sesion del worker activa (liveness= activity=)
- [review-changes] 11/13/2026 16:25:28 actor=loop motivo: round=1
- [commit] 11/13/2026 16:32:26 actor=loop motivo: 6ee8a83a2ba9c7dae6b827571939721a3ffb915e
- [integrated] 11/13/2026 16:33:33 actor=loop motivo: 6c2a4af2e27ca2caf0e48dc116dd64cd121b46cd
- [terminal-close] 11/13/2026 16:33:40 actor=cleanup motivo: cleanup
- [worktree-remove] 11/13/2026 16:34:10 actor=cleanup motivo: C:/Users/javie/orca/workspaces/Bibliotecario/h7-concept-bank-4bedbe-11
- [terminal-close] 11/13/2026 16:34:20 actor=loop motivo: settled
- [worker-report] # Reporte · task_4bedbef3b21a (h7-concept-bank) ## Resultado Creado el banco de preguntas de concepto H7: `evaluation/h3/concept-calibration-v1.jsonl` y `evaluation/h3/concept-validation-v1.jsonl` (12 casos cada uno, ids `CON-CAL-*`/`CON-VAL-*` únicos), el contrato `tests/test_concept_banks.py` (6 tests, pasa en el gate) y la documentación con evidencia `docs/h7/concept-bank.md`. Cada hecho bisagra se verificó leyendo el texto convertido del corpus (arnés `pdf_conversion_report.py`, una pasada, 17 ficheros); para cada par multi-documento se grepeó cada documento buscando el hecho del otro para descartar pseudo-multidocumento. Sin cambios en bancos existentes, catálogo, `apps/` ni `evaluation/h3/*acceptance*` (todo lo entregado es nuevo y sin stage).

