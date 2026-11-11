# Notificacion de fin de bucle. Escribe siempre en .orca-run/notifications.log
# y, si hay webhook, lo publica. No bloquea el cierre del runner.

param(
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$Status,
    [string]$Message = '',
    [string]$WebhookUrl = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

$stateDir = Get-StateDir
$entry = [ordered]@{
    runId   = $RunId
    status  = $Status
    at      = (Get-Date).ToUniversalTime().ToString('o')
    message = $Message
    host    = $env:COMPUTERNAME
}

$logPath = Join-Path $stateDir 'notifications.log'
$entry | ConvertTo-Json -Compress | Add-Content -Path $logPath -Encoding UTF8

if (-not $WebhookUrl) { $WebhookUrl = $env:ORCA_NOTIFY_WEBHOOK }
if ($WebhookUrl) {
    try {
        $body = $entry | ConvertTo-Json -Depth 10
        Invoke-RestMethod -Uri $WebhookUrl -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 10 | Out-Null
        Write-Output 'NOTIFY_SENT=webhook'
    }
    catch {
        Write-Warning "No se pudo enviar la notificacion: $($_.Exception.Message)"
        Write-Output 'NOTIFY_SENT=none'
    }
}
else {
    Write-Output 'NOTIFY_SENT=log'
}

if (Get-Command New-BurntToastNotification -ErrorAction SilentlyContinue) {
    try {
        New-BurntToastNotification -Text "Orca $Status", $Message | Out-Null
    }
    catch { }
}

Write-Output "NOTIFY=$Status"
