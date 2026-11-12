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

Assert-Contains (Join-Path $orcaDir 'integrate.ps1') "-split ','" 'integrate debe partir -Branches por comas'
Assert-Contains (Join-Path $orcaDir 'integrate.ps1') 'BASE_ADVANCED' 'integrate debe avanzar la rama base'
Assert-Contains (Join-Path $orcaDir 'integrate.ps1') 'setup-worktree\.ps1' 'integrate debe materializar dependencias con setup-worktree'
Assert-NotContains (Join-Path $orcaDir 'integrate.ps1') 'New-Item -ItemType Junction -Path \$nodeModules' 'node_modules no debe enlazarse: Turbopack lo rechaza'

Assert-Contains (Join-Path $orcaDir 'cleanup.ps1') 'WORKTREE_LOCKED' 'cleanup debe reportar worktrees bloqueados'
Assert-Contains (Join-Path $orcaDir 'cleanup.ps1') 'terminal close --worktree' 'cleanup debe cerrar terminales del workspace'

Assert-Contains (Join-Path $orcaDir 'review.ps1') 'BaseBranch' 'review debe comparar contra la rama base'
Assert-Contains (Join-Path $orcaDir 'review.ps1') 'git diff --name-only HEAD' 'review debe ver staged y unstaged'
Assert-Contains (Join-Path $orcaDir 'commit.ps1') 'COMMIT_EXISTING' 'commit debe aceptar un commit ya hecho por el worker'
Assert-Contains (Join-Path $orcaDir 'lib.ps1') 'Close-OrcaTerminal' 'falta el cierre verificado de terminal'
Assert-Contains (Join-Path $orcaDir 'graph.ps1') 'Test-LoopRunningForRun' 'retry-task no debe robar el binding a un bucle vivo'

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
