param(
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string[]]$Branches,
    [string]$BaseBranch = 'main'
)

$ErrorActionPreference = 'Stop'

$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
$integrationRoot = Join-Path $repoRoot ".orca-run\integration"
$integrationPath = Join-Path $integrationRoot $RunId
$integrationBranch = "orca/integration/$RunId"

New-Item -ItemType Directory -Force -Path $integrationRoot | Out-Null

if (-not (Test-Path $integrationPath)) {
    & git -C $repoRoot worktree add -B $integrationBranch $integrationPath $BaseBranch
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el worktree de integración" }
}

# El gate ejecuta el typecheck/build de la web y necesita node_modules. Los worktrees
# de Orca lo comparten via orca.yaml, pero este lo crea git directamente: enlazamos.
foreach ($shared in @('apps\web\node_modules', '.venv')) {
    $target = Join-Path $integrationPath $shared
    $source = Join-Path $repoRoot $shared
    if (-not (Test-Path $target) -and (Test-Path $source)) {
        $parent = Split-Path $target -Parent
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
        New-Item -ItemType Junction -Path $target -Target $source | Out-Null
    }
}

Push-Location $integrationPath
try {
    foreach ($branch in $Branches) {
        $name = $branch -replace '^refs/heads/', ''
        Write-Output "MERGING=$name"
        & git merge --no-ff $name -m "integrate: $name"
        if ($LASTEXITCODE -ne 0) {
            & git merge --abort 2>$null
            throw "Conflicto al integrar $name. Run bloqueado."
        }
    }

    # `-Full` anade el build de Next/Turbopack, que rechaza un node_modules
    # enlazado fuera del worktree: solo se pide si el diff toca la web.
    $webTouched = @(& git diff --name-only "$BaseBranch...HEAD" -- apps/web 2>$null)
    $checkArgs = @('-NoProfile', '-File', (Join-Path $PSScriptRoot 'check.ps1'), '-Worktree', $integrationPath)
    if ($webTouched.Count -gt 0) { $checkArgs += '-Full' } else { Write-Output 'FULL_SKIP=apps/web sin cambios en el Run' }
    & pwsh @checkArgs
    if ($LASTEXITCODE -ne 0) { throw "Los checks de integración fallaron" }

    $sha = (& git rev-parse HEAD).Trim()
    Write-Output "INTEGRATION_BRANCH=$integrationBranch"
    Write-Output "INTEGRATION_SHA=$sha"

    # El flujo del kit avanza la rama base por fast-forward a la rama de integracion.
    # Solo si el checkout principal esta en esa rama y el avance es limpio.
    $mainBranch = (& git -C $repoRoot rev-parse --abbrev-ref HEAD).Trim()
    if ($mainBranch -eq $BaseBranch) {
        & git -C $repoRoot merge --ff-only $integrationBranch
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "No se pudo avanzar $BaseBranch por fast-forward a $integrationBranch"
        }
        else {
            Write-Output "BASE_ADVANCED=$BaseBranch"
        }
    }
    else {
        Write-Output "BASE_SKIP=checkout en $mainBranch, no en $BaseBranch"
    }
}
finally {
    Pop-Location
}

