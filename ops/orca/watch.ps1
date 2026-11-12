param(
    [Parameter(Mandatory)][string]$RunId,
    [int]$TimeoutMs = 900000,
    [string]$Types = 'worker_done,question,escalation'
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$coordinator = Get-Coordinator -RunId $RunId
$response = Invoke-Orca orchestration check --terminal $coordinator --run $RunId --wait --types $Types --timeout-ms $TimeoutMs --json
$response | ConvertTo-Json -Depth 40
