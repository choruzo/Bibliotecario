# Prueba A/B del harness del worker (Fase 1 del PRD docs/08-prd-harnessing.md).
#
# Ejecuta la MISMA tarea de calibracion dos veces en paralelo:
#   probe-a  -> harness del repo tal cual (base)
#   probe-b  -> harness con la variante materializada (archivos completos que
#               sobrescriben el arbol editable; lo omitido se hereda)
# Decide con el verificador existente (check.ps1 + review.ps1) y solo adopta la
# variante si hay contraste medible. Nunca integra en la rama base ni hace push.
#
# Uso:
#   harness-probe.ps1 -SpecFile <spec.md> -VariantDir <dir> [-Domain default]
#                     [-BaseBranch main] [-ProbeLabel <nombre>] [-MaxProbeMinutes 25]
#                     [-Keep] [-DryRun]
#
# La variante la propone el agente harness-editor en .orca-run/harness-variants/<nombre>/
# (o un humano). Debe pasar Test-HarnessVariant antes de gastar workers.

param(
    [Parameter(Mandatory)][string]$SpecFile,
    [Parameter(Mandatory)][string]$VariantDir,
    [string]$Domain = 'default',
    [string]$BaseBranch = 'main',
    [string]$ProbeLabel,
    [int]$MaxProbeMinutes = 25,
    [switch]$Keep,
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$script:probeRun = $null
$script:probeCoord = $null
$script:probeTasks = @()
$script:probeRecords = @()

function New-ProbeTask {
    param([Parameter(Mandatory)][string]$Coordinator, [Parameter(Mandatory)][string]$RunId, [Parameter(Mandatory)][string]$Side, [Parameter(Mandatory)][string]$Spec)

    $response = Invoke-Orca orchestration task-create --from $Coordinator --run $RunId --task-title "probe-$Side-$script:probeLabel" --spec $Spec --json
    $result = Get-OrcaResult $response
    if ($result.PSObject.Properties['taskId'] -and $result.taskId) { return [string]$result.taskId }
    if ($result.PSObject.Properties['task'] -and $result.task.id) { return [string]$result.task.id }
    throw "task-create no devolvio taskId (lado $Side)"
}

function Get-ProbeSideResult {
    # Ejecuta el verificador existente sobre el worktree del probe y devuelve
    # el registro comparable: @{ finished; verdict; defects; files; reviewFile }
    param($Record, [Parameter(Mandatory)][string]$Side)

    $empty = @{ finished = $false; verdict = 'CAMBIOS'; defects = @(); files = @(); reviewFile = '' }
    if (-not $Record -or -not $Record.worktree -or -not (Test-Path $Record.worktree)) { return $empty }

    $reviewOutput = (& pwsh -NoProfile -File (Join-Path $PSScriptRoot 'review.ps1') -RunId $script:probeRun -TaskId $Record.taskId -Worktree $Record.worktree -BaseBranch $BaseBranch 2>&1 | Out-String)
    Write-Host ("[probe] review lado {0}: {1}" -f $Side, ([regex]::Match($reviewOutput, 'REVIEW=(ACEPTADO|CAMBIOS)').Groups[1].Value))

    $verdict = [regex]::Match($reviewOutput, 'REVIEW=(ACEPTADO|CAMBIOS)').Groups[1].Value
    $reviewFile = [regex]::Match($reviewOutput, 'REVIEW_FILE=(\S+)').Groups[1].Value.Trim()
    $review = $null
    if ($reviewFile -and (Test-Path $reviewFile)) {
        try { $review = Get-Content $reviewFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $review = $null }
    }
    $defects = @()
    $files = @()
    if ($review) {
        if ($review.PSObject.Properties['defects']) { $defects = @($review.defects | Where-Object { $_ }) }
        if ($review.PSObject.Properties['files']) { $files = @($review.files | Where-Object { $_ }) }
    }
    if (-not $verdict) { return $empty }
    return @{
        finished   = $true
        verdict    = $verdict
        defects    = $defects
        files      = $files
        reviewFile = $reviewFile
    }
}

# --- Flujo principal ---------------------------------------------------------

$repoRoot = Get-RepoRoot
if (-not (Test-Path $SpecFile)) { throw "No existe la spec: $SpecFile" }
$specText = Get-Content $SpecFile -Raw -Encoding UTF8
$script:variantDirResolved = (Resolve-Path $VariantDir).Path
$baseLabel = if ($ProbeLabel) { $ProbeLabel } else { Get-TaskSlug -Title ([IO.Path]::GetFileNameWithoutExtension($SpecFile)) }
$script:probeLabel = "$baseLabel-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Fail fast: la variante se valida ANTES de gastar un solo worker.
$issues = @(Test-HarnessVariant -VariantDir $script:variantDirResolved)
if ($issues.Count) {
    foreach ($issue in $issues) { Write-Host "VARIANT_INVALID $issue" }
    throw 'La variante no pasa la validacion del kit.'
}
Write-Host "[probe] variante valida: $($script:variantDirResolved)"

if ($DryRun) {
    Write-Output 'PROBE_DRYRUN_OK'
    return
}

try {
    $newRun = (& pwsh -NoProfile -File (Join-Path $PSScriptRoot 'new-run.ps1') -Objective "ORCA HARNESS PROBE $($script:probeLabel)" | Out-String)
    $script:probeRun = [regex]::Match($newRun, '(?m)^RUN=(run_[A-Za-z0-9_]+)').Groups[1].Value
    $script:probeCoord = [regex]::Match($newRun, '(?m)^COORDINATOR=(term_[A-Za-z0-9-]+)').Groups[1].Value
    if (-not $script:probeRun -or -not $script:probeCoord) { throw "new-run no devolvio RUN/COORDINATOR:`n$newRun" }
    Write-Audit -RunId $script:probeRun -Actor 'probe' -Action 'probe-start' -Reason "variante=$($script:variantDirResolved) base=$BaseBranch label=$($script:probeLabel)"

    $taskA = New-ProbeTask -Coordinator $script:probeCoord -RunId $script:probeRun -Side 'a' -Spec $specText
    $taskB = New-ProbeTask -Coordinator $script:probeCoord -RunId $script:probeRun -Side 'b' -Spec $specText
    $script:probeTasks = @($taskA, $taskB)
    Write-Host "[probe] tareas: base=$taskA variante=$taskB"

    $variantDirForHook = $script:variantDirResolved
    $prepare = {
        param([string]$WorktreePath, [string]$TaskTitle)
        if ($TaskTitle -match '^probe-b-') {
            $applied = Copy-HarnessVariant -VariantDir $variantDirForHook -Worktree $WorktreePath
            Write-Host "[probe] variante materializada en ${WorktreePath}: $($applied -join ', ')"
        }
    }
    $dispatchLog = (& (Join-Path $PSScriptRoot 'dispatch.ps1') -RunId $script:probeRun -MaxWorkers 2 -BaseBranch $BaseBranch -PrepareWorktree $prepare | Out-String)
    Write-Host $dispatchLog.TrimEnd()

    $script:probeRecords = @(Read-Dispatches -RunId $script:probeRun)
    $recA = @($script:probeRecords | Where-Object { $_.taskTitle -match '^probe-a-' }) | Select-Object -Last 1
    $recB = @($script:probeRecords | Where-Object { $_.taskTitle -match '^probe-b-' }) | Select-Object -Last 1
    if (-not $recA -or -not $recB) { throw 'No se despacharon las dos variantes; abortando el probe.' }

    # Espera a que ambas tareas alcancen estado terminal o se acabe el presupuesto.
    $deadline = (Get-Date).AddMinutes($MaxProbeMinutes)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 15
        $response = Invoke-OrcaTaskList -RunId $script:probeRun -Coordinator $script:probeCoord
        $tasks = @((Get-OrcaResult $response).tasks | Where-Object { $_ -and $_.id })
        $done = @($tasks | Where-Object { $_.status -in @('completed', 'failed', 'blocked', 'cancelled') })
        Write-Host ("[probe] esperando: {0}/{1} terminadas" -f $done.Count, $tasks.Count)
        if ($done.Count -ge 2) { break }
    }
    if ((Get-Date) -ge $deadline) {
        Write-Host '[probe] presupuesto agotado; marcando incompletas'
        foreach ($rec in @($recA, $recB)) {
            if ($rec.dispatchId) { try { Invoke-Orca orchestration worker-stop --dispatch $rec.dispatchId --json | Out-Null } catch { } }
        }
    }

    $baseResult = Get-ProbeSideResult -Record $recA -Side 'a'
    $variantResult = Get-ProbeSideResult -Record $recB -Side 'b'
    $decision = Test-HarnessContrast -Base $baseResult -Variant $variantResult

    $harnessDir = Join-Path (Join-Path (Join-Path (Get-LibraryRoot) $Domain) 'harnesses') $script:probeLabel
    [void](Write-ProbeResultDir -Dir $harnessDir -BaseResult $baseResult -VariantResult $variantResult -Decision $decision -SpecText $specText -RunId $script:probeRun -Label $script:probeLabel -VariantDir $script:variantDirResolved -BaseBranch $BaseBranch -TaskBase $taskA -TaskVariant $taskB -RepoRoot $repoRoot)

    Write-Audit -RunId $script:probeRun -Actor 'probe' -Action 'probe-result' -TaskId $taskA -DispatchId $recA.dispatchId -Reason "decision=$($decision.winner) motivo=$($decision.reason)"
    Write-Audit -RunId $script:probeRun -Actor 'probe' -Action 'probe-result' -TaskId $taskB -DispatchId $recB.dispatchId -Reason "decision=$($decision.winner) motivo=$($decision.reason)"
    Write-Audit -RunId $script:probeRun -Actor 'probe' -Action 'lesson-candidate' -TaskId $taskA -DispatchId $recA.dispatchId -Reason "probe $($script:probeLabel) decision=$($decision.winner)"

    Write-Output "PROBE_LABEL=$($script:probeLabel)"
    Write-Output "PROBE_RUN=$script:probeRun"
    Write-Output "PROBE_BASE verdict=$($baseResult.verdict) defects=$(@($baseResult.defects).Count) finished=$([bool]$baseResult.finished)"
    Write-Output "PROBE_VARIANT verdict=$($variantResult.verdict) defects=$(@($variantResult.defects).Count) finished=$([bool]$variantResult.finished)"
    Write-Output "PROBE_WINNER=$($decision.winner)"
    Write-Output "PROBE_REASON=$($decision.reason)"
    Write-Output "PROBE_ADOPTED=$(if ($decision.winner -eq 'variant') { (Join-Path $harnessDir 'variant') } else { '-' })"
    Write-Output "PROBE_DIR=$harnessDir"
}
finally {
    foreach ($rec in @($script:probeRecords)) {
        if ($rec.dispatchId) { try { Invoke-Orca orchestration worker-stop --dispatch $rec.dispatchId --json | Out-Null } catch { } }
        if ($rec.workerHandle) { [void](Close-OrcaTerminal -Handle $rec.workerHandle -Quiet) }
    }
    if ($script:probeRun -and $script:probeCoord) {
        try {
            $response = Invoke-OrcaTaskList -RunId $script:probeRun -Coordinator $script:probeCoord
            $tasks = @((Get-OrcaResult $response).tasks | Where-Object { $_ -and $_.id })
            foreach ($task in $tasks) {
                if ($task.status -in @('ready', 'dispatched')) {
                    Invoke-Orca orchestration task-update --from $script:probeCoord --run $script:probeRun --id $task.id --status failed --result 'probe cleanup' --json | Out-Null
                }
            }
        }
        catch { }
    }
    if (-not $Keep) {
        foreach ($rec in @($script:probeRecords)) {
            if ($rec.worktree) { try { & git -C $repoRoot worktree remove --force $rec.worktree 2>$null } catch { } }
            if ($rec.branch) {
                $branchName = ([string]$rec.branch) -replace '^refs/heads/', ''
                if ($branchName) { try { & git -C $repoRoot branch -D $branchName 2>$null } catch { } }
            }
        }
    }
    if ($script:probeCoord) { [void](Close-OrcaTerminal -Handle $script:probeCoord -Quiet) }
}
