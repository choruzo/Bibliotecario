---
task: task_449d349d269f
run: run_cba2f1ad82b5
date: 11/13/2026 22:49:48.ToUniversalTime().ToString('o')
domain: evaluation
confidence: high
status: draft
---

## Cue

Hay que aceptar una función de composición y el banco existente solo tiene preguntas de una respuesta: no hay dónde expresar «dos partes, cada una con sus documentos».

## Lesson

El banco se define con la forma de la respuesta (parts[]), no con la del mensaje, y los tres caminos son casos de primera clase: both, partial y none. partial/none son los que prueban que la composición no rellena lo que no hay; no los dejes como variantes de texto de both. Verifica cada parte contra el corpus convertido y deja la cita en el doc, y escribe un script de aceptación propio (el de una sola respuesta no entiende parts), con reglas puras testeables.

## Evidence

- [review-changes] 11/13/2026 19:42:00 actor=loop motivo: round=1
- [commit] 9387e699fab25ae16af3a2ffc8e8fac4c934b2e5
- [integrated] 89755e885edf6a44223484794235a3d8901360c4
- [worker-report] 10 casos + contrato; ambos documentos distintos en each both; partial/none con parte fuera de corpus; script con reglas puras
