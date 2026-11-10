param(
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$TaskId,
    [Parameter(Mandatory)][string]$Worktree
)

$ErrorActionPreference = 'Stop'

$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
$stateDir = Join-Path $repoRoot '.orca-run'
$destination = Join-Path $stateDir "runs\$RunId\artifacts\$TaskId"
New-Item -ItemType Directory -Force -Path $destination | Out-Null

$worktreePath = (Resolve-Path $Worktree).Path

foreach ($name in @('report.md', 'task.json', 'spec.md')) {
    $candidate = if ($name -eq 'task.json' -or $name -eq 'spec.md') {
        Join-Path $worktreePath ".orca-task\$name"
    } else {
        Join-Path $worktreePath $name
    }
    if (Test-Path $candidate) {
        Copy-Item $candidate (Join-Path $destination $name) -Force
    }
}

$qaDir = Join-Path (Join-Path $worktreePath '.orca-task') 'qa'
if (Test-Path $qaDir) {
    Copy-Item $qaDir (Join-Path $destination 'qa') -Recurse -Force
}

Push-Location $worktreePath
try {
    if (Test-Path (Join-Path $worktreePath '.git')) {
        & git show --stat --oneline HEAD 2>$null | Set-Content (Join-Path $destination 'commit.txt') -Encoding UTF8
        & git diff HEAD~1 HEAD 2>$null | Set-Content (Join-Path $destination 'diff.patch') -Encoding UTF8
    }
    else {
        & git diff 2>$null | Set-Content (Join-Path $destination 'diff.patch') -Encoding UTF8
    }
}
finally {
    Pop-Location
}

Write-Output "ARCHIVE=$destination"


