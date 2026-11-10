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

