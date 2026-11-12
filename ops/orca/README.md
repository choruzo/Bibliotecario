# Opción A · Orca + OpenCode

Esta carpeta implementa el ciclo de `docs/01-ciclo.md` usando **Orca como plano de control** y **OpenCode como runtime de agentes**.

## Requisitos

- Orca instalado y su runtime corriendo:
  - app de escritorio, o
  - `orca serve --no-pairing` (headless).
- `orca status --json` debe responder `runtime.state = ready`.
- OpenCode v2 en el PATH.
- El repo registrado en Orca:
  ```powershell
  orca repo add --path (Get-Location).Path --json
  orca repo set-base-ref --repo <selector> --ref main --json
  ```
- Modelo disponible: los agentes usan `nan/deepseek-v4-flash` (verificado). Cámbialo en `.opencode/agents/*.md` si usas otro proveedor.

## Estructura

| Archivo | Para qué |
|---|---|
| `lib.ps1` | Helpers: resolver el CLI, coordinador por Run, cierre verificado de terminal, auditoría y evidencia del worker. |
| `coordinator.ps1` | Crea/reutiliza la terminal coordinadora (`-RunId` para uno propio del Run). |
| `leader-terminal.ps1` | Crea una sesión OpenCode con agente `lider` y abre su TUI. |
| `worker-terminal.ps1` | Crea una sesión OpenCode con agente `worker` en el worktree y abre su TUI. |
| `new-run.ps1` | Crea un coordinador propio, crea el Run ligado a él y, opcionalmente, una tarea. |
| `dispatch.ps1` | Crea worktree + setup + terminal OpenCode + dispatch (tope duro 1-5). |
| `orchestrate.ps1` | Bucle automático: dispatch, espera, reconciliación, revisión, commit, integración, archivo y limpieza. |
| `start-loop.ps1` | Lanza el bucle de un Run de forma explícita, con validación y sin duplicados. |
| `stop-loop.ps1` | Para el runner y su árbol de procesos; no cancela workers ya despachados. |
| `loop-runner.ps1` | Runner interno: ejecuta `orchestrate.ps1`, escribe log y estado del bucle. |
| `answer-question.ps1` | Responde una pregunta con `advisor` y la envía a Orca (`-AutoAnswer`). |
| `notify.ps1` | Aviso de fin de bucle: log y webhook opcional. |
| `watch.ps1` | Espera mensajes `worker_done`, `question` o `escalation`. |
| `ack.ps1` | Reconoce una entrega procesada (evita que se repita). |
| `review.ps1` | Diff desde la rama base + staged/unstaged/untracked + `check.ps1` + veredicto. |
| `commit.ps1` | Commit de archivos exactos; acepta un HEAD ya creado por el worker. |
| `integrate.ps1` | Merge + `setup-worktree` + checks (`-Full` solo si toca la web) + fast-forward de la base. |
| `archive.ps1` | Archiva spec, reporte, commit y diff antes de limpiar. |
| `lesson.ps1` | Librería de lecciones: scaffold con evidencia de auditoría, `-Validate`, `-Index`, `-ListPending`. |
| `harness-probe.ps1` | Prueba A/B del harness: base vs variante sobre la misma tarea, contraste con el verificador y composición en la librería. |
| `library/` | Lecciones `EXPERIENCE.md` por dominio, commiteadas; el worker las consulta vía puntero. Ver `library/README.md`. |
| `cleanup.ps1` | Cierra terminales, reintenta y, opcionalmente, elimina el worktree. |
| `tests/cap5.ps1` | Prueba de tope: 6 tareas, 5 workers activos y 1 en cola. |
| `tests/graph-smoke.ps1` | Smoke del grafo: estado JSON, servidor, endpoints y HTML. |
| `tests/integrate-plan.ps1` | Repo temporal: `-Branches a,b`, `-Full` condicional y fast-forward real. |
| `tests/delivery-commit.ps1` | Review/commit con worker que commitea y con cambios sin stage. |
| `tests/kit-regression.ps1` | Invariantes estáticos y sintaxis de todos los scripts. |
| `tests/lesson.ps1` | Librería de lecciones: scaffold, `NO_ENTRY`, `-Validate` y `-Index` con estado sintético. |
| `tests/harness-probe.ps1` | Variante válida/inválida, materialización y contraste A/B con casos sintéticos. |
| `tests/session-evidence.ps1` | Registro de sesión del worker y degradación de la señal de sesión. |
| `check.ps1` | Checks del repo (whitespace, tests/lint/typecheck si existen). |
| `setup-worktree.ps1` | Setup idempotente del worktree. |
| `PROTOCOL.md` | Contrato del worker. |
| `graph.ps1` | Servidor local y estado del DAG; sirve la vista web. |
| `graph.html` | Vista del grafo: colores por estado, detalle y refresco automático. |
| `task-template.md` | Plantilla de spec autocontenida. |
| `report-template.md` | Plantilla de `report.md`. |

## Invariantes de entrega

- `completed` en Orca solo significa «el worker reportó». **No es una entrega.**
- Solo hay entrega cuando el registro local de la tarea tiene `integrationSha`.
- Al inicio de cada vuelta, el bucle reconcilia las tareas `completed` que aún
  no tienen integración: review → commit → integrate. Ver `RECONCILE` en el log.
- El worker **no** ejecuta `task-update`, `git add` ni `git commit`; el
  orquestador es el único que commitea e integra.
- Cada Run tiene su propio coordinador (`coordinator-<run>.json`). Compartir un
  coordinador entre dos bucles vivos hace que se expulsen con `consumer_fenced`.
- Una `escalation` no es fatal por sí sola: se contrasta con
  `orca orchestration worker-show` (estado del dispatch, `liveness`, `activity`
  y `agentWait`). Si el worker sigue vivo y trabajando, se ignora y se audita.
- El watchdog no reinicia por tiempo: exige prueba (`liveness=dead` o dispatch
  fallido). Silencio o `unverifiable` solo generan aviso.
- `integrate.ps1` materializa dependencias con `setup-worktree.ps1`; no enlaza
  `.venv` ni `node_modules` con junction: Turbopack rechaza un symlink fuera del
  worktree y el borrado recursivo podría seguir el enlace. `-Full` solo se pide
  si el Run toca `apps/web`.
- Un `worker_done` se contrasta con el estado vigente y con el **último**
  `dispatchId`. Si la tarea está `blocked/failed/cancelled/ready`, o el mensaje
  viene de un dispatch anterior, se descarta como `WORKER_DONE_STALE` y se
  audita; no hay review, commit ni integración.
- Si el review acepta pero `FILES=` está vacío, la rama se comprueba contra la
  base: si ya es ancestro, se registra `ALREADY_INTEGRATED` con el SHA de la
  base; si no, `review_sin_ficheros` bloquea la tarea. Nunca se reabre sin
  trabajo que commitear.
- Antes de re-despachar por defectos o conflicto, `Ensure-WorkerTerminal`
  valida el handle. Si está stale u orphaned, crea un terminal nuevo en el
  worktree, espera `tui-idle` y actualiza `workerHandle`/`dispatchId`
  (`TERMINAL_RECREATED`).

## Flujo de uso

### 1. Arrancar el runtime y el coordinador

```powershell
# En una terminal (o en segundo plano)
orca serve --no-pairing

# En otra
pwsh -NoProfile -File ops/orca/coordinator.ps1
```

Guarda el `ORCA_COORDINATOR=...` que imprime. Los scripts lo reutilizan desde `.orca-run/coordinator.json`.

### 2. Abrir el líder

En una terminal de Orca en el checkout principal:

```powershell
pwsh -NoProfile -File ops/orca/leader-terminal.ps1 -TaskTitle "fase-1"
```

Esto crea una sesión OpenCode con agente `lider` (modelo `nan/deepseek-v4-flash`) y abre su TUI. También puedes abrir `opencode` directamente: el proyecto tiene `default_agent: "lider"`.

Al arrancar, lanza en una ventana minimizada el grafo en vivo en `http://127.0.0.1:4599/` (ver sección 11). Usa `-NoDashboard` para no arrancarlo y `-OpenDashboard` para abrir el navegador. Si abres `opencode` directamente, lanza `graph.ps1` a mano.

El líder:
1. planifica con el usuario;
2. crea el Run y las tareas con `orca orchestration run-create` / `task-create`;
3. envía el mensaje corto al orquestador.

También puedes crear el Run a mano:

```powershell
pwsh -NoProfile -File ops/orca/new-run.ps1 -Objective "..." -TaskTitle "pilot-task" -Spec "..."
```

### 3. Despachar

```powershell
pwsh -NoProfile -File ops/orca/dispatch.ps1 -RunId run_... -MaxWorkers 5
```

Por cada tarea `ready`:
- crea un worktree de Orca;
- ejecuta `setup-worktree.ps1`;
- escribe `.orca-task/spec.md` y `task.json`;
- abre `worker-terminal.ps1`, que crea una sesión OpenCode con agente `worker` y lanza su TUI;
- espera `tui-idle`;
- crea el dispatch de bajo nivel con `orca orchestration dispatch --return-preamble`;
- entrega el preamble completo (incluye la spec) con `orca terminal send --enter`.

No depende de `dispatch --inject` ni de que Orca detecte el agente: el preamble se entrega como prompt. El tope 5 se calcula contando tareas en estado `dispatched`. Los dispatches se guardan en `.orca-run/dispatches-<run>.json`.

### 4. Esperar y revisar

```powershell
pwsh -NoProfile -File ops/orca/watch.ps1 -RunId run_... -TimeoutMs 900000
```

Cuando llegue un `worker_done`:

```powershell
pwsh -NoProfile -File ops/orca/review.ps1 `
  -RunId run_... `
  -TaskId task_... `
  -Worktree C:\Users\...\orca\workspaces\Pruebas\<worktree> `
  -DispatchId disp_... `
  -BaseBranch main
```

`review.ps1` compara con la rama base e incluye lo commiteado, lo staged, lo
unstaged y los archivos nuevos. Excluye `report.md`, `.orca-task/`, `.orca-run/`
y logs.

- `REVIEW=ACEPTADO` + `FILES=...` → commit.
- `REVIEW=CAMBIOS` → devuelve los defectos al mismo worker (máx. 2 rondas) y vuelve a esperar.
- Si no hay acuerdo, escala al líder.

### 5. Commit exacto

```powershell
pwsh -NoProfile -File ops/orca/commit.ps1 `
  -Worktree <worktree> `
  -TaskId task_... `
  -Files "PILOT.md","src/a.ts" `
  -Message "task(task_...): ..." `
  -BaseBranch main
```

`commit.ps1` verifica que el staged set coincide exactamente con `-Files`. Si el
worker ya había commiteado esos archivos (flujo antiguo), reutiliza el HEAD y
devuelve `COMMIT_EXISTING=1`; si mezcla archivos commiteados y sin commitear,
falla para que lo revise una persona. El flujo nuevo prohíbe al worker commitear.

### 6. Integrar

```powershell
pwsh -NoProfile -File ops/orca/integrate.ps1 `
  -RunId run_... `
  -Branches "Javi_1/pilot-dispatch-abc123" `
  -BaseBranch main
```

Crea un worktree de integración en `.orca-run/integration/<run>`, mergea las
ramas, materializa dependencias con `setup-worktree.ps1` y ejecuta los checks.
`-Branches` acepta una lista o una cadena con comas. `-Full` (build web) solo se
pide si el diff contra la base toca `apps/web`; se puede forzar con `-ForceFull`.
Al terminar imprime `INTEGRATION_SHA` y avanza la rama base por fast-forward
(`BASE_ADVANCED` o `BASE_SKIP`). Si hay conflicto, para y escala.

Para comprobar el plan sin tocar Orca:

```powershell
pwsh -NoProfile -File ops/orca/integrate.ps1 -RunId run_... -Branches "a,b" -PlanOnly
```

`tests/integrate-plan.ps1` prueba `-Branches a,b`, el `-Full` condicional y el
fast-forward en un repo temporal.

### 7. Archivar y confirmar

```powershell
pwsh -NoProfile -File ops/orca/archive.ps1 -RunId run_... -TaskId task_... -Worktree <worktree>
pwsh -NoProfile -File ops/orca/ack.ps1 -RunId run_... -DeliveryId delivery_...
```

`archive.ps1` guarda `spec.md`, `task.json`, `report.md`, `commit.txt` y `diff.patch` en `.orca-run/runs/<run>/artifacts/<task>/` antes de limpiar. `ack.ps1` marca la entrega como procesada para que `check` no la repita.

### 8. Limpiar

```powershell
pwsh -NoProfile -File ops/orca/cleanup.ps1 -RunId run_... -TaskId task_...
# y, cuando ya no necesites el worktree:
pwsh -NoProfile -File ops/orca/cleanup.ps1 -RunId run_... -TaskId task_... -RemoveWorktree -Force

# Todas las tareas asentadas del Run (integrated/failed/blocked/stalled):
pwsh -NoProfile -File ops/orca/cleanup.ps1 -RunId run_... -Settled -RemoveWorktree -Force

# Ver qué haría, sin tocar nada:
pwsh -NoProfile -File ops/orca/cleanup.ps1 -RunId run_... -Settled -RemoveWorktree -DryRun
```

`cleanup.ps1` cierra todos los terminales de los intentos de la tarea, reintenta
el borrado, cierra el workspace completo como último recurso y trata un
`terminal close` con `ok:false` + `orphaned:true` como cierre correcto. Si el
directorio sigue bloqueado, escribe `WORKTREE_LOCKED=` y sale con código 1.

### 9. Validar y push

El líder revisa el SHA de integración, comprueba que el worktree está limpio y hace el push **solo con aprobación**. Los workers tienen `git push`, `git merge` y `git rebase` denegados por permisos.

### 10. Bucle automático

Para no ejecutar los pasos 3-8 a mano:

```powershell
pwsh -NoProfile -File ops/orca/orchestrate.ps1 -RunId run_... -MaxWorkers 5 -MaxReviewRounds 2 -BaseBranch main
```

El bucle:
1. detecta reversiones silenciosas del runtime (`ready` con un dispatch que
   murió y dejó error) y las bloquea con el motivo;
2. reconcilia tareas `completed` sin `integrationSha` (review → commit → integrate);
3. cierra terminales de dispatches ya asentados;
4. despacha tareas `ready` hasta el tope (máximo duro 5);
5. espera `worker_done`, `question` o `escalation`; la escalación se cualifica
   con `worker-show` antes de matar el bucle;
6. revisa con `review.ps1` (diff desde la base + staged/unstaged + `check.ps1`);
7. si hay defectos, reabre la tarea y **re-despacha al mismo worker** con los defectos, hasta `MaxReviewRounds` (2 por defecto);
8. si se acepta, commit exacto, integración, archivo y limpieza;
9. repite hasta que no queden tareas activas ni listas.

Códigos de salida:

| Salida | Significado |
|---|---|
| `LOOP=DONE` (0) | Todas las tareas completadas/integradas. |
| `LOOP=QUESTION` (3) | Un worker preguntó; hay que responder con `reply` + `ack` y relanzar. |
| `LOOP=BLOCKED` (2) | Revisión agotada, fallo de integración o worker fallido. |
| `LOOP=ESCALATION` (2) | El worker escaló un bloqueo. |

Para lanzarlo de forma controlada, con validación y estado en el grafo, usa `start-loop.ps1` (sección 12).

Para probar el tope con 6 tareas y 5 workers:

```powershell
pwsh -NoProfile -File ops/orca/tests/cap5.ps1
```

### 11. Grafo en vivo

`leader-terminal.ps1` arranca el dashboard en una ventana minimizada al abrir la conversación del líder (salvo `-NoDashboard`). También puedes lanzarlo a mano:

```powershell
pwsh -NoProfile -File ops/orca/graph.ps1                        # http://127.0.0.1:4599/
pwsh -NoProfile -File ops/orca/graph.ps1 -Open                  # abre el navegador
pwsh -NoProfile -File ops/orca/graph.ps1 -RunId run_... -Port 4600
pwsh -NoProfile -File ops/orca/graph.ps1 -RunId run_... -Json    # estado una vez
pwsh -NoProfile -File ops/orca/graph.ps1 -Once                  # instantánea HTML
pwsh -NoProfile -File ops/orca/graph.ps1 -Stop                  # cierra los dashboards del repo
```

- Un nodo por tarea y una arista por dependencia (`deps`). Con dependencias agrupa por profundidad; sin ellas usa una rejilla compacta.
- Color por estado efectivo: `ready`, `dispatched`, `changes_requested`, `blocked`, `failed`, `escalated`, `completed`, `integrated`. Al cambiar un estado, el nodo parpadea.
- Refresco cada 3,5 s (`-RefreshMs`) sin recargar la página; si Orca deja de responder, mantiene el último estado y muestra un aviso.
- Si una tarea lleva más de `-StallMinutes` (30 por defecto) en `dispatched`, el watchdog consulta `worker-show` y la mtime de los archivos modificados. Si el worker está vivo o escribió hace poco, no avisa. Si no hay señal, escribe `WATCHDOG task=...`; con `-AutoRecoverStalled` solo reinicia cuando hay prueba (`liveness=dead` o dispatch fallido) y, si no, deja `WATCHDOG_NO_PROOF`.
- Panel de detalle: dispatch, worktree, rama, ronda, SHA de commit/integración y reporte del worker.
- Selector de Run: «Automático» sigue el Run más reciente de este repo o el que se cree con el dashboard abierto. También puedes fijar uno.
- El estado es de **solo lectura**: usa `run-list`, `run-show`, `task-list` y `.orca-run/dispatches-<run>.json`. El panel solo ejecuta las cuatro acciones permitidas (lanzar, parar, responder, reintentar) con el token local; no hay comandos libres.
- La franja de fases es **estimada** a partir de los estados. El push no se registra, así que «Push y cierre» no confirma que se haya publicado.
- Escucha solo en `127.0.0.1` y guarda su PID en `.orca-run/graph-<puerto>.json`.
- El dashboard es un `pwsh` en una ventana minimizada. Si el antivirus lo bloquea o lo deja colgado, añade una exclusión para la carpeta del proyecto y para `%LOCALAPPDATA%\Programs\orca`, o lánzalo en una terminal visible con `pwsh -NoProfile -File ops/orca/graph.ps1`.

Prueba de humo:

```powershell
pwsh -NoProfile -File ops/orca/tests/graph-smoke.ps1 -RunId run_...
```

### 12. Lanzar el bucle desde el líder

El líder **no** arranca el bucle al crear el Run. Después de `task-create` pregunta con `question`:

- **Ejecutar ahora** → ejecuta `start-loop.ps1`.
- **Solo planificar** → deja el Run listo y no lanza nada.
- **Ejecutar más tarde** → no lanza nada e indica el comando.

Solo en el primer caso:

```powershell
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -MaxWorkers 5
```

`start-loop.ps1`:

1. comprueba que el Run existe y que hay tareas `ready` o `dispatched`;
2. rechaza duplicados si el runner anterior sigue vivo;
3. avisa si hay otro bucle en marcha (el tope de 5 es por bucle);
4. crea o reutiliza el **coordinador propio del Run** (`coordinator-<run>.json`);
5. lanza `loop-runner.ps1` en una ventana minimizada;
6. deja `.orca-run/loop-<run>.json` (estado) y `.orca-run/loop-<run>.log` (salida).

Cada Run tiene su coordinador. Si creas el Run con `new-run.ps1`, nace ligado a
él y `start-loop` no re-liga ni expulsa al líder. Si lo creas con
`orca orchestration run-create`, el líder queda como consumidor y `start-loop`
lo re-ligará al coordinador; a partir de ahí, muta el Run con `--from
<coordinator>` o desde el panel.

El runner ejecuta `orchestrate.ps1` y traduce el resultado a `done`, `question`, `blocked`, `escalated` o `failed`. El grafo muestra el estado del bucle y la última línea del log; si el proceso muere, pasa a **sin proceso**.

Opciones:

```powershell
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -DryRun      # valida y muestra el comando
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -Foreground  # ejecuta en esta terminal
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -MaxReviewRounds 3 -BaseBranch main
```

No hay parada limpia: cerrar la ventana del runner lo mata, pero los workers ya despachados pueden seguir hasta enviar `worker_done`. El grafo lo refleja y la tarea queda visible.

### 13. Autonomía: asesor y rescate de conflictos

**Asesor de dudas.** El subagente `advisor` (`.opencode/agents/advisor.md`,
`nan/qwen3.8-flash`) es read-only. El worker lo consulta antes de bloquearse:

- Si el asesor responde `DECISION: ANSWER`, el worker sigue con esa decisión.
- Si responde `DECISION: ESCALATE`, el worker usa `orca orchestration ask` y el
  bucle se detiene para que decida una persona.

El asesor no edita, no ejecuta comandos y no puede aprobar cambios de alcance.

El worker tiene **300 pasos**, envía un `heartbeat` cada ~10 min o al cambiar de
fase, y si se queda sin pasos entrega primero (`report.md` + `worker_done`).

**Rescate de conflictos.** Con `-AutoRescue`, si la integración falla:

1. El orquestador mergea `orca/integration/<run>` en el worktree de la tarea.
2. Si el merge es limpio, reintenta la integración una vez.
3. Si hay conflicto, re-despacha al **mismo worker** con la lista de archivos y
   la orden de resolverlos conservando ambos lados. El worker no hace
   `git merge`, `git add`, `git commit` ni `git rebase`: solo edita, ejecuta el
   check y reporta.
4. `review.ps1` valida y `commit.ps1` cierra el merge con los archivos exactos.
5. Se reintenta la integración. Si vuelve a fallar, se repite hasta
   `-MaxRescueRounds` (2 por defecto); después queda `blocked` para una persona.

```powershell
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -AutoRescue -MaxRescueRounds 2 -DryRun
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -AutoRescue -MaxRescueRounds 2
```

Está **desactivado por defecto**: resolver conflictos es delicado y el LLM puede
equivocarse. El gate (`check.ps1`) y el máximo de rondas son la red de seguridad;
si el worker no lo ve claro, debe preguntar. No sustituye a revisar el merge
antes del push.

### 14. Responder preguntas automáticamente

Con `-AutoAnswer`, cuando el bucle termina en `LOOP=QUESTION`:

1. `orchestrate.ps1` guarda la pregunta completa en `.orca-run/question-<run>.json`
   antes de confirmar la entrega.
2. `loop-runner.ps1` llama a `answer-question.ps1`.
3. El script arma un contexto con la pregunta, opciones, objetivo, spec, reporte
   y estado del worktree, y se lo pasa al subagente `advisor` en modo read-only.
4. Si el asesor responde `DECISION: ANSWER`, el bucle envía la respuesta con
   `orca orchestration reply` y relanza `orchestrate.ps1`.
5. Si responde `DECISION: ESCALATE`, o el asesor falla, el bucle se detiene en
   `question` para que decida una persona.

```powershell
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -AutoAnswer -MaxAutoAnswers 3 -DryRun
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -AutoAnswer -MaxAutoAnswers 3
```

- Máximo `-MaxAutoAnswers` por ejecución (3 por defecto); después pregunta.
- Cada Q&A queda en `.orca-run/answers/<run>/<messageId>.json` y su prompt en
  `-prompt.md`.
- El asesor no puede editar, ejecutar comandos ni aprobar cambios de alcance;
  si falta spec o evidencia, escala.
- Se puede combinar con `-AutoRescue`:

```powershell
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -AutoAnswer -AutoRescue
```

Sigue siendo autonomía **con freno**: el push final y los cambios de alcance
siguen siendo humanos.

### 15. Modelos por rol

Routing actual (todos disponibles en `/v1/models` de NaN):

| Rol | Modelo | Criterio |
|---|---|---|
| `lider` | `nan/deepseek-v4-flash` | planificar y razonar; buen equilibrio |
| `auditor` | `nan/qwen3.8-flash` | lectura rápida y barata |
| `reviewer` | `nan/deepseek-v4-flash` | profundidad de revisión |
| `worker` | `nan/glm5.3-flash` | agente de código, 1M de contexto, menos créditos que `glm5.3` |
| `worker-reader` / `worker-writer` | `nan/glm5.3-flash` | mismo stack de código |
| `advisor` | `nan/qwen3.8-max` | razonamiento duro para dudas, volumen bajo |
| `worker-repair` | `nan/glm5.3` | una ronda extra de review con modelo distinto y más capacidad |

Los modelos «larger» (`glm5.3`, `qwen3.8-max`) consumen créditos más rápido;
por eso se usan solo en advisor y reparación. El modelo global de
`opencode.jsonc` sigue siendo el del líder; cada agente lo sobreescribe.

### 16. Recuperación y presupuesto

```powershell
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... `
  -AutoAnswer -AutoRescue -AutoRepair -AutoRecoverStalled `
  -MaxTotalWorkers 5 -MaxRunMinutes 240
```

- **Worker estancado** (`-AutoRecoverStalled`): el watchdog, tras
  `-StallMinutes` (30), consulta `worker-show`, la última escritura del
  worktree y la **actividad real de la sesión OpenCode** (RF2.3: el terminal
  registra la sesión vigente en `.orca-task/opencode-session.json` y el
  watchdog la consulta por la API local; ver `Get-SessionActivityUtc`). Si el
  worker sigue vivo o hay señal reciente, no hace nada. Solo
  reinicia cuando hay prueba (`liveness=dead` o dispatch fallido): para el
  dispatch, cierra su terminal, marca la tarea `ready` con `stalled_recovery` y
  deja que `dispatch.ps1` la re-despache. Máximo `-MaxStallRecoveries` (1);
  después queda `blocked`. Silencio o `unverifiable` dejan `WATCHDOG_NO_PROOF`
  con la edad de la señal de sesión (`session=<min>`). La señal de sesión
  **solo suma vida, nunca mata**: la actividad del modelo sin escrituras ni
  heartbeats ya no parece estancamiento.
- **Review agotada** (`-AutoRepair`): tras `MaxReviewRounds`, se crea un
  `worker-repair` (modelo `glm5.3`) en el mismo worktree, con presupuesto nuevo
  y los defectos; máximo `-MaxRepairRounds` (1). Después, `blocked`.
- **Tope global** (`-MaxTotalWorkers`, 5): suma los `maxWorkers` de los bucles
  vivos **de este repo** y rechaza el nuevo si se pasa. `0` desactiva el límite.
- **Presupuesto** (`-MaxRunMinutes`, 0 = sin límite): el runner comprueba el
  tiempo antes de cada intento y termina en `stopped` si se agotó. No interrumpe
  un `orchestrate` en curso. El presupuesto de **tokens** no está expuesto por
  Orca/OpenCode por Run; usa el tiempo como proxy o controla créditos en NaN.
- **Caída del runner**: al arrancar, `orchestrate.ps1` detecta tareas
  `dispatched` cuya terminal ya no está conectada. Solo las reabre si hay
  prueba (`liveness=dead`, dispatch `failed/cancelled` o `lastError` con la
  terminal desconectada); si no, deja `RESUME_UNPROVEN` y espera. Una tarea
  `ready` con un dispatch que murió por `stop was requested` se bloquea con
  `runtime_stop: <lastError>` en vez de reabrirse en silencio.
- **Escalaciones**: no toda `escalation` mata el bucle. Si el dispatch está
  `completed/failed`, o el worker está `live`/`working`, se registra
  `ESCALATION_IGNORED`. Si `liveness` es `unverifiable/unknown`, se difiere y
  se exigen dos avisos separados ≥30 s. Si `agentWait` no es nulo, el worker
  espera aprobación humana y se detiene en `ESCALATION_WAITING`. Todo queda en
  `audit-<run>.jsonl`.
- **Notificaciones**: `notify.ps1` escribe `.orca-run/notifications.log` y, si
  `ORCA_NOTIFY_WEBHOOK` está definido, hace POST JSON. Si existe BurntToast,
  también lanza un toast. Se dispara al cerrar el bucle (`done`, `question`,
  `blocked`, `escalated`, `failed`, `stopped`).

### 17. Panel de control

El grafo servido (`http://127.0.0.1:4599/`) incluye un panel para:

- **Lanzar bucle** con `Workers`, `Minutos` y los flags `AutoAnswer`,
  `AutoRescue`, `AutoRepair` y `Recuperar estancados`.
- **Parar** el runner (`stop-loop.ps1`). No cancela workers ya despachados.
- **Responder** la pregunta pendiente, con opciones clicables y
  «Responder y lanzar».
- **Reintentar tarea**: marca `ready` una tarea `blocked`/`failed`, actualiza el
  registro local y se niega si el runner sigue vivo (para no robarle el binding).
- **Ver log**: últimas 300 líneas de `loop-<run>.log`.

Seguridad:

- Solo escucha en `127.0.0.1`.
- El servidor genera un token por arranque y lo inyecta en la página; los POST
  exigen `X-Orca-Token`. Sin token: 403.
- No hay comandos libres: solo las cuatro acciones con IDs validados.
- `-Once` es una instantánea y desactiva el panel.
- El panel no hace push; el gate humano sigue en la terminal.

### 18. Librería de lecciones

Cada tarea integrada o escalada deja una marca `LESSON_PENDING` en el log y un
evento `lesson-candidate` en `audit-<run>.jsonl`. El líder (o una persona) la
convierte en una lección reutilizable:

```powershell
pwsh -NoProfile -File ops/orca/lesson.ps1 -ListPending      # tareas marcadas sin lección
pwsh -NoProfile -File ops/orca/lesson.ps1 -RunId <run>      # scaffoldea todas las pendientes
pwsh -NoProfile -File ops/orca/lesson.ps1 -Validate         # falla si hay lecciones incompletas
pwsh -NoProfile -File ops/orca/lesson.ps1 -Index            # regenera el índice
```

- El borrador autocompleta **evidencia** citando la auditoría y el report
  archivado; `Cue` y `Lesson` se rellenan a mano (o con `-Cue`/`-Lesson`).
- Sin evidencia real no hay lección: `lesson.ps1` lo registra como `NO_ENTRY`.
- Las lecciones viven en `ops/orca/library/` (commiteadas, viajan con los
  worktrees) y el worker recibe un puntero en su preamble para consultar
  `INDEX.md` antes de empezar. Formato y reglas: `ops/orca/library/README.md`.

### 19. Prueba A/B del harness

Para validar una hipótesis de mejora del worker se ejecuta la misma tarea de
calibración dos veces en paralelo — base (harness tal cual) y variante — y decide
el verificador que ya existe:

```powershell
# La variante la propone el agente harness-editor en .orca-run/harness-variants/<nombre>/
pwsh -NoProfile -File ops/orca/harness-probe.ps1 -SpecFile <spec.md> -VariantDir <dir> -DryRun
pwsh -NoProfile -File ops/orca/harness-probe.ps1 -SpecFile <spec.md> -VariantDir <dir> -MaxProbeMinutes 25
```

- La variante es un directorio de **archivos completos**: lo que incluye
  sobrescribe, lo que omite se hereda. `Test-HarnessVariant` la rechaza si toca
  superficies prohibidas, supera el tope always-on (24.000 chars) o pierde las
  denegaciones del kit (`git commit`, `task-update`).
- El contraste solo adopta con diferencia **medible**: veredicto del review, gate
  de checks o número de defectos. Empate → «sin contraste medible», nada se adopta.
- El resultado se compone en `ops/orca/library/<dominio>/harnesses/<probe>/`:
  `RESULT.md` siempre y, si la variante gana, `variant/` (árbol adoptado) +
  `proposal.diff` para que una persona lo aplique al kit. El probe nunca integra
  ni hace push; deja la marca `lesson-candidate` en la auditoría para el flujo de
  lecciones.

## Reglas y límites

| Límite | Dónde |
|---|---|
| 5 workers simultáneos | `dispatch.ps1 -MaxWorkers` |
| 3 subagentes por worker | Prompt del worker + permisos |
| 1 escritor por worktree | Permisos + disciplina del worker |
| 2 rondas de revisión | `review.ps1` / política del orquestador |
| Un bucle vivo por Run | `start-loop.ps1` |
| Un coordinador por Run | `lib.ps1` + `coordinator-<run>.json` |
| `completed` no es entrega | Reconciliación + `integrationSha` |
| Worker sin `task-update`/commit | Permisos de `worker.md` + `worker-repair.md` |
| Sin ejecución sin elección del usuario | Pregunta del líder (`question`) |
| Estado del bucle visible | `loop-<run>.json` + `graph.ps1` |
| Aviso de worker estancado | `orchestrate.ps1 -StallMinutes 30` con evidencia |
| Asesor de dudas read-only | `.opencode/agents/advisor.md` |
| Rescate de conflictos | `start-loop.ps1 -AutoRescue` |
| Respuesta automática de dudas | `start-loop.ps1 -AutoAnswer` |
| Reparación tras review | `start-loop.ps1 -AutoRepair` |
| Worker estancado | `start-loop.ps1 -AutoRecoverStalled` |
| Tope global de workers | `start-loop.ps1 -MaxTotalWorkers` (5) |
| Presupuesto de tiempo | `start-loop.ps1 -MaxRunMinutes` (0 = sin límite) |
| Notificaciones | `notify.ps1` + `ORCA_NOTIFY_WEBHOOK` |
| Reanudar terminales muertas | `orchestrate.ps1` al arrancar |
| Tope global entre Runs | No impuesto; `start-loop.ps1` solo avisa |
| Sin push/merge en workers | `opencode.jsonc` + agentes |
| Informes archivados antes de limpiar | `archive.ps1` + `cleanup.ps1` |

## Limitaciones actuales

- `GET /api/config` del servidor OpenCode local devuelve las claves de API de
  los proveedores en claro a cualquier cliente autenticado. El servidor solo
  escucha en localhost y el panel exige token, pero tenlo en cuenta si das
  acceso a la API a procesos no confiables.

- Es un **piloto**, no un orquestador completo: el bucle de revisión/devolución es semiautomático.
- El estado de negocio vive en Orca; `.orca-run/` solo guarda mappings y artefactos locales.
- `dispatch.ps1` asume que el worktree se crea desde `main`; para tareas dependientes, usa la rama de integración como `-BaseBranch`.
- La limpieza de worktrees es explícita (`cleanup.ps1 -RemoveWorktree` o `-Settled`); no se borra nada sin pedirlo. `cleanup.ps1` cierra todos los terminales de la tarea, reintenta el borrado y, si el directorio sigue bloqueado, deja `WORKTREE_LOCKED=<ruta>` y sale con código 1.
- El bucle automático está implementado y probado en el camino feliz y con una devolución por defectos; el escalado tras agotar `MaxReviewRounds` está codificado pero no se ha forzado en una prueba real.
- Orca Orchestration es experimental: los comandos pueden cambiar. Fija la versión y revisa `orca skills get orchestration --full`.
- Compatible con CLI 1.4.237 y 1.4.255: la nueva devuelve `task-list` conciso salvo `--full` (el kit lo pide con fallback) y puede omitir fechas en `run-list`/`run-show`; el grafo las muestra como «—».
- El worker se lanza con `--auto` para no bloquearse en permisos; las denegaciones explícitas (push/merge/reboot, `.env`, external dirs) siguen vigentes.
- El líder se lanza sin `--auto`; su `git push` queda en `ask` y requiere aprobación.
- El grafo es de solo lectura y sondea el CLI cada pocos segundos: no sustituye a la app de Orca ni conoce el estado real del push.
- `start-loop.ps1` protege contra duplicados del **mismo** Run, pero no impone un tope global entre Runs: dos bucles pueden sumar 10 workers. El aviso es informativo. Cada bucle usa su propio coordinador; no compartas `coordinator.json` entre Runs.
- `stop-loop.ps1` detiene el runner, pero **no cancela** los workers ya despachados. Sirve para dejar de revisar/integrar, no para abortar el trabajo en curso. Los workers que terminen después se reconciliarán en el siguiente arranque.

## Notas de Windows y antivirus

- Ejecuta los scripts con `pwsh -NoProfile -File ...`; evita `pwsh -Command` largos con rutas y JSON, porque algunos antivirus los marcan como heurística sospechosa.
- Si el antivirus escanea `orca.exe` u `opencode-cli.exe` en cada arranque, añade una **exclusión de carpeta** para `%LOCALAPPDATA%\Programs\orca` y `%APPDATA%\ai.opencode.desktop`, o lanza los scripts en segundo plano.
- No desactives la protección global del antivirus.
- `orca` puede tardar varios segundos la primera vez que se ejecuta tras un arranque; los timeouts de los scripts están pensados para eso.

## Estado local

```text
.orca-run/
├── coordinator.json              # legado / líder
├── coordinator-<run>.json        # coordinador propio del Run
├── dispatches-<run>.json
├── escalations-<run>.json
├── audit-<run>.jsonl             # quién hizo stop/restart/retry/integrate
├── question-<run>.json
├── graph-<puerto>.json
├── loop-<run>.json
├── loop-<run>.log
├── answers/<run>/
├── runs/<run>/artifacts/<task>/
└── integration/<run>/
```

No se versiona. Los worktrees de Orca viven en `C:\Users\<user>\orca\workspaces\<repo>\...`.
