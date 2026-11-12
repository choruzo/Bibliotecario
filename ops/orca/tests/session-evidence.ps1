# Test unitario de la evidencia de sesion (RF2.3, PRD docs/08-prd-harnessing.md).
# No requiere sesiones reales: el registro de sesion se sintetiza y la API se
# ejercita solo con identificadores inexistentes (debe degradar a $null).

$ErrorActionPreference = 'Stop'

$orcaDir = Split-Path $PSScriptRoot -Parent
. (Join-Path $orcaDir 'lib.ps1')

$id = [guid]::NewGuid().ToString('N').Substring(0, 8)
$worktree = Join-Path ([IO.Path]::GetTempPath()) "orca-session-test-$id"
New-Item -ItemType Directory -Force -Path (Join-Path $worktree '.orca-task') | Out-Null

try {
    # 1. Sin registro de sesion: $null, sin excepciones.
    if (Get-OpenCodeSessionId -Worktree $worktree) { throw 'Sin registro deberia devolver $null' }

    # 2. Registro valido: devuelve el sessionId.
    $record = @{ sessionId = 'ses_unit_test'; agent = 'worker'; taskTitle = 't'; worktree = 'w'; createdAt = '2026-11-12T12:00:00.000Z' }
    $record | ConvertTo-Json -Compress | Set-Content -Path (Join-Path $worktree '.orca-task\opencode-session.json') -Encoding UTF8
    if ((Get-OpenCodeSessionId -Worktree $worktree) -ne 'ses_unit_test') { throw 'No devolvio el sessionId registrado' }

    # 3. Registro corrupto: $null, sin excepciones.
    Set-Content -Path (Join-Path $worktree '.orca-task\opencode-session.json') -Value '{not json' -Encoding UTF8
    if (Get-OpenCodeSessionId -Worktree $worktree) { throw 'Un registro corrupto deberia devolver $null' }

    # 4. Sesion inexistente en la API: $null (degrada sin romper el watchdog).
    if (Get-SessionActivityUtc -SessionId 'ses_no_existe_unit_test') { throw 'Una sesion inexistente deberia devolver $null' }

    Write-Output 'SESSION_EVIDENCE_OK'
}
finally {
    Remove-Item -LiteralPath $worktree -Recurse -Force -ErrorAction SilentlyContinue
}
