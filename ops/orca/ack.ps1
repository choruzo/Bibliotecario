param(
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$DeliveryId
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$coordinator = Get-Coordinator
$response = Invoke-Orca orchestration check --terminal $coordinator --run $RunId --ack $DeliveryId --json
$response | ConvertTo-Json -Depth 20
