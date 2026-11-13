---
task: task_90b4600e0ecf
run: run_3216cca74749
date: 2026-11-13T22:15:00.0000000Z
domain: chat
confidence: high
status: draft
---

## Cue

Un artefacto opcional (figura, tabla, resumen) viaja como propiedad del mismo esquema que la respuesta principal y **no aparece nunca**, aunque el prompt lo pida expresamente y la validación no lo rechace después.

## Lesson

No retoques el prompt a ciegas: saca el artefacto a una **segunda llamada corta** con esquema propio y `decline` primero, y ábrela solo con un **disparador determinista** sobre los pasajes del turno (`figure_hint`): 3+ años → timeline, 2+ fuentes con cifras → tabla, 3+ pasos → pasos. Si el disparador no se activa, el problema es de datos, no del modelo. Deja una única puerta de validación (`validate_figure`), que el artefacto nunca cambie el destino del turno (`completed` con o sin figura, `text_fallback` cuando el texto cae a extracto) y registra `hint`, `present` y el motivo de descarte.

## Evidence

- [commit] 73e3742fc61b3cb76a1356fa2e93fa5efce8cf2d
- [integrated] 42f9e00dd021ba660a0e085e82020ad51278bd87
- [worker-report] dos llamadas: la sintesis deja de declarar y mencionar figure; figure_hint puro con umbrales en docstring; segunda llamada decline-first con FIGURE_SYSTEM y figure_call_schema; validate_figure sin cambios; 19 tests; con hint=None no hay segunda llamada (doble que falla si se invoca); answer byte-identico
- [medicion] 2026-11-13: cinco preguntas de figura sin figura, con figure_hint=null (4 pasajes de un documento con 2 anos distintos) y ninguna figure_rejected de contenido: la emision no quedo demostrada en vivo y el limite era de datos (docs/h6/figures-contract.md)