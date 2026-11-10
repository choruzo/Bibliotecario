param(
    [Parameter(Mandatory)][string]$Worktree
)

$ErrorActionPreference = 'Stop'

$worktreePath = (Resolve-Path $Worktree).Path
$mainRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel).Trim()

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Action
    )
    Write-Output "SETUP_STEP=$Name"
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "Fallo el setup: $Name (exit $LASTEXITCODE)" }
}

function Get-Tool {
    param([string]$Name)
    $command = Get-Command "$Name.cmd" -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command $Name -ErrorAction SilentlyContinue }
    return $command
}

# Los directorios compartidos de orca.yaml (.venv, apps/web/node_modules) aparecen
# como enlaces creados por Orca. Correr npm ci o uv venv sobre un enlace borra el
# contenido del checkout principal: hay que detectarlo antes de tocar nada.
function Test-SharedLink {
    param([string]$Path)
    $item = Get-Item $Path -Force -ErrorAction SilentlyContinue
    return [bool]($item -and $item.LinkType)
}

function Wait-ForPath {
    param([string]$Path, [string]$Child, [int]$Seconds = 30)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path (Join-Path $Path $Child)) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return (Test-Path (Join-Path $Path $Child))
}

# Archivos locales ignorados que el worktree necesita.
foreach ($relative in @('.env', '.env.local', 'apps\web\.env.local')) {
    $source = Join-Path $mainRoot $relative
    $destination = Join-Path $worktreePath $relative
    if ((Test-Path $source) -and -not (Test-Path $destination)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
        Copy-Item $source $destination -Force
    }
}

$webPath = Join-Path $worktreePath 'apps\web'
$nodeModules = Join-Path $webPath 'node_modules'
if (Test-Path (Join-Path $webPath 'package.json')) {
    if (-not (Test-Path $nodeModules)) { [void](Wait-ForPath -Path $webPath -Child 'node_modules') }
    if (-not (Test-Path (Join-Path $nodeModules '.bin'))) {
        if ((Test-Path $nodeModules) -and (Test-SharedLink $nodeModules)) {
            throw "node_modules es el enlace compartido y no tiene .bin; no ejecuto npm ci (borraria el del checkout principal)."
        }
        if ((Test-Path $nodeModules) -and @(Get-ChildItem $nodeModules -Force).Count -gt 0) {
            throw "node_modules existe sin .bin y con contenido; revisalo a mano antes de seguir."
        }
        $npm = Get-Tool 'npm'
        if (-not $npm) { throw "No se encontro npm" }
        Invoke-Step 'npm-ci' { & $npm.Source --prefix $webPath ci --prefer-offline --no-audit --no-fund }
    }
}

$venvRoot = Join-Path $worktreePath '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) { [void](Wait-ForPath -Path $venvRoot -Child 'Scripts\python.exe') }

$needsPython = -not (Test-Path $venvPython)
if (-not $needsPython) {
    & $venvPython -c "import pytest" 2>$null
    if ($LASTEXITCODE -ne 0) { $needsPython = $true }
}

if ($needsPython) {
    if ((Test-Path $venvRoot) -and (Test-SharedLink $venvRoot)) {
        throw ".venv es el enlace compartido y no tiene pytest; no lo recreo (romperia el checkout principal)."
    }

    $uv = Get-Tool 'uv'
    if (-not $uv) {
        throw "Falta .venv con pytest y no se encontro uv. Crea el entorno o comparte .venv desde el checkout principal."
    }

    Push-Location $worktreePath
    try {
        if (-not (Test-Path $venvPython)) {
            Invoke-Step 'uv-venv' { & $uv.Source venv --python 3.12 .venv }
        }
        Invoke-Step 'uv-pip-install-lock' { & $uv.Source pip install --python $venvPython -r 'apps/api/requirements.lock' }
        Invoke-Step 'uv-pip-install-editable' { & $uv.Source pip install --python $venvPython --no-deps -e 'apps/api' }
        Invoke-Step 'uv-pip-install-test' { & $uv.Source pip install --python $venvPython pytest }
        Invoke-Step 'uv-pip-install-h0' { & $uv.Source pip install --python $venvPython -r 'requirements-h0.txt' }
    }
    finally {
        Pop-Location
    }
}

$taskDir = Join-Path $worktreePath '.orca-task'
New-Item -ItemType Directory -Force -Path $taskDir | Out-Null

Write-Output "SETUP_OK=$worktreePath"
