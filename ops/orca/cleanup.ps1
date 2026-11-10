param(
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$TaskId,
    [switch]$RemoveWorktree,
    [switch]$Force
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$record = @(Read-Dispatches -RunId $RunId) | Where-Object { $_.taskId -eq $TaskId } | Select-Object -First 1
if (-not $record) { throw "No hay dispatch registrado para $TaskId en $RunId" }

if ($record.workerHandle) {
    $closed = Invoke-Orca terminal close --terminal $record.workerHandle --json
    if ($closed.ok) { Write-Output "CLOSED_WORKER=$($record.workerHandle)" }
}

if ($RemoveWorktree) {
    $selector = "path:$($record.worktree)"
    $orArgs = @('worktree', 'rm', '--worktree', $selector, '--json')
    if ($Force) { $orArgs += '--force' }
    $removed = Invoke-Orca @orArgs
    if (-not $removed.ok) { throw "No se pudo quitar el worktree: $($removed.error.Message)" }
    if (Test-Path $record.worktree) {
        Write-Warning "Orca quitó el worktree del registro, pero el directorio sigue existiendo (posible bloqueo de antivirus): $($record.worktree)"
    }
    else {
        Write-Output "REMOVED_WORKTREE=$($record.worktree)"
    }
}
else {
    Write-Output "WORKTREE_KEPT=$($record.worktree)"
}

