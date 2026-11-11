param(
    [string]$TaskTitle = 'leader',
    [int]$DashboardPort = 4599,
    [switch]$NoDashboard,
    [switch]$OpenDashboard
)

$ErrorActionPreference = 'Stop'

$worktree = (Get-Location).Path -replace '\\', '/'
$body = @{
    title    = "leader: $TaskTitle"
    agent    = 'lider'
    location = @{ directory = $worktree }
} | ConvertTo-Json -Compress -Depth 10

$escaped = $body -replace '"', '\"'
$raw = & opencode api POST /api/session --data $escaped 2>&1
$code = $LASTEXITCODE
$text = ($raw | Out-String).Trim()

if ($code -ne 0 -or -not $text) {
    throw "No se pudo crear la sesión del líder (exit $code): $text"
}

$session = $text | ConvertFrom-Json
$sessionID = $session.data.id
if (-not $sessionID) { throw "OpenCode no devolvió sessionID: $text" }

Write-Output "OPENCODE_SESSION=$sessionID"
Write-Output "OPENCODE_AGENT=lider"
Write-Output "OPENCODE_WORKTREE=$worktree"

# El grafo de ejecución arranca con la conversación del líder. Si ya hay uno
# escuchando en ese puerto, graph.ps1 se limita a devolver la URL existente.
if (-not $NoDashboard) {
    try {
        $graph = Join-Path $PSScriptRoot 'graph.ps1'
        $pwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
        if ($pwshExe -and (Test-Path $graph)) {
            $arguments = "-NoProfile -File `"$graph`" -Port $DashboardPort"
            if ($OpenDashboard) { $arguments += ' -Open' }
            Start-Process -FilePath $pwshExe -ArgumentList $arguments -WindowStyle Minimized -WorkingDirectory (Get-Location).Path | Out-Null
            Write-Output "ORCA_GRAPH=http://127.0.0.1:$DashboardPort/"
        }
    }
    catch {
        Write-Warning "No se pudo iniciar el grafo de ejecución: $($_.Exception.Message)"
    }
}

& opencode --session $sessionID
