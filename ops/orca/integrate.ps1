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

    & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'check.ps1') -Worktree $integrationPath -Full
    if ($LASTEXITCODE -ne 0) { throw "Los checks de integración fallaron" }

    $sha = (& git rev-parse HEAD).Trim()
    Write-Output "INTEGRATION_BRANCH=$integrationBranch"
    Write-Output "INTEGRATION_SHA=$sha"
}
finally {
    Pop-Location
}
