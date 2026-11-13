---
task: task_fa35dc8f492d
run: run_bc7e29e5e432
date: 11/13/2026 09:30:30.ToUniversalTime().ToString('o')
domain: web
confidence: high
status: draft
---

## Cue

Una tarea web pinta en el chat contenido generado por el modelo (figuras, bloques, HTML) que viene de documentos no confiables.

## Lesson

No renderices HTML del modelo: consume datos tipados y pinta con componentes fijos; sin dangerouslySetInnerHTML, sin iframe, sin img, sin recursos externos y sin ningún campo de URL en el contrato. Añade un guarda en la web (parseFigure) aunque la API ya valide —defensa en profundidad— y un test del caso desconocido/malformado: se descarta y el mensaje sigue. Cierra la evidencia con el grep que demuestra la ausencia de esas APIs.

## Evidence

- [commit] 11/13/2026 08:03:08 actor=loop motivo: 75dfb3628e4ca52f5deddfcc6abde02ffb8bd28f
- [integrated] 11/13/2026 08:04:32 actor=loop motivo: 80f998a16e9b11bee8223f1bbedec507e8732a38
- [terminal-close] 11/13/2026 08:04:39 actor=cleanup motivo: cleanup
- [worktree-remove] 11/13/2026 08:05:15 actor=cleanup motivo: C:/Users/javie/orca/workspaces/Bibliotecario/h6-web-figures-fa35dc
- [terminal-close] 11/13/2026 08:05:28 actor=loop motivo: settled
- [worker-report] # Reporte - task_fa35dc8f492d Task: `task_fa35dc8f492d` · dispatch `ctx_a1a59f516d33` · worktree `h6-web-figures-fa35dc` (branch `choruzo/h6-web-figures-fa35dc`) ## Resultado
