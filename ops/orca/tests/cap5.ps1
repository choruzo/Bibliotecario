param(
    [int]$WaitTimeoutMs = 240000
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot '..\lib.ps1')

Write-Output '=== CAP5 TEST START ==='
$runOutput = & pwsh -NoProfile -File (Join-Path $PSScriptRoot '..\new-run.ps1') -Objective 'Tope 5 workers: 6 tareas'
$runLine = @($runOutput) | Where-Object { $_ -match '^RUN=' } | Select-Object -Last 1
if (-not $runLine) { throw "No se pudo crear el Run: $runOutput" }
$runId = $runLine -replace '^RUN=', ''
Write-Output "RUN=$runId"

$coordinator = Get-Coordinator
for ($i = 1; $i -le 6; $i++) {
    $spec = "Escribe CAP$i.md en la raiz del worktree con el texto exacto: cap $i ok. Escribe report.md con el resumen. No hagas push ni merge. Al terminar envia worker_done con los IDs inyectados."
    $created = Invoke-Orca orchestration task-create --from $coordinator --run $runId --task-title "cap-$i" --spec $spec --json
    if (-not $created.ok) { throw "task-create cap-$i falló: $($created.error.message)" }
    Write-Output "TASK_CAP${i}=$($created.result.task.id)"
}

$before = (Get-OrcaResult (Invoke-OrcaTaskList -Coordinator $coordinator -RunId $runId)).tasks
Write-Output "BEFORE_READY=$(@($before | Where-Object { $_.status -eq 'ready' }).Count)"

$dispatchOutput = & pwsh -NoProfile -File (Join-Path $PSScriptRoot '..\dispatch.ps1') -RunId $runId -MaxWorkers 5
$dispatchOutput | ForEach-Object { Write-Output $_ }

$after = (Get-OrcaResult (Invoke-OrcaTaskList -Coordinator $coordinator -RunId $runId)).tasks
$active = @($after | Where-Object { $_.status -eq 'dispatched' }).Count
$ready = @($after | Where-Object { $_.status -eq 'ready' }).Count
Write-Output "CAP_ACTIVE=$active CAP_READY=$ready"

if ($active -ne 5 -or $ready -ne 1) {
    throw "El tope falló: se esperaban 5 activas y 1 lista, hay $active activas y $ready listas."
}
Write-Output 'CAP_CONFIRMED=5'

$loopOutput = & pwsh -NoProfile -File (Join-Path $PSScriptRoot '..\orchestrate.ps1') -RunId $runId -MaxWorkers 5 -WaitTimeoutMs $WaitTimeoutMs 2>&1
$loopOutput | ForEach-Object { Write-Output $_ }
$loopExit = $LASTEXITCODE
if ($loopExit -ne 0) { throw "orchestrate.ps1 terminó con $loopExit" }

$final = (Get-OrcaResult (Invoke-OrcaTaskList -Coordinator $coordinator -RunId $runId)).tasks
$completed = @($final | Where-Object { $_.status -eq 'completed' }).Count
Write-Output "FINAL_COMPLETED=$completed"
if ($completed -ne 6) { throw "Se esperaban 6 tareas completadas; hay $completed" }

Write-Output "CAP_TEST_RUN=$runId"
Write-Output '=== CAP5 TEST PASS ==='
