---
task: task_e58422eca6e3
run: run_ab6870b4c625
date: 2026-11-12T15:06:51.3063618Z
domain: pdf-conversion
confidence: high
status: draft
---

## Cue

Una rama quedó `BLOCKED` por conflicto semántico con `main` (dos implementaciones del mismo módulo), su commit está revisado y en verde, y ya no integra ni con rebase limpio.

## Lesson

No reabras, no rescates y no hagas merge de la ref de seguridad: Run nuevo con base `main`, spec de port autocontenida que cite el commit (`t2c-safety/8e91625`) y el artefacto `.orca-run/runs/<run>/artifacts/<task>/` (`spec.md`, `report.md`, `diff.patch`), que exija **una sola implementación** y prohíba tocar la métrica y las políticas. La aceptación se fija con el arnés (`pdf_conversion_report.py`, 2 pasadas, baseline T0) y un censo repetible (`scripts/h3/pdf_math_census.py`); así se revisa en una ronda.

## Evidence

- [commit] 11/12/2026 14:53:06 actor=loop motivo: eec48c1dd5bf40fb658b87bfdb5fba8f0fd0aeb4
- [integrated] 11/12/2026 14:56:07 actor=loop motivo: bb77a7a78b60ae8ab40181d7f9bd20001d0e1c61
- [git] bb77a7a integrate: choruzo/pdf-math-span-port-e58422 — review ACEPTADO en la ronda 1, sin defectos
- [worker-report] # Reporte task_e58422eca6e3 — Port completo de T2c: limpieza por spans y palabras pegadas en el conversor PDF Task: `task_e58422eca6e3` · dispatch `ctx_7fa7685cbc2b` · worktree `pdf-math-span-port-e58422` (base `main` en `c2a27b1`; HEAD del worktree `8cbce90`) ## Resultado

