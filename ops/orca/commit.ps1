param(
    [Parameter(Mandatory)][string]$Worktree,
    [Parameter(Mandatory)][string]$TaskId,
    [string[]]$Files = @(),
    [string]$FilesCsv,
    [string]$Message
)

$ErrorActionPreference = 'Stop'

if ($FilesCsv) {
    $Files = @($FilesCsv -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

if (-not $Files -or $Files.Count -eq 0) { throw "No hay archivos declarados para commitear" }

$worktreePath = (Resolve-Path $Worktree).Path
Push-Location $worktreePath
try {
    $expected = @($Files | ForEach-Object { $_ -replace '\\', '/' } | Sort-Object -Unique)
    if ($expected.Count -eq 0) { throw "No hay archivos declarados para commitear" }

    & git add -- @expected
    if ($LASTEXITCODE -ne 0) { throw "git add falló" }

    $staged = @((& git diff --cached --name-only) | ForEach-Object { $_ -replace '\\', '/' } | Sort-Object -Unique)

    # El worker puede haber commiteado ya: si HEAD contiene exactamente los
    # archivos declarados, no hay nada que commitear y el sha valido es HEAD.
    if ($staged.Count -eq 0) {
        $baseRef = if (& git rev-parse --verify --quiet main) { 'main' } elseif (& git rev-parse --verify --quiet master) { 'master' } else { $null }
        $committed = @()
        if ($baseRef) {
            $committed = @(& git diff --name-only "$baseRef...HEAD" 2>$null | ForEach-Object { $_ -replace '\\', '/' } | Sort-Object -Unique)
        }
        $missing = @($expected | Where-Object { $committed -notcontains $_ })
        if ($committed.Count -gt 0 -and $missing.Count -eq 0) {
            $sha = (& git rev-parse HEAD).Trim()
            Write-Output "COMMIT=$sha"
            Write-Output 'COMMIT_SKIP=ya commiteado por el worker'
            return
        }
    }

    $diff = Compare-Object -ReferenceObject $expected -DifferenceObject $staged
    if ($diff) {
        throw "El staged set no coincide con los archivos declarados.`nEsperado: $($expected -join ', ')`nStaged: $($staged -join ', ')"
    }

    if (-not $Message) { $Message = "task($TaskId): cambio" }
    & git commit -m $Message
    if ($LASTEXITCODE -ne 0) { throw "git commit falló" }

    $sha = (& git rev-parse HEAD).Trim()
    Write-Output "COMMIT=$sha"
}
finally {
    Pop-Location
}

