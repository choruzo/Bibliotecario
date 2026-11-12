---
task: task_ac91e49ebd62
run: run_a9e4664046a3
date: 2026-11-12T15:20:00.0000000Z
domain: orchestration
confidence: medium
status: draft
---

## Cue

Un worker manda `worker_done` con el árbol limpio (solo `?? .orca-task/`), el review sale `ACEPTADO` con `FILES=` vacío y el bucle queda `BLOCKED`; la tarea figura `completed` en Orca pero su dispatch no tiene `integrationSha`.

## Lesson

`completed` no es entrega: exige `FILES` no vacío en el review y `integrationSha` en el dispatch. Con el árbol limpio no hay entrega, y no se reabre la tarea por `task-update` cuando queda un dispatch fantasma activo (la fencía): se anota el hueco de ledger en el resultado y, si el trabajo hace falta, se abre un Run nuevo con spec fresca. Comprueba en `main` qué llegó de verdad antes de repetir el trabajo.

## Evidence

- [loop-log] run_a9e4664046a3 REVIEW_ROUND=1 REVIEW=ACEPTADO FILES= (vacio); git status solo ?? .orca-task/
- [loop-log] run_a9e4664046a3 ADVERTENCIA: No se pudo reabrir task_ac91e49ebd62: Task task_ac91e49ebd62 cannot move to ready while Dispatch ctx_796d82bfc456 is active
- [loop-log] run_a9e4664046a3 LOOP=BLOCKED
- [dispatch] ctx_d7b9967573e5 status=blocked, sin commitSha ni integrationSha (dispatches-run_a9e4664046a3.json)
- [git] 2b4f5e5 feat(api): translate non-Spanish first turns to Spanish — el codigo si llego a main, sin registro de integracion
- [git] evaluacion del 11/11 en docs/h3/translingual-first-turn.md: 13/13 coloquial, 36/40 agnostica, 5/6 translingues, 0 indebidas
- [task-update] 2026-11-12T15:05Z run_a9e4664046a3 cerrado como entregado anotando el hueco de ledger