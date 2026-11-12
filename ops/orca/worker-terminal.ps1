param(
    [string]$Agent = 'worker',
    [string]$TaskTitle = 'task'
)

$ErrorActionPreference = 'Stop'

$worktree = (Get-Location).Path -replace '\\', '/'
$body = @{
    title    = "worker: $TaskTitle"
    agent    = $Agent
    location = @{ directory = $worktree }
} | ConvertTo-Json -Compress -Depth 10

# `opencode api` pasa el cuerpo a un proceso nativo: hay que escapar las comillas.
$escaped = $body -replace '"', '\"'
$raw = & opencode api POST /api/session --data $escaped 2>&1
$code = $LASTEXITCODE
$text = ($raw | Out-String).Trim()

if ($code -ne 0 -or -not $text) {
    throw "No se pudo crear la sesión de OpenCode (exit $code): $text"
}

$session = $text | ConvertFrom-Json
$sessionID = $session.data.id
if (-not $sessionID) { throw "OpenCode no devolvió sessionID: $text" }

# Registro de la sesión para el watchdog (RF2.3 del PRD docs/08-prd-harnessing.md):
# la evidencia de liveness consulta la actividad real de esta sesión vía la API
# local de OpenCode. El último despacho que re-crea el terminal sobrescribe el
# registro, así que siempre apunta a la sesión vigente.
$sessionRecord = [ordered]@{
    sessionId = $sessionID
    agent     = $Agent
    taskTitle = $TaskTitle
    worktree  = $worktree
    createdAt = (Get-Date).ToUniversalTime().ToString('o')
}
$recordDir = Join-Path (Get-Location) '.orca-task'
if (Test-Path $recordDir) {
    try {
        $sessionRecord | ConvertTo-Json -Compress | Set-Content -Path (Join-Path $recordDir 'opencode-session.json') -Encoding UTF8
    }
    catch {
        Write-Warning "No se pudo registrar la sesión en .orca-task: $($_.Exception.Message)"
    }
}

Write-Output "OPENCODE_SESSION=$sessionID"
Write-Output "OPENCODE_AGENT=$Agent"
Write-Output "OPENCODE_WORKTREE=$worktree"

& opencode --session $sessionID --auto
