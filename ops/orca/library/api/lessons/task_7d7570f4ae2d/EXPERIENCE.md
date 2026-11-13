---
task: task_7d7570f4ae2d
run: run_f84ead8967c6
date: 11/13/2026 22:49:48.ToUniversalTime().ToString('o')
domain: api
confidence: high
status: draft
---

## Cue

La aceptación falla por detalles de contrato que no son de seguridad: una palabra de estado distinta entre la spec y la implementación, un script que muere al cerrar sesión y un dedup heredado que descarta una parte válida.

## Lesson

Separa las causas y arregla cada una en su sitio. El vocabulario se alinea con el contrato que congeló el banco (completed, no answered). El script escribe los informes antes del logout y cierra en try/finally, para que un fallo de cierre no cueste el resumen ni la latencia. Y un dedup pensado para «aspectos adicionales» no se reutiliza para «partes de una división»: dos funciones con dos prompts (decompose intacto, plan_parts nuevo), no un booleano en la existente. Si el caso de aceptación pide algo que el corpus no afirma, se reformula el banco y el original se conserva como control partial.

## Evidence

- [review-changes] 11/13/2026 21:07:17 actor=loop motivo: round=1
- [commit] 307c8a95db4ed1e5d254132684b367c5a793dbda
- [integrated] a15683c8a6aa4ebb609b674e31100ec816a31364
- [worker-report] plan_parts con prompt propio y [] para un solo tema; decompose intacto con golden; script escribe informes antes del logout; banco 8 both/2 partial/1 none
- [medicion] re-aceptacion: 10/11, improper=0, p50 18,6 s, caso 1 both, sin filtracion fuera de explain
