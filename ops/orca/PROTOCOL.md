# Protocolo del worker (opción A · Orca + OpenCode)

Este documento complementa el preamble que Orca inyecta en cada worker. Si algo no coincide, **manda el preamble de Orca**: contiene el `task_id`, el `dispatch_id` y el `--from` exactos de tu intento.

## Identidad del intento

- `task_id`: la tarea del Run.
- `dispatch_id`: tu intento autoritativo. No uses el de otro intento.
- `workerHandle`: la terminal que Orca te asignó; el CLI lo detecta solo.
- `fencing`: si Orca lo incluye, no lo cambies.

## Comandos

Dentro de una terminal de Orca, `ORCA_TERMINAL_HANDLE` ya está definido. No pases `--from` salvo que el preamble lo indique.

### Consultar mensajes

```bash
orca orchestration check --json
orca orchestration check --wait --types worker_done,question,escalation --timeout-ms 60000 --json
```

### Preguntar al orquestador (bloqueante)

```bash
orca orchestration ask --question "¿Actualizo el componente compartido o solo esta página?" --options "compartido,solo-pagina" --timeout-ms 600000 --json
```

Si hay timeout, la pregunta queda pendiente. Reanuda con el `message_id`; no la dupliques.

### Latir durante trabajo largo

```bash
orca orchestration send --type heartbeat --subject "alive" --phase "implementing" --task-id <task_id> --dispatch-id <dispatch_id> --json
```

### Terminar

```bash
orca orchestration send --type worker_done \
  --subject "<resumen corto>" \
  --body "<qué hiciste, qué encontraste, qué queda>" \
  --task-id <task_id> \
  --dispatch-id <dispatch_id> \
  --outcome succeeded \
  --files-modified "src/a.ts,tests/a.test.ts" \
  --report-path "report.md" \
  --json
```

- `worker_done` se envía **una sola vez**, también si fallas (`--outcome failed`).
- Incluye siempre `task_id` y `dispatch_id`.
- Después de `worker_done`, **detente**. No empieces trabajo nuevo ni esperes en bucle.

## Reglas

1. Una tarea, un worktree, un writer.
2. Hasta 3 subagentes; solo uno escribe. Los lectores son read-only.
3. No toques otros worktrees.
4. No hagas `git push`, `git merge` ni `git rebase`.
5. Ejecuta los checks con `pwsh ops/orca/check.ps1 -Worktree .`.
6. Escribe `report.md` en la raíz del worktree.
7. Si el orquestador devuelve defectos, corrige exactamente esos defectos y vuelve a reportar.
8. Si no puedes verificar algo, dilo; no lo declares verde.

## Informe mínimo

```markdown
# Reporte · <task_id>

## Resultado
<2-4 frases: qué se hizo y si cumple la aceptación>

## Archivos
- `...` — <qué cambió>

## Checks
| Check | Comando | Resultado |
|---|---|---|
| ... | ... | PASS/FAIL |

## Decisiones
- ...

## Riesgos / pendientes
- ...
```

## Si algo falla

- Falla de setup o de dependencia: no sigas; reporta `failed` con el error.
- Falla de test: corrige si está en el alcance; si no, pregunta.
- Conflicto de integración: no lo resuelvas por tu cuenta; escala.
- Push/merge: no lo intentes; el permiso está denegado.

