# Grafo en vivo del Run: sirve una pagina web local que dibuja el DAG de tareas
# y se refresca sola consultando el estado de Orca.
#
# Uso:
#   pwsh -NoProfile -File ops/orca/graph.ps1                 # sirve en 127.0.0.1:4599
#   pwsh -NoProfile -File ops/orca/graph.ps1 -RunId run_...  # fija un Run
#   pwsh -NoProfile -File ops/orca/graph.ps1 -Json           # estado una vez
#   pwsh -NoProfile -File ops/orca/graph.ps1 -Open           # abre el navegador
#   pwsh -NoProfile -File ops/orca/graph.ps1 -Once           # instantanea HTML
#   pwsh -NoProfile -File ops/orca/graph.ps1 -Stop           # para el servidor

param(
    [string]$RunId,
    [int]$Port = 4599,
    [int]$RefreshMs = 3500,
    [switch]$Open,
    [switch]$Once,
    [switch]$Json,
    [switch]$Stop,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

$stateDir = Get-StateDir
$pidFile = Join-Path $stateDir "graph-$Port.json"
$script:StartedAt = [datetime]::UtcNow
$script:RunListCache = $null
$script:RunListCacheAt = [datetime]::MinValue
$script:RunCache = @{}
$script:AutoRunId = $null

function Get-DashboardUrl {
    param([int]$P)
    return "http://127.0.0.1:$P/"
}

function Read-GraphMeta {
    if (-not (Test-Path $pidFile)) { return $null }
    try { return (Get-Content $pidFile -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

function Test-DashboardPort {
    param([int]$P)
    $client = $null
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $task = $client.ConnectAsync('127.0.0.1', $P)
        if (-not $task.Wait(300)) { return $false }
        return $client.Connected
    }
    catch { return $false }
    finally { if ($client) { $client.Dispose() } }
}

if ($Stop) {
    $stopped = 0
    $files = @(Get-ChildItem $stateDir -Filter 'graph*.json' -File -ErrorAction SilentlyContinue)
    foreach ($file in $files) {
        try { $meta = Get-Content $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $meta = $null }
        if ($meta -and $meta.pid) {
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($meta.pid)" -ErrorAction SilentlyContinue
            if ($proc -and $proc.CommandLine -match 'graph\.ps1') {
                Stop-Process -Id $meta.pid -Force -ErrorAction SilentlyContinue
                $stopped += 1
            }
        }
        Remove-Item $file.FullName -Force -ErrorAction SilentlyContinue
    }
    if ($stopped -gt 0) { Write-Host "Dashboard detenido ($stopped)." } else { Write-Host "No habia un dashboard en marcha." }
    return
}

$existing = Read-GraphMeta
if (-not $Force -and -not $Once -and -not $Json -and $existing -and [int]$existing.port -eq $Port -and (Test-DashboardPort ([int]$existing.port))) {
    $url = Get-DashboardUrl ([int]$existing.port)
    if ($Open) { Start-Process $url | Out-Null }
    Write-Output "DASHBOARD_URL=$url"
    Write-Output "DASHBOARD=already-running"
    return
}

# ---------- estado ----------

function ConvertTo-IsoString {
    param($Value)
    if ($null -eq $Value -or "$Value" -eq '') { return $null }
    if ($Value -is [datetime]) { return $Value.ToUniversalTime().ToString('o') }
    if ($Value -is [datetimeoffset]) { return $Value.ToUniversalTime().ToString('o') }
    $text = [string]$Value
    if ($text -match '^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?$') {
        return ($text -replace ' ', 'T') + 'Z'
    }
    return $text
}

function ConvertTo-DateTimeOffset {
    param($Value)
    if ($null -eq $Value -or "$Value" -eq '') { return $null }
    if ($Value -is [datetime]) { return [datetimeoffset]$Value }
    if ($Value -is [datetimeoffset]) { return $Value }
    $parsed = [datetimeoffset]::MinValue
    if ([datetimeoffset]::TryParse([string]$Value, [ref]$parsed)) { return $parsed }
    return $null
}

function Get-Runs {
    if ($script:RunListCache -and ((Get-Date) - $script:RunListCacheAt).TotalSeconds -lt 8) {
        return $script:RunListCache
    }
    $response = Invoke-OrcaRunList
    $runs = @((Get-OrcaResult $response).runs)
    foreach ($run in $runs) {
        $run | Add-Member -NotePropertyName createdAt -NotePropertyValue (ConvertTo-IsoString $run.created_at) -Force
        $run | Add-Member -NotePropertyName createdAtValue -NotePropertyValue (ConvertTo-DateTimeOffset $run.created_at) -Force
    }
    $script:RunListCache = $runs
    $script:RunListCacheAt = Get-Date
    return $runs
}

function Get-LocalRunIds {
    $ids = @{}
    $dispatches = Get-ChildItem $stateDir -Filter 'dispatches-run_*.json' -File -ErrorAction SilentlyContinue
    foreach ($file in $dispatches) {
        if ($file.Name -match 'dispatches-(run_[A-Za-z0-9_]+)\.json') { $ids[$Matches[1]] = $file.LastWriteTimeUtc }
    }
    $runsDir = Join-Path $stateDir 'runs'
    foreach ($dir in @(Get-ChildItem $runsDir -Directory -ErrorAction SilentlyContinue)) {
        if ($dir.Name -match '^run_[A-Za-z0-9_]+$') { $ids[$dir.Name] = $dir.LastWriteTimeUtc }
    }
    return $ids
}

function Get-RunInfo {
    param([Parameter(Mandatory)][string]$Id)
    if ($script:RunCache.ContainsKey($Id)) { return $script:RunCache[$Id] }
    $response = Invoke-Orca orchestration run-show --id $Id --json
    $run = Get-OrcaRun $response
    if (-not $run) { throw "Orca no devolvio el Run $Id" }

    if (-not $run.PSObject.Properties['created_at'] -or -not $run.created_at) {
        try {
            $listed = @(Get-Runs | Where-Object { $_.id -eq $Id }) | Select-Object -First 1
            if ($listed) { $run = $listed }
        }
        catch { }
    }

    $run | Add-Member -NotePropertyName createdAt -NotePropertyValue (ConvertTo-IsoString $run.created_at) -Force
    $run | Add-Member -NotePropertyName createdAtValue -NotePropertyValue (ConvertTo-DateTimeOffset $run.created_at) -Force
    $script:RunCache[$Id] = $run
    return $run
}

function Resolve-Run {
    param([string]$Pin)

    if ($Pin) {
        if ($Pin -notmatch '^run_[A-Za-z0-9_]+$') { throw "RunId invalido: $Pin" }
        return Get-RunInfo -Id $Pin
    }

    $runs = @(Get-Runs)
    if ($runs.Count -eq 0) { throw "No hay Runs en Orca." }

    $locals = Get-LocalRunIds
    $timed = @($runs | Where-Object { $_.createdAtValue })
    if ($timed.Count -eq 0) {
        # La CLI empaquetada no devuelve created_at en run-list; el orden de
        # run-list es el mas reciente primero.
        $pick = $runs[0]
        if ($pick -and -not $locals.ContainsKey($pick.id)) { $script:AutoRunId = $pick.id }
        return $pick
    }

    $fresh = [datetimeoffset]$script:StartedAt.AddMinutes(-3)
    $eligible = @($runs | Where-Object {
            $locals.ContainsKey($_.id) -or
            ($script:AutoRunId -and $_.id -eq $script:AutoRunId) -or
            ($_.createdAtValue -and $_.createdAtValue -ge $fresh)
        })

    $pick = @($eligible | Sort-Object createdAtValue -Descending | Select-Object -First 1)
    if ($pick.Count -eq 0) {
        $pick = @($runs | Sort-Object createdAtValue -Descending | Select-Object -First 1)
    }
    if ($pick[0] -and -not $locals.ContainsKey($pick[0].id)) { $script:AutoRunId = $pick[0].id }
    return $pick[0]
}

function Get-TaskDeps {
    param($Task)
    $raw = $Task.deps
    if ($null -eq $raw) { return @() }
    $parsed = $raw
    if ($raw -is [string]) {
        if (-not $raw.Trim()) { return @() }
        try { $parsed = $raw | ConvertFrom-Json } catch { return @() }
    }
    return @($parsed | ForEach-Object { "$_" } | Where-Object { $_ })
}

function Get-Field {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) { return $Object[$Name] }
        return $null
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($property) { return $property.Value }
    return $null
}

function Get-TaskResult {
    param($Task)
    $raw = $Task.result
    if (-not $raw) { return $null }
    if ($raw -is [string]) {
        try { return ($raw | ConvertFrom-Json) } catch { return @{ raw = $raw } }
    }
    return $raw
}

function Get-StageIndex {
    param([array]$Tasks)
    if ($Tasks.Count -eq 0) { return 0 }
    $statuses = @($Tasks | ForEach-Object { $_.status })
    if ($statuses -contains 'dispatched') { return 3 }
    if ($statuses -contains 'changes_requested') { return 4 }
    if ($statuses -contains 'blocked' -or $statuses -contains 'failed' -or $statuses -contains 'escalated') { return 4 }
    if ($statuses -contains 'pending') { return 1 }
    if ($statuses -contains 'ready') { return 2 }
    $done = @($statuses | Where-Object { $_ -in @('completed', 'integrated') }).Count
    if ($done -eq $statuses.Count) {
        $integrated = @($statuses | Where-Object { $_ -eq 'integrated' }).Count
        if ($integrated -eq $statuses.Count) { return 6 }
        return 5
    }
    return 5
}

function Get-DashboardState {
    param([string]$Pin)

    $state = [ordered]@{
        ok              = $true
        error           = $null
        updatedAt       = [datetime]::UtcNow.ToString('o')
        serverStartedAt = $script:StartedAt.ToString('o')
        run             = $null
        stage           = 0
        counts          = [ordered]@{}
        tasks           = @()
        loop            = $null
        question        = $null
    }

    $run = $null
    try {
        $run = Resolve-Run -Pin $Pin
        $state.run = [ordered]@{
            id          = [string]$run.id
            objective   = [string]$run.objective
            createdAt   = if ($run.createdAt) { [string]$run.createdAt } else { ConvertTo-IsoString $run.created_at }
            coordinator = [string]$run.coordinator_handle
        }
        $response = Invoke-OrcaTaskList -RunId $run.id
        $rawTasks = @((Get-OrcaResult $response).tasks)
    }
    catch {
        $state.ok = $false
        $state.error = $_.Exception.Message
        if ($run) {
            $state.run = [ordered]@{
                id          = [string]$run.id
                objective   = [string]$run.objective
                createdAt   = if ($run.createdAt) { [string]$run.createdAt } else { ConvertTo-IsoString $run.created_at }
                coordinator = [string]$run.coordinator_handle
            }
        }
        return $state
    }

    $dispatches = @()
    try { $dispatches = @(Read-Dispatches -RunId $run.id) } catch { $dispatches = @() }
    $dispatchesAt = $null
    $dispatchFile = Join-Path $stateDir "dispatches-$($run.id).json"
    if (Test-Path $dispatchFile) { $dispatchesAt = (Get-Item $dispatchFile).LastWriteTimeUtc.ToString('o') }

    # Estado del bucle, si start-loop.ps1 lo ha lanzado para este Run.
    $loopOut = $null
    $loopFile = Join-Path $stateDir "loop-$($run.id).json"
    if (Test-Path $loopFile) {
        $loopMeta = $null
        try { $loopMeta = Get-Content $loopFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $loopMeta = $null }
        if ($loopMeta) {
            $alive = $false
            if ($loopMeta.pid) { $alive = [bool](Get-Process -Id ([int]$loopMeta.pid) -ErrorAction SilentlyContinue) }
            $loopStatus = [string]$loopMeta.status
            if ($loopStatus -in @('running', 'starting') -and -not $alive) { $loopStatus = 'interrupted' }

            $lastLine = [string]$loopMeta.lastLine
            $loopLog = [string]$loopMeta.logPath
            if (-not $lastLine -and $loopLog -and (Test-Path $loopLog)) {
                $tail = @(Get-Content $loopLog -Tail 8 -ErrorAction SilentlyContinue | Where-Object { $_.Trim() })
                if ($tail.Count -gt 0) { $lastLine = [string]$tail[-1] }
            }

            $loopOut = [ordered]@{
                status          = $loopStatus
                rawStatus       = [string]$loopMeta.status
                alive           = $alive
                pid             = if ($loopMeta.pid) { [int]$loopMeta.pid } else { $null }
                startedAt       = ConvertTo-IsoString $loopMeta.startedAt
                finishedAt      = ConvertTo-IsoString $loopMeta.finishedAt
                exitCode        = $loopMeta.exitCode
                lastLine        = $lastLine
                error           = [string]$loopMeta.error
                logPath         = $loopLog
                maxWorkers      = $loopMeta.maxWorkers
                maxReviewRounds = $loopMeta.maxReviewRounds
                autoRescue      = $loopMeta.autoRescue
                maxRescueRounds = $loopMeta.maxRescueRounds
                autoAnswer      = $loopMeta.autoAnswer
                maxAutoAnswers  = $loopMeta.maxAutoAnswers
                autoAnswers     = $loopMeta.autoAnswers
                baseBranch      = [string]$loopMeta.baseBranch
            }
        }
    }
    $state.loop = $loopOut

    $questionFile = Join-Path $stateDir "question-$($run.id).json"
    if (Test-Path $questionFile) {
        try {
            $questionData = Get-Content $questionFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $message = $questionData.message
            if ($message) {
                $state.question = [ordered]@{
                    id         = [string]$message.id
                    body       = if ($message.body) { [string]$message.body } else { [string]$message.subject }
                    options    = @($message.options)
                    capturedAt = ConvertTo-IsoString $questionData.capturedAt
                }
            }
        }
        catch { }
    }

    $byTask = @{}
    foreach ($dispatch in $dispatches) {
        if ($dispatch.taskId) { $byTask[[string]$dispatch.taskId] = $dispatch }
    }

    $counts = [ordered]@{}
    $tasks = @()
    foreach ($task in $rawTasks) {
        $dispatch = $byTask[[string]$task.id]
        $rawStatus = [string]$task.status
        $status = $rawStatus
        if ($dispatch -and $dispatch.status -in @('integrated', 'changes_requested', 'blocked', 'failed', 'escalated')) {
            $status = [string]$dispatch.status
        }

        $result = Get-TaskResult $task
        $resultOut = $null
        if ($result) {
            $files = @(Get-Field $result 'filesModified' | Where-Object { $_ })
            $resultOut = [ordered]@{
                outcome       = [string](Get-Field $result 'outcome')
                subject       = [string](Get-Field $result 'subject')
                body          = [string](Get-Field $result 'body')
                raw           = [string](Get-Field $result 'raw')
                filesModified = $files
                reportPath    = [string](Get-Field $result 'reportPath')
                completedAt   = if (Get-Field $result 'completedAt') { ConvertTo-IsoString (Get-Field $result 'completedAt') } else { ConvertTo-IsoString $task.completed_at }
            }
        }

        $dispatchOut = $null
        if ($dispatch) {
            $round = 0
            if ($dispatch.PSObject.Properties['reviewRounds'] -and $dispatch.reviewRounds) { $round = [int]$dispatch.reviewRounds }
            $dispatchOut = [ordered]@{
                id             = [string]$dispatch.dispatchId
                status         = [string]$dispatch.status
                round          = $round
                worktree       = [string]$dispatch.worktree
                branch         = [string]$dispatch.branch
                commitSha      = [string]$dispatch.commitSha
                integrationSha = [string]$dispatch.integrationSha
                createdAt      = ConvertTo-IsoString $dispatch.createdAt
            }
        }

        $counts[$status] = 1 + $(if ($counts.Contains($status)) { [int]$counts[$status] } else { 0 })

        $tasks += [ordered]@{
            id          = [string]$task.id
            title       = if ($task.task_title) { [string]$task.task_title } else { [string]$task.display_name }
            status      = $status
            rawStatus   = $rawStatus
            deps        = @(Get-TaskDeps $task)
            createdAt   = ConvertTo-IsoString $task.created_at
            completedAt = ConvertTo-IsoString $task.completed_at
            dispatch    = $dispatchOut
            result      = $resultOut
        }
    }

    $state.counts = $counts
    $state.tasks = $tasks
    $state.stage = Get-StageIndex -Tasks $tasks
    $state.dispatchesAt = $dispatchesAt
    return $state
}

function Get-RunListPayload {
    try {
        $locals = Get-LocalRunIds
        $runs = @(Get-Runs | ForEach-Object {
                [ordered]@{
                    id        = [string]$_.id
                    objective = [string]$_.objective
                    createdAt = if ($_.createdAt) { [string]$_.createdAt } else { ConvertTo-IsoString $_.created_at }
                    local     = $locals.ContainsKey($_.id)
                }
            })
        $current = $null
        try { $current = (Resolve-Run).id } catch { $current = $null }
        return @{ ok = $true; current = $current; runs = $runs }
    }
    catch {
        return @{ ok = $false; error = $_.Exception.Message; runs = @() }
    }
}

# ---------- instantanea estatica ----------

function Write-StaticSnapshot {
    param([string]$Pin)

    $templatePath = Join-Path $PSScriptRoot 'graph.html'
    if (-not (Test-Path $templatePath)) { throw "Falta graph.html junto a graph.ps1." }

    $state = Get-DashboardState -Pin $Pin
    $json = ($state | ConvertTo-Json -Depth 30 -Compress)
    $json = $json -replace '</', '<\/'
    $html = Get-Content $templatePath -Raw -Encoding UTF8
    $html = $html.Replace('__STATIC_MODE__', 'true')
    $html = $html.Replace('__REFRESH_MS__', [string]$RefreshMs)
    $html = $html.Replace('__DEFAULT_RUN__', 'null')
    $html = $html.Replace('__UI_TOKEN__', 'null')
    $html = $html.Replace('/*__BOOTSTRAP__*/null', $json)

    $name = 'sin-run'
    if ($state.run -and $state.run.id) { $name = $state.run.id }
    $out = Join-Path $stateDir "graph-$name.html"
    Set-Content -Path $out -Value $html -Encoding UTF8
    return $out
}

if ($Json) {
    $state = Get-DashboardState -Pin $RunId
    $state | ConvertTo-Json -Depth 30
    return
}

if ($Once) {
    $path = Write-StaticSnapshot -Pin $RunId
    if ($Open) { Start-Process $path | Out-Null }
    Write-Output "GRAPH_HTML=$path"
    return
}

# ---------- servidor HTTP minimo (TcpListener, sin URL ACL) ----------

$listener = $null
try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $listener.Start()
}
catch {
    throw "No se pudo escuchar en 127.0.0.1:$Port. Prueba otro -Port. Detalle: $($_.Exception.Message)"
}

$template = Get-Content (Join-Path $PSScriptRoot 'graph.html') -Raw -Encoding UTF8
$template = $template.Replace('__STATIC_MODE__', 'false').Replace('__REFRESH_MS__', [string]$RefreshMs)
$defaultRunJson = if ($RunId) { $RunId | ConvertTo-Json -Compress } else { 'null' }
$template = $template.Replace('__DEFAULT_RUN__', $defaultRunJson)
$uiToken = [guid]::NewGuid().ToString('N')
$template = $template.Replace('__UI_TOKEN__', ($uiToken | ConvertTo-Json -Compress))

@{
    pid       = $PID
    port      = $Port
    runId     = $RunId
    startedAt = $script:StartedAt.ToString('o')
} | ConvertTo-Json | Set-Content $pidFile -Encoding UTF8

function Send-Http {
    param($Stream, [int]$Code, [string]$ContentType, [string]$Body)

    $reason = switch ($Code) {
        200 { 'OK' }
        400 { 'Bad Request' }
        403 { 'Forbidden' }
        404 { 'Not Found' }
        405 { 'Method Not Allowed' }
        default { 'Internal Server Error' }
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Body)
    $header = "HTTP/1.1 $Code $reason`r`nContent-Type: $ContentType; charset=utf-8`r`nContent-Length: $($bytes.Length)`r`nCache-Control: no-store`r`nConnection: close`r`n`r`n"
    $headerBytes = [System.Text.Encoding]::ASCII.GetBytes($header)
    $Stream.Write($headerBytes, 0, $headerBytes.Length)
    $Stream.Write($bytes, 0, $bytes.Length)
    $Stream.Flush()
}

function Get-QueryParams {
    param([uri]$Uri)
    $params = @{}
    $query = $Uri.Query
    if (-not $query) { return $params }
    foreach ($pair in $query.TrimStart('?').Split('&', [System.StringSplitOptions]::RemoveEmptyEntries)) {
        $parts = $pair.Split('=', 2)
        $name = [uri]::UnescapeDataString($parts[0])
        $value = if ($parts.Count -gt 1) { [uri]::UnescapeDataString($parts[1]) } else { '' }
        $params[$name] = $value
    }
    return $params
}

function Invoke-UiAction {
    param(
        [Parameter(Mandatory)][string]$Action,
        $Payload
    )

    $runId = [string]$Payload.runId
    if ($runId -notmatch '^run_[A-Za-z0-9_]+$') {
        return [ordered]@{ ok = $false; error = 'runId invalido' }
    }

    switch ($Action) {
        'start-loop' {
            $maxWorkers = if ($Payload.maxWorkers) { [int]$Payload.maxWorkers } else { 5 }
            if ($maxWorkers -lt 1) { $maxWorkers = 1 }
            if ($maxWorkers -gt 5) { $maxWorkers = 5 }
            $maxTotal = if ($null -ne $Payload.maxTotalWorkers) { [int]$Payload.maxTotalWorkers } else { 5 }
            $startArgs = @(
                '-NoProfile', '-File', (Join-Path $PSScriptRoot 'start-loop.ps1'),
                '-RunId', $runId, '-MaxWorkers', "$maxWorkers", '-MaxTotalWorkers', "$maxTotal"
            )
            if ([bool]$Payload.autoAnswer) { $startArgs += @('-AutoAnswer', '-MaxAutoAnswers', '3') }
            if ([bool]$Payload.autoRescue) { $startArgs += @('-AutoRescue', '-MaxRescueRounds', '2') }
            if ([bool]$Payload.autoRepair) { $startArgs += @('-AutoRepair', '-MaxRepairRounds', '1') }
            if ([bool]$Payload.autoRecoverStalled) { $startArgs += @('-AutoRecoverStalled', '-MaxStallRecoveries', '1') }
            if ($Payload.maxRunMinutes -and [int]$Payload.maxRunMinutes -gt 0) {
                $startArgs += @('-MaxRunMinutes', "$([int]$Payload.maxRunMinutes)")
            }
            $output = (& pwsh @startArgs 2>&1 | Out-String).Trim()
            return [ordered]@{ ok = ($LASTEXITCODE -eq 0); output = $output }
        }
        'stop-loop' {
            $stopArgs = @('-NoProfile', '-File', (Join-Path $PSScriptRoot 'stop-loop.ps1'), '-RunId', $runId)
            $output = (& pwsh @stopArgs 2>&1 | Out-String).Trim()
            return [ordered]@{ ok = ($LASTEXITCODE -eq 0); output = $output }
        }
        'answer-question' {
            $answer = [string]$Payload.body
            if (-not $answer.Trim()) { return [ordered]@{ ok = $false; error = 'La respuesta esta vacia' } }
            $questionFile = Join-Path $stateDir "question-$runId.json"
            if (-not (Test-Path $questionFile)) { return [ordered]@{ ok = $false; error = 'No hay pregunta pendiente' } }
            try { $question = Get-Content $questionFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return [ordered]@{ ok = $false; error = 'Pregunta ilegible' } }
            $messageId = [string]$question.message.id
            if (-not $messageId) { return [ordered]@{ ok = $false; error = 'La pregunta no tiene message id' } }
            $coordinator = if ($question.coordinator) { [string]$question.coordinator } else { Get-Coordinator }
            $reply = Invoke-Orca orchestration reply --id $messageId --body $answer --run $runId --from $coordinator --json
            if (-not $reply.ok) { return [ordered]@{ ok = $false; error = "Orca rechazo la respuesta: $($reply.error.message)" } }
            try {
                $current = Get-Content $questionFile -Raw -Encoding UTF8 | ConvertFrom-Json
                if ([string]$current.message.id -eq $messageId) { Remove-Item $questionFile -Force }
            }
            catch { }
            return [ordered]@{ ok = $true; output = "Respuesta enviada a $messageId" }
        }
        'retry-task' {
            $taskId = [string]$Payload.taskId
            if ($taskId -notmatch '^task_[A-Za-z0-9_]+$') { return [ordered]@{ ok = $false; error = 'taskId invalido' } }
            try {
                $coordinator = Get-Coordinator
                Bind-Run -RunId $runId -Coordinator $coordinator
                $update = Invoke-Orca orchestration task-update --from $coordinator --run $runId --id $taskId --status ready --result 'ui_retry' --json
            }
            catch {
                return [ordered]@{ ok = $false; error = $_.Exception.Message }
            }
            if (-not $update.ok) { return [ordered]@{ ok = $false; error = "Orca rechazo el reintento: $($update.error.message)" } }
            return [ordered]@{ ok = $true; output = "Tarea $taskId marcada ready" }
        }
        default {
            return [ordered]@{ ok = $false; error = "Accion desconocida: $Action" }
        }
    }
}

$url = Get-DashboardUrl $Port
Write-Host ""
Write-Host "  Orca - grafo de ejecucion" -ForegroundColor Cyan
Write-Host "  $url"
if ($RunId) { Write-Host "  Run fijado: $RunId" } else { Write-Host "  Run: automatico (el mas reciente de este repo o el que se cree ahora)" }
Write-Host "  Ctrl+C para parar.  (-Stop para cerrarlo en segundo plano)" -ForegroundColor DarkGray
Write-Host ""

$stopServer = $false
try {
    while (-not $stopServer) {
        $client = $listener.AcceptTcpClient()
        $stream = $null
        try {
            $stream = $client.GetStream()
            $stream.ReadTimeout = 5000
            $stream.WriteTimeout = 15000

            $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $false, 1024, $true)
            $requestLine = $reader.ReadLine()
            if (-not $requestLine) { continue }

            $headers = @{}
            $contentLength = 0
            while ($true) {
                $line = $reader.ReadLine()
                if ($null -eq $line -or $line -eq '') { break }
                $colon = $line.IndexOf(':')
                if ($colon -gt 0) {
                    $name = $line.Substring(0, $colon).Trim().ToLowerInvariant()
                    $value = $line.Substring($colon + 1).Trim()
                    $headers[$name] = $value
                    if ($name -eq 'content-length') { [void][int]::TryParse($value, [ref]$contentLength) }
                }
            }

            $parts = $requestLine.Split(' ')
            if ($parts.Count -lt 2) { Send-Http -Stream $stream -Code 400 -ContentType 'text/plain' -Body 'Bad request'; continue }
            $method = $parts[0].ToUpperInvariant()
            $rawPath = $parts[1]

            $bodyText = ''
            if ($method -eq 'POST' -and $contentLength -gt 0) {
                $builder = [System.Text.StringBuilder]::new()
                $bytesRead = 0
                while ($bytesRead -lt $contentLength) {
                    $charCode = $reader.Read()
                    if ($charCode -lt 0) { break }
                    [void]$builder.Append([char]$charCode)
                    $bytesRead += [System.Text.Encoding]::UTF8.GetByteCount([string][char]$charCode)
                }
                $bodyText = $builder.ToString()
            }

            if ($method -notin @('GET', 'POST')) {
                Send-Http -Stream $stream -Code 405 -ContentType 'text/plain' -Body 'Method not allowed'
                continue
            }

            $uri = [uri]::new("http://127.0.0.1:$Port$rawPath")
            $query = Get-QueryParams -Uri $uri
            $pin = $null
            if ($query.ContainsKey('run') -and $query['run']) { $pin = [string]$query['run'] }
            if (-not $pin -and $RunId) { $pin = $RunId }
            if ($pin -and $pin -notmatch '^run_[A-Za-z0-9_]+$') {
                Send-Http -Stream $stream -Code 400 -ContentType 'application/json' -Body '{"ok":false,"error":"run invalido"}'
                continue
            }

            if ($method -eq 'POST') {
                if ($uri.AbsolutePath -notmatch '^/api/actions/([a-z-]+)$') {
                    Send-Http -Stream $stream -Code 404 -ContentType 'application/json' -Body '{"ok":false,"error":"accion desconocida"}'
                    continue
                }
                $action = $Matches[1]
                if ($headers['x-orca-token'] -ne $uiToken) {
                    Send-Http -Stream $stream -Code 403 -ContentType 'application/json' -Body '{"ok":false,"error":"token invalido"}'
                    continue
                }
                $payload = $null
                try { $payload = $bodyText | ConvertFrom-Json } catch { $payload = $null }
                if (-not $payload) {
                    Send-Http -Stream $stream -Code 400 -ContentType 'application/json' -Body '{"ok":false,"error":"body invalido"}'
                    continue
                }
                try {
                    $result = Invoke-UiAction -Action $action -Payload $payload
                }
                catch {
                    $result = [ordered]@{ ok = $false; error = $_.Exception.Message }
                }
                $body = $result | ConvertTo-Json -Depth 10
                Send-Http -Stream $stream -Code 200 -ContentType 'application/json' -Body $body
                continue
            }

            switch ($uri.AbsolutePath) {
                '/' {
                    Send-Http -Stream $stream -Code 200 -ContentType 'text/html' -Body $template
                }
                '/index.html' {
                    Send-Http -Stream $stream -Code 200 -ContentType 'text/html' -Body $template
                }
                '/health' {
                    $body = @{ ok = $true; pid = $PID; port = $Port; startedAt = $script:StartedAt.ToString('o') } | ConvertTo-Json -Compress
                    Send-Http -Stream $stream -Code 200 -ContentType 'application/json' -Body $body
                }
                '/api/runs' {
                    $body = Get-RunListPayload | ConvertTo-Json -Depth 20
                    Send-Http -Stream $stream -Code 200 -ContentType 'application/json' -Body $body
                }
                '/api/state' {
                    $state = Get-DashboardState -Pin $pin
                    $body = $state | ConvertTo-Json -Depth 30
                    Send-Http -Stream $stream -Code 200 -ContentType 'application/json' -Body $body
                }
                '/api/log' {
                    if ($headers['x-orca-token'] -ne $uiToken) {
                        Send-Http -Stream $stream -Code 403 -ContentType 'application/json' -Body '{"ok":false,"error":"token invalido"}'
                        continue
                    }
                    if (-not $pin) {
                        Send-Http -Stream $stream -Code 400 -ContentType 'application/json' -Body '{"ok":false,"error":"falta run"}'
                        continue
                    }
                    $lineCount = if ($query.ContainsKey('lines')) { [int]$query['lines'] } else { 200 }
                    if ($lineCount -lt 10) { $lineCount = 10 }
                    if ($lineCount -gt 2000) { $lineCount = 2000 }
                    $logPath = Join-Path $stateDir "loop-$pin.log"
                    if (-not (Test-Path $logPath)) {
                        Send-Http -Stream $stream -Code 404 -ContentType 'text/plain' -Body 'Sin log para este Run'
                        continue
                    }
                    $body = (Get-Content $logPath -Tail $lineCount -Encoding UTF8 | Out-String)
                    Send-Http -Stream $stream -Code 200 -ContentType 'text/plain' -Body $body
                }
                '/quit' {
                    Send-Http -Stream $stream -Code 200 -ContentType 'text/plain' -Body 'bye'
                    $stopServer = $true
                }
                default {
                    Send-Http -Stream $stream -Code 404 -ContentType 'text/plain' -Body 'Not found'
                }
            }
        }
        catch {
            try {
                if ($stream) {
                    Send-Http -Stream $stream -Code 500 -ContentType 'application/json' -Body (@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress)
                }
            }
            catch { }
        }
        finally {
            if ($stream) { $stream.Dispose() }
            $client.Close()
        }
    }
}
finally {
    try { $listener.Stop() } catch { }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host "Dashboard detenido." -ForegroundColor DarkGray
}

