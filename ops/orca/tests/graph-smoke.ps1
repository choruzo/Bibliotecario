# Smoke test del grafo: estado por -Json, servidor HTTP, endpoints y HTML.
# Uso: pwsh -NoProfile -File ops/orca/tests/graph-smoke.ps1 [-RunId run_...] [-Port 4611]

param(
    [string]$RunId,
    [int]$Port = 4611
)

$ErrorActionPreference = 'Stop'

$orcaDir = Split-Path $PSScriptRoot -Parent
$graph = Join-Path $orcaDir 'graph.ps1'
$repoRoot = Split-Path $orcaDir -Parent
$stateDir = Join-Path $repoRoot '.orca-run'

if (-not (Test-Path $graph)) { throw "No se encontro $graph" }

if (-not $RunId) {
    $dispatchFile = Get-ChildItem $stateDir -Filter 'dispatches-run_*.json' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $dispatchFile) { throw "No hay dispatches locales; pasa -RunId." }
    if ($dispatchFile.Name -notmatch 'dispatches-(run_[A-Za-z0-9_]+)\.json') { throw "Nombre inesperado: $($dispatchFile.Name)" }
    $RunId = $Matches[1]
}

function Assert-True {
    param($Condition, [string]$Message)
    if (-not $Condition) { throw "ASSERT: $Message" }
}

function As-Iso {
    param($Value)
    if ($Value -is [datetime]) { return $Value.ToUniversalTime().ToString('o') }
    if ($Value -is [datetimeoffset]) { return $Value.ToUniversalTime().ToString('o') }
    return [string]$Value
}

Write-Output "[graph-smoke] estado -Json para $RunId"
$raw = & pwsh -NoProfile -File $graph -RunId $RunId -Json | Out-String
$state = $raw | ConvertFrom-Json
Assert-True ($state.ok -eq $true) "state.ok debe ser true: $($state.error)"
Assert-True ($state.run.id -eq $RunId) "run inesperado: $($state.run.id)"
Assert-True ($state.tasks.Count -gt 0) "el Run no tiene tareas"
Assert-True ((As-Iso $state.updatedAt) -match '^\d{4}-\d{2}-\d{2}T') "updatedAt no es ISO: $($state.updatedAt)"
if ($state.run.createdAt) {
    Assert-True ((As-Iso $state.run.createdAt) -match '^\d{4}-\d{2}-\d{2}T') "run.createdAt no es ISO: $($state.run.createdAt)"
}
Assert-True ($null -ne $state.PSObject.Properties['loop']) "falta state.loop"

foreach ($task in $state.tasks) {
    Assert-True ($task.id -match '^task_') "task id raro: $($task.id)"
    Assert-True ((As-Iso $task.createdAt) -match '^\d{4}-\d{2}-\d{2}T') "task.createdAt no es ISO: $($task.createdAt)"
    Assert-True ($null -ne $task.deps) "deps nulo en $($task.id)"
    if ($task.status -eq 'integrated') {
        Assert-True ($task.dispatch.integrationSha) "integrada sin integrationSha: $($task.id)"
    }
}

$argumentLine = "-NoProfile -File `"$graph`" -Port $Port -RunId $RunId"
$server = Start-Process -FilePath (Get-Command pwsh).Source -ArgumentList $argumentLine -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru

try {
    $base = "http://127.0.0.1:$Port"
    $up = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 400
        try {
            $health = Invoke-RestMethod "$base/health"
            if ($health.ok) { $up = $true; break }
        }
        catch { }
    }
    Assert-True $up "el servidor no respondio en $Port"

    $live = Invoke-RestMethod "$base/api/state"
    Assert-True ($live.run.id -eq $RunId) "el servidor devolvio otro Run: $($live.run.id)"
    Assert-True ($live.tasks.Count -eq $state.tasks.Count) "conteo de tareas distinto por HTTP"
    Assert-True ($null -ne $live.PSObject.Properties['loop']) "el endpoint no incluye loop"

    $runs = Invoke-RestMethod "$base/api/runs"
    Assert-True ($runs.ok -eq $true) "api/runs fallo: $($runs.error)"
    Assert-True (@($runs.runs | Where-Object { $_.id -eq $RunId }).Count -eq 1) "el Run no aparece en api/runs"

    $html = (Invoke-WebRequest -UseBasicParsing "$base/").Content
    Assert-True ($html -match 'const DEFAULT_RUN = "run_') "el HTML no fija el Run por defecto"
    Assert-True ($html -match 'Orca') "el HTML no parece la vista del grafo"

    Write-Output "[graph-smoke] OK run=$RunId tasks=$($state.tasks.Count) port=$Port"
}
finally {
    try { Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/quit" -TimeoutSec 3 | Out-Null } catch { }
    Start-Sleep -Milliseconds 500
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item (Join-Path $stateDir "graph-$Port.json") -Force -ErrorAction SilentlyContinue
}
