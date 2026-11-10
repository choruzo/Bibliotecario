# Lanza el bucle de ejecucion de un Run de forma explicita y controlada.
# No se ejecuta solo: lo llama el lider solo si el usuario elige "Ejecutar ahora"
# o lo lanzas tu a mano. Valida el Run, arranca orchestrate.ps1 en una ventana
# minimizada y deja estado/log para el grafo.
#
# Uso:
#   pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_...
#   pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -DryRun
#   pwsh -NoProfile -File ops/orca/start-loop.ps1 -RunId run_... -Foreground

param(
    [Parameter(Mandatory)][string]$RunId,
    [ValidateRange(1, 5)][int]$MaxWorkers = 5,
    [ValidateRange(1, 10)][int]$MaxReviewRounds = 2,
    [string]$BaseBranch = 'main',
    [switch]$KeepWorktrees,
    [switch]$Foreground,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

if ($RunId -notmatch '^run_[A-Za-z0-9_]+$') { throw "RunId invalido: $RunId" }

$stateDir = Get-StateDir
$repoRoot = Get-RepoRoot
$metaPath = Join-Path $stateDir "loop-$RunId.json"
$logPath = Join-Path $stateDir "loop-$RunId.log"
$runner = Join-Path $PSScriptRoot 'loop-runner.ps1'
$orchestrate = Join-Path $PSScriptRoot 'orchestrate.ps1'

function Read-LoopMeta {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    try { return (Get-Content $Path -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

function Test-LoopAlive {
    param($Meta)
    if (-not $Meta -or -not $Meta.pid) { return $false }
    $proc = Get-Process -Id ([int]$Meta.pid) -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    try {
        $info = Get-CimInstance Win32_Process -Filter "ProcessId=$($Meta.pid)" -ErrorAction Stop
    }
    catch {
        return $true
    }
    if (-not $info) { return $true }
    if (-not $info.CommandLine) { return $true }
    return ($info.CommandLine -match '(loop-runner|start-loop)\.ps1')
}

function Quote-Arg {
    param([string]$Value)
    if ($Value -match '[\s"]') { return '"' + ($Value -replace '"', '\"') + '"' }
    return $Value
}

# Un solo bucle por Run. Si el proceso anterior sigue vivo, no se duplica.
$existing = Read-LoopMeta -Path $metaPath
if (Test-LoopAlive -Meta $existing) {
    throw "Ya hay un bucle en marcha para $RunId (PID $($existing.pid), estado $($existing.status))."
}
if ($existing -and $existing.status -in @('running', 'starting')) {
    Write-Warning "El estado anterior de $RunId decia '$($existing.status)' pero el proceso ya no vive; se sobrescribe."
}

# Aviso: el tope es por bucle, no global.
foreach ($file in @(Get-ChildItem $stateDir -Filter 'loop-*.json' -File -ErrorAction SilentlyContinue)) {
    if ($file.FullName -eq $metaPath) { continue }
    $other = Read-LoopMeta -Path $file.FullName
    if (Test-LoopAlive -Meta $other) {
        Write-Warning "Hay otro bucle en marcha ($($other.runId), PID $($other.pid)). El tope de $MaxWorkers workers es por bucle."
    }
}

# Validar Run y tareas.
$runResponse = Invoke-Orca orchestration run-show --id $RunId --json
$run = (Get-OrcaResult $runResponse).run
if (-not $run) { throw "No existe el Run $RunId." }

$taskResponse = Invoke-Orca orchestration task-list --run $RunId --json
$tasks = @((Get-OrcaResult $taskResponse).tasks)
if ($tasks.Count -eq 0) {
    throw "El Run $RunId no tiene tareas. Crea las tareas antes de lanzar el bucle."
}

$hasLocalState = (Test-Path (Join-Path $stateDir "dispatches-$RunId.json")) -or (Test-Path (Join-Path $stateDir "runs/$RunId"))
if (-not $hasLocalState) {
    Write-Warning "El Run $RunId no tiene estado local en .orca-run; comprueba que pertenece a este repo antes de seguir."
}

$ready = @($tasks | Where-Object { $_.status -eq 'ready' })
$dispatched = @($tasks | Where-Object { $_.status -eq 'dispatched' })
$summary = (@($tasks | Group-Object status | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ', ')

if ($ready.Count -eq 0 -and $dispatched.Count -eq 0) {
    throw "No hay tareas ready ni dispatched en $RunId ($summary). No hay nada que ejecutar."
}

if (-not (Test-Path $runner)) { throw "No se encontro $runner" }
if (-not (Test-Path $orchestrate)) { throw "No se encontro $orchestrate" }

$runnerArgs = @(
    '-NoProfile', '-File', $runner,
    '-RunId', $RunId,
    '-MaxWorkers', "$MaxWorkers",
    '-MaxReviewRounds', "$MaxReviewRounds",
    '-BaseBranch', $BaseBranch,
    '-LogPath', $logPath,
    '-MetaPath', $metaPath
)
if ($KeepWorktrees) { $runnerArgs += '-KeepWorktrees' }

$pwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
if (-not $pwshExe) { throw "No se encontro pwsh en el PATH." }

if ($DryRun) {
    $printable = (@($runnerArgs | ForEach-Object { Quote-Arg $_ }) -join ' ')
    Write-Output "LOOP_RUN=$RunId"
    Write-Output "LOOP_OBJECTIVE=$($run.objective)"
    Write-Output "LOOP_READY=$($ready.Count)"
    Write-Output "LOOP_DISPATCHED=$($dispatched.Count)"
    Write-Output "LOOP_STATUSES=$summary"
    Write-Output "LOOP_COMMAND=pwsh $printable"
    Write-Output "LOOP_STATUS=dry-run"
    return
}

if ($Foreground) {
    & $pwshExe @runnerArgs
    $final = Read-LoopMeta -Path $metaPath
    Write-Output "LOOP_RUN=$RunId"
    Write-Output "LOOP_STATUS=$($final.status)"
    Write-Output "LOOP_EXIT=$($final.exitCode)"
    Write-Output "LOOP_LOG=$logPath"
    return
}

$argumentLine = (@($runnerArgs | ForEach-Object { Quote-Arg $_ }) -join ' ')
$proc = Start-Process -FilePath $pwshExe -ArgumentList $argumentLine -WorkingDirectory $repoRoot -WindowStyle Minimized -PassThru

$meta = $null
for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep -Milliseconds 250
    $meta = Read-LoopMeta -Path $metaPath
    if ($meta -and $meta.pid -eq $proc.Id -and $meta.status) { break }
}

if (-not $meta) {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    throw "El runner no escribio estado. Revisa $logPath"
}

if ($meta.status -eq 'failed') {
    throw "El bucle fallo al arrancar: $($meta.error). Log: $logPath"
}

Write-Output "LOOP_RUN=$RunId"
Write-Output "LOOP_STATUS=$($meta.status)"
Write-Output "LOOP_PID=$($meta.pid)"
Write-Output "LOOP_READY=$($ready.Count)"
Write-Output "LOOP_DISPATCHED=$($dispatched.Count)"
Write-Output "LOOP_LOG=$logPath"
Write-Output "LOOP_META=$metaPath"
Write-Output "LOOP_GRAPH=http://127.0.0.1:4599/"

