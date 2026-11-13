---
task: task_9a1ae15609c0
run: run_1aab5f1a2c1d
date: 11/13/2026 19:21:20.ToUniversalTime().ToString('o')
domain: web
confidence: high
status: draft
---

## Cue

Una tarea web añade un parámetro al cuerpo de una petición existente (modo, idioma, variante) y solo lo comprueba en pantalla.

## Lesson

Haz que el test del mock capture postDataJSON y afirme el valor enviado —también el valor por defecto, explícito— y no solo que el control se vea; el control debe estar deshabilitado mientras hay respuesta en curso y ser usable con teclado. No presentes el parámetro como un ajuste persistente de la conversación si la API no lo guarda.

## Evidence

- [escalation-deferred] 11/13/2026 08:53:41 actor=loop motivo: liveness  intento=1
- [escalation] 11/13/2026 08:53:55 actor=orca motivo: confirmada: liveness 
- [escalation] 11/13/2026 08:57:25 actor=orca motivo: confirmada: liveness 
- [worker-done-stale] 11/13/2026 09:03:20 actor=worker motivo: dispatch-not-latest latest=ctx_fa4dda86f11f
- [commit] 11/13/2026 09:23:35 actor=loop motivo: 14a5889b29d27bf9ebdd734bcbc9779e3c306fbc
- [integrated] 11/13/2026 09:26:56 actor=loop motivo: 992023b570fa9bfc9454ec69ebead317b1768c79
- [terminal-close] 11/13/2026 09:27:02 actor=cleanup motivo: cleanup
- [worktree-remove] 11/13/2026 09:27:38 actor=cleanup motivo: C:/Users/javie/orca/workspaces/Bibliotecario/h6-web-mode-9a1ae1-2
- [terminal-close] 11/13/2026 09:27:59 actor=loop motivo: settled
- [worker-report] # Reporte · task_9a1ae15609c0 Task: `task_9a1ae15609c0` · dispatch `ctx_fa4dda86f11f` · worktree `h6-web-mode-9a1ae1-2` (branch `choruzo/h6-web-mode-9a1ae1-2`) ## Resultado
