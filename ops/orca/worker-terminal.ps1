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

Write-Output "OPENCODE_SESSION=$sessionID"
Write-Output "OPENCODE_AGENT=$Agent"
Write-Output "OPENCODE_WORKTREE=$worktree"

& opencode --session $sessionID --auto
