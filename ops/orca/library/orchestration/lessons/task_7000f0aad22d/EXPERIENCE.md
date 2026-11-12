---
task: task_7000f0aad22d
run: run_caaf01ac878e
date: 2026-11-12T15:06:50.3291646Z
domain: orchestration
confidence: high
status: draft
---

## Cue

Primer review de una tarea despierta: `REVIEW=ACEPTADO` pero `FILES=` vacío y `git status` solo muestra `.orca-task/`. No es un defecto del worker ni una entrega.

## Lesson

El bucle ya lo trata como `CHANGES` y re-despacha la misma tarea con un `ctx` nuevo sin tocar su estado; si la ronda 2 trae diff, se commitea e integra. No marques la tarea `completed` a mano ni cierres el Run por un `FILES` vacío: espera el re-despacho y verifica que el segundo review trae ficheros.

## Evidence

- [loop-log] run_caaf01ac878e REVIEW_TASK=task_7000f0aad22d REVIEW_ROUND=1 REVIEW=ACEPTADO FILES= (vacio)
- [loop-log] run_caaf01ac878e [loop] CHANGES task_7000f0aad22d round 1 -> re-dispatched ctx_6e70c4823a07
- [loop-log] run_caaf01ac878e REVIEW_ROUND=2 REVIEW=ACEPTADO con 6 ficheros y diff de 228 lineas
- [commit] be1479f9c3b5b469827aba904ffbb8477e70048e
- [integrated] f3dfeca3221b9d44b3e1c346b25a16dd65f9ca53
- [worktree-remove] 2026-11-12T13:50:49Z actor=cleanup motivo: C:/Users/javie/orca/workspaces/Bibliotecario/pdf-conv-layout-7000f0-2
- [worker-report] # Reporte · task_7000f0aad22d ## Resultado Se convirtió la rama PDF en estrategias seleccionables (`BIB_PDF_LAYOUT=legacy|layout`, por defecto `legacy`) y se midieron tres variantes sobre los 17 PDF del corpus agnóstico con el arnés existente, ampliado con `--layout`. `layout` reduce las páginas con pérdida de texto (26 → 19) pero empeora la métrica de tablas (19 → 13 correctas, 1496 → 4983 palabras perdidas) y tarda 40,6 % más, así que **el valor por defecto sigue siendo `legacy`**. La evidencia, la decisión y la reproducción quedan en `docs/h3/pdf-conversion.md`; el gate termina en `CHECK_OK`.

