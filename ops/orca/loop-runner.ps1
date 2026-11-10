# Runner interno de un bucle Orca. Lo lanza start-loop.ps1 en una ventana
# minimizada; ejecuta orchestrate.ps1, escribe el log y deja el estado en
# .orca-run/loop-<run>.json para que el grafo lo muestre.

param(
    [Parameter(Mandatory)][string]$RunId,
    [ValidateRange(1, 5)][int]$MaxWorkers = 5,
    [ValidateRange(1, 10)][int]$MaxReviewRounds = 2,
    [string]$BaseBranch = 'main',
    [switch]$KeepWorktrees,
    [Parameter(Mandatory)][string]$LogPath,
    [Parameter(Mandatory)][string]$MetaPath
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

$startedAt = [datetime]::UtcNow.ToString('o')
$orchestrate = Join-Path $PSScriptRoot 'orchestrate.ps1'

function Write-LoopMeta {
    param(
        [Parameter(Mandatory)][string]$Status,
        [Nullable[int]]$ExitCode = $null,
        [string]$LastLine = '',
        [string]$ErrorText = ''
    )

    $terminal = @('done', 'question', 'blocked', 'escalated', 'failed', 'stopped')
    $meta = [ordered]@{
        runId           = $RunId
        pid             = $PID
        status          = $Status
        startedAt       = $startedAt
        finishedAt      = if ($Status -in $terminal) { [datetime]::UtcNow.ToString('o') } else { $null }
        exitCode        = $ExitCode
        lastLine        = $LastLine
        error           = $ErrorText
        maxWorkers      = $MaxWorkers
        maxReviewRounds = $MaxReviewRounds
        baseBranch      = $BaseBranch
        logPath         = $LogPath
    }

    $tmp = "$MetaPath.tmp"
    $meta | ConvertTo-Json -Depth 10 | Set-Content $tmp -Encoding UTF8
    Move-Item $tmp $MetaPath -Force
}

if (-not (Test-Path $orchestrate)) {
    Write-LoopMeta -Status 'failed' -ExitCode 1 -ErrorText "No se encontro $orchestrate"
    throw "No se encontro $orchestrate"
}

Write-LoopMeta -Status 'running'

$text = ''
$code = 1
try {
    $orcaArgs = @(
        '-NoProfile', '-File', $orchestrate,
        '-RunId', $RunId,
        '-MaxWorkers', "$MaxWorkers",
        '-MaxReviewRounds', "$MaxReviewRounds",
        '-BaseBranch', $BaseBranch
    )
    if ($KeepWorktrees) { $orcaArgs += '-KeepWorktrees' }

    $lines = & pwsh @orcaArgs 2>&1 | Tee-Object -FilePath $LogPath
    $code = $LASTEXITCODE
    $text = ($lines | Out-String)

    $nonEmpty = @($text -split "`r?`n" | Where-Object { $_.Trim() })
    $loopLine = @($nonEmpty | Where-Object { $_ -match 'LOOP=' } | Select-Object -Last 1)
    $errorLine = @($nonEmpty | Where-Object { $_ -match 'No se pudo|was not found|Error:|FATAL|failed to|Exception:' } | Select-Object -Last 1)
    $lastLine = if ($loopLine.Count -gt 0) {
        [string]$loopLine[-1]
    }
    elseif ($errorLine.Count -gt 0) {
        [string]$errorLine[-1]
    }
    elseif ($nonEmpty.Count -gt 0) {
        [string]$nonEmpty[-1]
    }
    else {
        ''
    }
    $lastLine = ($lastLine -replace '^\s*\|\s*', '').Trim()

    $status = switch -Regex ($lastLine) {
        'LOOP=DONE' { 'done' }
        'LOOP=QUESTION' { 'question' }
        'LOOP=ESCALATION' { 'escalated' }
        'LOOP=BLOCKED' { 'blocked' }
        default {
            switch ($code) {
                0 { 'done' }
                3 { 'question' }
                2 { 'blocked' }
                default { 'failed' }
            }
        }
    }

    Write-LoopMeta -Status $status -ExitCode $code -LastLine $lastLine
    Write-Host "[loop-runner] $status (exit $code) $lastLine"
}
catch {
    $message = $_.Exception.Message
    Write-LoopMeta -Status 'failed' -ExitCode $code -LastLine '' -ErrorText $message
    Write-Host "[loop-runner] failed: $message" -ForegroundColor Red
    throw
}

