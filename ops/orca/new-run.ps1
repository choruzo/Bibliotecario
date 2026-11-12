param(
    [Parameter(Mandatory)][string]$Objective,
    [string]$TaskTitle,
    [string]$Spec,
    [string]$Deps = '[]'
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$repoRoot = Get-RepoRoot
$coordinator = New-OrcaCoordinatorTerminal -Title "Orca Coordinator" -RepoRoot $repoRoot

$runResponse = Invoke-Orca orchestration run-create --from $coordinator --objective $Objective --json
$run = Get-OrcaRun $runResponse
if (-not $run) { throw "Orca no devolvio el Run creado." }

# El Run nace ligado al coordinador que lo va a ejecutar. Asi el lider no se
# queda como consumidor y start-loop no tiene que re-ligarlo.
Save-Coordinator -Handle $coordinator -Worktree $repoRoot -RunId $run.id
Write-Output "RUN=$($run.id)"
Write-Output "COORDINATOR=$coordinator"

if ($TaskTitle) {
    if (-not $Spec) { $Spec = "Tarea $TaskTitle" }
    $taskResponse = Invoke-Orca orchestration task-create --from $coordinator --run $run.id --task-title $TaskTitle --spec $Spec --deps $Deps --json
    $taskResult = Get-OrcaResult $taskResponse
    $taskId = $null
    if ($taskResult.PSObject.Properties['taskId'] -and $taskResult.taskId) { $taskId = [string]$taskResult.taskId }
    elseif ($taskResult.PSObject.Properties['task'] -and $taskResult.task.id) { $taskId = [string]$taskResult.task.id }
    elseif ($taskResult.PSObject.Properties['tasks'] -and @($taskResult.tasks).Count -gt 0) { $taskId = [string]@($taskResult.tasks)[0].id }
    if (-not $taskId) { throw "Orca creo la tarea pero no devolvio taskId: $($taskResponse | ConvertTo-Json -Compress -Depth 10)" }
    Write-Output "TASK=$taskId"
}
