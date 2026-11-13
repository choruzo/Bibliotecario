---
task: task_6f14a75af448
run: run_d0f4915e4cc7
date: 2026-11-13T20:00:00.0000000Z
domain: api
confidence: high
status: draft
---

## Cue

Una traza guardada dice merged=65 y candidates=0 a la vez, y no hay forma de saber si el rerank no devolvió nada, si el evaluador abstuvo o si un filtro vació la evidencia.

## Lesson

Instrumenta contadores por etapa (pools, merged, post_rerank, assessed, support, visible, dropped_invisible) con un helper puro que valide invariantes, calculados siempre y sin cambiar la decisión; un reason de abstención no atribuye la causa, y sin assessed/support la traza se contradice. La instrumentación va antes de cualquier arreglo, y su coste es de líneas añadidas, no de comportamiento.

## Evidence

- [escalation-ignored] 11/13/2026 18:05:32 actor=loop motivo: msg_stop espureo: sesion del worker activa
- [commit] c19d9f2cb6aea62b6e866ebe718cdfc19f81fa3d
- [integrated] e49689800fc3adc130d8bae35065ae6164b0e764
- [worker-report] stages con 7 contadores e invariantes; helper puro con ValueError antes de grabar una traza mentirosa; 16 tests nuevos; 318 passed en el gate; solo lineas anadidas
- [medicion] 2026-11-13 en vivo: abejas pools[30] merged=30 post_rerank=60 assessed=60 support=0 visible=60 dropped_invisible=0; revolucion 30/30/57/57/0/57/0