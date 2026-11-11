param(
    [Parameter(Mandatory)][string]$RunId,
    [ValidateRange(1, 5)][int]$MaxWorkers = 5,
    [ValidateRange(1, 10)][int]$MaxReviewRounds = 2,
    [int]$WaitTimeoutMs = 900000,
    [string]$BaseBranch = 'main',
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

$coordinator = Get-Coordinator
Bind-Run -RunId $RunId -Coordinator $coordinator

$script:Dispatches = @(Read-Dispatches -RunId $RunId)
$script:Watchdog = @{}
$script:StallRecoveries = @{}
$script:WatchdogRestarted = $false
$script:WatchdogBlocked = $false
$commitScript = Join-Path $PSScriptRoot 'commit.ps1'
$reviewScript = Join-Path $PSScriptRoot 'review.ps1'
$integrateScript = Join-Path $PSScriptRoot 'integrate.ps1'
$archiveScript = Join-Path $PSScriptRoot 'archive.ps1'
$cleanupScript = Join-Path $PSScriptRoot 'cleanup.ps1'

function Get-Tasks {
    $response = Invoke-OrcaTaskList -Coordinator $coordinator -RunId $RunId
    return @((Get-OrcaResult $response).tasks)
}

function Get-Record {
    param([string]$TaskId)
    $items = @($script:Dispatches) | Where-Object { $_.taskId -eq $TaskId } | Select-Object -Last 1
    return $items
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
        if ($minutes -ge $StallMinutes -and (-not $state.warnedAt -or ($now - $state.warnedAt).TotalMinutes -ge $StallMinutes)) {
            if ($StallAction -ne 'restart') {
                Write-Output "[loop] WATCHDOG task=$($task.id) minutes=$([int]$minutes) terminal=$($record.terminal)"
                $state.warnedAt = $now
                continue
            }

            $recoveries = [int]$script:StallRecoveries[$task.id]
            if ($recoveries -ge $MaxStallRecoveries) {
                $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $task.id --status blocked --result "stalled max_recoveries=$MaxStallRecoveries" --json
                if (-not $update.ok) { Write-Warning $update.error.message }
                Set-RecordValue -Record $record -Name 'status' -Value 'blocked'
                Save-Record -Record $record
                Write-Output "[loop] WATCHDOG_BLOCKED task=$($task.id) recoveries=$recoveries"
                $script:WatchdogBlocked = $true
                continue
            }

            if (-not $record.dispatchId) {
                Write-Output "[loop] WATCHDOG_NO_DISPATCH task=$($task.id); no se puede reiniciar"
                $script:WatchdogBlocked = $true
                continue
            }

            $stop = Invoke-Orca orchestration worker-stop --dispatch $record.dispatchId --json
            if (-not $stop.ok) {
                Write-Warning "No se pudo parar el worker estancado de $($task.id): $($stop.error.message)"
                $script:WatchdogBlocked = $true
                continue
            }
            [void](Invoke-Orca terminal close --terminal $record.workerHandle --json)

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
            Write-Output "[loop] WATCHDOG_RESTART task=$($task.id) attempt=$($recoveries + 1) terminal=$($record.terminal)"
        }
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
        if (-not $update.ok) { Write-Warning $update.error.message }
        Set-RecordValue -Record $Record -Name 'status' -Value 'escalated'
        Save-Record -Record $Record
        Write-Host "[loop] ESCALATED $TaskId after $MaxReviewRounds defect rounds"
        return 'STOP'
    }

    $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status ready --result "review_round=$Round" --json
    if (-not $update.ok) {
        Write-Warning "No se pudo reabrir ${TaskId}: $($update.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }

    $dispatch = Invoke-Orca orchestration dispatch --from $coordinator --run $RunId --task $TaskId --to $Record.workerHandle --return-preamble --json
    if (-not $dispatch.ok) {
        Write-Warning "No se pudo re-despachar ${TaskId}: $($dispatch.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }

    $dispatchResult = Get-OrcaResult $dispatch
    $preamble = $dispatchResult.preamble
    $preamble += "`n`n=== REVIEW DEFECTS (round $Round / max $MaxReviewRounds) ===`n$defects`n`n"
    $preamble += "Corrige exactamente estos defectos. Vuelve a ejecutar el check y envía un nuevo worker_done con el nuevo dispatch_id. No hagas push ni merge."

    $send = Invoke-Orca terminal send --terminal $Record.workerHandle --text $preamble --enter --json
    if (-not $send.ok) {
        Write-Warning "No se pudo entregar los defectos a ${TaskId}: $($send.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }

    Set-RecordValue -Record $Record -Name 'dispatchId' -Value $dispatchResult.dispatch.id
    Set-RecordValue -Record $Record -Name 'reviewRounds' -Value $Round
    Set-RecordValue -Record $Record -Name 'status' -Value 'changes_requested'
    Save-Record -Record $Record
    Write-Host "[loop] CHANGES $TaskId round $Round -> re-dispatched $($Record.dispatchId)"
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
        $closed = Invoke-Orca terminal close --terminal $Record.workerHandle --json
        if (-not $closed.ok) { Write-Warning "No se pudo cerrar el worker anterior de ${TaskId}: $($closed.error.message)" }
    }

    Set-RecordValue -Record $Record -Name 'dispatchId' -Value $dispatchResult.dispatch.id
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
        if (-not $update.ok) { Write-Warning $update.error.message }
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        Write-Host "[loop] ESCALATED $TaskId after $MaxRescueRounds rescue rounds"
        return 'STOP'
    }

    $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $TaskId --status ready --result "merge_conflict round=$Round" --json
    if (-not $update.ok) {
        Write-Warning "No se pudo reabrir ${TaskId}: $($update.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }

    $dispatch = Invoke-Orca orchestration dispatch --from $coordinator --run $RunId --task $TaskId --to $Record.workerHandle --return-preamble --json
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

    $send = Invoke-Orca terminal send --terminal $Record.workerHandle --text $preamble --enter --json
    if (-not $send.ok) {
        Write-Warning "No se pudo entregar el conflicto a ${TaskId}: $($send.error.message)"
        Set-RecordValue -Record $Record -Name 'status' -Value 'blocked'
        Save-Record -Record $Record
        return 'STOP'
    }

    Set-RecordValue -Record $Record -Name 'dispatchId' -Value $dispatchResult.dispatch.id
    Set-RecordValue -Record $Record -Name 'rescueRounds' -Value $Round
    Set-RecordValue -Record $Record -Name 'status' -Value 'changes_requested'
    Save-Record -Record $Record
    Write-Host "[loop] RESCUE $TaskId round $Round -> worker $($Record.workerHandle)"
    return 'CONTINUE'
}

function Handle-Done {
    param($Message)

    $payload = $null
    try { $payload = $Message.payload | ConvertFrom-Json } catch { $payload = $null }
    if (-not $payload -or -not $payload.taskId) {
        Write-Warning "worker_done sin taskId: $($Message.id)"
        return 'CONTINUE'
    }

    $taskId = $payload.taskId
    $record = Get-Record -TaskId $taskId
    if (-not $record) {
        Write-Warning "No hay mapping local para $taskId"
        return 'CONTINUE'
    }

    if ($payload.outcome -ne 'succeeded') {
        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $taskId --status failed --result "worker outcome: $($payload.outcome)" --json
        if (-not $update.ok) { Write-Warning $update.error.message }
        Set-RecordValue -Record $record -Name 'status' -Value 'failed'
        Save-Record -Record $record
        Write-Host "[loop] FAILED $taskId outcome=$($payload.outcome)"
        return 'CONTINUE'
    }

    $round = [int]($record.reviewRounds) + 1
    $reviewOutput = (& pwsh -NoProfile -File $reviewScript -RunId $RunId -TaskId $taskId -Worktree $record.worktree -DispatchId $record.dispatchId -Round $round 2>&1 | Out-String)
    $reviewExit = $LASTEXITCODE
    Write-Host $reviewOutput.TrimEnd()

    $reviewPath = Join-Path $record.worktree '.orca-task\review.json'
    $review = $null
    if (Test-Path $reviewPath) {
        try { $review = Get-Content $reviewPath -Raw | ConvertFrom-Json } catch { $review = $null }
    }

    if ($reviewExit -ne 0) {
        return Request-Changes -Record $record -Review $review -Round $round -TaskId $taskId
    }

    $files = @($review.files) | Where-Object { $_ }
    if ($files.Count -eq 0) {
        $review = [pscustomobject]@{ defects = @('El review aceptó pero no declaró archivos para commitear.') }
        return Request-Changes -Record $record -Review $review -Round $round -TaskId $taskId
    }

    $commitOutput = (& pwsh -NoProfile -File $commitScript -Worktree $record.worktree -TaskId $taskId -FilesCsv ($files -join ',') -Message "task($taskId): review round $round" 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Commit falló para ${TaskId}: $commitOutput"
        $review = [pscustomobject]@{ defects = @("Commit falló: $($commitOutput.Trim())") }
        return Request-Changes -Record $record -Review $review -Round $round -TaskId $taskId
    }
    $commitSha = ([regex]::Match($commitOutput, 'COMMIT=([0-9a-f]+)')).Groups[1].Value
    Write-Host "[loop] COMMIT $taskId $commitSha"

    $branch = $record.branch -replace '^refs/heads/', ''
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
        $rescueRound = ([int]($record.rescueRounds)) + 1
        $merge = Invoke-RescueMerge -Worktree $record.worktree -IntegrationBranch $integrationBranch

        if ($merge.status -eq 'conflict') {
            return Request-Rescue -Record $record -ConflictFiles $merge.files -Round $rescueRound -TaskId $taskId -IntegrationBranch $integrationBranch
        }

        if ($merge.status -eq 'error') {
            Write-Warning "El rescate no pudo preparar el merge de ${TaskId}"
            break
        }

        Write-Host "[loop] RESCUE_MERGE $TaskId limpio; reintentando integración"
    }

    if (-not $integrationOk) {
        Write-Warning "Integración falló para ${TaskId}: $integrationOutput"
        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $taskId --status blocked --result 'integration failed' --json
        if (-not $update.ok) { Write-Warning $update.error.message }
        Set-RecordValue -Record $record -Name 'status' -Value 'blocked'
        Save-Record -Record $record
        return 'STOP'
    }
    $integrationSha = ([regex]::Match($integrationOutput, 'INTEGRATION_SHA=([0-9a-f]+)')).Groups[1].Value
    Write-Host "[loop] INTEGRATED $taskId $integrationSha"

    & pwsh -NoProfile -File $archiveScript -RunId $RunId -TaskId $taskId -Worktree $record.worktree | Out-Host

    $cleanupArgs = @('-NoProfile', '-File', $cleanupScript, '-RunId', $RunId, '-TaskId', $taskId)
    if (-not $KeepWorktrees) { $cleanupArgs += @('-RemoveWorktree', '-Force') }
    & pwsh @cleanupArgs | Out-Host

    Set-RecordValue -Record $record -Name 'status' -Value 'integrated'
    Set-RecordValue -Record $record -Name 'commitSha' -Value $commitSha
    Set-RecordValue -Record $record -Name 'integrationSha' -Value $integrationSha
    Save-Record -Record $record
    return 'CONTINUE'
}

function Resume-DeadDispatches {
    $tasks = @(Get-Tasks)
    foreach ($task in @($tasks | Where-Object { $_.status -eq 'dispatched' })) {
        $record = Get-Record -TaskId $task.id
        if (-not $record -or -not $record.workerHandle) { continue }

        $show = Invoke-Orca terminal show --terminal $record.workerHandle --json
        $alive = $false
        if ($show.ok -and $show.result -and $show.result.terminal) {
            $alive = $show.result.terminal.connected -eq $true
        }
        if ($alive) { continue }

        Write-Output "RESUME_DEAD task=$($task.id) terminal=$($record.terminal)"
        if ($record.dispatchId) {
            [void](Invoke-Orca orchestration worker-stop --dispatch $record.dispatchId --json)
        }
        $update = Invoke-Orca orchestration task-update --from $coordinator --run $RunId --id $task.id --status ready --result 'resume_dead_worker' --json
        if (-not $update.ok) {
            Write-Warning "No se pudo reabrir $($task.id) tras perder su terminal: $($update.error.message)"
            continue
        }
        Set-RecordValue -Record $record -Name 'status' -Value 'lost'
        Save-Record -Record $record
    }
}

Resume-DeadDispatches

$stopReason = $null

while (-not $stopReason) {
    $tasks = @(Get-Tasks)
    if ($tasks.Count -eq 0) { $stopReason = 'EMPTY'; break }
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
        & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'dispatch.ps1') -RunId $RunId -MaxWorkers $MaxWorkers -BaseBranch $BaseBranch | Out-Host
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
            Write-Output "[loop] ESCALATION $($message.id): $($message.body)"
            $stopReason = 'ESCALATION'
            break
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


