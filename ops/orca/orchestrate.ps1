param(
    [Parameter(Mandatory)][string]$RunId,
    [ValidateRange(1, 5)][int]$MaxWorkers = 5,
    [ValidateRange(1, 10)][int]$MaxReviewRounds = 2,
    [int]$WaitTimeoutMs = 900000,
    [string]$BaseBranch = 'main',
    # Variante del harness para tareas [HARNESS-PROBE]: se pasa a dispatch para
    # despachar el par base/variante (RF1.1). Vacio = despacho normal.
    [string]$VariantDir = '',
    [switch]$KeepWorktrees,
    [switch]$AutoRescue,
    [ValidateRange(1, 5)][int]$MaxRescueRounds = 2,
    [switch]$AutoRepair,
    [ValidateRange(0, 3)][int]$MaxRepairRounds = 1,
    [int]$StallMinutes = 30,
    [ValidateSet('warn', 'restart')][string]$StallAction = 'warn',
    [ValidateRange(0, 5)][int]$MaxStallRecoveries = 1
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib.ps1')

$coordinator = Get-Coordinator -RunId $RunId
Bind-Run -RunId $RunId -Coordinator $coordinator
Write-Host "[loop] VariantDir=[$VariantDir]"

$script:Dispatches = @(Read-Dispatches -RunId $RunId)
$script:Watchdog = @{}
$script:StallRecoveries = @{}
$script:WatchdogRestarted = $false
$script:WatchdogBlocked = $false
$script:ClosedTerminals = @{}
$script:IntegrityBlocked = $false
$commitScript = Join-Path $PSScriptRoot 'commit.ps1'
$reviewScript = Join-Path $PSScriptRoot 'review.ps1'
$integrateScript = Join-Path $PSScriptRoot 'integrate.ps1'
$archiveScript = Join-Path $PSScriptRoot 'archive.ps1'
$cleanupScript = Join-Path $PSScriptRoot 'cleanup.ps1'

function Get-Tasks {
    $response = Invoke-OrcaTaskList -Coordinator $coordinator -RunId $RunId
    $tasks = @((Get-OrcaResult $response).tasks)
    return @($tasks | Where-Object { $_ -and $_.id })
}

function Get-TaskSnapshot {
    param([string]$TaskId)
    try {
        return @((Get-Tasks) | Where-Object { $_.id -eq $TaskId }) | Select-Object -First 1
    }
    catch { return $null }
}

function Get-Record {
    param([string]$TaskId)
    $items = @($script:Dispatches) | Where-Object { $_.taskId -eq $TaskId } | Select-Object -Last 1
    return $items
}

function Get-PayloadObject {
    param($Payload)
    if (-not $Payload) { return $null }
    if ($Payload -is [string]) {
        try { return ($Payload | ConvertFrom-Json) } catch { return $null }
    }
    return $Payload
}

function Get-MessageText {
    param($Message)
    try { return ($Message | ConvertTo-Json -Depth 20 -Compress) } catch { return '' }
}

function Resolve-MessageContext {
    param($Message)

    $payload = Get-PayloadObject -Payload $Message.payload
    $taskId = $null
    $dispatchId = $null
    if ($payload) {
        foreach ($name in @('taskId', 'task_id')) {
            if ($payload.PSObject.Properties[$name] -and $payload.$name) { $taskId = [string]$payload.$name; break }
        }
        foreach ($name in @('dispatchId', 'dispatch_id')) {
            if ($payload.PSObject.Properties[$name] -and $payload.$name) { $dispatchId = [string]$payload.$name; break }
        }
    }

    $text = Get-MessageText -Message $Message
    if (-not $taskId -and $text -match '(task_[A-Za-z0-9_]+)') { $taskId = $Matches[1] }
    if (-not $dispatchId -and $text -match '(ctx_[A-Za-z0-9_]+)') { $dispatchId = $Matches[1] }

    $record = $null
    if ($dispatchId) {
        $record = @($script:Dispatches | Where-Object { $_.dispatchId -eq $dispatchId }) | Select-Object -Last 1
    }
    if (-not $record -and $taskId) {
        $record = Get-Record -TaskId $taskId
    }
    if (-not $record) {
        foreach ($handle in @([regex]::Matches($text, 'term_[A-Za-z0-9-]+') | ForEach-Object { $_.Value })) {
            $record = @($script:Dispatches | Where-Object { $_.workerHandle -eq $handle }) | Select-Object -Last 1
            if ($record) { break }
        }
    }
    if (-not $record) {
        foreach ($candidate in @($script:Dispatches)) {
            if ($candidate.taskTitle -and $text.Contains([string]$candidate.taskTitle)) {
                $record = $candidate
                break
            }
        }
    }

    if (-not $taskId -and $record) { $taskId = [string]$record.taskId }
    if (-not $dispatchId -and $record) { $dispatchId = [string]$record.dispatchId }
    return [pscustomobject]@{ TaskId = $taskId; DispatchId = $dispatchId; Record = $record }
}

function Get-EscalationFile {
    return (Join-Path (Get-StateDir) "escalations-$RunId.json")
}

function Register-Escalation {
    param(
        [string]$Key,
        [string]$MessageId,
        [int]$MinSeconds = 30,
        [int]$Required = 2
    )

    if (-not $Key) { $Key = $MessageId }
    if (-not $Key) { return $Required }

    $file = Get-EscalationFile
    $state = @{}
    if (Test-Path $file) {
        try { $state = Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable } catch { $state = @{} }
    }
    if ($null -eq $state) { $state = @{} }

    $now = [datetime]::UtcNow
    $entry = $state[$Key]
    if (-not $entry) {
        $entry = @{ count = 0; firstAt = $now.ToString('o'); lastAt = $null }
    }
    $last = $null
    if ($entry.lastAt) {
        try { $last = ([datetimeoffset]::Parse([string]$entry.lastAt)).UtcDateTime } catch { $last = $null }
    }
    if (-not $last -or ($now - $last).TotalSeconds -ge $MinSeconds) {
        $entry.count = [int]$entry.count + 1
        $entry.lastAt = $now.ToString('o')
    }
    $state[$Key] = $entry
    $state | ConvertTo-Json -Depth 10 | Set-Content $file -Encoding UTF8
    return [int]$entry.count
}

function Clear-Escalation {
    param([string]$Key)
    if (-not $Key) { return }
    $file = Get-EscalationFile
    if (-not (Test-Path $file)) { return }
    try {
        $state = Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
        if ($null -eq $state) { return }
        if ($state.ContainsKey($Key)) {
            $state.Remove($Key)
            $state | ConvertTo-Json -Depth 10 | Set-Content $file -Encoding UTF8
        }
    }
    catch { }
}

function Resolve-Escalation {
    param($Message)

    $context = Resolve-MessageContext -Message $Message
    $record = $context.Record
    if ($record -and ($record.integrationSha -or $record.status -in @('integrated', 'lost'))) {
        return [pscustomobject]@{ Action = 'ignore'; Reason = 'dispatch ya integrado o perdido por su par'; Context = $context }
    }

    $dispatchId = if ($context.DispatchId) { [string]$context.DispatchId } elseif ($record) { [string]$record.dispatchId } else { $null }
    if (-not $dispatchId) {
        return [pscustomobject]@{ Action = 'escalate'; Reason = 'sin dispatch identificable'; Context = $context }
    }

    $show = Get-OrcaWorkerShow -DispatchId $dispatchId
    if (-not $show) {
        return [pscustomobject]@{ Action = 'defer'; Reason = 'worker-show no disponible'; Context = $context; DispatchId = $dispatchId }
    }

    $dispatchStatus = [string]$show.dispatch.status
    if ($dispatchStatus -in @('completed', 'failed', 'cancelled', 'settled')) {
        return [pscustomobject]@{ Action = 'ignore'; Reason = "dispatch $dispatchStatus"; Context = $context; DispatchId = $dispatchId }
    }

    $liveness = [string]$show.projection.liveness.verdict
    $activity = [string]$show.projection.stage.activity
    $wait = $show.observation.agentWait
    if ($wait) {
        return [pscustomobject]@{ Action = 'waiting'; Reason = 'agentWait'; Context = $context; DispatchId = $dispatchId; Liveness = $liveness; Activity = $activity }
    }
    if ($liveness -eq 'live' -or $activity -eq 'working') {
        return [pscustomobject]@{ Action = 'ignore'; Reason = "worker $liveness/$activity"; Context = $context; DispatchId = $dispatchId }
    }
    if ($liveness -in @('', 'unknown', 'unverifiable')) {
        return [pscustomobject]@{ Action = 'defer'; Reason = "liveness $liveness"; Context = $context; DispatchId = $dispatchId }
    }
    return [pscustomobject]@{ Action = 'escalate'; Reason = "liveness $liveness activity $activity"; Context = $context; DispatchId = $dispatchId }
}

function Handle-Escalation {
    param($Message)

    $resolution = Resolve-Escalation -Message $Message
    $taskId = $resolution.Context.TaskId
    $dispatchId = $resolution.DispatchId

    switch ($resolution.Action) {
        'ignore' {
            Write-Host "[loop] ESCALATION_IGNORED $($Message.id): $($resolution.Reason) dispatch=$dispatchId"
            Clear-Escalation -Key $dispatchId
            Write-Audit -RunId $RunId -Actor 'loop' -Action 'escalation-ignored' -TaskId $taskId -DispatchId $dispatchId -Reason $resolution.Reason
            return 'CONTINUE'
        }
        'defer' {
            $count = Register-Escalation -Key $dispatchId -MessageId $Message.id -MinSeconds 30 -Required 2
            if ($count -lt 2) {
                Write-Host "[loop] ESCALATION_DEFER $($Message.id): $($resolution.Reason) intento=$count"
                Write-Audit -RunId $RunId -Actor 'loop' -Action 'escalation-deferred' -TaskId $taskId -DispatchId $dispatchId -Reason "$($resolution.Reason) intento=$count"
                return 'CONTINUE'
            }
            Write-Host "[loop] ESCALATION $($Message.id): $($Message.body)"
            Write-Audit -RunId $RunId -Actor 'orca' -Action 'escalation' -TaskId $taskId -DispatchId $dispatchId -Reason "confirmada: $($resolution.Reason)"
            return 'ESCALATION'
        }
        'waiting' {
            Write-Host "[loop] ESCALATION_WAITING $($Message.id): el worker espera aprobacion humana (dispatch=$dispatchId)"
            Write-Audit -RunId $RunId -Actor 'worker' -Action 'waiting-human' -TaskId $taskId -DispatchId $dispatchId -Reason $resolution.Reason
            return 'ESCALATION'
        }
        default {
            Write-Host "[loop] ESCALATION $($Message.id): $($Message.body)"
            Write-Audit -RunId $RunId -Actor 'orca' -Action 'escalation' -TaskId $taskId -DispatchId $dispatchId -Reason $resolution.Reason
            return 'ESCALATION'
        }
    }
}

function Get-DispatchIdFromResponse {
    param($Response)
    if (-not $Response) { return $null }
    if ($Response.result -and $Response.result.dispatch -and $Response.result.dispatch.id) { return [string]$Response.result.dispatch.id }
    if ($Response.result -and $Response.result.dispatchId) { return [string]$Response.result.dispatchId }
    $text = ''
    try { $text = ($Response | ConvertTo-Json -Depth 20 -Compress) } catch { return $null }
    $matches = @([regex]::Matches($text, 'ctx_[A-Za-z0-9_]+') | ForEach-Object { $_.Value })
    if ($matches.Count -gt 0) { return $matches[-1] }
    return $null
}

function Send-ToWorker {
    param(
        $Record,
        [string]$TaskId,
        [string]$Preamble,
        [string]$Subject,
        [string]$DispatchId
    )

    if ($Record.workerHandle) {
        $send = Invoke-Orca terminal send --terminal $Record.workerHandle --text $Preamble --enter --json
        if ($send.ok) { return $true }
        Write-Warning "terminal send fallo para ${TaskId}: $($send.error.message)"
    }

    $target = if ($DispatchId) { $DispatchId } elseif ($Record.dispatchId) { $Record.dispatchId } else { $null }
    if (-not $target) { return $false }
    $fallback = Invoke-Orca orchestration send --to "dispatch:$target" --run $RunId --from $coordinator --subject $Subject --body $Preamble --task-id $TaskId --dispatch-id $target --json
    if (-not $fallback.ok) {
        Write-Warning "No se pudo entregar el mensaje a ${TaskId}: $($fallback.error.message)"
        return $false
    }
    $newId = Get-DispatchIdFromResponse -Response $fallback
    if ($newId -and $newId -ne $target) {
        Set-RecordValue -Record $Record -Name 'dispatchId' -Value $newId
        Save-Record -Record $Record
    }
    return $true
}

function Test-OrcaTerminalLive {
    param([string]$Handle)

    if (-not $Handle) { return $false }
    try {
        $show = Invoke-Orca terminal show --terminal $Handle --json
        if (-not $show.ok) { return $false }
        $terminal = $show.result.terminal
        return [bool]($terminal -and $terminal.connected -eq $true -and $terminal.orphaned -ne $true)
    }
    catch { return $false }
}

function New-OrcaTaskWorkerTerminal {
    param(
        $Record,
        [string]$Agent = 'worker'
    )

    $slug = Get-TaskSlug -Title ([string]$Record.taskTitle)
    $short = Get-TaskShortId -TaskId ([string]$Record.taskId)
    $name = "$slug-$short"
    $wrapper = Join-Path $PSScriptRoot 'worker-terminal.ps1'
    $command = "pwsh -NoProfile -File `"$wrapper`" -TaskTitle `"$name`" -Agent $Agent"

    $response = Invoke-Orca terminal create --worktree "path:$($Record.worktree)" --title "worker:$name" --command $command --json
    if (-not $response.ok) {
        Write-Warning "No se pudo crear un terminal nuevo para $($Record.taskId): $($response.error.message)"
        return $null
    }
    $handle = (Get-OrcaResult $response).terminal.handle
    if (-not $handle) {
        Write-Warning "Orca no devolvio handle para el terminal de $($Record.taskId)"
        return $null
    }

    $wait = Invoke-Orca terminal wait --terminal $handle --for tui-idle --timeout-ms 180000 --json
    if (-not $wait.ok) {
        Write-Warning "El terminal nuevo de $($Record.taskId) no llego a tui-idle: $($wait.error.message)"
        [void](Close-OrcaTerminal -Handle $handle -Quiet)
        return $null
    }

    return [pscustomobject]@{ Handle = $handle; Terminal = "worker:$name" }
}

function Ensure-WorkerTerminal {
    param(
        $Record,
        [string]$Agent = 'worker'
    )

    if (Test-OrcaTerminalLive -Handle $Record.workerHandle) { return [string]$Record.workerHandle }

    $created = New-OrcaTaskWorkerTerminal -Record $Record -Agent $Agent
    if (-not $created) { return $null }

    Set-RecordValue -Record $Record -Name 'workerHandle' -Value $created.Handle
    Set-RecordValue -Record $Record -Name 'terminal' -Value $created.Terminal
    Save-Record -Record $Record
    Write-Host "[loop] TERMINAL_RECREATED task=$($Record.taskId) handle=$($created.Handle)"
    Write-Audit -RunId $RunId -Actor 'loop' -Action 'worker-terminal-recreated' -TaskId $Record.taskId -DispatchId $Record.dispatchId -Terminal $created.Handle -Reason 'stale-handle'
    return [string]$created.Handle
}

function Test-RecordSettled {
    param($Record)
    if (-not $Record) { return $false }
    if ($Record.integrationSha) { return $true }
    return ($Record.status -in @('integrated', 'completed', 'failed', 'lost'))
}

function Get-WorkerEvidence {
    param($Record)

    if (-not $Record -or -not $Record.dispatchId) { return $null }
    $show = Get-OrcaWorkerShow -DispatchId $Record.dispatchId
    if (-not $show) { return $null }

    $lastSignal = $null
    $heartbeat = $show.dispatch.lastHeartbeatAt
    if ($heartbeat) {
        try { $lastSignal = ([datetimeoffset]::Parse([string]$heartbeat)).UtcDateTime } catch { }
    }
    if (-not $lastSignal -and $show.projection.evidence.lastObservedAt) {
        try { $lastSignal = ([datetimeoffset]::Parse([string]$show.projection.evidence.lastObservedAt)).UtcDateTime } catch { }
    }
    $write = Get-LatestWriteUtc -Worktree $Record.worktree
    if ($write -and (-not $lastSignal -or $write -gt $lastSignal)) { $lastSignal = $write }

    # Evidencia de sesion OpenCode (RF2.3): la actividad real del modelo es otra
    # senal de vida. Solo suma, nunca mata: el reinicio sigue exigiendo prueba
    # de muerte (liveness dead / dispatch failed) segun el contrato de Orca.
    $sessionId = Get-OpenCodeSessionId -Worktree $Record.worktree
    $sessionActivity = $null
    if ($sessionId) {
        $sessionActivity = Get-SessionActivityUtc -SessionId $sessionId
        if ($sessionActivity -and (-not $lastSignal -or $sessionActivity -gt $lastSignal)) { $lastSignal = $sessionActivity }
    }

    return [pscustomobject]@{
        DispatchStatus     = [string]$show.dispatch.status
        Liveness           = [string]$show.projection.liveness.verdict
        Activity           = [string]$show.projection.stage.activity
        AgentWait          = $show.observation.agentWait
        LastSignalUtc      = $lastSignal
        LastError          = [string]$show.dispatch.lastError
        Attention          = $show.projection.attention
        SessionId          = $sessionId
        SessionActivityUtc = $sessionActivity
    }
}

function Update-Watchdog {
    param([array]$Tasks)

    $now = [datetime]::UtcNow
    $activeIds = @()
    foreach ($task in @($Tasks | Where-Object { $_.status -eq 'dispatched' })) {
        $record = Get-Record -TaskId $task.id
        if (-not $record) { continue }
        $activeIds += $task.id

        $state = $script:Watchdog[$task.id]
        if (-not $state -or $state.dispatchId -ne $record.dispatchId) {
            $started = $now
            if ($record.createdAt) {
                try { $started = ([datetimeoffset]$record.createdAt).UtcDateTime } catch { $started = $now }
            }
            $state = @{ dispatchId = $record.dispatchId; startedAt = $started; warnedAt = $null }
            $script:Watchdog[$task.id] = $state
        }

        $minutes = ($now - $state.startedAt).TotalMinutes
        if ($minutes -lt $StallMinutes) { continue }

        $evidence = Get-WorkerEvidence -Record $record
        if ($evidence -and $evidence.DispatchStatus -in @('completed', 'failed', 'cancelled', 'settled')) { continue }
        if ($evidence -and $evidence.AgentWait) {
            if (-not $state.warnedAt -or ($now - $state.warnedAt).TotalMinutes -ge $StallMinutes) {
                Write-Host "[loop] WATCHDOG_WAITING task=$($task.id) minutes=$([int]$minutes) (espera humana)"
                $state.warnedAt = $now
            }
            continue
        }

        $signalMinutes = $minutes
        if ($evidence -and $evidence.LastSignalUtc) {
            $signalMinutes = ($now - $evidence.LastSignalUtc).TotalMinutes
        }
        if ($evidence -and $evidence.Activity -eq 'working') {
            $state.warnedAt = $null
            continue
        }
        if ($evidence -and $evidence.Liveness -eq 'live' -and (-not $evidence.LastSignalUtc -or $signalMinutes -lt $StallMinutes)) {
            $state.warnedAt = $null
            continue
        }
        if ($signalMinutes -lt $StallMinutes) { continue }

        if ($StallAction -ne 'restart') {
            Write-Host "[loop] WATCHDOG task=$($task.id) minutes=$([int]$minutes) signal=$([int]$signalMinutes) terminal=$($record.terminal)"
            $state.warnedAt = $now
            continue
        }

        # Reiniciar solo con prueba. Silencio o liveness unverifiable nunca
        # autorizan matar a un worker segun el contrato de Orca.
        $provenDead = $evidence -and ($evidence.Liveness -eq 'dead' -or $evidence.DispatchStatus -in @('failed', 'cancelled'))
        if (-not $provenDead) {
            $sessionMinutes = if ($evidence.SessionActivityUtc) { [int](($now - $evidence.SessionActivityUtc).TotalMinutes) } else { -1 }
            Write-Host "[loop] WATCHDOG_NO_PROOF task=$($task.id) minutes=$([int]$minutes) signal=$([int]$signalMinutes) session=$($sessionMinutes): no se reinicia"
            $state.warnedAt = $now
            Write-Audit -RunId $RunId -Actor 'loop' -Action 'watchdog-no-proof' -TaskId $task.id -DispatchId $record.dispatchId -Reason "liveness=$($evidence.Liveness) activity=$($evidence.Activity) session=$($sessionMinutes)"
            continue
        }

        $recoveries = [int]$script:StallRecoveries[$task.id]
        if ($recoveries -ge $MaxStallRecoveries) {
            $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $task.id --status blocked --result "stalled max_recoveries=$MaxStallRecoveries" --json
            if (-not $update.ok) { Write-Warning $update.error.message }
            Set-RecordValue -Record $record -Name 'status' -Value 'blocked'
            Save-Record -Record $record
            Write-Host "[loop] WATCHDOG_BLOCKED task=$($task.id) recoveries=$recoveries"
            Write-Audit -RunId $RunId -Actor 'loop' -Action 'watchdog-blocked' -TaskId $task.id -DispatchId $record.dispatchId -Reason "max_recoveries=$MaxStallRecoveries"
            $script:WatchdogBlocked = $true
            continue
        }

        if (-not $record.dispatchId) {
            Write-Host "[loop] WATCHDOG_NO_DISPATCH task=$($task.id); no se puede reiniciar"
            $script:WatchdogBlocked = $true
            continue
        }

        Write-Host "[loop] WATCHDOG_STOP task=$($task.id) dispatch=$($record.dispatchId) liveness=$($evidence.Liveness)"
        $stop = Invoke-Orca orchestration worker-stop --dispatch $record.dispatchId --json
        if (-not $stop.ok) {
            Write-Warning "No se pudo parar el worker estancado de $($task.id): $($stop.error.message)"
            $script:WatchdogBlocked = $true
            continue
        }
        [void](Close-OrcaTerminal -Handle $record.workerHandle -Quiet)

        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $task.id --status ready --result "stalled_recovery=$($recoveries + 1)" --json
        if (-not $update.ok) {
            Write-Warning "No se pudo reabrir $($task.id) tras el estancamiento: $($update.error.message)"
            $script:WatchdogBlocked = $true
            continue
        }

        Set-RecordValue -Record $record -Name 'status' -Value 'stalled'
        Save-Record -Record $record
        $script:StallRecoveries[$task.id] = $recoveries + 1
        $script:WatchdogRestarted = $true
        $state.warnedAt = $now
        Write-Host "[loop] WATCHDOG_RESTART task=$($task.id) attempt=$($recoveries + 1) terminal=$($record.terminal)"
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'watchdog-restart' -TaskId $task.id -DispatchId $record.dispatchId -Reason "liveness=$($evidence.Liveness)"
    }

    foreach ($id in @($script:Watchdog.Keys)) {
        if ($id -notin $activeIds) { $script:Watchdog.Remove($id) }
    }
}

function Save-Record {
    param($Record)
    $script:Dispatches = @(@($script:Dispatches | Where-Object { $_.taskId -ne $Record.taskId }) + $Record)
    Save-Dispatches -RunId $RunId -Dispatches $script:Dispatches | Out-Null
}

function Set-RecordValue {
    param($Record, [string]$Name, $Value)
    if ($Record.PSObject.Properties[$Name]) {
        $Record.$Name = $Value
    }
    else {
        $Record | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Get-DefectText {
    param($Review)
    $defects = @($Review.defects) | Where-Object { $_ }
    if ($defects.Count -eq 0) {
        return 'Los checks fallaron. Revisa review.json y corrige la causa.'
    }
    return ($defects -join "`n")
}

function Ack-Delivery {
    param([string]$DeliveryId)
    if (-not $DeliveryId) { return }
    $ack = Invoke-Orca orchestration check --terminal $coordinator --run $RunId --ack $DeliveryId --json
    if (-not $ack.ok) { Write-Warning "No se pudo confirmar ${DeliveryId}: $($ack.error.message)" }
}

function Request-Changes {
    param($Record, $Review, [int]$Round, [string]$TaskId)

    $defects = Get-DefectText -Review $Review

    if ($Round -gt $MaxReviewRounds) {
        if ($AutoRepair -and ([int]($Record.repairRounds)) -lt $MaxRepairRounds) {
            return Request-Repair -Record $Record -Defects $defects -TaskId $TaskId -Round $Round
        }
        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status blocked --result "review_round=$Round max=$MaxReviewRounds" --json
        if (-not $update.ok) {
            Write-Warning $update.error.message
            $script:IntegrityBlocked = $true
        }
        Set-RecordValue -Record $Record -Name 'status' -Value 'escalated'
        Save-Record -Record $Record
        Write-Host "[loop] ESCALATED $TaskId after $MaxReviewRounds defect rounds"
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'lesson-candidate' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason "escalada tras $MaxReviewRounds rondas de defectos"
        Write-Host "[loop] LESSON_PENDING task=$TaskId evidence=audit-$RunId.jsonl"
        return 'STOP'
    }

    $workerHandle = Ensure-WorkerTerminal -Record $Record -Agent 'worker'
    if (-not $workerHandle) {
        $result = 'worker_terminal_unavailable'
        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status blocked --result $result --json
        if (-not $update.ok) {
            Write-Warning $update.error.message
            $script:IntegrityBlocked = $true
        }
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'blocked' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason $result
        return 'STOP'
    }

    $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status ready --result "review_round=$Round" --json
    if (-not $update.ok) {
        Write-Warning "No se pudo reabrir ${TaskId}: $($update.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }

    $dispatch = Invoke-Orca orchestration dispatch --from $coordinator --run $RunId --task $TaskId --to $workerHandle --return-preamble --json
    if (-not $dispatch.ok) {
        Write-Warning "No se pudo re-despachar ${TaskId}: $($dispatch.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }

    $dispatchResult = Get-OrcaResult $dispatch
    $previousDispatchId = [string]$Record.dispatchId
    $newDispatchId = Get-DispatchIdFromResponse -Response $dispatch
    if (-not $newDispatchId) { $newDispatchId = $previousDispatchId }
    $preamble = $dispatchResult.preamble
    $preamble += "`n`n=== REVIEW DEFECTS (round $Round / max $MaxReviewRounds) ===`n$defects`n`n"
    $preamble += "Corrige exactamente estos defectos. Vuelve a ejecutar el check y envia un nuevo worker_done con el nuevo dispatch_id. No hagas push ni merge ni task-update."

    if (-not (Send-ToWorker -Record $Record -TaskId $TaskId -Preamble $preamble -Subject "review changes $TaskId" -DispatchId $newDispatchId)) {
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'blocked' -TaskId $TaskId -DispatchId $newDispatchId -Reason 'no se pudo entregar los defectos'
        return 'STOP'
    }

    if (-not $Record.dispatchId -or $Record.dispatchId -eq $previousDispatchId) {
        Set-RecordValue -Record $Record -Name 'dispatchId' -Value $newDispatchId
    }
    Set-RecordValue -Record $Record -Name 'reviewRounds' -Value $Round
    Set-RecordValue -Record $Record -Name 'status' -Value 'changes_requested'
    Save-Record -Record $Record
    Write-Host "[loop] CHANGES $TaskId round $Round -> re-dispatched $($Record.dispatchId)"
    Write-Audit -RunId $RunId -Actor 'loop' -Action 'review-changes' -TaskId $TaskId -DispatchId $newDispatchId -Reason "round=$Round"
    return 'CONTINUE'
}

function Request-Repair {    param(
        $Record,
        [string]$Defects,
        [string]$TaskId,
        [int]$Round
    )

    $repairRound = ([int]($Record.repairRounds)) + 1
    $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status ready --result "repair_round=$repairRound" --json
    if (-not $update.ok) {
        Write-Warning "No se pudo reabrir ${TaskId} para reparacion: $($update.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        $script:IntegrityBlocked = $true
        return 'STOP'
    }

    $name = "repair-$($Record.taskId)"
    $wrapper = Join-Path $PSScriptRoot 'worker-terminal.ps1'
    $command = "pwsh -NoProfile -File `"$wrapper`" -TaskTitle `"$name`" -Agent worker-repair"
    $terminalResponse = Invoke-Orca terminal create --worktree "path:$($Record.worktree)" --title "repair:$TaskId" --command $command --json
    if (-not $terminalResponse.ok) {
        Write-Warning "No se pudo crear el worker de reparacion de ${TaskId}: $($terminalResponse.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }
    $workerHandle = (Get-OrcaResult $terminalResponse).terminal.handle

    $waitResponse = Invoke-Orca terminal wait --terminal $workerHandle --for tui-idle --timeout-ms 180000 --json
    if (-not $waitResponse.ok) {
        Write-Warning "El worker de reparacion no llego a tui-idle: $($waitResponse.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }

    $dispatch = Invoke-Orca orchestration dispatch --from $coordinator --run $RunId --task $TaskId --to $workerHandle --return-preamble --json
    if (-not $dispatch.ok) {
        Write-Warning "No se pudo despachar la reparacion de ${TaskId}: $($dispatch.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }

    $dispatchResult = Get-OrcaResult $dispatch
    $repairDispatchId = Get-DispatchIdFromResponse -Response $dispatch
    $preamble = $dispatchResult.preamble
    $preamble += "`n`n=== REPARACION (ronda $repairRound / $MaxRepairRounds) ===`n"
    $preamble += "El worker original agoto $MaxReviewRounds rondas de review. Tienes un presupuesto nuevo y un modelo distinto.`n"
    $preamble += "Corrige exactamente estos defectos, vuelve a ejecutar el check y envia un unico worker_done con el nuevo dispatch_id.`n"
    $preamble += $Defects

    $send = Invoke-Orca terminal send --terminal $workerHandle --text $preamble --enter --json
    if (-not $send.ok) {
        Write-Warning "No se pudo entregar la reparacion a ${TaskId}: $($send.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }

    if ($Record.workerHandle -and $Record.workerHandle -ne $workerHandle) {
        if (Close-OrcaTerminal -Handle $Record.workerHandle -Quiet) {
            Write-Audit -RunId $RunId -Actor 'loop' -Action 'terminal-close' -TaskId $TaskId -Terminal $Record.workerHandle -Reason 'repair-replaces-worker'
        }
        else {
            Write-Warning "No se pudo cerrar el worker anterior de ${TaskId}"
        }
    }

    if ($repairDispatchId) { Set-RecordValue -Record $Record -Name 'dispatchId' -Value $repairDispatchId }
    Set-RecordValue -Record $Record -Name 'workerHandle' -Value $workerHandle
    Set-RecordValue -Record $Record -Name 'terminal' -Value "repair:$name"
    Set-RecordValue -Record $Record -Name 'reviewRounds' -Value 0
    Set-RecordValue -Record $Record -Name 'repairRounds' -Value $repairRound
    Set-RecordValue -Record $Record -Name 'status' -Value 'changes_requested'
    Save-Record -Record $Record
    Write-Host "[loop] REPAIR $TaskId round $repairRound -> worker-repair $workerHandle"
    return 'CONTINUE'
}

function Invoke-RescueMerge {
    param(
        [Parameter(Mandatory)][string]$Worktree,
        [Parameter(Mandatory)][string]$IntegrationBranch
    )

    if (-not (Test-Path $Worktree)) {
        return [pscustomobject]@{ status = 'error'; files = @() }
    }

    Push-Location $Worktree
    try {
        # Si ya hay un merge en curso (rescate anterior), no lo repetimos.
        $mergeHead = (& git rev-parse --verify -q MERGE_HEAD) 2>$null
        $files = @(& git diff --name-only --diff-filter=U | Where-Object { $_ } | ForEach-Object { $_ -replace '\r', '' })
        if ($mergeHead) {
            return [pscustomobject]@{ status = 'conflict'; files = $files }
        }

        & git merge --no-ff $IntegrationBranch -m "rescue: merge $IntegrationBranch into task branch"
        $exit = $LASTEXITCODE
        $files = @(& git diff --name-only --diff-filter=U | Where-Object { $_ } | ForEach-Object { $_ -replace '\r', '' })

        if ($exit -ne 0 -and $files.Count -gt 0) {
            return [pscustomobject]@{ status = 'conflict'; files = $files }
        }
        if ($exit -ne 0) {
            & git merge --abort 2>$null
            return [pscustomobject]@{ status = 'error'; files = @() }
        }
        return [pscustomobject]@{ status = 'clean'; files = @() }
    }
    finally {
        Pop-Location
    }
}

function Request-Rescue {
    param(
        $Record,
        [string[]]$ConflictFiles,
        [int]$Round,
        [string]$TaskId,
        [string]$IntegrationBranch
    )

    if ($Round -gt $MaxRescueRounds) {
        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status blocked --result "merge_conflict max=$MaxRescueRounds" --json
        if (-not $update.ok) {
            Write-Warning $update.error.message
            $script:IntegrityBlocked = $true
        }
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        Write-Host "[loop] ESCALATED $TaskId after $MaxRescueRounds rescue rounds"
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'lesson-candidate' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason "escalada tras $MaxRescueRounds rondas de rescate"
        Write-Host "[loop] LESSON_PENDING task=$TaskId evidence=audit-$RunId.jsonl"
        return 'STOP'
    }

    $workerHandle = Ensure-WorkerTerminal -Record $Record -Agent 'worker'
    if (-not $workerHandle) {
        $result = 'worker_terminal_unavailable'
        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status blocked --result $result --json
        if (-not $update.ok) {
            Write-Warning $update.error.message
            $script:IntegrityBlocked = $true
        }
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'blocked' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason $result
        return 'STOP'
    }

    $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status ready --result "merge_conflict round=$Round" --json
    if (-not $update.ok) {
        Write-Warning "No se pudo reabrir ${TaskId}: $($update.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }

    $dispatch = Invoke-Orca orchestration dispatch --from $coordinator --run $RunId --task $TaskId --to $workerHandle --return-preamble --json
    if (-not $dispatch.ok) {
        Write-Warning "No se pudo re-despachar ${TaskId}: $($dispatch.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }

    $dispatchResult = Get-OrcaResult $dispatch
    $preamble = $dispatchResult.preamble
    $list = (@($ConflictFiles) | ForEach-Object { "- $_" }) -join "`n"
    $preamble += @"

=== CONFLICTO DE INTEGRACION (rescate $Round / $MaxRescueRounds) ===
El orquestador ha empezado a mergear $IntegrationBranch en tu worktree y hay conflictos.
Archivos en conflicto:
$list

Resuelve SOLO esos conflictos conservando la intencion de ambos lados y los criterios de la spec.
Reglas:
- NO ejecutes git merge, git add, git commit ni git rebase. El orquestador cerrara el merge.
- NO ejecutes git merge --abort: el merge en curso es el que hay que resolver.
- Deja los archivos editados, sin stage.
- Ejecuta pwsh ops/orca/check.ps1 -Worktree . y actualiza report.md con lo que hiciste.
- Si el conflicto no es trivial, consulta al subagente advisor con los archivos y el diff antes de decidir.
- Si no lo ves claro, usa orca orchestration ask antes de inventar.
- Envia un unico worker_done con el nuevo dispatch_id.
"@

    $previousDispatchId = [string]$Record.dispatchId
    $newDispatchId = Get-DispatchIdFromResponse -Response $dispatch
    if (-not $newDispatchId) { $newDispatchId = $previousDispatchId }
    if (-not (Send-ToWorker -Record $Record -TaskId $TaskId -Preamble $preamble -Subject "rescue conflict $TaskId" -DispatchId $newDispatchId)) {
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'blocked' -TaskId $TaskId -DispatchId $newDispatchId -Reason 'no se pudo entregar el conflicto'
        return 'STOP'
    }

    if (-not $Record.dispatchId -or $Record.dispatchId -eq $previousDispatchId) {
        Set-RecordValue -Record $Record -Name 'dispatchId' -Value $newDispatchId
    }
    Set-RecordValue -Record $Record -Name 'rescueRounds' -Value $Round
    Set-RecordValue -Record $Record -Name 'status' -Value 'changes_requested'
    Save-Record -Record $Record
    Write-Host "[loop] RESCUE $TaskId round $Round -> worker $($Record.workerHandle)"
    Write-Audit -RunId $RunId -Actor 'loop' -Action 'rescue' -TaskId $TaskId -DispatchId $newDispatchId -Reason "round=$Round"
    return 'CONTINUE'
}

function Invoke-ArchiveAndCleanup {
    param($Record, [string]$TaskId)

    & pwsh -NoProfile -File $archiveScript -RunId $RunId -TaskId $TaskId -Worktree $Record.worktree | Out-Host

    $cleanupArgs = @('-NoProfile', '-File', $cleanupScript, '-RunId', $RunId, '-TaskId', $TaskId)
    if (-not $KeepWorktrees) { $cleanupArgs += @('-RemoveWorktree', '-Force') }
    $cleanupOutput = (& pwsh @cleanupArgs 2>&1 | Out-String)
    if ($cleanupOutput.Trim()) { Write-Host $cleanupOutput.TrimEnd() }
}

function Set-TaskCompletedIfNeeded {
    param([string]$TaskId, [string]$IntegrationSha)

    $current = Get-TaskSnapshot -TaskId $TaskId
    if ($current -and $current.status -ne 'completed') {
        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status completed --result "integrated=$IntegrationSha" --json
        if (-not $update.ok) {
            Write-Warning "No se pudo marcar ${TaskId} como completed: $($update.error.message)"
        }
    }
}

function Invoke-TaskDelivery {
    param(
        [Parameter(Mandatory)][string]$TaskId,
        $Record
    )

    if (-not $Record) { $Record = Get-Record -TaskId $TaskId }
    if (-not $Record) {
        Write-Warning "No hay mapping local para $TaskId"
        return 'CONTINUE'
    }
    if ($Record.integrationSha -or $Record.status -eq 'integrated') {
        Write-Host "[loop] DELIVERY_SKIP $TaskId ya integrada"
        return 'CONTINUE'
    }

    # Arbitraje de pares [HARNESS-PROBE] (RF1.1): esperar a la hermana y decidir
    # con el verificador existente. La perdedora se cierra sin integrar; la
    # ganadora sigue el flujo normal de entrega debajo.
    if ($Record.PSObject.Properties['pairId'] -and $Record.pairId) {
        $sibling = Get-PairSibling -Records @($script:Dispatches) -Record $Record
        if (-not $sibling) {
            Write-Warning "Tarea probe $($Record.taskId) sin hermana en el registro; despacho normal"
        }
        elseif (-not (Test-HarnessPairReady -Record $Record -Sibling $sibling)) {
            Write-Host "[loop] PAIR_WAIT $($Record.taskId) hermana=$($sibling.taskId) status=$($sibling.status)"
            return 'CONTINUE'
        }
        else {
            $decision = Resolve-HarnessPairWinner -Record $Record -Sibling $sibling
            $variantRec = if ([string]$Record.side -eq 'b') { $Record } else { $sibling }
            $baseRec = if ([string]$Record.side -eq 'b') { $sibling } else { $Record }
            $winnerRec = if ($decision.winner -eq 'variant') { $variantRec } else { $baseRec }
            $loserRec = if ($decision.winner -eq 'variant') { $baseRec } else { $variantRec }
            Write-Host "[loop] PAIR_DECISION pair=$($Record.pairId) winner=$($winnerRec.taskId) loser=$($loserRec.taskId) motivo=$($decision.reason)"
            Write-Audit -RunId $RunId -Actor 'loop' -Action 'probe-pair-decision' -TaskId $winnerRec.taskId -DispatchId $winnerRec.dispatchId -Reason "pair=$($Record.pairId) loser=$($loserRec.taskId) motivo=$($decision.reason)"
            if ($loserRec.taskId -eq $Record.taskId) {
                # La actual es la perdedora: se cierra aqui y no integra.
                $loserUpdate = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $Record.taskId --status failed --result "probe-loser: $($decision.reason)" --json
                if (-not $loserUpdate.ok) { Write-Warning $loserUpdate.error.message }
                Set-RecordValue -Record $Record -Name 'status' -Value 'lost'
                Save-Record -Record $Record
                Write-Audit -RunId $RunId -Actor 'loop' -Action 'probe-loser' -TaskId $Record.taskId -DispatchId $Record.dispatchId -Reason $decision.reason
                Invoke-ArchiveAndCleanup -Record $Record -TaskId $Record.taskId
                try {
                    $branchName = ([string]$Record.branch) -replace '^refs/heads/', ''
                    if ($branchName) { & git -C (Get-RepoRoot) branch -D $branchName 2>$null }
                }
                catch { }
                return 'CONTINUE'
            }
            # La perdedora no es la actual: se cierra ahora y la actual (ganadora)
            # prosigue con el flujo normal.
            $loserUpdate = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $loserRec.taskId --status failed --result "probe-loser: $($decision.reason)" --json
            if (-not $loserUpdate.ok) { Write-Warning $loserUpdate.error.message }
            Set-RecordValue -Record $loserRec -Name 'status' -Value 'lost'
            Save-Record -Record $loserRec
            Write-Audit -RunId $RunId -Actor 'loop' -Action 'probe-loser' -TaskId $loserRec.taskId -DispatchId $loserRec.dispatchId -Reason $decision.reason
            Invoke-ArchiveAndCleanup -Record $loserRec -TaskId $loserRec.taskId
            try {
                $branchName = ([string]$loserRec.branch) -replace '^refs/heads/', ''
                if ($branchName) { & git -C (Get-RepoRoot) branch -D $branchName 2>$null }
            }
            catch { }
        }
    }

    $current = Get-TaskSnapshot -TaskId $TaskId
    if (-not $current) {
        Write-Warning "DELIVERY_STALE $TaskId no existe en Orca"
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'worker-done-stale' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason 'task-missing'
        return 'CONTINUE'
    }
    if (-not (Test-TaskDeliverable -Status $current.status)) {
        Write-Host "[loop] DELIVERY_STALE $TaskId status=$($current.status)"
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'worker-done-stale' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason "status=$($current.status)"
        return 'CONTINUE'
    }

    if (-not $Record.worktree -or -not (Test-Path $Record.worktree)) {
        $result = 'completed_sin_worktree'
        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status blocked --result $result --json
        if (-not $update.ok) {
            Write-Warning $update.error.message
            $script:IntegrityBlocked = $true
        }
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'blocked' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason $result
        Write-Host "[loop] BLOCKED $TaskId $result"
        return 'STOP'
    }

    $round = [int]($Record.reviewRounds) + 1
    $reviewOutput = (& pwsh -NoProfile -File $reviewScript -RunId $RunId -TaskId $TaskId -Worktree $Record.worktree -DispatchId $Record.dispatchId -Round $round -BaseBranch $BaseBranch 2>&1 | Out-String)
    $reviewExit = $LASTEXITCODE
    Write-Host $reviewOutput.TrimEnd()

    $reviewPath = Join-Path $Record.worktree '.orca-task\review.json'
    $review = $null
    if (Test-Path $reviewPath) {
        try { $review = Get-Content $reviewPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $review = $null }
    }

    if ($reviewExit -ne 0) {
        return Request-Changes -Record $Record -Review $review -Round $round -TaskId $TaskId
    }

    $files = @($review.files) | Where-Object { $_ }
    if ($files.Count -eq 0) {
        $branchName = ([string]$Record.branch) -replace '^refs/heads/', ''
        if ($branchName -and (Test-BranchAncestor -Worktree $Record.worktree -Branch $branchName -Ancestor $BaseBranch)) {
            $baseSha = (& git -C $Record.worktree rev-parse $BaseBranch).Trim()
            Set-RecordValue -Record $Record -Name 'status' -Value 'integrated'
            Set-RecordValue -Record $Record -Name 'commitSha' -Value $baseSha
            Set-RecordValue -Record $Record -Name 'integrationSha' -Value $baseSha
            Save-Record -Record $Record
            Write-Host "[loop] ALREADY_INTEGRATED $TaskId $baseSha"
            Write-Audit -RunId $RunId -Actor 'loop' -Action 'already-integrated' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason $baseSha
            Write-Audit -RunId $RunId -Actor 'loop' -Action 'lesson-candidate' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason "rama ya integrada $baseSha"
            Write-Host "[loop] LESSON_PENDING task=$TaskId evidence=audit-$RunId.jsonl"
            Set-TaskCompletedIfNeeded -TaskId $TaskId -IntegrationSha $baseSha
            Invoke-ArchiveAndCleanup -Record $Record -TaskId $TaskId
            return 'CONTINUE'
        }

        # Sin diff y sin rama integrada no hay nada que commitear: reabrir y
        # re-despachar solo crea tareas fantasma. Se bloquea y se corta.
        $result = 'review_sin_ficheros'
        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status blocked --result $result --json
        if (-not $update.ok) { Write-Warning $update.error.message }
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        $script:IntegrityBlocked = $true
        Write-Host "[loop] BLOCKED $TaskId $result"
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'blocked' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason $result
        return 'STOP'
    }

    $commitOutput = (& pwsh -NoProfile -File $commitScript -Worktree $Record.worktree -TaskId $TaskId -FilesCsv ($files -join ',') -Message "task($TaskId): review round $round" -BaseBranch $BaseBranch 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Commit fallo para ${TaskId}: $commitOutput"
        $review = [pscustomobject]@{ defects = @("Commit fallo: $($commitOutput.Trim())") }
        return Request-Changes -Record $Record -Review $review -Round $round -TaskId $TaskId
    }
    $commitSha = ([regex]::Match($commitOutput, 'COMMIT=([0-9a-f]+)')).Groups[1].Value
    Write-Host "[loop] COMMIT $TaskId $commitSha"
    Write-Audit -RunId $RunId -Actor 'loop' -Action 'commit' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason $commitSha

    $branch = $Record.branch -replace '^refs/heads/', ''
    $integrationBranch = "orca/integration/$RunId"
    $integrationOutput = ''
    $integrationOk = $false

    for ($attempt = 0; $attempt -le 1; $attempt++) {
        $integrationOutput = (& pwsh -NoProfile -File $integrateScript -RunId $RunId -Branches $branch -BaseBranch $BaseBranch 2>&1 | Out-String)
        if ($LASTEXITCODE -eq 0) {
            $integrationOk = $true
            break
        }

        if (-not $AutoRescue -or $attempt -ge 1) { break }
        if ($integrationOutput -notmatch 'Conflicto al integrar') {
            # Un fallo de checks o de worktree no se arregla mergeando la integración.
            break
        }

        Write-Warning "Integración falló para ${TaskId}; intentando rescate"
        $rescueRound = ([int]($Record.rescueRounds)) + 1
        $merge = Invoke-RescueMerge -Worktree $Record.worktree -IntegrationBranch $integrationBranch

        if ($merge.status -eq 'conflict') {
            return Request-Rescue -Record $Record -ConflictFiles $merge.files -Round $rescueRound -TaskId $TaskId -IntegrationBranch $integrationBranch
        }

        if ($merge.status -eq 'error') {
            Write-Warning "El rescate no pudo preparar el merge de ${TaskId}"
            break
        }

        Write-Host "[loop] RESCUE_MERGE $TaskId limpio; reintentando integración"
    }

    if (-not $integrationOk) {
        Write-Warning "Integración falló para ${TaskId}: $integrationOutput"
        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status blocked --result 'integration failed' --json
        if (-not $update.ok) {
            Write-Warning $update.error.message
            $script:IntegrityBlocked = $true
        }
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'blocked' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason 'integration failed'
        return 'STOP'
    }
    $integrationSha = ([regex]::Match($integrationOutput, 'INTEGRATION_SHA=([0-9a-f]+)')).Groups[1].Value
    Write-Host "[loop] INTEGRATED $TaskId $integrationSha"

    # Guardamos la evidencia ANTES de archivar/limpiar: si la limpieza falla o
    # el proceso muere, la reconciliacion no vuelve a integrar la misma tarea.
    Set-RecordValue -Record $Record -Name 'status' -Value 'integrated'
    Set-RecordValue -Record $Record -Name 'commitSha' -Value $commitSha
    Set-RecordValue -Record $Record -Name 'integrationSha' -Value $integrationSha
    Save-Record -Record $Record
    Write-Audit -RunId $RunId -Actor 'loop' -Action 'integrated' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason $integrationSha

    # Evidencia para la libreria de lecciones (PRD docs/08-prd-harnessing.md).
    Write-Audit -RunId $RunId -Actor 'loop' -Action 'lesson-candidate' -TaskId $TaskId -DispatchId $Record.dispatchId -Reason "integrada $integrationSha"
    Write-Host "[loop] LESSON_PENDING task=$TaskId evidence=audit-$RunId.jsonl"

    Set-TaskCompletedIfNeeded -TaskId $TaskId -IntegrationSha $integrationSha
    Invoke-ArchiveAndCleanup -Record $Record -TaskId $TaskId
    return 'CONTINUE'
}

function Handle-Done {
    param($Message)

    $context = Resolve-MessageContext -Message $Message
    if (-not $context.TaskId) {
        Write-Warning "worker_done sin taskId resoluble: $($Message.id)"
        Write-Audit -RunId $RunId -Actor 'worker' -Action 'worker-done-unresolved' -Reason $Message.id
        return 'CONTINUE'
    }

    $taskId = $context.TaskId
    $record = $context.Record
    $latestRecord = Get-Record -TaskId $taskId
    if ($latestRecord) {
        if ($context.DispatchId -and $latestRecord.dispatchId -and $context.DispatchId -ne $latestRecord.dispatchId) {
            Write-Host "[loop] WORKER_DONE_STALE $taskId dispatch=$($context.DispatchId) latest=$($latestRecord.dispatchId)"
            Write-Audit -RunId $RunId -Actor 'worker' -Action 'worker-done-stale' -TaskId $taskId -DispatchId $context.DispatchId -Reason "dispatch-not-latest latest=$($latestRecord.dispatchId)"
            return 'CONTINUE'
        }
        $record = $latestRecord
    }
    if (-not $record) {
        Write-Warning "No hay mapping local para $taskId"
        Write-Audit -RunId $RunId -Actor 'worker' -Action 'worker-done-sin-record' -TaskId $taskId
        return 'CONTINUE'
    }

    # Un worker_done puede sobrevivir al runtime y llegar cuando la tarea ya
    # esta blocked/failed/ready. No se entrega: el estado vigente manda.
    $current = Get-TaskSnapshot -TaskId $taskId
    if (-not $current) {
        Write-Host "[loop] WORKER_DONE_STALE $taskId reason=task-missing"
        Write-Audit -RunId $RunId -Actor 'worker' -Action 'worker-done-stale' -TaskId $taskId -DispatchId $record.dispatchId -Reason 'task-missing'
        return 'CONTINUE'
    }
    if (-not (Test-TaskDeliverable -Status $current.status)) {
        Write-Host "[loop] WORKER_DONE_STALE $taskId status=$($current.status)"
        Write-Audit -RunId $RunId -Actor 'worker' -Action 'worker-done-stale' -TaskId $taskId -DispatchId $record.dispatchId -Reason "status=$($current.status)"
        return 'CONTINUE'
    }
    if ($context.DispatchId -and $record.dispatchId -and $context.DispatchId -ne $record.dispatchId) {
        Write-Host "[loop] WORKER_DONE_STALE $taskId dispatch=$($context.DispatchId) record=$($record.dispatchId)"
        Write-Audit -RunId $RunId -Actor 'worker' -Action 'worker-done-stale' -TaskId $taskId -DispatchId $context.DispatchId -Reason "dispatch-mismatch record=$($record.dispatchId)"
        return 'CONTINUE'
    }

    $payload = Get-PayloadObject -Payload $Message.payload
    $outcome = 'succeeded'
    if ($payload -and $payload.PSObject.Properties['outcome'] -and $payload.outcome) {
        $outcome = [string]$payload.outcome
    }

    if ($outcome -ne 'succeeded') {
        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $taskId --status failed --result "worker outcome: $outcome" --json
        if (-not $update.ok) { Write-Warning $update.error.message }
        Set-RecordValue -Record $record -Name 'status' -Value 'failed'
        Save-Record -Record $record
        Write-Host "[loop] FAILED $taskId outcome=$outcome"
        Write-Audit -RunId $RunId -Actor 'worker' -Action 'failed' -TaskId $taskId -DispatchId $record.dispatchId -Reason $outcome
        return 'CONTINUE'
    }

    return Invoke-TaskDelivery -TaskId $taskId -Record $record
}

function Reconcile-CompletedTasks {
    param([array]$Tasks)

    if (-not $script:Dispatches -or $script:Dispatches.Count -eq 0) {
        return $Tasks
    }

    $completed = @($Tasks | Where-Object { $_.status -eq 'completed' })
    if ($completed.Count -eq 0) { return $Tasks }

    foreach ($task in $completed) {
        $record = Get-Record -TaskId $task.id
        if (-not $record) {
            Write-Warning "RECONCILE_NO_RECORD task=$($task.id)"
            $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $task.id --status blocked --result 'completed_sin_dispatch_local' --json
            if (-not $update.ok) {
                Write-Warning $update.error.message
                $script:IntegrityBlocked = $true
            }
            Write-Audit -RunId $RunId -Actor 'loop' -Action 'blocked' -TaskId $task.id -Reason 'completed_sin_dispatch_local'
            continue
        }
        if ($record.integrationSha -or $record.status -in @('integrated', 'lost')) { continue }

        Write-Host "[loop] RECONCILE task=$($task.id) completed sin integrar"
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'reconcile' -TaskId $task.id -DispatchId $record.dispatchId -Reason 'completed_sin_integracion'
        $outcome = Invoke-TaskDelivery -TaskId $task.id -Record $record
        if ($outcome -eq 'STOP') { break }
    }

    return @(Get-Tasks)
}

function Settle-SettledDispatches {
    param([array]$Tasks)

    $byTask = @{}
    foreach ($task in @($Tasks)) {
        if (-not $task -or -not $task.id) { continue }
        $byTask[[string]$task.id] = $task
    }

    foreach ($record in @($script:Dispatches)) {
        if (-not $record.workerHandle) { continue }
        $task = $null
        if ($record.taskId -and $byTask.ContainsKey([string]$record.taskId)) {
            $task = $byTask[[string]$record.taskId]
        }
        $settled = $false

        if ($record.integrationSha -or $record.status -eq 'integrated') {
            $settled = $true
        }
        elseif ($task -and $task.status -in @('completed', 'failed', 'blocked')) {
            $settled = $true
        }
        elseif ($record.dispatchId) {
            $show = Get-OrcaWorkerShow -DispatchId $record.dispatchId
            if ($show -and ([string]$show.dispatch.status) -in @('completed', 'failed', 'cancelled', 'settled')) {
                if (-not $task -or $task.status -notin @('dispatched', 'changes_requested', 'ready')) {
                    $settled = $true
                }
            }
        }

        if (-not $settled) { continue }
        if ($script:ClosedTerminals[$record.workerHandle]) { continue }
        if (Close-OrcaTerminal -Handle $record.workerHandle -Quiet) {
            $script:ClosedTerminals[$record.workerHandle] = $true
            Write-Host "TERMINAL_SETTLED=$($record.workerHandle) task=$($record.taskId)"
            Write-Audit -RunId $RunId -Actor 'loop' -Action 'terminal-close' -TaskId $record.taskId -DispatchId $record.dispatchId -Terminal $record.workerHandle -Reason 'settled'
        }
    }
}

function Detect-RuntimeReverts {
    param([array]$Tasks)

    foreach ($task in @($Tasks | Where-Object { $_.status -eq 'ready' })) {
        $record = Get-Record -TaskId $task.id
        if (-not $record -or -not $record.dispatchId) { continue }
        # Solo investigamos un dispatch que creiamos activo. Los estados que el
        # propio bucle escribe (lost/stalled/changes_requested/ready) ya llevan
        # su result y no son una reversion silenciosa del runtime.
        if ($record.status -and $record.status -ne 'dispatched') { continue }

        $show = Get-OrcaWorkerShow -DispatchId $record.dispatchId
        if (-not $show) { continue }
        $lastError = [string]$show.dispatch.lastError
        $attention = ''
        if ($show.projection.attention -and $show.projection.attention.categories) {
            $attention = (@($show.projection.attention.categories) -join ',')
        }
        if ($lastError -match 'stop was requested|never confirmed|worker_identity_changed' -or $attention -match 'failure') {
            $reason = if ($lastError) { $lastError } else { $attention }
            $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $task.id --status blocked --result "runtime_stop: $reason" --json
            if (-not $update.ok) {
                Write-Warning $update.error.message
                $script:IntegrityBlocked = $true
            }
            Set-RecordValue -Record $record -Name 'status' -Value 'blocked'
            Save-Record -Record $record
            Write-Host "[loop] RUNTIME_STOP task=$($task.id): $reason"
            Write-Audit -RunId $RunId -Actor 'orca' -Action 'blocked' -TaskId $task.id -DispatchId $record.dispatchId -Reason "runtime_stop: $reason"
        }
    }
}

function Resume-DeadDispatches {
    $tasks = @(Get-Tasks)
    foreach ($task in @($tasks | Where-Object { $_.status -eq 'dispatched' })) {
        $record = Get-Record -TaskId $task.id
        if (-not $record -or -not $record.workerHandle) { continue }

        $show = Get-OrcaWorkerShow -DispatchId $record.dispatchId
        $liveness = if ($show) { [string]$show.projection.liveness.verdict } else { 'unknown' }
        $dispatchStatus = if ($show) { [string]$show.dispatch.status } else { 'unknown' }

        $terminal = $null
        try {
            $terminalResponse = Invoke-Orca terminal show --terminal $record.workerHandle --json
            if ($terminalResponse.ok) { $terminal = $terminalResponse.result.terminal }
        }
        catch { }
        $connected = [bool]($terminal -and $terminal.connected -eq $true)

        if ($connected -and $liveness -ne 'dead' -and $dispatchStatus -notin @('failed', 'cancelled')) { continue }

        $proven = ($liveness -eq 'dead') -or ($dispatchStatus -in @('failed', 'cancelled'))
        if (-not $proven -and -not $connected -and $liveness -ne 'live' -and $show -and $show.dispatch.lastError) {
            $proven = $true
        }
        if (-not $proven) {
            Write-Host "RESUME_UNPROVEN task=$($task.id) liveness=$liveness dispatch=$dispatchStatus terminal_connected=$connected"
            Write-Audit -RunId $RunId -Actor 'loop' -Action 'resume-unproven' -TaskId $task.id -DispatchId $record.dispatchId -Reason "liveness=$liveness dispatch=$dispatchStatus"
            continue
        }

        $reason = if ($show -and $show.dispatch.lastError) { [string]$show.dispatch.lastError } else { "terminal_connected=$connected liveness=$liveness dispatch=$dispatchStatus" }
        Write-Host "RESUME_DEAD task=$($task.id) terminal=$($record.terminal) reason=$reason"
        if ($record.dispatchId) {
            [void](Invoke-Orca orchestration worker-stop --dispatch $record.dispatchId --json)
        }
        [void](Close-OrcaTerminal -Handle $record.workerHandle -Quiet)

        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $task.id --status ready --result "resume_dead_worker: $reason" --json
        if (-not $update.ok) {
            Write-Warning "No se pudo reabrir $($task.id) tras perder su terminal: $($update.error.message)"
            continue
        }
        Set-RecordValue -Record $record -Name 'status' -Value 'lost'
        Set-RecordValue -Record $record -Name 'lastError' -Value $reason
        Save-Record -Record $record
        Write-Audit -RunId $RunId -Actor 'loop' -Action 'resume-dead' -TaskId $task.id -DispatchId $record.dispatchId -Reason $reason
    }
}

Detect-RuntimeReverts -Tasks @(Get-Tasks)
Resume-DeadDispatches

$stopReason = $null

while (-not $stopReason) {
    $tasks = @(Get-Tasks)
    if ($tasks.Count -eq 0) { $stopReason = 'EMPTY'; break }

    # Una tarea completed solo es una entrega cuando tiene integrationSha.
    # Reconciliar antes de contar evita que un worker_done sin taskId o un
    # task-update manual salten review, commit e integracion.
    Detect-RuntimeReverts -Tasks $tasks
    $tasks = @(Get-Tasks)
    $tasks = @(Reconcile-CompletedTasks -Tasks $tasks)
    if ($script:IntegrityBlocked) { $stopReason = 'BLOCKED'; break }
    Settle-SettledDispatches -Tasks $tasks

    Update-Watchdog -Tasks $tasks
    if ($script:WatchdogBlocked) { $stopReason = 'BLOCKED'; break }
    if ($script:WatchdogRestarted) {
        $script:WatchdogRestarted = $false
        $tasks = @(Get-Tasks)
    }

    $active = @($tasks | Where-Object { $_.status -eq 'dispatched' }).Count
    $ready = @($tasks | Where-Object { $_.status -eq 'ready' })
    $completed = @($tasks | Where-Object { $_.status -eq 'completed' })
    $blocked = @($tasks | Where-Object { $_.status -in @('blocked', 'failed') })

    Write-Output "[loop] tasks=$($tasks.Count) active=$active ready=$($ready.Count) completed=$($completed.Count) blocked=$($blocked.Count)"

    if ($completed.Count -eq $tasks.Count) { $stopReason = 'DONE'; break }

    if ($active -eq 0 -and $ready.Count -eq 0) {
        $stopReason = if ($blocked.Count -gt 0) { 'BLOCKED' } else { 'DONE' }
        break
    }

    if ($ready.Count -gt 0 -and $active -lt $MaxWorkers) {
        $dispatchArgs = @('-NoProfile', '-File', (Join-Path $PSScriptRoot 'dispatch.ps1'), '-RunId', $RunId, '-MaxWorkers', $MaxWorkers, '-BaseBranch', $BaseBranch)
        if ($VariantDir) { $dispatchArgs += @('-VariantDir', $VariantDir) }
        & pwsh @dispatchArgs | Out-Host
        $script:Dispatches = @(Read-Dispatches -RunId $RunId)
        continue
    }

    $check = Invoke-Orca orchestration check --terminal $coordinator --run $RunId --wait --types 'worker_done,question,escalation' --timeout-ms $WaitTimeoutMs --json
    if (-not $check.ok) { throw "check falló: $($check.error.message)" }

    $result = $check.result
    if ($result.timedOut -or $result.count -eq 0) {
        Write-Output '[loop] wait timeout; comprobando workers'
        continue
    }

    foreach ($message in $result.messages) {
        if ($message.type -eq 'question') {
            $questionFile = Join-Path (Get-StateDir) "question-$RunId.json"
            [ordered]@{
                runId      = $RunId
                deliveryId = $result.deliveryId
                coordinator = $coordinator
                capturedAt = (Get-Date).ToUniversalTime().ToString('o')
                message    = $message
            } | ConvertTo-Json -Depth 20 | Set-Content $questionFile -Encoding UTF8
            Write-Output "QUESTION_FILE=$questionFile"
            Write-Output "[loop] QUESTION $($message.id) task=$($message.payload)"
            $stopReason = 'QUESTION'
            break
        }
        if ($message.type -eq 'escalation') {
            $escalationOutcome = Handle-Escalation -Message $message
            if ($escalationOutcome -eq 'ESCALATION') {
                $stopReason = 'ESCALATION'
                break
            }
            continue
        }
        if ($message.type -eq 'worker_done') {
            $outcome = Handle-Done -Message $message
            if ($outcome -eq 'STOP') { $stopReason = 'BLOCKED'; break }
        }
    }

    Ack-Delivery -DeliveryId $result.deliveryId
}

Write-Output "LOOP=$stopReason"

switch ($stopReason) {
    'DONE' { exit 0 }
    'EMPTY' { exit 0 }
    'QUESTION' { exit 3 }
    'BLOCKED' { exit 2 }
    'ESCALATION' { exit 2 }
    default { exit 1 }
}


