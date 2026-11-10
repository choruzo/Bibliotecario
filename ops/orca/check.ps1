param(
    [string]$Worktree = '.',
    [switch]$Full,
    [switch]$RequireReport
)

$ErrorActionPreference = 'Stop'

$worktreePath = (Resolve-Path $Worktree).Path
$oldPythonPath = $env:PYTHONPATH

Push-Location $worktreePath
try {
    & git diff --check
    if ($LASTEXITCODE -ne 0) { throw "git diff --check encontro problemas de whitespace/conflictos" }

    if ($RequireReport -and -not (Test-Path (Join-Path $worktreePath 'report.md'))) {
        throw "Falta report.md en el worktree"
    }

    $gitCommon = & git -C $worktreePath rev-parse --git-common-dir 2>$null
    $mainRoot = $null
    if ($LASTEXITCODE -eq 0 -and $gitCommon) {
        $gitCommonPath = if ([IO.Path]::IsPathRooted($gitCommon)) { $gitCommon } else { Join-Path $worktreePath $gitCommon }
        $mainRoot = Split-Path (Resolve-Path $gitCommonPath).Path -Parent
    }

    $candidates = @((Join-Path $worktreePath '.venv\Scripts\python.exe'))
    if ($mainRoot) { $candidates += (Join-Path $mainRoot '.venv\Scripts\python.exe') }
    $python = $null
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { $python = (Resolve-Path $candidate).Path; break }
    }
    if (-not $python) { $python = 'python' }

    $apiPath = Join-Path $worktreePath 'apps\api'
    $webPath = Join-Path $worktreePath 'apps\web'

    # La API se instala en modo editable desde el checkout principal. En un
    # worktree, PYTHONPATH hace que se importe el codigo de ESTE worktree.
    if (Test-Path (Join-Path $apiPath 'pyproject.toml')) {
        $env:PYTHONPATH = if ($oldPythonPath) { "$apiPath;$oldPythonPath" } else { $apiPath }

        & $python -c "import pytest" 2>$null
        if ($LASTEXITCODE -ne 0) { throw "pytest no esta instalado en $python" }

        Push-Location $apiPath
        try {
            & $python -m pytest tests -q
            if ($LASTEXITCODE -ne 0) { throw "pytest de apps/api fallo" }
        }
        finally { Pop-Location }
    }

    # Contratos H0 del repositorio (unittest). Dependen del corpus privado
    # docs/*.md, que no se versiona ni viaja al worktree: en ese caso se omite.
    $rootTests = Join-Path $worktreePath 'tests'
    $docCount = @(Get-ChildItem (Join-Path $worktreePath 'docs') -Filter '*.md' -File -ErrorAction SilentlyContinue).Count
    if ((Test-Path $rootTests) -and $docCount -ge 5) {
        & $python -m unittest discover -s $rootTests -v
        if ($LASTEXITCODE -ne 0) { throw "unittest H0 fallo" }
    }
    elseif (Test-Path $rootTests) {
        Write-Output "H0_SKIP=corpus docs/*.md no presente en el worktree ($docCount archivos)"
    }

    # Web: typecheck siempre; build solo con -Full.
    if (Test-Path (Join-Path $webPath 'package.json')) {
        $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if (-not $npm) { $npm = Get-Command npm -ErrorAction SilentlyContinue }
        if (-not $npm) { throw "npm no esta instalado" }

        & $npm.Source --prefix $webPath run typecheck
        if ($LASTEXITCODE -ne 0) { throw "typecheck de apps/web fallo" }

        if ($Full) {
            $nextEnv = Join-Path $webPath 'next-env.d.ts'
            $nextEnvBefore = if (Test-Path $nextEnv) { Get-Content $nextEnv -Raw } else { $null }
            try {
                & $npm.Source --prefix $webPath run build
                $buildExit = $LASTEXITCODE
            }
            finally {
                if ($null -ne $nextEnvBefore) {
                    Set-Content -Path $nextEnv -Value $nextEnvBefore -NoNewline -Encoding UTF8
                }
            }
            if ($buildExit -ne 0) { throw "build de apps/web fallo" }
        }
    }

    $taskCheck = Join-Path (Join-Path $worktreePath '.orca-task') 'check.ps1'
    if (Test-Path $taskCheck) {
        & pwsh -NoProfile -File $taskCheck
        if ($LASTEXITCODE -ne 0) { throw "El check especifico de la tarea fallo" }
    }

    Write-Output "CHECK_OK=$worktreePath"
}
finally {
    $env:PYTHONPATH = $oldPythonPath
    Pop-Location
}
