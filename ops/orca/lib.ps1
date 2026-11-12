# Helpers compartidos de la capa de orquestación (opción A: Orca + OpenCode).
# Requiere PowerShell 7 y el runtime de Orca corriendo.

$ErrorActionPreference = 'Stop'

function Get-RepoRoot {
    $root = & git -C $PSScriptRoot rev-parse --show-toplevel 2>$null
    if (-not $root) { throw "No se encontró un repositorio git desde $PSScriptRoot" }
    return $root.Trim()
}

function Get-OrcaExe {
    $candidates = @(
        (Get-Command orca -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
        (Get-Command orca-ide -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
        (Join-Path $env:APPDATA 'orca\cli\bin\orca.exe')
        (Join-Path $env:LOCALAPPDATA 'Programs\orca\resources\bin\orca.exe')
    ) | Where-Object { $_ -and (Test-Path $_) }

    if (-not $candidates) {
        throw "No se encontró el CLI de Orca. Instálalo o añade resources/bin al PATH."
    }
    return $candidates[0]
}

function Invoke-Orca {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$OrcaArgs)

    $exe = Get-OrcaExe
    $raw = & $exe @OrcaArgs 2>$null
    $code = $LASTEXITCODE
    $text = ($raw | Out-String).Trim()

    if (-not $text) {
        throw "Orca no devolvió salida (exit $code): $($OrcaArgs -join ' ')"
    }

    try {
        return $text | ConvertFrom-Json -Depth 40
    }
    catch {
        throw "Orca devolvió algo que no es JSON (exit $code):`n$text"
    }
}

function Get-OrcaResult {
    param([Parameter(Mandatory)]$Response)

    if (-not $Response.PSObject.Properties['ok'] -or -not $Response.ok) {
        $message = if ($Response.PSObject.Properties['error']) { $Response.error.message } else { 'error desconocido' }
        throw "Orca rechazó la operación: $message"
    }
    return $Response.result
}

function Get-OrcaRun {
    param([Parameter(Mandatory)]$Response)

    $result = Get-OrcaResult $Response
    $run = @($result.run | Where-Object { $_ }) | Select-Object -First 1
    if ($run) { return $run }

    # La CLI empaquetada con la app devuelve result.runId/objective en run-show.
    if ($result.PSObject.Properties['runId'] -and $result.runId) {
        return [pscustomobject]@{
            id                 = [string]$result.runId
            objective          = if ($result.PSObject.Properties['objective']) { [string]$result.objective } else { '' }
            coordinator_handle = if ($result.PSObject.Properties['coordinator_handle']) { $result.coordinator_handle } else { $null }
            created_at         = if ($result.PSObject.Properties['created_at']) { $result.created_at } else { $null }
            updated_at         = if ($result.PSObject.Properties['updated_at']) { $result.updated_at } else { $null }
        }
    }
    return $null
}

function Invoke-OrcaTaskList {
    param(
        [Parameter(Mandatory)][string]$RunId,
        [string]$Coordinator
    )

    $base = @('orchestration', 'task-list', '--run', $RunId, '--json')
    if ($Coordinator) { $base += @('--from', $Coordinator) }

    # La CLI nueva devuelve una vista concisa salvo con --full; la antigua no
    # acepta --full pero ya devuelve el registro completo. Sondeamos una vez
    # por proceso y reutilizamos la capacidad.
    if ($null -ne $script:OrcaTaskListFull) {
        if ($script:OrcaTaskListFull) { return Invoke-Orca @($base + '--full') }
        return Invoke-Orca @base
    }

    $response = Invoke-Orca @($base + '--full')
    if ($response.PSObject.Properties['ok'] -and $response.ok) {
        $script:OrcaTaskListFull = $true
        return $response
    }
    if ($response.PSObject.Properties['error']) {
        $message = [string]$response.error.message
        if ($message -match 'Unknown flag --full') {
            $script:OrcaTaskListFull = $false
            return Invoke-Orca @base
        }
    }
    return $response
}

function Invoke-OrcaRunList {
    $base = @('orchestration', 'run-list', '--json')
    if ($null -ne $script:OrcaRunListFull) {
        if ($script:OrcaRunListFull) { return Invoke-Orca @($base + '--full') }
        return Invoke-Orca @base
    }

    $response = Invoke-Orca @($base + '--full')
    if ($response.PSObject.Properties['ok'] -and $response.ok) {
        $script:OrcaRunListFull = $true
        return $response
    }
    if ($response.PSObject.Properties['error']) {
        $message = [string]$response.error.message
        if ($message -match 'Unknown flag --full') {
            $script:OrcaRunListFull = $false
            return Invoke-Orca @base
        }
    }
    return $response
}

function Get-StateDir {
    $dir = Join-Path (Get-RepoRoot) '.orca-run'
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    return $dir
}

function Get-RepoId {
    $repoRoot = (Get-RepoRoot) -replace '\\', '/'
    $response = Invoke-Orca repo list --json
    $result = Get-OrcaResult $response
    $repo = @($result.repos) | Where-Object { ($_.path -replace '\\', '/') -eq $repoRoot } | Select-Object -First 1

    if (-not $repo) {
        $added = Invoke-Orca repo add --path (Get-RepoRoot) --json
        $repo = (Get-OrcaResult $added).repo
    }
    return $repo.id
}

function Get-CoordinatorFile {
    param([string]$RunId)

    $stateDir = Get-StateDir
    if ($RunId) { return (Join-Path $stateDir "coordinator-$RunId.json") }
    return (Join-Path $stateDir 'coordinator.json')
}

function Save-Coordinator {
    param(
        [Parameter(Mandatory)][string]$Handle,
        [string]$Worktree,
        [string]$RunId
    )

    $file = Get-CoordinatorFile -RunId $RunId
    @{
        handle    = $Handle
        worktree  = $Worktree
        runId     = $RunId
        createdAt = (Get-Date).ToString('o')
    } | ConvertTo-Json | Set-Content $file -Encoding UTF8
}

function New-OrcaCoordinatorTerminal {
    param(
        [string]$Title = 'Orca Coordinator',
        [string]$RepoRoot
    )

    if (-not $RepoRoot) { $RepoRoot = Get-RepoRoot }
    $repoPath = $RepoRoot -replace '\\', '/'
    $created = Invoke-Orca terminal create --worktree "path:$repoPath" --title $Title --command 'pwsh -NoLogo -NoProfile' --json
    $terminal = (Get-OrcaResult $created).terminal
    return $terminal.handle
}

function Get-Coordinator {
    param(
        [switch]$Recreate,
        [string]$RunId
    )

    $file = Get-CoordinatorFile -RunId $RunId

    if (-not $Recreate -and (Test-Path $file)) {
        try {
            $saved = Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json
            $show = Invoke-Orca terminal show --terminal $saved.handle --json
            if ($show.ok -and $show.result.terminal.connected -eq $true) {
                return $saved.handle
            }
        }
        catch { }
    }

    $repoRoot = Get-RepoRoot
    $title = if ($RunId) { "Orca Coordinator $RunId" } else { 'Orca Coordinator' }
    $handle = New-OrcaCoordinatorTerminal -Title $title -RepoRoot $repoRoot
    Save-Coordinator -Handle $handle -Worktree $repoRoot -RunId $RunId
    return $handle
}

function Close-OrcaTerminal {
    param(
        [string]$Handle,
        [switch]$Quiet
    )

    if (-not $Handle) { return $true }

    $closed = $null
    try { $closed = Invoke-Orca terminal close --terminal $Handle --json } catch { $closed = $null }
    if ($closed -and $closed.ok) { return $true }

    # `terminal close` puede devolver ok:false con ptyStopVerdict unverifiable
    # después de cerrar de verdad. La prueba es el estado del terminal, no `ok`.
    for ($attempt = 0; $attempt -lt 2; $attempt++) {
        Start-Sleep -Milliseconds (300 + 500 * $attempt)
        $show = $null
        try { $show = Invoke-Orca terminal show --terminal $Handle --json } catch { $show = $null }
        $terminal = if ($show -and $show.ok) { $show.result.terminal } else { $null }
        if ($terminal -and ($terminal.orphaned -eq $true -or $terminal.connected -eq $false)) {
            if (-not $Quiet) { Write-Output "TERMINAL_CLOSED_UNVERIFIED=$Handle" }
            return $true
        }
        if ($attempt -eq 0) {
            try { [void](Invoke-Orca terminal close --terminal $Handle --json) } catch { }
        }
    }

    if (-not $Quiet) {
        $reason = if ($closed -and $closed.error) { $closed.error.message } else { 'sin respuesta de Orca' }
        Write-Warning "No se pudo cerrar el terminal ${Handle}: $reason"
    }
    return $false
}

function Write-Audit {
    param(
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$Actor,
        [Parameter(Mandatory)][string]$Action,
        [string]$TaskId,
        [string]$DispatchId,
        [string]$Terminal,
        [string]$Reason
    )

    $file = Join-Path (Get-StateDir) "audit-$RunId.jsonl"
    $entry = [ordered]@{
        at         = (Get-Date).ToUniversalTime().ToString('o')
        actor      = $Actor
        action     = $Action
        taskId     = $TaskId
        dispatchId = $DispatchId
        terminal   = $Terminal
        reason     = $Reason
    }
    ($entry | ConvertTo-Json -Compress) | Add-Content -Path $file -Encoding UTF8
}

function Get-OrcaWorkerShow {
    param([string]$DispatchId)

    if (-not $DispatchId) { return $null }
    try {
        $show = Invoke-Orca orchestration worker-show --dispatch $DispatchId --json
        if ($show.ok) { return $show.result }
    }
    catch { }
    return $null
}

function Test-BranchAncestor {
    param(
        [Parameter(Mandatory)][string]$Worktree,
        [Parameter(Mandatory)][string]$Branch,
        [Parameter(Mandatory)][string]$Ancestor
    )

    if (-not $Worktree -or -not (Test-Path $Worktree)) { return $false }
    if (-not $Branch -or -not $Ancestor -or $Branch -eq $Ancestor) { return $false }

    & git -C $Worktree rev-parse --verify -q $Branch *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    & git -C $Worktree rev-parse --verify -q $Ancestor *> $null
    if ($LASTEXITCODE -ne 0) { return $false }

    & git -C $Worktree merge-base --is-ancestor $Branch $Ancestor 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Test-TaskDeliverable {
    param([string]$Status)

    if (-not $Status) { return $false }
    return ($Status -notin @('blocked', 'failed', 'cancelled', 'ready', 'pending'))
}

function Get-LatestWriteUtc {
    param([string]$Worktree)

    if (-not $Worktree -or -not (Test-Path $Worktree)) { return $null }
    $latest = $null
    try {
        $status = @(& git -C $Worktree status --porcelain --untracked-files=all 2>$null)
        foreach ($line in $status) {
            if (-not $line -or $line.Length -lt 4) { continue }
            $relative = $line.Substring(3).Trim()
            if ($relative -match ' -> ') { $relative = ($relative -split ' -> ')[-1] }
            $path = Join-Path $Worktree $relative
            if (-not (Test-Path $path)) { continue }
            $item = Get-Item $path -Force -ErrorAction SilentlyContinue
            if ($item -and (-not $latest -or $item.LastWriteTimeUtc -gt $latest)) { $latest = $item.LastWriteTimeUtc }
        }
    }
    catch { }
    return $latest
}

function Bind-Run {
    param(
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$Coordinator
    )

    $current = Invoke-Orca orchestration run-current --from $Coordinator --json
    $currentRun = if ($current.ok) { Get-OrcaRun $current } else { $null }
    if ($currentRun -and $currentRun.id -eq $RunId) { return }

    $used = Invoke-Orca orchestration run-use --id $RunId --from $Coordinator --json
    if (-not $used.ok) {
        throw "No se pudo vincular el coordinador al Run ${RunId}: $($used.error.message)"
    }
}

function Get-TaskSlug {
    param([Parameter(Mandatory)][string]$Title)

    $slug = $Title.ToLowerInvariant() -replace '[^a-z0-9]+', '-' -replace '^-+|-+$', ''
    if ($slug.Length -gt 40) { $slug = $slug.Substring(0, 40).TrimEnd('-') }
    if (-not $slug) { $slug = 'task' }
    return $slug
}

function Get-TaskShortId {
    param([Parameter(Mandatory)][string]$TaskId)
    $bare = $TaskId -replace '^task_', ''
    if ($bare.Length -gt 6) { return $bare.Substring(0, 6) }
    return $bare
}

function Save-Dispatches {
    param(
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][array]$Dispatches
    )
    $file = Join-Path (Get-StateDir) "dispatches-$RunId.json"
    $Dispatches | ConvertTo-Json -Depth 20 | Set-Content $file -Encoding UTF8
    return $file
}

function Read-Dispatches {
    param([Parameter(Mandatory)][string]$RunId)
    $file = Join-Path (Get-StateDir) "dispatches-$RunId.json"
    if (-not (Test-Path $file)) { return @() }
    return @(Get-Content $file -Raw | ConvertFrom-Json)
}

# --- Libreria de lecciones (Fase 0, PRD docs/08-prd-harnessing.md) ---

function Get-LibraryRoot {
    # Vive dentro del repo: se commitea y viaja con los worktrees sin infra extra.
    return (Join-Path (Get-RepoRoot) 'ops\orca\library')
}

function Get-LibraryPointer {
    # Puntero corto para el preamble del worker. $null si no hay libreria:
    # un texto que no senala nada solo consume contexto del worker.
    $index = Join-Path (Get-LibraryRoot) 'INDEX.md'
    if (-not (Test-Path $index)) { return $null }
    return @"

=== LIBRERIA DE LECCIONES ===
Este repo guarda lecciones de runs anteriores en ops/orca/library/.
Lee ops/orca/library/INDEX.md y abre solo las entradas relevantes a tu tarea.
Cada leccion lleva evidencia citada; si tu tarea la contradice, comentalo en report.md.
"@
}

# --- Harness probing (Fase 1, PRD docs/08-prd-harnessing.md) ---

function Test-HarnessVariant {
    # Una variante es un directorio con archivos COMPLETOS del arbol editable del
    # worker: lo que incluye sobrescribe, lo que omite se hereda del checkout.
    # Solo se permiten superficies orientadas al worker y las reglas duras del
    # kit (denegar git commit / task-update) deben sobrevivir a la edicion.
    param([Parameter(Mandatory)][string]$VariantDir)

    $issues = @()
    if (-not (Test-Path $VariantDir)) { return @('la variante no existe') }
    $allowed = @(
        '^\.opencode/agents/worker\.md$',
        '^\.opencode/skills/[^/]+/SKILL\.md$',
        '^\.opencode/skills/[^/]+/scripts/[^/]+$',
        '^AGENTS\.md$'
    )
    $variantRoot = (Resolve-Path $VariantDir).Path
    # RATIONALE.md en la raiz es metadato de la propuesta (contrato del agente
    # harness-editor), no superficie del harness: se ignora al validar y nunca
    # se materializa.
    $files = @(Get-ChildItem $VariantDir -Recurse -File | Where-Object { -not ($_.Name -eq 'RATIONALE.md' -and $_.DirectoryName -eq $variantRoot) } | ForEach-Object { $_.FullName.Substring($VariantDir.Length + 1) -replace '\\', '/' })
    if (-not $files.Count) { return @('la variante esta vacia') }
    foreach ($rel in $files) {
        $ok = $false
        foreach ($pattern in $allowed) { if ($rel -match $pattern) { $ok = $true; break } }
        if (-not $ok) { $issues += "ruta no editable por una variante: $rel" }
    }
    # Tope de texto always-on: el mismo orden que harness2 aplica a su superficie
    # OpenCode (cada token aqui compite con la salida del worker).
    $alwaysOn = 0
    foreach ($name in @('.opencode/agents/worker.md', 'AGENTS.md')) {
        $path = Join-Path $VariantDir ($name -replace '/', '\')
        if (Test-Path $path) { $alwaysOn += (Get-Content $path -Raw -Encoding UTF8).Length }
    }
    if ($alwaysOn -gt 24000) { $issues += "el texto always-on supera el tope de 24000 chars ($alwaysOn)" }
    $workerPath = Join-Path $VariantDir '.opencode\agents\worker.md'
    if (Test-Path $workerPath) {
        $raw = Get-Content $workerPath -Raw -Encoding UTF8
        if ($raw -notmatch 'git commit \*') { $issues += 'worker.md de la variante pierde la denegacion de git commit' }
        if ($raw -notmatch 'orca orchestration task-update \*') { $issues += 'worker.md de la variante pierde la denegacion de task-update' }
    }
    # RATIONALE.md es metadato no materializable, pero forma parte del contrato
    # del editor: si existe debe tener contenido (un RATIONALE vacio no valida).
    $rationalePath = Join-Path $variantRoot 'RATIONALE.md'
    if (Test-Path $rationalePath) {
        $rationale = (Get-Content $rationalePath -Raw -Encoding UTF8).Trim()
        if (-not $rationale) { $issues += 'RATIONALE.md en la raiz esta vacio' }
    }
    return $issues
}

function Copy-HarnessVariant {
    # Materializa la variante en el worktree: archivo completo sobrescribe,
    # lo ausente se hereda. Devuelve las rutas aplicadas (relativas, con /).
    param([Parameter(Mandatory)][string]$VariantDir, [Parameter(Mandatory)][string]$Worktree)

    $applied = @()
    $skipRoot = (Resolve-Path $VariantDir).Path
    foreach ($file in (Get-ChildItem $VariantDir -Recurse -File | Where-Object { -not ($_.Name -eq 'RATIONALE.md' -and $_.DirectoryName -eq $skipRoot) })) {
        $rel = $file.FullName.Substring($VariantDir.Length + 1)
        $target = Join-Path $Worktree $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
        Copy-Item $file.FullName $target -Force
        $applied += ($rel -replace '\\', '/')
    }
    return $applied
}

function Remove-SharedLinks {
    # Desmonta los enlaces compartidos (.venv, node_modules) de un worktree
    # ANTES de cualquier borrado: atravesar una junction destruye el destino
    # compartido del checkout principal (reproducido y confirmado: un
    # `git worktree remove --force` vacio un .venv de 4325 ficheros a traves
    # de la junction de un worktree). [IO.Directory]::Delete quita el enlace,
    # nunca su destino. Devuelve los enlaces desmontados.
    param([Parameter(Mandatory)][string]$Path)

    $detached = @()
    if (-not (Test-Path $Path)) { return $detached }
    foreach ($link in @(Get-ChildItem $Path -Recurse -Force -Attributes ReparsePoint -ErrorAction SilentlyContinue)) {
        try {
            [IO.Directory]::Delete($link.FullName)
            $detached += $link.FullName
        }
        catch { }
    }
    return $detached
}

# --- In-run harness probing (RF1.1, PRD docs/08-prd-harnessing.md) ---

function Test-HarnessProbeSpec {
    # Las tareas marcadas con el token [HARNESS-PROBE] en su spec se despachan
    # dos veces (base y variante) y el verificador arbitra al integrar.
    param([string]$Spec)

    return ($Spec -and $Spec.Contains('[HARNESS-PROBE]'))
}

function Get-PairSibling {
    # Devuelve el record hermano de una tarea de probe (mismo pairId, lado opuesto).
    param([Parameter(Mandatory)][array]$Records, [Parameter(Mandatory)]$Record)

    if (-not $Record.pairId) { return $null }
    return @($Records | Where-Object { $_.pairId -eq $Record.pairId -and $_.taskId -ne $Record.taskId }) | Select-Object -Last 1
}

function Test-HarnessPairReady {
    # El arbitraje solo procede cuando ambos lados dejan de estar en vuelo.
    param($Record, $Sibling)

    if (-not $Sibling) { return $false }
    $statuses = @([string]$Record.status, [string]$Sibling.status)
    $inFlight = $statuses | Where-Object { $_ -in @('dispatched', 'ready') }
    return (-not $inFlight)
}

function Resolve-HarnessPairWinner {
    # Arbitraje del par con el verificador existente. Lee review.json del
    # worktree de cada lado (ya lo escribio el review) y aplica el mismo
    # contraste que el probe offline. Devuelve @{ winner='base'|'variant'|'none';
    # reason } donde 'none' significa empate -> se integra la base.
    param($Record, $Sibling)

    function Get-SideOutcome {
        param($Rec)
        $outcome = @{ finished = $false; verdict = 'CAMBIOS'; defects = @(); files = @(); evidenceMissing = $null }
        if (-not $Rec -or $Rec.status -notin @('completed', 'integrated', 'failed', 'blocked')) { return $outcome }
        if ($Rec.status -eq 'failed') { return $outcome }
        $reviewFile = if ($Rec.worktree) { Join-Path $Rec.worktree '.orca-task\review.json' } else { $null }
        if ($reviewFile -and (Test-Path $reviewFile)) {
            try {
                $review = Get-Content $reviewFile -Raw -Encoding UTF8 | ConvertFrom-Json
                $outcome.finished = $true
                $outcome.verdict = [string]$review.verdict
                if ($review.PSObject.Properties['defects']) { $outcome.defects = @($review.defects | Where-Object { $_ }) }
                if ($review.PSObject.Properties['files']) { $outcome.files = @($review.files | Where-Object { $_ }) }
            }
            catch { }
        }
        return $outcome
    }

    # side 'a' = base (la tarea original), side 'b' = variante (la hermana clonada).
    $baseSide = if ([string]$Record.side -eq 'b') { $Sibling } else { $Record }
    $variantSide = if ([string]$Record.side -eq 'b') { $Record } else { $Sibling }
    if (-not $baseSide -or -not $variantSide) { return @{ winner = 'none'; reason = 'par incompleto' } }

    $decision = Test-HarnessContrast -Base (Get-SideOutcome $baseSide) -Variant (Get-SideOutcome $variantSide)
    if ($decision.winner -eq 'none') { $decision.winner = 'base'; $decision.reason = "empate: $($decision.reason); se integra la base" }
    return $decision
}

# --- Contraste de trayectorias (P3 del roadmap, PRD 08) ---

function ConvertFrom-SessionTrajectory {
    # Parsea el JSON de mensajes de una sesion OpenCode (GET /api/session/{id}/message)
    # y devuelve estadisticas de trayectoria: mensajes del asistente, llamadas a
    # tools, duracion y tokens. Funcion pura (testable con fixture, sin API).
    # Tolerante a variaciones de esquema entre versiones.
    param([Parameter(Mandatory)][AllowEmptyString()][string]$JsonText)

    $stats = @{ assistantMessages = 0; userMessages = 0; toolCalls = 0; durationSec = $null; tokensOutput = $null; firstCreated = $null; lastCompleted = $null }
    if (-not $JsonText.Trim()) { return $stats }
    try { $payload = $JsonText | ConvertFrom-Json -Depth 40 } catch { return $stats }
    $messages = @()
    if ($payload.PSObject.Properties['data'] -and $payload.data) { $messages = @($payload.data) }
    elseif ($payload -is [array]) { $messages = @($payload) }
    elseif ($payload.PSObject.Properties['type']) {
        # ConvertFrom-Json desenvuelve los arrays de un elemento: mensaje unico.
        $messages = @($payload)
    }

    $minCreated = $null
    $maxCompleted = $null
    foreach ($message in $messages) {
        $type = if ($message.PSObject.Properties['type']) { [string]$message.type } else { '' }
        if ($type -eq 'assistant') {
            $stats.assistantMessages++
            if ($message.PSObject.Properties['content'] -and $message.content) {
                foreach ($part in @($message.content)) {
                    $partType = if ($part.PSObject.Properties['type']) { [string]$part.type } else { '' }
                    if ($partType -in @('tool', 'tool_use')) { $stats.toolCalls++ }
                }
            }
            if ($message.PSObject.Properties['tokens'] -and $message.tokens -and $message.tokens.PSObject.Properties['output']) {
                if ($null -eq $stats.tokensOutput) { $stats.tokensOutput = 0 }
                try { $stats.tokensOutput += [long]$message.tokens.output } catch { }
            }
        }
        elseif ($type -eq 'user') { $stats.userMessages++ }

        if ($message.PSObject.Properties['time'] -and $message.time) {
            $created = $message.time.PSObject.Properties['created'] ? $message.time.created : $null
            $completed = $message.time.PSObject.Properties['completed'] ? $message.time.completed : $null
            if ($created) {
                $minCreated = if ($null -eq $minCreated) { $created } else { [Math]::Min([long]$minCreated, [long]$created) }
            }
            if ($completed) {
                $maxCompleted = if ($null -eq $maxCompleted) { $completed } else { [Math]::Max([long]$maxCompleted, [long]$completed) }
            }
        }
    }
    if ($null -ne $minCreated -and $null -ne $maxCompleted) {
        $stats.firstCreated = $minCreated
        $stats.lastCompleted = $maxCompleted
        try { $stats.durationSec = [Math]::Round(([long]$maxCompleted - [long]$minCreated) / 1000.0, 1) } catch { }
    }
    return $stats
}

function Get-SessionTrajectoryStats {
    # Estadisticas de trayectoria de una sesion real via la API local.
    # $null si la API no responde o la sesion no existe: metrica descriptiva,
    # nunca bloquea.
    param([Parameter(Mandatory)][string]$SessionId)

    try {
        $raw = & opencode api GET "/api/session/$SessionId/message" 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $text = ($raw | Out-String).Trim()
        if (-not $text) { return $null }
        return ConvertFrom-SessionTrajectory -JsonText $text
    }
    catch { return $null }
}

function Measure-EvidenceCoverage {    # Metrica de cobertura de evidencia para probes A/B (RF1.6 refinado): ejecuta
    # un auditorOffline (p. ej. el evidence_audit.py de la variante) contra el
    # report de un lado y cuenta los needles MISSING. Es un instrumento neutro:
    # se aplica IGUAL a base y variante. Devuelve el numero de MISSING, o $null
    # si no hay audit/python/report (la metrica es opcional, nunca bloquea).
    param(
        [Parameter(Mandatory)][string]$AuditScript,
        [Parameter(Mandatory)][string]$SpecPath,
        [Parameter(Mandatory)][string]$ReportPath,
        [Parameter(Mandatory)][string]$Python
    )

    if (-not (Test-Path $AuditScript) -or -not (Test-Path $ReportPath)) { return $null }
    try {
        $raw = & $Python $AuditScript --spec $SpecPath --report $ReportPath 2>$null
        if ($LASTEXITCODE -notin @(0, 1)) { return $null }
        return @($raw | Where-Object { $_ -match '^MISSING\b' }).Count
    }
    catch { return $null }
}

function Test-HarnessContrast {
    # Decide si hay contraste medible entre los dos probes de una prueba A/B.
    # Solo hay adopcion con diferencia medible (RF1.6): veredicto del review,
    # gate de checks o numero de defectos. $Base y $Variant:
    # @{ finished = bool; verdict = 'ACEPTADO'|'CAMBIOS'; defects = @() }
    param(
        [Parameter(Mandatory)][hashtable]$Base,
        [Parameter(Mandatory)][hashtable]$Variant
    )

    if (-not $Base.finished -and -not $Variant.finished) { return @{ winner = 'none'; reason = 'ambas incompletas' } }
    if (-not $Base.finished -and $Variant.finished -and $Variant.verdict -eq 'ACEPTADO') { return @{ winner = 'variant'; reason = 'base incompleta y variante aceptada' } }
    if (-not $Variant.finished -and $Base.finished -and $Base.verdict -eq 'ACEPTADO') { return @{ winner = 'base'; reason = 'variante incompleta y base aceptada' } }
    if ($Base.verdict -ne $Variant.verdict) {
        if ($Variant.verdict -eq 'ACEPTADO') { return @{ winner = 'variant'; reason = 'variante aceptada y base con cambios' } }
        return @{ winner = 'base'; reason = 'base aceptada y variante con cambios' }
    }
    if ($Base.verdict -eq 'ACEPTADO') {
        # Desempate por cobertura de evidencia (ambos lados medidos con el mismo
        # auditorOffline). Solo si la diferencia existe: veredictos iguales y
        # evidencia distinta es contraste medible.
        $bm = $Base.evidenceMissing
        $vm = $Variant.evidenceMissing
        if ($null -ne $bm -and $null -ne $vm -and $bm -ne $vm) {
            if ($vm -lt $bm) { return @{ winner = 'variant'; reason = "menos evidencia faltante ($vm vs $bm MISSING)" } }
            return @{ winner = 'base'; reason = "menos evidencia faltante ($bm vs $vm MISSING)" }
        }
        return @{ winner = 'none'; reason = 'sin contraste medible' }
    }
    $baseDefects = @($Base.defects).Count
    $variantDefects = @($Variant.defects).Count
    if ($variantDefects -lt $baseDefects) { return @{ winner = 'variant'; reason = "menos defectos ($variantDefects vs $baseDefects)" } }
    if ($baseDefects -lt $variantDefects) { return @{ winner = 'base'; reason = "menos defectos ($baseDefects vs $variantDefects)" } }
    return @{ winner = 'none'; reason = 'sin contraste medible' }
}

function Write-ProbeResultDir {
    # Compone la evidencia del probe en la libreria: RESULT.md siempre y, si la
    # variante gano, el arbol adoptado + el diff de propuesta para adopcion humana.
    # Puro (sin estado de sesion) para poder testearlo sin Orca.
    param(
        [Parameter(Mandatory)][string]$Dir,
        [Parameter(Mandatory)][hashtable]$BaseResult,
        [Parameter(Mandatory)][hashtable]$VariantResult,
        [Parameter(Mandatory)][hashtable]$Decision,
        [Parameter(Mandatory)][string]$SpecText,
        [Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string]$VariantDir,
        [Parameter(Mandatory)][string]$BaseBranch,
        [Parameter(Mandatory)][string]$TaskBase,
        [Parameter(Mandatory)][string]$TaskVariant,
        [Parameter(Mandatory)][string]$RepoRoot,
        [string]$Note = '',
        [string]$MetricStatus = 'not_run',
        [string]$MetricReason = ''
    )

    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
        $baseTraj = if ($BaseResult.trajectory) { "assistants=$($BaseResult.trajectory.assistantMessages) tools=$($BaseResult.trajectory.toolCalls) dur=$($BaseResult.trajectory.durationSec)s tokens=$($BaseResult.trajectory.tokensOutput)" } else { 'sin sesion' }
        $variantTraj = if ($VariantResult.trajectory) { "assistants=$($VariantResult.trajectory.assistantMessages) tools=$($VariantResult.trajectory.toolCalls) dur=$($VariantResult.trajectory.durationSec)s tokens=$($VariantResult.trajectory.tokensOutput)" } else { 'sin sesion' }
    $lines = @(
        '# Probe de harness: ' + $Label,
        '',
        "- Run: ``$RunId``",
        "- Rama base: ``$BaseBranch``",
        "- Variante: ``$VariantDir``",
        "- Tareas: base ``$TaskBase`` / variante ``$TaskVariant``",
        "- Decision: **$($Decision.winner)** - $($Decision.reason)",
        "- Nota: $(if ($Note) { $Note } else { '-' })",
        '',
        ('- ``side=base`` delivered={0} started_at={1} ended_at={2}' -f ([bool]$BaseResult.finished), $BaseResult.startedAt, $BaseResult.endedAt),
        ('- ``side=variante`` delivered={0} started_at={1} ended_at={2}' -f ([bool]$VariantResult.finished), $VariantResult.startedAt, $VariantResult.endedAt),
        ("- Trayectoria (descriptiva, no decisiva): base $baseTraj / variante $variantTraj"),
        "- Metrica de evidencia: ``metric_status=$MetricStatus`` ``metric_reason=$MetricReason``",
        '',
        '| Lado | Terminada | Veredicto | Defectos | Archivos | Evidencia |',
        '|---|---|---|---|---|---|',
        ("| base | $([bool]$BaseResult.finished) | $($BaseResult.verdict) | $(@($BaseResult.defects).Count) | $(@($BaseResult.files).Count) ($($BaseResult.filesExclHarness) sin harness) | $(if ($null -eq $BaseResult.evidenceMissing) { 'sin medir' } else { "MISSING=$($BaseResult.evidenceMissing)" }) |"),
        ("| variante | $([bool]$VariantResult.finished) | $($VariantResult.verdict) | $(@($VariantResult.defects).Count) | $(@($VariantResult.files).Count) ($($VariantResult.filesExclHarness) sin harness) | $(if ($null -eq $VariantResult.evidenceMissing) { 'sin medir' } else { "MISSING=$($VariantResult.evidenceMissing)" }) |"),
        '',
        'La columna Evidencia cuenta needles MISSING segun el auditor offline aplicado igual a los dos lados; `sin medir` = no se pidio auditoria. Los artefactos de cada lado (`report.md`, `review.json`) quedan en `side-base/` y `side-variant/` junto a este fichero.',
        '',
        '## Spec de calibracion',
        '',
        $SpecText.Trim()
    )
    Set-Content -Path (Join-Path $Dir 'RESULT.md') -Value (($lines -join "`r`n") + "`r`n") -Encoding UTF8

    if ($Decision.winner -eq 'variant') {
        $adopted = Join-Path $Dir 'variant'
        New-Item -ItemType Directory -Force -Path $adopted | Out-Null
        Copy-Item (Join-Path $VariantDir '*') $adopted -Recurse -Force
        $diffParts = @()
        foreach ($file in (Get-ChildItem $adopted -Recurse -File)) {
            $rel = $file.FullName.Substring($adopted.Length + 1) -replace '\\', '/'
            $orig = Join-Path $RepoRoot ($rel -replace '/', '\')
            $diff = ''
            if (Test-Path $orig) {
                $diff = (& git diff --no-index -- $orig $file.FullName 2>$null | Out-String).TrimEnd()
            }
            else {
                # Archivo nuevo en la variante: diff contra un vacio temporal.
                $emptyFile = Join-Path ([IO.Path]::GetTempPath()) "probe-empty-$([guid]::NewGuid().ToString('N'))"
                Set-Content -Path $emptyFile -Value '' -Encoding UTF8
                $diff = (& git diff --no-index -- $emptyFile $file.FullName 2>$null | Out-String).TrimEnd()
                Remove-Item $emptyFile -Force -ErrorAction SilentlyContinue
            }
            if ($diff) {
                $diff = $diff -replace [regex]::Escape($orig), "a/$rel" -replace [regex]::Escape($file.FullName), "b/$rel"
                $diffParts += "### $rel`r`n$diff"
            }
        }
        Set-Content -Path (Join-Path $Dir 'proposal.diff') -Value (($diffParts -join "`r`n`r`n") + "`r`n") -Encoding UTF8
    }
    return $Dir
}

# --- Evidencia de sesion OpenCode (RF2.3, PRD docs/08-prd-harnessing.md) ---

function Get-OpenCodeSessionId {
    # El worker-terminal registra la sesion vigente en .orca-task del worktree.
    # $null si no hay registro: la evidencia de sesion es opcional, nunca bloquea.
    param([Parameter(Mandatory)][string]$Worktree)

    $file = Join-Path $Worktree '.orca-task\opencode-session.json'
    if (-not (Test-Path $file)) { return $null }
    try {
        $record = Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($record.PSObject.Properties['sessionId'] -and $record.sessionId) { return [string]$record.sessionId }
    }
    catch { }
    return $null
}

function Get-SessionActivityUtc {
    # Actividad real de una sesion OpenCode via la API local: fecha UTC del ultimo
    # mensaje. Acepta epoch ms (BD) o ISO (API). $null si la API no responde o la
    # sesion no existe: una senal ausente nunca debe empeorar la decision del watchdog.
    param([Parameter(Mandatory)][string]$SessionId)

    try {
        $raw = & opencode api GET "/api/session/$SessionId/message" 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        $text = ($raw | Out-String).Trim()
        if (-not $text) { return $null }
        $payload = $text | ConvertFrom-Json -Depth 30
        $messages = @()
        if ($payload.PSObject.Properties['data'] -and $payload.data) { $messages = @($payload.data) }
        elseif ($payload -is [array]) { $messages = @($payload) }
        foreach ($message in $messages) {
            $stamp = $null
            if ($message.PSObject.Properties['time'] -and $message.time) {
                if ($message.time.PSObject.Properties['streamed'] -and $message.time.streamed) { $stamp = $message.time.streamed }
                elseif ($message.time.PSObject.Properties['created'] -and $message.time.created) { $stamp = $message.time.created }
            }
            if (-not $stamp) { continue }
            if ($stamp -is [long] -or $stamp -is [int] -or ($stamp -match '^\d{10,}$')) {
                return [DateTimeOffset]::FromUnixTimeMilliseconds([long]$stamp).UtcDateTime
            }
            try { return ([datetimeoffset]::Parse([string]$stamp)).UtcDateTime } catch { }
        }
    }
    catch { }
    return $null
}
