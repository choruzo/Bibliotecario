param(
    [Parameter(Mandatory)][string]$RunId,
    [ValidateRange(1, 5)][int]$MaxWorkers = 5,
    [ValidateRange(1, 10)][int]$MaxReviewRounds = 2,
    [int]$WaitTimeoutMs = 900000,
    [string]$BaseBranch = 'main',
    [switch]$KeepWorktrees
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib.ps1')

$coordinator = Get-Coordinator
Bind-Run -RunId $RunId -Coordinator $coordinator

$script:Dispatches = @(Read-Dispatches -RunId $RunId)
$commitScript = Join-Path $PSScriptRoot 'commit.ps1'
$reviewScript = Join-Path $PSScriptRoot 'review.ps1'
$integrateScript = Join-Path $PSScriptRoot 'integrate.ps1'
$archiveScript = Join-Path $PSScriptRoot 'archive.ps1'
$cleanupScript = Join-Path $PSScriptRoot 'cleanup.ps1'

function Get-Tasks {
    $response = Invoke-Orca orchestration task-list --from $coordinator --run $RunId --json
    return @((Get-OrcaResult $response).tasks)
}

function Get-Record {
    param([string]$TaskId)
    $items = @($script:Dispatches) | Where-Object { $_.taskId -eq $TaskId } | Select-Object -Last 1
    return $items
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

function Handle-Done {
    param($Message)

    # Orca puede entregar `payload` como objeto ya parseado o como cadena JSON.
    $payload = $null
    try {
        $payload = if ($Message.payload -is [string]) { $Message.payload | ConvertFrom-Json } else { $Message.payload }
    }
    catch { $payload = $null }

    $taskId = if ($payload) { $payload.taskId } else { $null }
    if (-not $taskId -and $payload -and $payload.dispatchId) {
        $match = @($script:Dispatches | Where-Object { $_.dispatchId -eq $payload.dispatchId }) | Select-Object -Last 1
        if ($match) { $taskId = $match.taskId }
    }
    if (-not $taskId -and $Message.from) {
        $match = @($script:Dispatches | Where-Object { $_.workerHandle -eq $Message.from }) | Select-Object -Last 1
        if ($match) { $taskId = $match.taskId }
    }
    if (-not $taskId) {
        Write-Warning "worker_done sin taskId ni dispatch reconocible: $($Message.id)"
        return 'CONTINUE'
    }
    $record = Get-Record -TaskId $taskId
    if (-not $record) {
        Write-Warning "No hay mapping local para $taskId"
        return 'CONTINUE'
    }

    if ($payload -and $payload.outcome -and $payload.outcome -ne 'succeeded') {
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
    $integrationOutput = (& pwsh -NoProfile -File $integrateScript -RunId $RunId -Branches $branch -BaseBranch $BaseBranch 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
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

$stopReason = $null

while (-not $stopReason) {
    $tasks = @(Get-Tasks)
    if ($tasks.Count -eq 0) { $stopReason = 'EMPTY'; break }

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
            Write-Output "[loop] QUESTION $($message.id) task=$($message.payload)"
            $stopReason = 'QUESTION'
            break
        }
        if ($message.type -eq 'escalation') {
            # Orca marca `needs-input` cuando el TUI queda quieto; en la practica el
            # worker sigue trabajando en un comando largo. Solo se detiene el bucle
            # ante una escalada de otro tipo (el watchdog cubre un worker de verdad parado).
            $payload = $null
            if ($message.payload) {
                try { $payload = if ($message.payload -is [string]) { $message.payload | ConvertFrom-Json } else { $message.payload } } catch { $payload = $null }
            }
            if ($payload -and $payload.stopReason -eq 'needs-input') {
                Write-Output "[loop] IGNORED needs-input $($message.id) task=$($payload.taskId)"
                continue
            }
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



