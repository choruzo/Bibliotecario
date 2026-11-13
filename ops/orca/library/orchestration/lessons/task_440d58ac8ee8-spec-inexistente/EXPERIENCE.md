---
task: task_440d58ac8ee8-spec-inexistente
run: run_bc7e29e5e432
date: 2026-11-13T10:30:00.0000000Z
domain: orchestration
confidence: high
status: draft
---

## Cue

El `## Checks obligatorios` de la spec apunta a una ruta que no existe en el worktree: un fichero de tests inexistente (`apps/api/tests/test_chat.py`) o un intérprete con la profundidad del checkout principal (`../../.venv`) cuando el `.venv` del worktree es una junction en su raíz.

## Lesson

No crees el fichero ni el directorio para satisfacer la ruta, y no te saltes el check: localiza el equivalente real —los tests que cubren esa zona (`test_h4.py`, `test_sufficiency.py`, `test_domain_agnostic.py`, `test_translingual.py`, `test_retrieval_context.py`) y el intérprete del worktree (`../.venv/Scripts/python.exe` desde `apps/api`)—, ejecuta el bloque completo y deja en `Evidencia` la ruta real, el motivo y la salida. `check.ps1` sigue siendo la fuente de verdad del gate; una ruta inventada solo produce un verde falso.

## Evidence

- [worker-report] el check obligatorio cita apps/api/tests/test_chat.py, pero ese fichero no existe en el repo; las pruebas del turno de chat viven en test_h4.py, test_sufficiency.py, test_domain_agnostic.py, test_translingual.py y test_retrieval_context.py
- [worker-report] en este worktree .venv es una junction en la raiz, asi que desde apps/api el ejecutable es ../.venv/Scripts/python.exe; el ../../.venv de la spec corresponde al checkout principal
- [worker-report] ejecute esos cinco ficheros como bloque de no regresion; el gate ademas corre toda la suite de apps/api/tests (235 passed)
- [commit] 11/13/2026 actor=loop motivo: b37aa2ba5063b602ad8e4e57b5ed48a6bae70a04
- [integrated] 11/13/2026 actor=loop motivo: 75cbd855c8495780d640e873cbc6a9066190a6fd