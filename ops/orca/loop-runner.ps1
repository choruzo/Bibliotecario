# Runner interno de un bucle Orca. Lo lanza start-loop.ps1 en una ventana
# minimizada; ejecuta orchestrate.ps1, escribe el log y deja el estado en
# .orca-run/loop-<run>.json para que el grafo lo muestre.
#
# Con -AutoAnswer, si orchestrate termina en LOOP=QUESTION, pide una respuesta
# al subagente advisor y la envia a Orca; despues relanza el bucle. Si el asesor
# escala o falla, se detiene para que decida una persona.

param(
    [Parameter(Mandatory)][string]$RunId,
    [ValidateRange(1, 5)][int]$MaxWorkers = 5,
    [ValidateRange(1, 10)][int]$MaxReviewRounds = 2,
    [string]$BaseBranch = 'main',
    [switch]$KeepWorktrees,
    [switch]$AutoRescue,
    [ValidateRange(1, 5)][int]$MaxRescueRounds = 2,
    [switch]$AutoRepair,
    [ValidateRange(0, 3)][int]$MaxRepairRounds = 1,
    [ValidateSet('warn', 'restart')][string]$StallAction = 'warn',
    [ValidateRange(0, 5)][int]$MaxStallRecoveries = 1,
    [switch]$AutoAnswer,
    [ValidateRange(0, 10)][int]$MaxAutoAnswers = 3,
    [ValidateRange(0, 1440)][int]$MaxRunMinutes = 0,
    [Parameter(Mandatory)][string]$LogPath,
    [Parameter(Mandatory)][string]$MetaPath
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

$startedAt = [datetime]::UtcNow.ToString('o')
$orchestrate = Join-Path $PSScriptRoot 'orchestrate.ps1'
$answerScript = Join-Path $PSScriptRoot 'answer-question.ps1'

function Write-LoopMeta {
    param(
        [Parameter(Mandatory)][string]$Status,
        [Nullable[int]]$ExitCode = $null,
        [string]$LastLine = '',
        [string]$ErrorText = '',
        [int]$AutoAnswers = 0
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
        autoRescue      = [bool]$AutoRescue
        maxRescueRounds = $MaxRescueRounds
        autoRepair      = [bool]$AutoRepair
        maxRepairRounds = $MaxRepairRounds
        stallAction     = $StallAction
        maxStallRecoveries = $MaxStallRecoveries
        autoAnswer      = [bool]$AutoAnswer
        maxAutoAnswers  = $MaxAutoAnswers
        autoAnswers     = $AutoAnswers
        maxRunMinutes   = $MaxRunMinutes
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
Set-Content -Path $LogPath -Value "=== LOOP $RunId $startedAt ===" -Encoding UTF8

$status = 'failed'
$lastLine = ''
$code = 1
$attempt = 0
$autoAnswers = 0

try {
    while ($true) {
        if ($MaxRunMinutes -gt 0) {
            $elapsed = ([datetimeoffset]::UtcNow - [datetimeoffset]::Parse($startedAt)).TotalMinutes
            if ($elapsed -ge $MaxRunMinutes) {
                $status = 'stopped'
                $lastLine = "BUDGET max_minutes=$MaxRunMinutes elapsed=$([int]$elapsed)"
                break
            }
        }

        $attempt += 1
        Add-Content -Path $LogPath -Value "`n=== ORCHESTRATE ATTEMPT $attempt ===" -Encoding UTF8

        $orcaArgs = @(
            '-NoProfile', '-File', $orchestrate,
            '-RunId', $RunId,
            '-MaxWorkers', "$MaxWorkers",
            '-MaxReviewRounds', "$MaxReviewRounds",
            '-BaseBranch', $BaseBranch
        )
        if ($KeepWorktrees) { $orcaArgs += '-KeepWorktrees' }
        if ($AutoRescue) {
            $orcaArgs += @('-AutoRescue', '-MaxRescueRounds', "$MaxRescueRounds")
        }
        if ($AutoRepair) {
            $orcaArgs += @('-AutoRepair', '-MaxRepairRounds', "$MaxRepairRounds")
        }
        if ($StallAction -eq 'restart') {
            $orcaArgs += @('-StallAction', 'restart', '-MaxStallRecoveries', "$MaxStallRecoveries")
        }

        $lines = & pwsh @orcaArgs 2>&1 | Tee-Object -FilePath $LogPath -Append
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

        if ($status -ne 'question' -or -not $AutoAnswer) { break }

        if ($autoAnswers -ge $MaxAutoAnswers) {
            $lastLine = "AUTOANSWER=MAX ($MaxAutoAnswers)"
            break
        }

        if (-not (Test-Path $answerScript)) {
            $status = 'failed'
            $lastLine = "AUTOANSWER=FAILED falta $answerScript"
            break
        }

        $answerOutput = (& pwsh -NoProfile -File $answerScript -RunId $RunId 2>&1 | Out-String)
        $answerCode = $LASTEXITCODE
        Add-Content -Path $LogPath -Value $answerOutput -Encoding UTF8
        Write-Host $answerOutput.TrimEnd()

        $answerStatus = ([regex]::Match($answerOutput, 'AUTOANSWER=([A-Z]+)')).Groups[1].Value
        $answerReason = ([regex]::Match($answerOutput, 'AUTOANSWER_REASON=(.*)')).Groups[1].Value.Trim()

        if ($answerStatus -eq 'ANSWERED') {
            $autoAnswers += 1
            Write-Host "[loop-runner] auto-answer $autoAnswers / $MaxAutoAnswers"
            continue
        }

        if ($answerStatus -eq 'ESCALATED') {
            $status = 'question'
            $lastLine = "AUTOANSWER=ESCALATED $answerReason"
            break
        }

        $status = 'failed'
        $lastLine = "AUTOANSWER=FAILED (exit $answerCode) $answerReason"
        break
    }

    Write-LoopMeta -Status $status -ExitCode $code -LastLine $lastLine -AutoAnswers $autoAnswers
    Write-Host "[loop-runner] $status (exit $code) $lastLine"

    $notify = Join-Path $PSScriptRoot 'notify.ps1'
    if (Test-Path $notify) {
        & pwsh -NoProfile -File $notify -RunId $RunId -Status $status -Message $lastLine | Out-Host
    }
}
catch {
    $message = $_.Exception.Message
    Write-LoopMeta -Status 'failed' -ExitCode $code -LastLine $lastLine -ErrorText $message -AutoAnswers $autoAnswers
    Write-Host "[loop-runner] failed: $message" -ForegroundColor Red
    $notify = Join-Path $PSScriptRoot 'notify.ps1'
    if (Test-Path $notify) {
        & pwsh -NoProfile -File $notify -RunId $RunId -Status 'failed' -Message $message | Out-Host
    }
    throw
}
