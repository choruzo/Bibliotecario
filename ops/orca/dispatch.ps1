param(
    [Parameter(Mandatory)][string]$RunId,
    [ValidateRange(1, 5)][int]$MaxWorkers = 5,
    [string]$BaseBranch = 'main',
    [string]$WorkerAgent = 'worker',
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$coordinator = Get-Coordinator
Bind-Run -RunId $RunId -Coordinator $coordinator
$repoId = Get-RepoId
$stateDir = Get-StateDir
$dispatches = @(Read-Dispatches -RunId $RunId)

$taskResponse = Invoke-Orca orchestration task-list --from $coordinator --run $RunId --json --full
$tasks = @((Get-OrcaResult $taskResponse).tasks)

$active = @($tasks | Where-Object { $_.status -eq 'dispatched' }).Count
$slots = [Math]::Max(0, $MaxWorkers - $active)
$ready = @($tasks | Where-Object { $_.status -eq 'ready' } | Select-Object -First $slots)

Write-Output "RUN=$RunId"
Write-Output "ACTIVE=$active"
Write-Output "SLOTS=$slots"
Write-Output "READY=$($ready.Count)"

if ($ready.Count -eq 0) {
    Write-Output 'NO_READY_TASKS'
    return
}

foreach ($task in $ready) {
    $slug = Get-TaskSlug -Title ($(if ($task.task_title) { $task.task_title } elseif ($task.display_name) { $task.display_name } else { $task.title }))
    $shortId = Get-TaskShortId -TaskId $task.id
    $name = "$slug-$shortId"

    Write-Output "DISPATCHING=$($task.id) NAME=$name"

    if ($DryRun) { continue }

    if ([string]::IsNullOrWhiteSpace($task.spec)) {
        Write-Warning "La tarea $($task.id) no tiene spec; se omite"
        continue
    }

    try {
        $worktreeResponse = Invoke-Orca worktree create --repo "id:$repoId" --name $name --base-branch $BaseBranch --setup skip --json
        if (-not $worktreeResponse.ok) {
            $existing = Invoke-Orca worktree show --worktree "name:$name" --json
            if (-not $existing.ok) {
                throw "No se pudo crear ni reutilizar el worktree '$name': $($worktreeResponse.error.message)"
            }
            $worktree = $existing.result.worktree
        }
        else {
            $worktree = (Get-OrcaResult $worktreeResponse).worktree
        }
        $worktreePath = $worktree.path -replace '/', '\'

        & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'setup-worktree.ps1') -Worktree $worktreePath
        if ($LASTEXITCODE -ne 0) { throw "Setup falló para $worktreePath" }

        $taskDir = Join-Path $worktreePath '.orca-task'
        New-Item -ItemType Directory -Force -Path $taskDir | Out-Null
        Set-Content -Path (Join-Path $taskDir 'spec.md') -Value $task.spec -Encoding UTF8
        $task | ConvertTo-Json -Depth 20 | Set-Content -Path (Join-Path $taskDir 'task.json') -Encoding UTF8

        $wrapper = Join-Path $PSScriptRoot 'worker-terminal.ps1'
        $command = "pwsh -NoProfile -File `"$wrapper`" -TaskTitle $name -Agent $WorkerAgent"

        $terminalResponse = Invoke-Orca terminal create --worktree "path:$($worktree.path)" --title "worker:$name" --command $command --json
        $workerHandle = (Get-OrcaResult $terminalResponse).terminal.handle

        $waitResponse = Invoke-Orca terminal wait --terminal $workerHandle --for tui-idle --timeout-ms 180000 --json
        if (-not $waitResponse.ok) {
            throw "El worker no llegó a tui-idle: $($waitResponse.error.message)"
        }

        # Dispatch de bajo nivel: Orca devuelve el preamble completo (incluye la spec).
        # Lo entregamos con terminal send para no depender de la detección de agente.
        $dispatchResponse = Invoke-Orca orchestration dispatch --from $coordinator --run $RunId --task $task.id --to $workerHandle --return-preamble --json
        $dispatchResult = Get-OrcaResult $dispatchResponse
        $preamble = $dispatchResult.preamble
        if (-not $preamble) { throw "Orca no devolvió preamble para $($task.id)" }

        $sendResponse = Invoke-Orca terminal send --terminal $workerHandle --text $preamble --enter --json
        if (-not $sendResponse.ok) {
            throw "No se pudo entregar el preamble al worker: $($sendResponse.error.message)"
        }

        $dispatchId = $null
        if ($dispatchResult.PSObject.Properties['dispatch']) { $dispatchId = $dispatchResult.dispatch.id }
        if (-not $dispatchId -and $dispatchResult.PSObject.Properties['dispatch_id']) { $dispatchId = $dispatchResult.dispatch_id }

        $record = [pscustomobject]@{
            runId        = $RunId
            taskId       = $task.id
            taskTitle    = $task.task_title
            dispatchId   = $dispatchId
            workerHandle = $workerHandle
            worktree     = $worktree.path
            branch       = $worktree.branch
            terminal     = "worker:$name"
            createdAt    = (Get-Date).ToString('o')
        }
        $dispatches += $record
        Save-Dispatches -RunId $RunId -Dispatches $dispatches | Out-Null

        Write-Output "DISPATCHED=$($task.id) DISPATCH_ID=$dispatchId WORKER=$workerHandle WORKTREE=$($worktree.path)"
    }
    catch {
        Write-Error "Falló el dispatch de $($task.id): $($_.Exception.Message)"
    }
}

Write-Output "DISPATCH_SUMMARY=$($dispatches.Count)"

