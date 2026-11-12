---
task: task_8cba7ea2d0d2
run: run_43fca8504d61
date: 2026-11-12T15:06:49.2967374Z
domain: orchestration
confidence: medium
status: draft
---

## Cue

Dos tareas hermanas se despachan en paralelo desde el mismo commit y ambas crean el mismo módulo nuevo o reescriben el mismo fichero: la segunda en integrar choca con `MERGING` y conflictos `add/add`, aunque las dos pasaron review y `CHECK_OK`.

## Lesson

Al planificar, declara en la spec la propiedad del fichero y serializa con `--deps` las tareas que crean el mismo módulo; el orquestador no reordena ramas ya despachadas. Si el conflicto ya existe, no lo lances con `-AutoRescue`: es una decisión semántica entre dos implementaciones y la toma el usuario. Salida limpia: Run nuevo con base `main` y una spec de port que cite el commit revisado (`8e91625`) y exija una sola implementación.

## Evidence

- [commit] 11/12/2026 06:57:55 actor=loop motivo: 8e91625cec40874f047645df4626c3bff2eb5c6b
- [blocked] 11/12/2026 06:57:58 actor=loop motivo: integration failed
- [loop-log] 2026-11-12T06:57Z CONFLICT (add/add): Merge conflict in apps/api/bibliotecario/pdf_math_clean.py, apps/api/tests/test_pdf_math_clean.py, docs/h3/pdf-two-column-format.md y report.md; CONFLICT (content) en apps/api/bibliotecario/converters.py
- [git] 44863a8 integrate: choruzo/pdf-math-block-5b5eb9 — la rama hermana se integro despues del review de T2c
- [git] bb77a7a integrate: choruzo/pdf-math-span-port-e58422 — el port cerro la deuda 24 h despues
- [worker-report] # T2c — Informe: limpiar el formato de las ecuaciones en los dos PDF de arXiv - Task: `task_8cba7ea2d0d2` / dispatch `ctx_211f63fdff11` - Worktree: `choruzo/pdf-math-cleanup-8cba7e` (base `orca/integration/run_43fca8504d61`)

