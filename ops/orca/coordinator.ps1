param([switch]$Recreate)

. (Join-Path $PSScriptRoot 'lib.ps1')

$handle = Get-Coordinator -Recreate:$Recreate
Write-Output "ORCA_COORDINATOR=$handle"
