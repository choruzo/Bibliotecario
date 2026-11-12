param(
    [Parameter(Mandatory)][string]$RunId,
    [ValidateRange(1, 5)][int]$MaxWorkers = 5,
    [string]$BaseBranch = 'main',
    [string]$WorkerAgent = 'worker',
    # Hook opcional para materializar variantes del harness ANTES de crear la
    # sesion del worker (pruebas A/B, ver harness-probe.ps1). Recibe
    # -WorktreePath y -TaskTitle; no altera el comportamiento si no se pasa.
    [scriptblock]$PrepareWorktree,
    # Variante candidata para tareas marcadas con [HARNESS-PROBE]: la tarea se
    # despacha dos veces (base + hermana clonada con la variante materializada)
    # y el bucle arbitra con el verificador al integrar (RF1.1).
    [string]$VariantDir,
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$coordinator = Get-Coordinator -RunId $RunId
Bind-Run -RunId $RunId -Coordinator $coordinator
Write-Host "[dispatch] VariantDir=[$VariantDir]"
$repoId = Get-RepoId
$stateDir = Get-StateDir
$dispatches = @(Read-Dispatches -RunId $RunId)

$taskResponse = Invoke-OrcaTaskList -Coordinator $coordinator -RunId $RunId
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

function Invoke-WorkerDispatch {
    # Despacha una tarea y devuelve su registro (o $null). $Side 'b' anade el
    # sufijo -var al nombre y materializa $VariantDir en el worktree.
    param($Task, [string]$Side, [string]$PairId, [string]$VariantDir)

    $slug = Get-TaskSlug -Title $Task.task_title
    $shortId = Get-TaskShortId -TaskId $Task.id
    $name = "$slug-$shortId$(if ($Side -eq 'b') { '-var' } else { '' })"

    # Progreso con Write-Host: los Write-Output dentro de una funcion que
    # devuelve un objeto contaminan el retorno (bug ya visto en TERMINAL_RECREATED).
    Write-Host "DISPATCHING=$($Task.id) NAME=$name SIDE=$Side"

    if ($DryRun) { return $null }

    if ([string]::IsNullOrWhiteSpace($Task.spec)) {
        Write-Warning "La tarea $($Task.id) no tiene spec; se omite"
        return $null
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

        # Capturado: dentro de una funcion que devuelve el record, la salida del
        # setup contaminaria el retorno (visto: DISPATCH_SUMMARY=2 con 1 tarea).
        $setupOut = (& pwsh -NoProfile -File (Join-Path $PSScriptRoot 'setup-worktree.ps1') -Worktree $worktreePath 2>&1 | Out-String)
        if ($setupOut.Trim()) { Write-Host $setupOut.TrimEnd() }
        if ($LASTEXITCODE -ne 0) { throw "Setup falló para $worktreePath" }

        if ($PrepareWorktree) {
            & $PrepareWorktree -WorktreePath $worktreePath -TaskTitle $Task.task_title
        }
        if ($Side -eq 'b' -and $VariantDir) {
            $applied = @(Copy-HarnessVariant -VariantDir $VariantDir -Worktree $worktreePath)
            Write-Host "VARIANT_APPLIED=$($applied -join ',')"
        }

        $taskDir = Join-Path $worktreePath '.orca-task'
        New-Item -ItemType Directory -Force -Path $taskDir | Out-Null
        Set-Content -Path (Join-Path $taskDir 'spec.md') -Value $Task.spec -Encoding UTF8
        $Task | ConvertTo-Json -Depth 20 | Set-Content -Path (Join-Path $taskDir 'task.json') -Encoding UTF8

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
        $dispatchResponse = Invoke-Orca orchestration dispatch --from $coordinator --run $RunId --task $Task.id --to $workerHandle --return-preamble --json
        $dispatchResult = Get-OrcaResult $dispatchResponse
        $preamble = $dispatchResult.preamble
        if (-not $preamble) { throw "Orca no devolvió preamble para $($Task.id)" }

        # Puntero a la libreria de lecciones (PRD docs/08-prd-harnessing.md).
        $libraryPointer = Get-LibraryPointer
        if ($libraryPointer) { $preamble += $libraryPointer }

        $sendResponse = Invoke-Orca terminal send --terminal $workerHandle --text $preamble --enter --json
        if (-not $sendResponse.ok) {
            throw "No se pudo entregar el preamble al worker: $($sendResponse.error.message)"
        }

        $dispatchId = $null
        if ($dispatchResult.PSObject.Properties['dispatch']) { $dispatchId = $dispatchResult.dispatch.id }
        if (-not $dispatchId -and $dispatchResult.PSObject.Properties['dispatch_id']) { $dispatchId = $dispatchResult.dispatch_id }

        $record = [pscustomobject]@{
            runId        = $RunId
            taskId       = $Task.id
            taskTitle    = $Task.task_title
            dispatchId   = $dispatchId
            workerHandle = $workerHandle
            worktree     = $worktree.path
            branch       = $worktree.branch
            terminal     = "worker:$name"
            status       = 'dispatched'
            baseBranch   = $BaseBranch
            createdAt    = (Get-Date).ToString('o')
            side         = $Side
            pairId       = $PairId
            variantDir   = $VariantDir
        }
        Write-Host "DISPATCHED=$($Task.id) DISPATCH_ID=$dispatchId WORKER=$workerHandle WORKTREE=$($worktree.path)"
        return $record
    }
    catch {
        Write-Error "Falló el dispatch de $($Task.id): $($_.Exception.Message)"
        return $null
    }
}

foreach ($task in $ready) {
    # Pares [HARNESS-PROBE]: la tarea se despacha dos veces (base + hermana
    # clonada con la variante) y el bucle arbitra al integrar (RF1.1).
    $pairId = $null
    $variantDir = $null
    $siblingTask = $null
    if (Test-HarnessProbeSpec -Spec $task.spec) {
        if ($VariantDir -and (Test-Path $VariantDir)) {
            $pairId = "pair-$($task.id)"
            $variantDir = (Resolve-Path $VariantDir).Path
            Write-Output "PROBE_PAIR=$($task.id) VARIANT=$variantDir"
            if (-not $DryRun) {
                $cloneResponse = Invoke-Orca orchestration task-create --from $coordinator --run $RunId --task-title "$($task.task_title)-var" --spec $task.spec --json
                $cloneResult = Get-OrcaResult $cloneResponse
                $siblingTaskId = $null
                if ($cloneResult.PSObject.Properties['taskId'] -and $cloneResult.taskId) { $siblingTaskId = [string]$cloneResult.taskId }
                elseif ($cloneResult.PSObject.Properties['task'] -and $cloneResult.task.id) { $siblingTaskId = [string]$cloneResult.task.id }
                if (-not $siblingTaskId) { throw "task-create no devolvio taskId para la hermana de $($task.id)" }
                $siblingTask = [pscustomobject]@{ id = $siblingTaskId; task_title = "$($task.task_title)-var"; spec = $task.spec }
            }
        }
        else {
            Write-Warning "Tarea probe $($task.id) sin -VariantDir; despacho normal"
        }
    }

    $record = Invoke-WorkerDispatch -Task $task -Side 'a' -PairId $pairId -VariantDir $variantDir
    if ($record) { $dispatches += $record }

    if ($siblingTask) {
        $recordB = Invoke-WorkerDispatch -Task $siblingTask -Side 'b' -PairId $pairId -VariantDir $variantDir
        if ($recordB) { $dispatches += $recordB }
    }
    if ($record -or $recordB) {
        Save-Dispatches -RunId $RunId -Dispatches $dispatches | Out-Null
    }
}

Write-Output "DISPATCH_SUMMARY=$($dispatches.Count)"
