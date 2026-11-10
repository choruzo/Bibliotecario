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

function Get-RunRecord {
    # Orca 1.4 devuelve `runId`/`objective` en la raiz de run-show y run-create;
    # el kit antiguo esperaba `result.run` con `id` y `created_at`. Acepta ambos.
    param([Parameter(Mandatory)]$Response)

    $result = Get-OrcaResult $Response
    if ($result.PSObject.Properties['run'] -and $result.run) { return $result.run }

    $id = if ($result.PSObject.Properties['runId']) { $result.runId } else { $result.id }
    if (-not $id) { return $null }

    return [pscustomobject]@{
        id         = $id
        objective  = $result.objective
        created_at = if ($result.PSObject.Properties['createdAt']) { $result.createdAt } else { $null }
    }
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
    if ($current.ok -and (Get-RunRecord $current).id -eq $RunId) { return }

    $used = Invoke-Orca orchestration run-use --id $RunId --from $Coordinator --json
    if (-not $used.ok) {
        throw "No se pudo vincular el coordinador al Run ${RunId}: $($used.error.message)"
    }
}

function Get-TaskSlug {
    param([string]$Title = '')

    if ([string]::IsNullOrWhiteSpace($Title)) { return 'task' }
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

