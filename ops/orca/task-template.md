# Tasks del ciclo (plantilla)

Copia esta plantilla en `task-create --spec` y rellénala. La spec debe ser **autocontenida**: el worker no verá la conversación del líder.

## Objetivo
<Qué debe existir al terminar, en una frase verificable.>

## Contexto
<Repo, módulo, decisiones previas, enlaces. Sin remitir a la conversación del líder.>

## Alcance
- Incluye: ...
- No incluye: ...

## Archivos probablemente afectados
- `src/...`
- `tests/...`

## Dependencias
- `<task_id>` (debe estar integrada)

## Criterios de aceptación
- [ ] ...
- [ ] ...

## Checks obligatorios
- `pwsh ops/orca/check.ps1 -Worktree .`
- <otros checks del repo>

## Entrega
- Worktree: el que asigne Orca.
- Rama: la que cree Orca para el worktree.
- Informe: `report.md`.
- Prohibido: push, merge, rebase, `task-update`, `git add`, `git commit`, tocar otros worktrees.
- Deja los cambios sin stage: el orquestador hace el review, el commit y la integración.

## Riesgos / notas
- ...
