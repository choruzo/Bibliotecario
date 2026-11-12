# Para el supervisor de un Run. Por defecto no toca los workers ya despachados:
# solo mata el runner y su arbol de procesos (orchestrate/dispatch hijos).

param(
    [Parameter(Mandatory)][string]$RunId
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

if ($RunId -notmatch '^run_[A-Za-z0-9_]+$') { throw "RunId invalido: $RunId" }

$stateDir = Get-StateDir
$metaPath = Join-Path $stateDir "loop-$RunId.json"
if (-not (Test-Path $metaPath)) {
    Write-Output 'LOOP_STOPPED=none'
    return
}

try { $meta = Get-Content $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $meta = $null }
if (-not $meta) {
    Write-Output 'LOOP_STOPPED=none'
    return
}

function Get-Descendants {
    param([int]$ParentId)
    $result = @()
    foreach ($child in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentId" -ErrorAction SilentlyContinue)) {
        $result += Get-Descendants -ParentId ([int]$child.ProcessId)
        $result += [int]$child.ProcessId
    }
    return $result
}

$stoppedPid = $null
if ($meta.pid) {
    $process = Get-Process -Id ([int]$meta.pid) -ErrorAction SilentlyContinue
    if ($process) {
        $info = Get-CimInstance Win32_Process -Filter "ProcessId=$($meta.pid)" -ErrorAction SilentlyContinue
        if (-not $info -or -not $info.CommandLine -or $info.CommandLine -match '(loop-runner|start-loop)\.ps1') {
            foreach ($childId in @(Get-Descendants -ParentId ([int]$meta.pid))) {
                Stop-Process -Id $childId -Force -ErrorAction SilentlyContinue
            }
            Stop-Process -Id ([int]$meta.pid) -Force -ErrorAction SilentlyContinue
            $stoppedPid = [int]$meta.pid
        }
    }
}

$meta | Add-Member -NotePropertyName status -NotePropertyValue 'stopped' -Force
$meta | Add-Member -NotePropertyName finishedAt -NotePropertyValue ((Get-Date).ToUniversalTime().ToString('o')) -Force
$meta | Add-Member -NotePropertyName lastLine -NotePropertyValue 'STOPPED_BY_UI' -Force
$tmp = "$metaPath.tmp"
$meta | ConvertTo-Json -Depth 10 | Set-Content $tmp -Encoding UTF8
Move-Item $tmp $metaPath -Force

$auditReason = if ($stoppedPid) { "runner=$stoppedPid" } else { 'sin runner vivo; meta actualizado' }
Write-Audit -RunId $RunId -Actor 'panel' -Action 'stop-loop' -Reason $auditReason

$notify = Join-Path $PSScriptRoot 'notify.ps1'
if (Test-Path $notify) {
    & pwsh -NoProfile -File $notify -RunId $RunId -Status 'stopped' -Message 'Detenido desde el panel de control' | Out-Host
}

if ($stoppedPid) { Write-Output "LOOP_STOPPED=$stoppedPid" }
else { Write-Output 'LOOP_STOPPED=stale-meta' }
