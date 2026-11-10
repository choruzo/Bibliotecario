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
if ((Test-Path (Join-Path $webPath 'package.json')) -and -not (Test-Path (Join-Path $webPath 'node_modules'))) {
    $npm = Get-Tool 'npm'
    if (-not $npm) { throw "No se encontro npm" }
    Invoke-Step 'npm-ci' { & $npm.Source --prefix $webPath ci --prefer-offline --no-audit --no-fund }
}

$venvPython = Join-Path $worktreePath '.venv\Scripts\python.exe'
$needsPython = -not (Test-Path $venvPython)
if (-not $needsPython) {
    & $venvPython -c "import pytest" 2>$null
    if ($LASTEXITCODE -ne 0) { $needsPython = $true }
}

if ($needsPython) {
    $uv = Get-Tool 'uv'
    if (-not $uv) {
        throw "Falta .venv con pytest y no se encontro uv. Crea el entorno o comparte .venv desde el checkout principal."
    }

    Push-Location $worktreePath
    try {
        if (-not (Test-Path $venvPython)) {
            Invoke-Step 'uv-venv' { & $uv.Source venv .venv }
        }
        Invoke-Step 'uv-pip-install' {
            & $uv.Source pip install --python $venvPython `
                -r 'apps/api/requirements.lock' `
                pytest `
                -r 'requirements-h0.txt'
        }
    }
    finally {
        Pop-Location
    }
}

$taskDir = Join-Path $worktreePath '.orca-task'
New-Item -ItemType Directory -Force -Path $taskDir | Out-Null

Write-Output "SETUP_OK=$worktreePath"
