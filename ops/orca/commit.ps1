param(
    [Parameter(Mandatory)][string]$Worktree,
    [Parameter(Mandatory)][string]$TaskId,
    [string[]]$Files = @(),
    [string]$FilesCsv,
    [string]$Message,
    [string]$BaseBranch = 'main',
    [bool]$AllowExistingCommit = $true
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

    # Archivos declarados que sí tienen cambios frente a HEAD (staged, unstaged
    # o untracked). Si el worker ya los commiteó, la lista queda vacía.
    $changed = @()
    $changed += @(& git diff --name-only HEAD -- @expected)
    $changed += @(& git ls-files --others --exclude-standard -- @expected)
    $changed = @($changed | Where-Object { $_ } | ForEach-Object { $_ -replace '\\', '/' } | Sort-Object -Unique)

    if ($changed.Count -eq 0) {
        if (-not $AllowExistingCommit) { throw "No hay cambios que commitear para $TaskId" }

        $baseOk = $false
        & git rev-parse --verify -q $BaseBranch *> $null
        if ($LASTEXITCODE -eq 0) { $baseOk = $true }

        $ahead = 0
        if ($baseOk) { $ahead = [int]((& git rev-list --count "$BaseBranch..HEAD").Trim()) }
        if ($ahead -lt 1) {
            throw "No hay cambios ni commits nuevos para $TaskId (base=$BaseBranch)"
        }

        $committed = @(& git diff --name-only "$BaseBranch...HEAD" | ForEach-Object { $_ -replace '\\', '/' } | Sort-Object -Unique)
        $missing = @(Compare-Object -ReferenceObject $expected -DifferenceObject $committed | Where-Object { $_.SideIndicator -eq '<=' })
        if ($missing.Count -gt 0) {
            $names = ($missing | ForEach-Object { $_.InputObject }) -join ', '
            throw "El commit existente no contiene los archivos declarados: $names"
        }

        $head = (& git rev-parse HEAD).Trim()
        Write-Output "COMMIT=$head"
        Write-Output 'COMMIT_EXISTING=1'
        return
    }

    $missingChanges = @(Compare-Object -ReferenceObject $expected -DifferenceObject $changed | Where-Object { $_.SideIndicator -eq '<=' })
    if ($missingChanges.Count -gt 0) {
        $names = ($missingChanges | ForEach-Object { $_.InputObject }) -join ', '
        throw "Hay archivos declarados ya commiteados y otros sin commitear ($names). Revisa el flujo: el worker no debe hacer git add/commit."
    }

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
