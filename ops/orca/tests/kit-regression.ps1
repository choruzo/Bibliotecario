# Invariantes del kit que no deben volver a romperse.
# No sustituye a los tests de integracion reales; evita regresiones baratas.

$ErrorActionPreference = 'Stop'

$orcaDir = Split-Path $PSScriptRoot -Parent
$repoRoot = Split-Path (Split-Path $orcaDir -Parent) -Parent

function Assert-Contains {
    param([string]$Path, [string]$Pattern, [string]$Message)
    $text = Get-Content $Path -Raw -Encoding UTF8
    if ($text -notmatch $Pattern) { throw "ASSERT: $Message ($Path)" }
}

function Assert-NotContains {
    param([string]$Path, [string]$Pattern, [string]$Message)
    $text = Get-Content $Path -Raw -Encoding UTF8
    if ($text -match $Pattern) { throw "ASSERT: $Message ($Path)" }
}

Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'Reconcile-CompletedTasks' 'falta la reconciliacion de completed'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'ESCALATION_IGNORED' 'falta la cualificacion de escalaciones'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'WATCHDOG_NO_PROOF' 'el watchdog debe exigir prueba'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'Get-Coordinator -RunId' 'el bucle debe usar coordinador por Run'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'Settle-SettledDispatches' 'faltan cierres de terminales asentados'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'worker-done-stale' 'falta el descarte de worker_done rancios'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'review_sin_ficheros' 'review vacio no debe reabrir la tarea'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'Ensure-WorkerTerminal' 'el re-despacho debe validar o recrear el terminal'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'Write-Host "\[loop\] TERMINAL_RECREATED' 'el log de TERMINAL_RECREATED no debe contaminar el handle'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'TERMINAL_RECREATED' 'falta la auditoria de terminal recreado'
Assert-Contains (Join-Path $orcaDir 'new-run.ps1') 'taskResult\.taskId' 'new-run debe leer result.taskId'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'ALREADY_INTEGRATED' 'falta el camino de rama ya integrada'
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'Test-BranchAncestor' 'falta la comprobacion de rama ya integrada'
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'Test-TaskDeliverable' 'falta la guardia de estado entregable'

Assert-Contains (Join-Path $orcaDir 'integrate.ps1') "-split ','" 'integrate debe partir -Branches por comas'
Assert-Contains (Join-Path $orcaDir 'integrate.ps1') 'BASE_ADVANCED' 'integrate debe avanzar la rama base'
Assert-Contains (Join-Path $orcaDir 'integrate.ps1') 'setup-worktree\.ps1' 'integrate debe materializar dependencias con setup-worktree'
Assert-NotContains (Join-Path $orcaDir 'integrate.ps1') 'New-Item -ItemType Junction -Path \$nodeModules' 'node_modules no debe enlazarse: Turbopack lo rechaza'

Assert-Contains (Join-Path $orcaDir 'cleanup.ps1') 'WORKTREE_LOCKED' 'cleanup debe reportar worktrees bloqueados'
Assert-Contains (Join-Path $orcaDir 'cleanup.ps1') 'terminal close --worktree' 'cleanup debe cerrar terminales del workspace'
Assert-Contains (Join-Path $orcaDir 'cleanup.ps1') 'Remove-SharedLinks' 'cleanup debe desmontar las junctions compartidas antes de borrar'
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'function Remove-SharedLinks' 'falta el desmontador seguro de junctions (incidencia del .venv)'

Assert-Contains (Join-Path $orcaDir 'review.ps1') 'BaseBranch' 'review debe comparar contra la rama base'
Assert-Contains (Join-Path $orcaDir 'review.ps1') 'git diff --name-only HEAD' 'review debe ver staged y unstaged'
Assert-Contains (Join-Path $orcaDir 'commit.ps1') 'COMMIT_EXISTING' 'commit debe aceptar un commit ya hecho por el worker'
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'Close-OrcaTerminal' 'falta el cierre verificado de terminal'
Assert-Contains (Join-Path $orcaDir 'graph.ps1') 'Test-LoopRunningForRun' 'retry-task no debe robar el binding a un bucle vivo'

# Libreria de lecciones (Fase 0, PRD docs/08-prd-harnessing.md).
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'function Get-LibraryPointer' 'falta el puntero de la libreria'
Assert-Contains (Join-Path $orcaDir 'dispatch.ps1') 'Get-LibraryPointer' 'el dispatch debe inyectar el puntero de la libreria en el preamble'
Assert-Contains (Join-Path $orcaDir 'lesson.ps1') 'NO_ENTRY' 'lesson.ps1 debe registrar NO_ENTRY sin evidencia'
Assert-Contains (Join-Path $orcaDir 'lesson.ps1') 'EXPERIENCE\.md' 'lesson.ps1 debe escribir EXPERIENCE.md'
Assert-Contains (Join-Path $orcaDir 'lesson.ps1') 'Update-LibraryIndex' 'INDEX.md debe regenerarse desde disco'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'LESSON_PENDING' 'el bucle debe marcar tareas candidatas a leccion'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') "Action 'lesson-candidate'" 'la marca de leccion debe quedar en la auditoria'
Assert-Contains (Join-Path $repoRoot '.opencode\agents\worker.md') 'ops/orca/library/INDEX\.md' 'worker debe saber consultar la libreria de lecciones'
Assert-Contains (Join-Path $repoRoot '.opencode\agents\lider.md') 'lesson\.ps1 -ListPending' 'el lider debe recoger las lecciones pendientes al terminar el bucle'
Assert-Contains (Join-Path $repoRoot 'ops\orca\library\README.md') 'Evidencia o nada' 'la regla de evidencia debe estar documentada en la libreria'

# Harness probing (Fase 1, PRD docs/08-prd-harnessing.md).
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'function Test-HarnessVariant' 'falta el validador de variantes'
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'function Test-HarnessContrast' 'falta la decision de contraste A/B'
Assert-Contains (Join-Path $orcaDir 'dispatch.ps1') 'PrepareWorktree' 'dispatch debe aceptar el hook de materializacion de variante'
Assert-Contains (Join-Path $orcaDir 'harness-probe.ps1') 'Test-HarnessVariant' 'el probe debe validar la variante antes de gastar workers'
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'proposal\.diff' 'la adopcion debe producir un diff de propuesta para una persona'
Assert-Contains (Join-Path $orcaDir 'harness-probe.ps1') 'Write-ProbeResultDir' 'el probe debe componer la evidencia en la libreria'
# Colision case-insensitive: $script:evidenceAudit pisaba el param $EvidenceAudit
# (v2-v4 midieron siempre "sin medir"). El nombre renombrado debe existir y el
# viejo no puede volver.
Assert-Contains (Join-Path $orcaDir 'harness-probe.ps1') 'evidenceAuditPath' 'la metrica de evidencia usa el nombre renombrado'
Assert-NotContains (Join-Path $orcaDir 'harness-probe.ps1') '\$script:evidenceAudit(?![A-Za-z])' 'no se puede reintroducir script:evidenceAudit (colision con el param)'
# La metrica no puede fallar en silencio: si se pidio auditor y no corrio en
# vuelo, el resultado se marca invalido (condicion de archivo del lider).
Assert-Contains (Join-Path $orcaDir 'harness-probe.ps1') 'PROBE_EVIDENCE_METRIC_NOT_RUN' 'la metrica de evidencia no ejecutada debe invalidar el resultado'
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'metric_status=' 'RESULT.md debe llevar metric_status y metric_reason'

# La palanca esta en la especificacion (hallazgo del ciclo v1-v4): la plantilla
# de tareas codifica la seccion Evidencia y el worker sabe que es obligatoria.
Assert-Contains (Join-Path $repoRoot 'ops\orca\task-template.md') '## Evidencia' 'task-template debe codificar la seccion Evidencia (hallazgo del experimento)'
Assert-Contains (Join-Path $repoRoot 'ops\orca\task-template.md') 'no cumple' 'la regla de evidencia debe ser explicita en la plantilla'
Assert-Contains (Join-Path $repoRoot 'ops\orca\report-template.md') '## Evidencia' 'report-template debe tener el hueco para la evidencia'
Assert-Contains (Join-Path $repoRoot '.opencode\agents\worker.md') '## Evidencia' 'worker debe saber que la seccion Evidencia es obligatoria'

# Retro automatica (etapa 1 del roadmap de auto-mejoramiento, PRD 08).
Assert-Contains (Join-Path $orcaDir 'harnessing-retro.ps1') 'RETRO_BRIEF' 'la retro debe componer el briefing de hipotesis'
Assert-Contains (Join-Path $orcaDir 'harnessing-retro.ps1') 'CommissionEditor' 'la comision del editor debe ser opt-in'
Assert-Contains (Join-Path $orcaDir 'lesson.ps1') 'if \(\$Confidence\) \{ \$childArgs' 'el scaffold multi-candidato no puede pasar -Confidence vacio (ValidateSet lo rechaza)'
Assert-Contains (Join-Path $repoRoot '.opencode\agents\lider.md') 'harnessing-retro\.ps1' 'el lider debe ejecutar la retro al cierre del bucle'

# Par in-run (RF1.1): token, arbitraje y estado lost nunca re-entregado.
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'function Resolve-HarnessPairWinner' 'falta el arbitraje del par in-run'
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'Test-HarnessProbeSpec' 'falta el detector del token [HARNESS-PROBE]'
Assert-Contains (Join-Path $orcaDir 'dispatch.ps1') 'Test-HarnessProbeSpec' 'dispatch debe detectar las tareas probe'
Assert-Contains (Join-Path $orcaDir 'dispatch.ps1') 'task-create' 'dispatch debe clonar la tarea hermana del par'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'PAIR_DECISION' 'el bucle debe arbitrar el par al integrar'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'probe-loser' 'la perdedora del par debe cerrarse sin integrar'
Assert-NotContains (Join-Path $orcaDir 'orchestrate.ps1') "status -eq 'integrated'\) \{ continue \}" 'los guards de reconciliacion deben excluir lost tambien'

# Auto-probe presupuestado (P4): decisor, nunca lanzador.
Assert-Contains (Join-Path $orcaDir 'harnessing-budget.ps1') 'BLOCK reason=daily_cap' 'el presupuesto debe toparse por dia'
Assert-Contains (Join-Path $orcaDir 'harnessing-budget.ps1') 'BLOCK reason=cooldown' 'el presupuesto debe respetar el cooldown'
Assert-Contains (Join-Path $orcaDir 'harnessing-budget.ps1') 'BLOCK reason=no_briefing' 'sin briefing de retro no hay probe'
Assert-Contains (Join-Path $orcaDir 'harnessing-budget.ps1') 'PROCEED domain=' 'el decisor debe devolver PROCEED con dominio'
Assert-Contains (Join-Path $orcaDir 'harness-probe.ps1') "Action 'lesson-candidate'" 'el probe debe dejar marca para el flujo de lecciones'
Assert-Contains (Join-Path $orcaDir 'harness-probe.ps1') 'review\.ps1' 'el contraste debe venir del verificador existente'
$editor = Join-Path $repoRoot '.opencode\agents\harness-editor.md'
Assert-Contains $editor 'harness-variants' 'el editor debe escribir sus variantes en .orca-run/harness-variants'
Assert-Contains $editor 'RATIONALE\.md' 'el editor debe justificar cada cambio con evidencia'
Assert-Contains $editor 'effect: deny' 'el editor debe tener permisos restrictivos'
Assert-Contains (Join-Path $repoRoot '.opencode\agents\lider.md') 'harness-probe\.ps1' 'el lider debe poder lanzar probes de calibracion'

# Evidencia de sesion para el watchdog (RF2.3, PRD docs/08-prd-harnessing.md).
Assert-Contains (Join-Path $orcaDir 'worker-terminal.ps1') 'opencode-session\.json' 'worker-terminal debe registrar la sesion vigente para el watchdog'
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'function Get-SessionActivityUtc' 'falta la senal de actividad de sesion'
Assert-Contains (Join-Path $orcaDir 'orchestrate.ps1') 'SessionActivityUtc' 'el watchdog debe incorporar la actividad de sesion como senal'

$worker = Join-Path $repoRoot '.opencode\agents\worker.md'
Assert-Contains $worker 'orca orchestration task-update \*' 'worker debe denegar task-update'
Assert-Contains $worker 'git commit \*' 'worker debe denegar git commit'
Assert-NotContains $worker 'actualiza el estado' 'worker no debe pedir que actualice el estado'

$repair = Join-Path $repoRoot '.opencode\agents\worker-repair.md'
Assert-Contains $repair 'orca orchestration task-update \*' 'worker-repair debe denegar task-update'
Assert-Contains $repair 'git commit \*' 'worker-repair debe denegar git commit'
Assert-NotContains $repair 'actualiza el estado' 'worker-repair no debe pedir que actualice el estado'

$ps1 = @(Get-ChildItem $orcaDir -Recurse -Filter '*.ps1' -File)
foreach ($file in $ps1) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) {
        throw "Error de sintaxis en $($file.FullName): $($errors[0].Message)"
    }
}

Write-Output 'KIT_REGRESSION_OK'
