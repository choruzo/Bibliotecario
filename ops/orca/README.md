# Ciclo Orca + OpenCode

> **Adaptación a Bibliotecario**
>
> `check.ps1` ejecuta los tests de `apps/api`, los contratos H0 (solo si el
> corpus `docs/*.md` está presente) y `npm --prefix apps/web run typecheck`;
> `-Full` añade el build de Next.js. `setup-worktree.ps1` usa `.venv` y
> `apps/web/node_modules` compartidos y copia `.env`. Ver `AGENTS.md` en la raíz.

Guía operativa del kit. Los detalles del proyecto están en `CHECKS.md` y en el `README` del repo.

## Arranque

```powershell
orca serve --no-pairing          # o la app de Orca
orca status --json               # runtime.state = ready

orca repo add --path (Get-Location).Path --json
orca repo set-base-ref --repo id:<id> --ref main --json

pwsh -NoProfile -File ops/orca/coordinator.ps1
```

## Líder y tareas

```powershell
pwsh -NoProfile -File ops/orca/leader-terminal.ps1 -TaskTitle "fase-1"
```

El líder trabaja en PLAN, crea el Run y las tareas, y manda el mensaje corto al orquestador.

Al arrancar, lanza también el grafo en vivo en `http://127.0.0.1:4599/`
(`-NoDashboard` para evitarlo, `-OpenDashboard` para abrir el navegador).

Después de crear las tareas, el líder pregunta con `question`: ejecutar ahora,
solo planificar o ejecutar más tarde. No arranca el bucle sin esa elección.

Para una tarea manual:

```powershell
pwsh -NoProfile -File ops/orca/new-run.ps1 `
  -Objective "..." `
  -TaskTitle "..." `
  -Spec "..."
```

## Ciclo

Automático:

```powershell
pwsh -NoProfile -File ops/orca/orchestrate.ps1 `
  -RunId run_... `
  -MaxWorkers 5 `
  -MaxReviewRounds 2 `
  -BaseBranch main
```

O con el disparo controlado que usa el líder (recomendado):

```powershell
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -MaxWorkers 5
```

`start-loop.ps1` valida las tareas, evita duplicados y deja estado/log para el grafo.

Manual:

```powershell
pwsh ops/orca/dispatch.ps1 -RunId run_... -MaxWorkers 5
pwsh ops/orca/watch.ps1 -RunId run_...
pwsh ops/orca/review.ps1 -RunId run_... -TaskId task_... -Worktree <worktree>
pwsh ops/orca/commit.ps1 -Worktree <worktree> -TaskId task_... -Files "..." -Message "..."
pwsh ops/orca/integrate.ps1 -RunId run_... -Branches "<branch>" -BaseBranch main
pwsh ops/orca/archive.ps1 -RunId run_... -TaskId task_... -Worktree <worktree>
pwsh ops/orca/ack.ps1 -RunId run_... -DeliveryId delivery_...
pwsh ops/orca/cleanup.ps1 -RunId run_... -TaskId task_... -RemoveWorktree -Force
```

## Grafo en vivo

`graph.ps1` sirve una vista web del DAG de tareas (colores por estado, dependencias, rondas y reporte del worker):

```powershell
pwsh -NoProfile -File ops/orca/graph.ps1                 # http://127.0.0.1:4599/
pwsh -NoProfile -File ops/orca/graph.ps1 -Open           # abre el navegador
pwsh -NoProfile -File ops/orca/graph.ps1 -RunId run_...  # fija un Run
pwsh -NoProfile -File ops/orca/graph.ps1 -Stop
```

Es de solo lectura: consulta Orca y `.orca-run/dispatches-<run>.json`, y se refresca cada 3,5 s.
El modo «Automático» sigue el Run más reciente de este repo o el que se cree con el dashboard abierto.
También muestra el estado de `loop-<run>.json`: ejecutando, pregunta pendiente, terminado, bloqueado o sin proceso.

## Reglas

- Hasta 5 workers activos.
- Hasta 2 rondas de defectos por tarea.
- Un worker no hace push, merge ni rebase.
- El commit es de archivos exactos.
- Los informes se archivan antes de limpiar.
- `LOOP=QUESTION` significa que un worker espera respuesta: `reply` + `ack` + relanzar.
- Los checks reales están en `check.ps1`; el worker no decide si pasa.

## Solución rápida

| Síntoma | Acción |
|---|---|
| `no_active_sender_terminal` | Ejecutar desde el coordinador o pasar `--from`/`--terminal`. |
| `Agent not found` | Revisar que el worktree tenga `.opencode/agents` y que el modelo exista. |
| `no recognized agent detected` | Usar el dispatch de bajo nivel + `terminal send` (ya lo hace `dispatch.ps1`). |
| Worktree bloqueado | Antivirus/archivo en uso; excluir la carpeta o borrar cuando termine. |
| Check lento | Ajustar `check.ps1` o usar `ORCA_PYTEST_ARGS`/equivalente. |



## Sincronizacion con el kit central

Actualizado desde `C:\Users\javie\Documents\Pruebas` el 2026-11-11: grafo y
panel de control, AutoAnswer/AutoRescue/AutoRepair, recuperacion de workers
estancados, reanudacion de terminales muertas, presupuesto, notificaciones y
routing de modelos. `check.ps1` y `setup-worktree.ps1` siguen siendo los
adaptados a Bibliotecario.

## Sincronizacion 2026-11-12

Integridad de entrega: `completed` no cuenta hasta tener `integrationSha`;
reconciliacion de tareas completadas sin integrar, worker sin `task-update` ni
commit, coordinador por Run, escalaciones cualificadas con `worker-show`,
watchdog con evidencia, `integrate.ps1` con `setup-worktree`/`-Full`
condicional/fast-forward y `cleanup.ps1` con reintentos y `-Settled`.
`check.ps1` y `setup-worktree.ps1` siguen siendo los adaptados a Bibliotecario.
