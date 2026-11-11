param(
    [Parameter(Mandatory)][string]$RunId,
    [string]$TaskId,
    [switch]$Settled,
    [switch]$RemoveWorktree,
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

if (-not $TaskId -and -not $Settled) {
    throw "Indica -TaskId <task_id> o -Settled para limpiar todas las tareas asentadas del Run."
}

$allRecords = @(Read-Dispatches -RunId $RunId)
$groups = @($allRecords | Group-Object taskId)

if ($TaskId) {
    $groups = @($groups | Where-Object { $_.Name -eq $TaskId })
}
elseif ($Settled) {
    $settledStatuses = @('integrated', 'completed', 'failed', 'blocked', 'stalled', 'lost')
    $groups = @($groups | Where-Object {
            $latest = @($_.Group) | Select-Object -Last 1
            $latest -and ($latest.integrationSha -or $latest.status -in $settledStatuses)
        })
}

if ($groups.Count -eq 0) {
    Write-Output "NOTHING_TO_CLEAN=$RunId"
    return
}

function Remove-OraWorktree {
    param([string]$Path)

    if (-not $Path -or -not (Test-Path $Path)) {
        Write-Output "WORKTREE_ABSENT=$Path"
        return $true
    }

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $orArgs = @('worktree', 'rm', '--worktree', "path:$Path", '--json')
        if ($Force) { $orArgs += '--force' }
        $removed = $null
        try { $removed = Invoke-Orca @orArgs } catch { $removed = $null }
        if ($removed -and $removed.ok -and -not (Test-Path $Path)) { return $true }
        Start-Sleep -Seconds 2
    }

    $repoRoot = Get-RepoRoot
    & git -C $repoRoot worktree remove --force $Path 2>$null
    if ($LASTEXITCODE -eq 0 -and -not (Test-Path $Path)) { return $true }

    if ($Force -and (Test-Path $Path)) {
        # No usamos Remove-Item -Recurse: el worktree puede contener junctions
        # compartidos (.venv, node_modules) y borraríamos el checkout principal.
        Write-Warning "No se borra recursivamente ${Path} para no seguir enlaces compartidos. Cierra procesos y reintenta, o bórralo a mano."
    }

    return (-not (Test-Path $Path))
}

$failures = 0
foreach ($group in $groups) {
    $taskRecords = @($group.Group)
    $latest = $taskRecords | Select-Object -Last 1

    foreach ($record in $taskRecords) {
        if (-not $record.workerHandle) { continue }
        if ($DryRun) {
            Write-Output "WOULD_CLOSE_WORKER=$($record.workerHandle) task=$($record.taskId)"
            continue
        }
        if (Close-OrcaTerminal -Handle $record.workerHandle -Quiet) {
            Write-Output "CLOSED_WORKER=$($record.workerHandle)"
            Write-Audit -RunId $RunId -Actor 'cleanup' -Action 'terminal-close' -TaskId $record.taskId -DispatchId $record.dispatchId -Terminal $record.workerHandle -Reason 'cleanup'
        }
        else {
            Write-Warning "No se pudo cerrar el terminal $($record.workerHandle) de $($record.taskId)"
            $failures++
        }
    }

    if (-not $RemoveWorktree) {
        Write-Output "WORKTREE_KEPT=$($latest.worktree)"
        continue
    }

    $paths = @($taskRecords | ForEach-Object { $_.worktree } | Where-Object { $_ } | Sort-Object -Unique)
    $mainRoot = Get-RepoRoot
    foreach ($path in $paths) {
        if ((Resolve-Path $path -ErrorAction SilentlyContinue).Path -eq $mainRoot) {
            Write-Warning "Se ignora el checkout principal como worktree de tarea: $path"
            continue
        }
        if ($DryRun) {
            Write-Output "WOULD_REMOVE_WORKTREE=$path task=$($latest.taskId)"
            continue
        }
        # Cerrar todo lo que quede abierto en ese workspace antes de borrarlo.
        if (Test-Path $path) {
            try { [void](Invoke-Orca terminal close --worktree "path:$path" --all --json) } catch { }
        }
        if (Remove-OraWorktree -Path $path) {
            Write-Output "REMOVED_WORKTREE=$path"
            Write-Audit -RunId $RunId -Actor 'cleanup' -Action 'worktree-remove' -TaskId $latest.taskId -Reason $path
        }
        else {
            Write-Warning "No se pudo quitar el worktree: $path. Cierra procesos/terminales y reintenta cleanup.ps1."
            Write-Output "WORKTREE_LOCKED=$path"
            Write-Audit -RunId $RunId -Actor 'cleanup' -Action 'worktree-locked' -TaskId $latest.taskId -Reason $path
            $failures++
        }
    }
}

if ($failures -gt 0) { exit 1 }
