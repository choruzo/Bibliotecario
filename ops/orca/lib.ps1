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
