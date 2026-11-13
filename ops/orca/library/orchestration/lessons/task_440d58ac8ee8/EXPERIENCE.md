---
task: task_440d58ac8ee8
run: run_bc7e29e5e432
date: 11/13/2026 09:30:30.ToUniversalTime().ToString('o')
domain: orchestration
confidence: high
status: draft
---

## Cue

Una tarea lleva [HARNESS-PROBE] en su spec: el bucle la despacha dos veces (base y hermana -var con la variante) y, mientras se arbitra el par, la base figura completed sin integrationSha durante varios minutos.

## Lesson

No la reabras ni la trates como atascada: el par se decide al integrar y, con empate, se integra la base y la hermana se cierra como probe-loser. Su worker_done tardío llega con la tarea ya cerrada y se descarta (worker-done-stale). Presupuesta dos plazas de worker por tarea probe: con -MaxWorkers 2 el otro carril no arranca hasta que un lado del par termina.

## Evidence

- [reconcile] 11/13/2026 07:21:36 actor=loop motivo: completed_sin_integracion
- [terminal-close] 11/13/2026 07:21:48 actor=loop motivo: settled
- [reconcile] 11/13/2026 07:33:56 actor=loop motivo: completed_sin_integracion
- [reconcile] 11/13/2026 07:34:47 actor=loop motivo: completed_sin_integracion
- [probe-pair-decision] 11/13/2026 07:36:47 actor=loop motivo: pair=pair-task_440d58ac8ee8 loser=task_b9316b407100 motivo=empate: sin contraste medible; se integra la base
- [commit] 11/13/2026 07:38:24 actor=loop motivo: b37aa2ba5063b602ad8e4e57b5ed48a6bae70a04
- [integrated] 11/13/2026 07:39:26 actor=loop motivo: 75cbd855c8495780d640e873cbc6a9066190a6fd
- [terminal-close] 11/13/2026 07:39:33 actor=cleanup motivo: cleanup
- [worktree-remove] 11/13/2026 07:40:04 actor=cleanup motivo: C:/Users/javie/orca/workspaces/Bibliotecario/h6-explain-mode-440d58
- [terminal-close] 11/13/2026 07:50:46 actor=loop motivo: settled
- [worker-report] # Reporte · task_440d58ac8ee8 (h6-explain-mode) ## Resultado Implementado el modo `mode="explain"` en el chat de la API: turno con síntesis didáctica por
- [probe-loser] 11/13/2026 07:36:50 actor=loop motivo: empate: sin contraste medible; se integra la base
- [worker-done-stale] 11/13/2026 07:41:05 actor=worker motivo: status=failed
