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

function Get-Coordinator {
    param([switch]$Recreate)

    $stateDir = Get-StateDir
    $file = Join-Path $stateDir 'coordinator.json'

    if (-not $Recreate -and (Test-Path $file)) {
        $saved = Get-Content $file -Raw | ConvertFrom-Json
        $show = Invoke-Orca terminal show --terminal $saved.handle --json
        if ($show.ok -and $show.result.terminal.connected -eq $true) {
            return $saved.handle
        }
    }

    $repoRoot = (Get-RepoRoot) -replace '\\', '/'
    $created = Invoke-Orca terminal create --worktree "path:$repoRoot" --title 'Orca Coordinator' --command 'pwsh -NoLogo -NoProfile' --json
    $terminal = (Get-OrcaResult $created).terminal

    @{
        handle    = $terminal.handle
        worktree  = $repoRoot
        createdAt = (Get-Date).ToString('o')
    } | ConvertTo-Json | Set-Content $file -Encoding UTF8

    return $terminal.handle
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
