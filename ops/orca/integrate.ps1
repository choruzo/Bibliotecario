param(
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string[]]$Branches,
    [string]$BaseBranch = 'main',
    [string]$RepoRoot,
    [string[]]$FullOnChange = @('apps/web'),
    [switch]$ForceFull,
    [switch]$PlanOnly,
    [switch]$NoSetup,
    [switch]$NoAdvanceBase
)

$ErrorActionPreference = 'Stop'

if (-not $RepoRoot) {
    $RepoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
}
$repoRoot = (Resolve-Path $RepoRoot).Path.TrimEnd('\')
$integrationRoot = Join-Path $repoRoot ".orca-run\integration"
$integrationPath = Join-Path $integrationRoot $RunId
$integrationBranch = "orca/integration/$RunId"

# `pwsh -File script.ps1 -Branches a,b` entrega una sola cadena. Partimos por
# comas dentro del script para que el uso documentado funcione.
$branchList = @(
    $Branches |
        ForEach-Object { $_ -split ',' } |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ } |
        ForEach-Object { $_ -replace '^refs/heads/', '' } |
        Select-Object -Unique
)
if ($branchList.Count -eq 0) { throw "No hay ramas que integrar" }

function Test-RegisteredWorktree {
    param([string]$Path)

    $target = (Resolve-Path $Path).Path.TrimEnd('\')
    $lines = @(& git -C $repoRoot worktree list --porcelain)
    foreach ($line in $lines) {
        if ($line -like 'worktree *') {
            $candidate = ($line.Substring(9) -replace '/', '\').TrimEnd('\')
            if ($candidate -ieq $target) { return $true }
        }
    }
    return $false
}

function Get-TouchedPaths {
    param(
        [string]$Range,
        [string]$Worktree = $repoRoot
    )

    $diffArgs = @('diff', '--name-only', $Range, '--') + @($FullOnChange)
    return @(& git -C $Worktree @diffArgs 2>$null | Where-Object { $_ })
}

if ($PlanOnly) {
    $touched = @()
    foreach ($branch in $branchList) {
        $touched += @(Get-TouchedPaths -Range "$BaseBranch...$branch")
    }
    $fullNeeded = [bool]($ForceFull -or (@($touched | Where-Object { $_ }).Count -gt 0))

    Write-Output "REPO=$repoRoot"
    Write-Output "RUN=$RunId"
    Write-Output "BASE_BRANCH=$BaseBranch"
    Write-Output "BRANCHES=$($branchList -join ',')"
    Write-Output "BRANCH_COUNT=$($branchList.Count)"
    Write-Output "FULL_ON_CHANGE=$($FullOnChange -join ',')"
    Write-Output "FULL_NEEDED=$fullNeeded"
    Write-Output "INTEGRATION_PATH=$integrationPath"
    Write-Output "INTEGRATION_BRANCH=$integrationBranch"
    return
}

New-Item -ItemType Directory -Force -Path $integrationRoot | Out-Null

if (-not (Test-Path $integrationPath)) {
    & git -C $repoRoot worktree add -B $integrationBranch $integrationPath $BaseBranch
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el worktree de integración" }
}
elseif (-not (Test-RegisteredWorktree -Path $integrationPath)) {
    throw "Existe $integrationPath pero no es un worktree registrado. Bórralo o muévelo antes de integrar."
}

# Un intento anterior pudo dejar un merge a medias. Este script no reanuda
# conflictos: el orquestador los manda al worker y vuelve a integrar.
Push-Location $integrationPath
try {
    $mergeHead = (& git rev-parse --verify -q MERGE_HEAD) 2>$null
    if ($mergeHead) {
        & git merge --abort 2>$null
    }

    foreach ($branch in $branchList) {
        Write-Output "MERGING=$branch"
        & git merge --no-ff $branch -m "integrate: $branch"
        if ($LASTEXITCODE -ne 0) {
            & git merge --abort 2>$null
            throw "Conflicto al integrar $branch. Run bloqueado."
        }
    }
}
finally {
    Pop-Location
}

# No enlazamos .venv ni node_modules dentro del worktree de integración:
# un junction fuera del worktree rompe Turbopack y hace peligroso el borrado
# recursivo. setup-worktree.ps1 materializa las dependencias reales (y el
# worktree de integración se reutiliza durante todo el Run).
if (-not $NoSetup) {
    $setupScript = Join-Path $PSScriptRoot 'setup-worktree.ps1'
    if (Test-Path $setupScript) {
        & pwsh -NoProfile -File $setupScript -Worktree $integrationPath
        if ($LASTEXITCODE -ne 0) { throw "El setup del worktree de integración falló" }
    }
    else {
        Write-Warning "No existe setup-worktree.ps1; el worktree de integración puede quedarse sin dependencias."
    }
}

Push-Location $integrationPath
try {
    $touched = @(Get-TouchedPaths -Range "$BaseBranch...HEAD" -Worktree $integrationPath)
    $fullNeeded = [bool]($ForceFull -or $touched.Count -gt 0)

    $checkArgs = @('-NoProfile', '-File', (Join-Path $PSScriptRoot 'check.ps1'), '-Worktree', $integrationPath)
    if ($fullNeeded) {
        Write-Output 'FULL=on'
        $checkArgs += '-Full'
    }
    else {
        Write-Output "FULL_SKIP=sin cambios en $($FullOnChange -join ',')"
    }

    & pwsh @checkArgs
    if ($LASTEXITCODE -ne 0) { throw "Los checks de integración fallaron" }

    $sha = (& git rev-parse HEAD).Trim()
    Write-Output "INTEGRATION_BRANCH=$integrationBranch"
    Write-Output "INTEGRATION_SHA=$sha"
}
finally {
    Pop-Location
}

if ($NoAdvanceBase) {
    Write-Output 'BASE_SKIP=no-advance'
    return
}

$currentBranch = (& git -C $repoRoot rev-parse --abbrev-ref HEAD).Trim()
if ($currentBranch -ne $BaseBranch) {
    Write-Output "BASE_SKIP=checkout en $currentBranch, no en $BaseBranch"
    return
}

& git -C $repoRoot merge --ff-only $integrationBranch
if ($LASTEXITCODE -ne 0) {
    Write-Warning "No se pudo avanzar $BaseBranch por fast-forward. Ejecuta a mano: git merge --ff-only $integrationBranch"
    Write-Output "BASE_SKIP=ff-failed"
    return
}

$baseSha = (& git -C $repoRoot rev-parse HEAD).Trim()
Write-Output "BASE_ADVANCED=$BaseBranch"
Write-Output "BASE_SHA=$baseSha"
