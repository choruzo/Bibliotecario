param(
    [switch]$Recreate,
    [string]$RunId
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$handle = Get-Coordinator -Recreate:$Recreate -RunId $RunId
Write-Output "ORCA_COORDINATOR=$handle"
