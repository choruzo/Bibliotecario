# Prueba determinista de integrate.ps1 sin Orca:
# - parte -Branches "a,b";
# - no pide -Full si el Run no toca apps/web;
# - lo pide si toca apps/web;
# - avanza la rama base por fast-forward.

param(
    [switch]$Keep,
    [switch]$Full
)

$ErrorActionPreference = 'Stop'
$integrate = Join-Path (Split-Path $PSScriptRoot -Parent) 'integrate.ps1'
if (-not (Test-Path $integrate)) { throw "No se encontro $integrate" }

function Assert-True {
    param($Condition, [string]$Message)
    if (-not $Condition) { throw "ASSERT: $Message" }
}

$root = Join-Path $env:TEMP ("orca-integrate-test-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $root | Out-Null

try {
    & git -C $root init -b main | Out-Null
    & git -C $root config user.email 'test@example.invalid' | Out-Null
    & git -C $root config user.name 'Orca Test' | Out-Null

    Set-Content -Path (Join-Path $root 'README.md') -Value 'base' -Encoding UTF8
    & git -C $root add README.md
    & git -C $root commit -m 'base' | Out-Null

    & git -C $root checkout -b docs | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $root 'docs') | Out-Null
    Set-Content -Path (Join-Path $root 'docs\a.md') -Value 'docs' -Encoding UTF8
    & git -C $root add docs/a.md
    & git -C $root commit -m 'docs' | Out-Null
    & git -C $root checkout main | Out-Null

    & git -C $root checkout -b web | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $root 'apps\web') | Out-Null
    Set-Content -Path (Join-Path $root 'apps\web\page.tsx') -Value 'export default 1;' -Encoding UTF8
    & git -C $root add apps/web/page.tsx
    & git -C $root commit -m 'web' | Out-Null
    & git -C $root checkout main | Out-Null

    $planDocs = (& pwsh -NoProfile -File $integrate -RepoRoot $root -RunId run_test -Branches docs -PlanOnly | Out-String)
    Assert-True ($planDocs -match 'BRANCH_COUNT=1') "plan docs no tiene 1 rama:`n$planDocs"
    Assert-True ($planDocs -match 'FULL_NEEDED=False') "docs no debe pedir Full:`n$planDocs"

    $planWeb = (& pwsh -NoProfile -File $integrate -RepoRoot $root -RunId run_test -Branches web -PlanOnly | Out-String)
    Assert-True ($planWeb -match 'FULL_NEEDED=True') "web debe pedir Full:`n$planWeb"

    $planBoth = (& pwsh -NoProfile -File $integrate -RepoRoot $root -RunId run_test -Branches 'docs,web' -PlanOnly | Out-String)
    Assert-True ($planBoth -match 'BRANCH_COUNT=2') "a,b debe partirse en 2:`n$planBoth"

    if ($Full) {
        $integration = (& pwsh -NoProfile -File $integrate -RepoRoot $root -RunId run_test -Branches docs -BaseBranch main 2>&1 | Out-String)
        Assert-True ($LASTEXITCODE -eq 0) "integrate fallo:`n$integration"
        Assert-True ($integration -match 'INTEGRATION_SHA=([0-9a-f]+)') "falta INTEGRATION_SHA:`n$integration"
        Assert-True ($integration -match 'BASE_ADVANCED=main') "falta BASE_ADVANCED:`n$integration"

        $sha = [regex]::Match($integration, 'INTEGRATION_SHA=([0-9a-f]+)').Groups[1].Value
        $mainSha = (& git -C $root rev-parse main).Trim()
        Assert-True ($sha -eq $mainSha) "main no avanzo al SHA de integracion (main=$mainSha sha=$sha)"
    }

    Write-Output 'INTEGRATE_PLAN_OK'
}
finally {
    if (-not $Keep) {
        $integrationPath = Join-Path $root '.orca-run\integration\run_test'
        try { & git -C $root worktree remove --force $integrationPath 2>$null } catch { }
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
}
