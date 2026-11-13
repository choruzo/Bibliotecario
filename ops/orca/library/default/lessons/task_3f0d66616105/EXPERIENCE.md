---
task: task_3f0d66616105
run: run_6c32899d3c9c
date: 2026-11-13T16:36:50.5823652Z
domain: default
confidence: low
status: draft
---

## Cue

TODO: describe la situacion que dispara esta leccion (que reconoceria el worker antes de actuar).

## Lesson

TODO: indica la operacion a hacer, nombrando el componente del kit al que afecta.

## Evidence

- [escalation-deferred] 11/13/2026 16:01:54 actor=loop motivo: liveness  intento=1
- [escalation] 11/13/2026 16:01:56 actor=orca motivo: confirmada: liveness 
- [escalation-ignored] 11/13/2026 16:06:40 actor=loop motivo: msg_stop espureo: sesion del worker activa (liveness= activity=)
- [commit] 11/13/2026 16:18:46 actor=loop motivo: c446d37f984141c7ccb3a6e249520275ef8807ee
- [integrated] 11/13/2026 16:22:03 actor=loop motivo: a89edb458ed98bd6b74a35e16dd9b36dfb6f352a
- [terminal-close] 11/13/2026 16:22:10 actor=cleanup motivo: cleanup
- [worktree-remove] 11/13/2026 16:22:41 actor=cleanup motivo: C:/Users/javie/orca/workspaces/Bibliotecario/h7-multi-query-retrieval-3f0d66
- [terminal-close] 11/13/2026 16:22:55 actor=loop motivo: settled
- [worker-report] # Reporte - task_3f0d66616105 (H7: recuperación multi-consulta) ## Resultado Implementada la recuperación multi-consulta tras la bandera `BIB_MULTI_QUERY` (apagada por defecto). Con la bandera encendida, `retrieval.retrieve` descompone la pregunta en 0–2 facets autocontenidas (`facets.py`, que nunca lanza), hace **una sola llamada** `embed([query, *facets])`, un pool por consulta con fusión RRF propia, **unión por `chunk_id`** (mayor `rrf_score`, unión de `channels` con procedencia por consulta), un `expand_context`, **un solo rerank** con la consulta compuesta y `assess` intacto sobre la unión ordenada. `sufficiency.policy_signature` añade el contrato de descomposición solo con la bandera encendida: con la bandera apagada el digest es **byte a byte el de `main`** (golden capturado antes del cambio y verificado). Fallos de descomposición degradan al camino actual con `facet_error` registrado. Todos los checks en verde; sin cambios en `apps/web`, `figures.py`, `explain.py`, `evaluation/` ni en el prompt/VERSION/esquema de `assess`.

