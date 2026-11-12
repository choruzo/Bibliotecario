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
    # Auditoria offline opcional de cobertura de evidencia (RF1.6 refinado):
    # se aplica IGUAL a base y variante contra su report.md. Espera exit 0 (todo
    # capturado) o 1 (faltan needles) y cuenta las lineas 'MISSING'.
    [string]$EvidenceAudit,
    # Import de integridad del entorno (RF2.3 del lider): el probe lo comprueba
    # con el python del repo antes de despachar y despues del cleanup. Si falla
    # antes, aborta con PROBE_VENV_BROKEN sin gastar workers.
    [string]$SanityImport,
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
    # el registro comparable: @{ finished; verdict; defects; files; reviewFile;
    # evidenceMissing }. Preserva report.md y review.json en -ArtifactsDir
    # (trayectoria completa: sin esto, el cleanup destruye la evidencia).
    param(
        $Record,
        [Parameter(Mandatory)][string]$Side,
        [string]$ArtifactsDir,
        [string]$AuditScript,
        [string]$SpecPath,
        [string]$PythonExe
    )

    $empty = @{ finished = $false; verdict = 'CAMBIOS'; defects = @(); files = @(); filesExclHarness = 0; reviewFile = ''; evidenceMissing = $null; trajectory = $null }
    if (-not $Record -or -not $Record.worktree -or -not (Test-Path $Record.worktree)) { return $empty }

    $reviewOutput = (& pwsh -NoProfile -File (Join-Path $PSScriptRoot 'review.ps1') -RunId $script:probeRun -TaskId $Record.taskId -Worktree $Record.worktree -BaseBranch $BaseBranch 2>&1 | Out-String)
    $endedAt = (Get-Date).ToUniversalTime().ToString('o')
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
    # Comparacion de entrega sin el overlay del harness: los ficheros que la
    # variante materializo (.opencode/...) no cuentan como trabajo del worker.
    $filesExclHarness = @($files | Where-Object { $script:harnessOverlay -notcontains $_ }).Count

    # Preservar la evidencia del lado antes de que el cleanup borre el worktree:
    # report.md, review.json y el estado parcial (porcelain + diff) para que un
    # timeout tambien deje rastro auditable.
    $reportPath = Join-Path $Record.worktree 'report.md'
    if ($ArtifactsDir) {
        New-Item -ItemType Directory -Force -Path $ArtifactsDir | Out-Null
        if (Test-Path $reportPath) { Copy-Item $reportPath (Join-Path $ArtifactsDir 'report.md') -Force }
        if ($reviewFile -and (Test-Path $reviewFile)) { Copy-Item $reviewFile (Join-Path $ArtifactsDir 'review.json') -Force }
        try {
            $status = (& git -C $Record.worktree status --porcelain 2>$null | Out-String)
            $diff = (& git -C $Record.worktree diff --stat 2>$null | Out-String)
            Set-Content -Path (Join-Path $ArtifactsDir 'state.txt') -Value ("-- git status --porcelain`r`n" + $status + "`r`n-- git diff --stat`r`n" + $diff) -Encoding UTF8
        }
        catch { }
    }

    # Metrica de cobertura de evidencia: instrumento neutral aplicado igual a los
    # dos lados; parametrizacion explicita para que un fallo no sea silencioso.
    $evidenceMissing = $null
    if ($AuditScript -and $PythonExe -and (Test-Path $reportPath)) {
        $evidenceMissing = Measure-EvidenceCoverage -AuditScript $AuditScript -SpecPath $SpecPath -ReportPath $reportPath -Python $PythonExe
        Write-Host ("[probe] evidencia lado {0}: MISSING={1}" -f $Side, $(if ($null -eq $evidenceMissing) { 'sin medir (auditor fallo)' } else { $evidenceMissing }))
    }
    elseif ($AuditScript) {
        Write-Host "[probe] evidencia lado ${Side}: sin medir (report.md no existe en el worktree)"
    }

    # Trayectoria de la sesion (P3): metrica descriptiva (pasos, tools, duracion),
    # no decisoria. La sesion la registro worker-terminal en .orca-task.
    $trajectory = $null
    $sessionId = Get-OpenCodeSessionId -Worktree $Record.worktree
    if ($sessionId) {
        $trajectory = Get-SessionTrajectoryStats -SessionId $sessionId
        if ($trajectory) {
            Write-Host ("[probe] trayectoria lado {0}: assistants={1} tools={2} dur={3}s" -f $Side, $trajectory.assistantMessages, $trajectory.toolCalls, $trajectory.durationSec)
        }
    }

    if (-not $verdict) { return $empty }
    return @{
        finished         = $true
        verdict          = $verdict
        defects          = $defects
        files            = $files
        filesExclHarness = $filesExclHarness
        reviewFile       = $reviewFile
        evidenceMissing  = $evidenceMissing
        trajectory       = $trajectory
        startedAt        = if ($Record.createdAt) { [string]$Record.createdAt } else { '' }
        endedAt          = $endedAt
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

# Auditoria de evidencia (opcional): fail fast antes de gastar workers.
$script:evidenceAuditPath = $null
if ($EvidenceAudit) {
    $script:evidenceAuditPath = (Resolve-Path $EvidenceAudit -ErrorAction SilentlyContinue).Path
    if (-not $script:evidenceAuditPath -or -not (Test-Path $script:evidenceAuditPath)) { throw "No existe el auditor de evidencia: $EvidenceAudit" }
}
$script:specFileResolved = (Resolve-Path $SpecFile).Path
$script:pythonExe = $null
$venvPython = Join-Path $PSScriptRoot '..\..\.venv\Scripts\python.exe'
if (Test-Path $venvPython) { $script:pythonExe = (Resolve-Path $venvPython).Path }
else {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $script:pythonExe = $cmd.Source }
}
if ($script:evidenceAuditPath -and -not $script:pythonExe) { throw 'Se pidio auditoria de evidencia pero no hay python disponible.' }
if ($script:evidenceAuditPath) { Write-Host "[probe] auditor de evidencia activo: $($script:evidenceAuditPath)" }
# El A/B exige que los dos lados ejecuten la MISMA spec: sellamos su contenido.
Write-Output "PROBE_SPEC_SHA256=$((Get-FileHash $script:specFileResolved -Algorithm SHA256).Hash.ToLower())"

function Test-VenvSanity {
    # Integridad del entorno del repo (parametro -SanityImport del lider):
    # import de una dependencia critica con el python del checkout. $null si no
    # se pidio comprobacion.
    if (-not $SanityImport) { return $null }
    try {
        [void](& $script:pythonExe -c "import $SanityImport" 2>$null)
        return ($LASTEXITCODE -eq 0)
    }
    catch { return $false }
}

try {
    $newRun = (& pwsh -NoProfile -File (Join-Path $PSScriptRoot 'new-run.ps1') -Objective "ORCA HARNESS PROBE $($script:probeLabel)" | Out-String)
    $script:probeRun = [regex]::Match($newRun, '(?m)^RUN=(run_[A-Za-z0-9_]+)').Groups[1].Value
    $script:probeCoord = [regex]::Match($newRun, '(?m)^COORDINATOR=(term_[A-Za-z0-9-]+)').Groups[1].Value
    if (-not $script:probeRun -or -not $script:probeCoord) { throw "new-run no devolvio RUN/COORDINATOR:`n$newRun" }
    Write-Audit -RunId $script:probeRun -Actor 'probe' -Action 'probe-start' -Reason "variante=$($script:variantDirResolved) base=$BaseBranch label=$($script:probeLabel)"

    $script:probeLabels = @()
    if ($SanityImport) {
        Write-Host '[probe] venv sanity (antes del dispatch)...'
        if (-not (Test-VenvSanity)) { throw 'PROBE_VENV_BROKEN: el entorno del checkout principal no pasa la asercion de integridad antes del dispatch.' }
        Write-Host '[probe] venv sanity OK'
    }

    $taskA = New-ProbeTask -Coordinator $script:probeCoord -RunId $script:probeRun -Side 'a' -Spec $specText
    $taskB = New-ProbeTask -Coordinator $script:probeCoord -RunId $script:probeRun -Side 'b' -Spec $specText
    $script:probeTasks = @($taskA, $taskB)
    Write-Host "[probe] tareas: base=$taskA variante=$taskB"

    $variantDirForHook = $script:variantDirResolved
    # Autocomprobacion: enlaza TODOS los parametros de Get-ProbeSideResult antes
    # de gastar workers (el binding de param() falla aqui y no a mitad de probe).
    $precheck = Get-ProbeSideResult -Record $null -Side 'a' -ArtifactsDir $null -AuditScript $script:evidenceAuditPath -SpecPath $script:specFileResolved -PythonExe $script:pythonExe
    if (-not $precheck) { throw 'Get-ProbeSideResult no devuelve el registro vacio de arranque' }
    Write-Output 'BINDING_SELFCHECK_OK'
    Write-Host '[probe] binding de Get-ProbeSideResult verificado'
    $prepare = {
        param([string]$WorktreePath, [string]$TaskTitle)
        if ($TaskTitle -match '^probe-b-') {
            $applied = Copy-HarnessVariant -VariantDir $variantDirForHook -Worktree $WorktreePath
            $script:harnessOverlay = @($applied)
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
    $budgetExhausted = $false
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
        $budgetExhausted = $true
        Write-Host '[probe] presupuesto agotado; marcando incompletas'
        foreach ($rec in @($recA, $recB)) {
            if ($rec.dispatchId) { try { Invoke-Orca orchestration worker-stop --dispatch $rec.dispatchId --json | Out-Null } catch { } }
        }
    }

    # Review en el deadline pase lo que pase: un lado incompleto da CAMBIOS con
    # los defectos del gate como dato; el review nunca vuelve vacio el turno.
    $noteProbe = if ($budgetExhausted) { 'presupuesto agotado; review ejecutado sobre lo entregado' } else { '' }
    $harnessDir = Join-Path (Join-Path (Join-Path (Get-LibraryRoot) $Domain) 'harnesses') $script:probeLabel
    $baseResult = Get-ProbeSideResult -Record $recA -Side 'a' -ArtifactsDir (Join-Path $harnessDir 'side-base') -AuditScript $script:evidenceAuditPath -SpecPath $script:specFileResolved -PythonExe $script:pythonExe
    $variantResult = Get-ProbeSideResult -Record $recB -Side 'b' -ArtifactsDir (Join-Path $harnessDir 'side-variant') -AuditScript $script:evidenceAuditPath -SpecPath $script:specFileResolved -PythonExe $script:pythonExe
    $decision = Test-HarnessContrast -Base $baseResult -Variant $variantResult

    # La metrica no puede fallar en silencio (condicion de archivo del lider):
    # si se pidio auditor y no se ejecuto en vuelo, el resultado es invalido
    # hasta que se recupere offline desde los artefactos.
    $metricStatus = 'not_run'
    $metricReason = 'no se pidio auditoria de evidencia'
    if ($script:evidenceAuditPath) {
        if ($null -ne $baseResult.evidenceMissing -and $null -ne $variantResult.evidenceMissing) {
            $metricStatus = 'in_probe_fired'
            $metricReason = 'auditor ejecutado en vuelo en ambos lados'
        }
        else {
            $metricStatus = 'not_run'
            $metricReason = 'el auditor no se ejecuto en vuelo; recuperable offline desde side-base/ y side-variant/'
            Write-Host '[probe] PROBE_EVIDENCE_METRIC_NOT_RUN'
            $decision = @{ winner = 'invalid'; reason = 'metrica de evidencia pedida pero no ejecutada; resultado invalido hasta medicion offline' }
        }
    }

    [void](Write-ProbeResultDir -Dir $harnessDir -BaseResult $baseResult -VariantResult $variantResult -Decision $decision -SpecText $specText -RunId $script:probeRun -Label $script:probeLabel -VariantDir $script:variantDirResolved -BaseBranch $BaseBranch -TaskBase $taskA -TaskVariant $taskB -RepoRoot $repoRoot -Note $noteProbe -MetricStatus $metricStatus -MetricReason $metricReason)

    Write-Audit -RunId $script:probeRun -Actor 'probe' -Action 'probe-result' -TaskId $taskA -DispatchId $recA.dispatchId -Reason "decision=$($decision.winner) motivo=$($decision.reason)"
    Write-Audit -RunId $script:probeRun -Actor 'probe' -Action 'probe-result' -TaskId $taskB -DispatchId $recB.dispatchId -Reason "decision=$($decision.winner) motivo=$($decision.reason)"
    Write-Audit -RunId $script:probeRun -Actor 'probe' -Action 'lesson-candidate' -TaskId $taskA -DispatchId $recA.dispatchId -Reason "probe $($script:probeLabel) decision=$($decision.winner)"

    Write-Output "PROBE_LABEL=$($script:probeLabel)"
    Write-Output "PROBE_RUN=$script:probeRun"
    Write-Output "PROBE_BASE verdict=$($baseResult.verdict) defects=$(@($baseResult.defects).Count) finished=$([bool]$baseResult.finished) evidence=$(if ($null -eq $baseResult.evidenceMissing) { '-' } else { $baseResult.evidenceMissing })"
    Write-Output "PROBE_VARIANT verdict=$($variantResult.verdict) defects=$(@($variantResult.defects).Count) finished=$([bool]$variantResult.finished) evidence=$(if ($null -eq $variantResult.evidenceMissing) { '-' } else { $variantResult.evidenceMissing })"
    Write-Output "PROBE_WINNER=$($decision.winner)"
    Write-Output "PROBE_REASON=$($decision.reason)"
    Write-Output "PROBE_METRIC_STATUS=$metricStatus"
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
        # La eliminacion del worktree es siempre del kit: cleanup.ps1 sabe
        # desmontar los enlaces compartidos (.venv/node_modules por junction);
        # un git worktree remove --force crudo los atraviesa y destruye el
        # .venv real del checkout principal (leido por las carcasas de hoy).
        foreach ($rec in @($script:probeRecords)) {
            $cleanupArgs = @('-NoProfile', '-File', (Join-Path $PSScriptRoot 'cleanup.ps1'), '-RunId', $script:probeRun, '-TaskId', $rec.taskId, '-RemoveWorktree', '-Force')
            $out = (& pwsh @cleanupArgs 2>&1 | Out-String)
            if ($out -match 'WORKTREE_LOCKED|No se pudo quitar el worktree') {
                Write-Host "[probe] worktree quedo bloqueado (carcasa inofensiva): $($rec.worktree)"
            }
        }
        foreach ($rec in @($script:probeRecords)) {
            if ($rec.branch) {
                $branchName = ([string]$rec.branch) -replace '^refs/heads/', ''
                if ($branchName) { try { & git -C $repoRoot branch -D $branchName 2>$null } catch { } }
            }
        }
    }
    if ($script:probeCoord) { [void](Close-OrcaTerminal -Handle $script:probeCoord -Quiet) }
    if ($SanityImport) {
        # Integridad del entorno principal tras tocar worktrees compartidos.
        Write-Host '[probe] venv sanity (tras cleanup)...'
        if (-not (Test-VenvSanity)) {
            Write-Host '[probe] PROBE_VENV_BROKEN: el entorno del checkout principal quedo danado tras el cleanup'
            Write-Audit -RunId ([string]$script:probeRun) -Actor 'probe' -Action 'venv-broken' -Reason "sanity import $SanityImport fallo tras cleanup"
        }
        else { Write-Host '[probe] venv sanity OK tras cleanup' }
    }
}
