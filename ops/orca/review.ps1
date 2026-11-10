param(
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$TaskId,
    [Parameter(Mandatory)][string]$Worktree,
    [string]$DispatchId,
    [int]$Round = 1
)

$ErrorActionPreference = 'Stop'

$worktreePath = (Resolve-Path $Worktree).Path
$reviewPath = Join-Path (Join-Path $worktreePath '.orca-task') 'review.json'

$review = [ordered]@{
    taskId      = $TaskId
    runId       = $RunId
    dispatchId  = $DispatchId
    round       = $Round
    verdict     = 'CAMBIOS'
    files       = @()
    defects     = @()
    checkOutput = @()
    at          = (Get-Date).ToString('o')
}

Push-Location $worktreePath
try {
    Write-Output "REVIEW_TASK=$TaskId"
    Write-Output "REVIEW_ROUND=$Round"
    Write-Output '--- git status ---'
    & git status --porcelain
    Write-Output '--- git diff --stat ---'
    & git diff --stat

    $checkOutput = (& pwsh -NoProfile -File (Join-Path $PSScriptRoot 'check.ps1') -Worktree $worktreePath -RequireReport 2>&1 | Out-String)
    $checkExit = $LASTEXITCODE
    $review.checkOutput = @($checkOutput -split "`r?`n" | Where-Object { $_ -ne '' })

    if ($checkExit -ne 0) {
        $review.verdict = 'CAMBIOS'
        $review.defects = @($review.checkOutput)
        $review | ConvertTo-Json -Depth 10 | Set-Content $reviewPath -Encoding UTF8
        Write-Output 'REVIEW=CAMBIOS'
        Write-Output "REVIEW_FILE=$reviewPath"
        exit 2
    }

    $files = @(
        (& git diff --name-only)
        (& git ls-files --others --exclude-standard)
    ) |
        Where-Object { $_ -and $_ -notmatch '^(report\.md|\.orca-task/)|(^|/)logs/|\.log$' } |
        ForEach-Object { $_ -replace '\\', '/' } |
        Sort-Object -Unique

    $review.verdict = 'ACEPTADO'
    $review.files = @($files)
    $review | ConvertTo-Json -Depth 10 | Set-Content $reviewPath -Encoding UTF8

    Write-Output 'REVIEW=ACEPTADO'
    Write-Output "FILES=$($files -join ',')"
    Write-Output "REVIEW_FILE=$reviewPath"
}
finally {
    Pop-Location
}



