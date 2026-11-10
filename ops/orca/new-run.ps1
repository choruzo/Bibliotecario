param(
    [Parameter(Mandatory)][string]$Objective,
    [string]$TaskTitle,
    [string]$Spec,
    [string]$Deps = '[]'
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$coordinator = Get-Coordinator
$runResponse = Invoke-Orca orchestration run-create --from $coordinator --objective $Objective --json
$run = Get-RunRecord $runResponse
Write-Output "RUN=$($run.id)"

if ($TaskTitle) {
    if (-not $Spec) { $Spec = "Tarea $TaskTitle" }
    $taskResponse = Invoke-Orca orchestration task-create --from $coordinator --run $run.id --task-title $TaskTitle --spec $Spec --deps $Deps --json
    $taskResult = Get-OrcaResult $taskResponse
    $taskId = if ($taskResult.PSObject.Properties['taskId']) { $taskResult.taskId } else { $taskResult.task.id }
    Write-Output "TASK=$taskId"
}

