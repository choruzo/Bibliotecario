# AGENTS.md - Bibliotecario

Este repo es una aplicacion local de biblioteca conversacional: API FastAPI +
web Next.js 16 + Postgres/pgvector + LiteLLM, orquestada con Docker Compose.
La capa de agentes vive en `ops/orca/` y `.opencode/agents/`.

## Stack

| Area | Ruta | Comandos |
|---|---|---|
| API | `apps/api` | Python 3.12, FastAPI, SQLAlchemy, Alembic, pytest |
| Web | `apps/web` | Next.js 16, React 19, TypeScript, Playwright |
| Datos | `compose.yaml` | Postgres/pgvector, LiteLLM, worker |
| Corpus | `docs/` | `docs/*.md` no se versiona; `docs/h0/` si |

- Entorno Python: `.venv` (creado con `uv`; no tiene `pip`). Usa `uv pip`.
- `venv/` es un entorno antiguo de Python 3.10: no lo uses.
- Node: `npm` 11 y Node 22; no hay `pnpm`.
- Next.js 16 tiene reglas propias en `apps/web/AGENTS.md` (lo regenera
  `next dev`). Leelo antes de tocar la web y no borres ese bloque.

## Gate

```powershell
pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .
pwsh -NoProfile -File ops/orca/check.ps1 -Worktree . -Full
```

- Default: `git diff --check`, tests de `apps/api`, tests H0 de `tests/` y
  `npm --prefix apps/web run typecheck`.
- H0 depende del corpus privado `docs/*.md`, que no se versiona ni viaja al
  worktree. En un worktree el check lo omite con `H0_SKIP`; en el checkout
  principal si se ejecuta.
- `-Full`: ademas `npm --prefix apps/web run build`.
- `review.ps1` anade `-RequireReport`; sin `report.md` la revision falla.
- Playwright **no** esta en el gate: necesita servidor web y navegador. Si una
  tarea toca UI, ejecutalo a mano con `npm --prefix apps/web test`.
- El check de API tarda ~90 s. Es normal.

## Worktrees

- `orca.yaml` comparte `.venv` y `apps/web/node_modules` entre worktrees.
- La API esta instalada en modo editable apuntando al checkout principal. Para
  probar el codigo del worktree, `check.ps1` pone
  `PYTHONPATH=<worktree>/apps/api`. Si ejecutas pytest a mano, haz lo mismo.
- `.env` se copia al worktree. `bibliotecario-data/` **no** se copia: contiene
  datos persistentes y no debe compartirse entre tareas.
- Un test que necesite Docker/Postgres debe usar un `BIB_DATA_DIR` propio y
  puertos libres; no apuntes al `bibliotecario-data/` del checkout principal.
- Commit del kit antes de crear worktrees: el worktree parte de `main` y no ve
  archivos sin commitear.

## Ciclo Orca + OpenCode

```powershell
orca status --json
pwsh -NoProfile -File ops/orca/coordinator.ps1
pwsh -NoProfile -File ops/orca/leader-terminal.ps1 -TaskTitle "fase-1"
```

- El lider planifica y crea Run/Tasks; no edita codigo ni despacha workers.
- Tras crear las tareas pregunta: **Ejecutar ahora**, **Solo planificar** o
  **Ejecutar mas tarde**. Solo el primer caso lanza el bucle.
- Nunca lances `orchestrate.ps1` directamente. Usa:

```powershell
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -MaxWorkers 2 -DryRun
pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -MaxWorkers 2
```

- Empieza con 2 workers; el tope duro es 5 **por bucle**. No hay tope global
  entre Runs.
- Dashboard: `http://127.0.0.1:4599/`; estado del bucle en
  `.orca-run/loop-<run>.json` y log en `.orca-run/loop-<run>.log`.
- Una tarea = una rama = un worktree = un writer. Maximo 3 subagentes por worker.
- `worker_done` se envia una sola vez; el worker se detiene despues.
- `completed` en Orca no es entrega: el bucle reconcilia y exige `integrationSha`.
- El worker no ejecuta `task-update`, `git add` ni `git commit`.
- Sin push/merge/rebase en workers. El push del lider requiere aprobacion.
- `LOOP=QUESTION` (3): responder con `reply` y relanzar. `LOOP=BLOCKED` o
  `ESCALATION` (2): decidir con la evidencia. `stop-loop.ps1` detiene el runner y su arbol de procesos, pero no cancela
workers ya despachados. `LOOP=QUESTION` puede resolverse con `-AutoAnswer`; si
el asesor escala, se responde desde el panel o con `reply`.

## Panel y recuperacion

- Panel local en `http://127.0.0.1:4599/`: lanzar/parar el bucle, responder
  preguntas, reintentar tareas y ver el log. Los POST exigen el token local que
  inyecta la pagina.
- Flags del bucle: `-AutoAnswer`, `-AutoRescue`, `-AutoRepair`,
  `-AutoRecoverStalled`, `-MaxTotalWorkers` (5) y `-MaxRunMinutes`.
- `stop-loop.ps1` para el runner; no cancela workers ya despachados.
- `-AutoRepair` usa `worker-repair` con `glm5.3`; `advisor` usa `qwen3.8-max`.
- `notify.ps1` avisa en `done`, `question`, `blocked`, `escalated`, `failed` y
  `stopped`; webhook opcional en `ORCA_NOTIFY_WEBHOOK`.


## Integridad de entrega

- `completed` en Orca solo significa «el worker reporto». Solo hay entrega
  cuando `dispatches-<run>.json` tiene `integrationSha`.
- Al inicio de cada vuelta, el bucle reconcilia las tareas `completed` sin
  integrar: review -> commit -> integrate (`RECONCILE` en el log).
- El worker no ejecuta `task-update`, `git add` ni `git commit`; el
  orquestador es el unico que commitea e integra.
- Cada Run tiene su coordinador (`coordinator-<run>.json`). `new-run.ps1` crea
  el Run ya ligado a el. No compartas un coordinador entre dos bucles vivos:
  el segundo expulsa al primero con `consumer_fenced`.
- Las escalaciones se cualifican con `worker-show`: `ESCALATION_IGNORED` si el
  dispatch esta settled o el worker sigue `live/working`; `ESCALATION_DEFER`
  si es `unverifiable` (dos avisos >=30 s); `ESCALATION_WAITING` si hay
  `agentWait`.
- El watchdog no reinicia por tiempo: exige `liveness=dead` o dispatch
  fallido. Si no hay prueba, deja `WATCHDOG_NO_PROOF`.
- `cleanup.ps1` cierra todos los intentos, reintenta y soporta
  `-Settled -RemoveWorktree -Force` y `-DryRun`.
- `integrate.ps1` usa `setup-worktree.ps1`, pide `-Full` solo si el Run toca
  `apps/web` y avanza `main` por fast-forward (`BASE_ADVANCED`).

## Modelos y claves

| Rol | Modelo |
|---|---|
| `lider` | `nan/deepseek-v4-flash` |
| `auditor` | `nan/qwen3.8-flash` |
| `reviewer` | `nan/deepseek-v4-flash` |
| `worker` / `worker-reader` / `worker-writer` | `nan/glm5.3-flash` |
| `advisor` | `nan/qwen3.8-max` |
| `worker-repair` | `nan/glm5.3` |

- `opencode.jsonc` mantiene el modelo global del lider; cada agente lo
  sobreescribe.
- `NAN_API_KEY` debe estar en el entorno del proceso de Orca, no solo en tu
  shell: los workers heredan el de la app.
## Registro en Orca

Con el runtime en marcha (`orca status --json` -> `runtime.state = ready`):

```powershell
orca repo add --path "D:/Archivos/Javier/Proyectos/Bibliotecario" --json
orca repo set-base-ref --repo id:<id> --ref main --json
```

## Git

- Conventional commits con scope: `feat(api):`, `fix(web):`, `test(api):`,
  `docs(h0):`, `chore(orca):`.
- No commitear: `.venv/`, `venv/`, `bibliotecario-data/`, `.artifacts/`,
  `node_modules/`, `.next/`, `docs/*.md`, `.orca-run/`.
- No push automatico.

## Trampas conocidas

- La API editable apunta al checkout principal; sin `PYTHONPATH` los tests del
  worktree prueban el codigo de `main`. El gate ya lo corrige.
- `docs/*.md` esta ignorado salvo `docs/h0/`; el corpus no esta en el repo.
- Los tests H0 dependen de `evaluation/h3/` y `docs/h0/`; no los borres.
- `apps/web/AGENTS.md` lo regenera Next.js; no lo edites a mano.
- El antivirus de Windows puede bloquear worktrees: usa `cleanup.ps1` con
  paciencia y excluye `%USERPROFILE%\orca\workspaces` si hace falta.
