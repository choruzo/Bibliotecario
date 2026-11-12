# Test del parser de trayectoria (P3): fixture JSON sin API + verificacion en
# vivo contra una sesion real si la hay.

$ErrorActionPreference = 'Stop'

$orcaDir = Split-Path $PSScriptRoot -Parent
. (Join-Path $orcaDir 'lib.ps1')

$fixture = @'
{"data":[
 {"type":"user","time":{"created":1700000000000}},
 {"type":"assistant","time":{"created":1700000002000,"completed":1700000010000},
  "tokens":{"output":512},
  "content":[{"type":"text","text":"hola"},{"type":"tool","tool":"bash"},{"type":"reasoning"}]},
 {"type":"assistant","time":{"created":1700000012000,"completed":1700000020000},
  "tokens":{"output":768},
  "content":[{"type":"tool","tool":"edit"},{"type":"tool","tool":"bash"},{"type":"text","text":"listo"}]},
 {"type":"idle","time":{"created":1700000021000}}
]}
'@

try {
    $stats = ConvertFrom-SessionTrajectory -JsonText $fixture
    if ($stats.assistantMessages -ne 2) { throw "assistantMessages esperado 2, got $($stats.assistantMessages)" }
    if ($stats.userMessages -ne 1) { throw "userMessages esperado 1, got $($stats.userMessages)" }
    if ($stats.toolCalls -ne 3) { throw "toolCalls esperado 3, got $($stats.toolCalls)" }
    if ($stats.tokensOutput -ne 1280) { throw "tokensOutput esperado 1280, got $($stats.tokensOutput)" }
    if ($stats.durationSec -ne 20) { throw "durationSec esperado 20, got $($stats.durationSec)" }

    # Robustez: JSON vacio, corrupto y esquema sin 'data' (array plano).
    $empty = ConvertFrom-SessionTrajectory -JsonText ''
    if ($empty.assistantMessages -ne 0) { throw 'JSON vacio deberia dar cero' }
    $broken = ConvertFrom-SessionTrajectory -JsonText '{not json'
    if ($broken.assistantMessages -ne 0) { throw 'JSON corrupto deberia dar cero sin explotar' }
    $flat = ConvertFrom-SessionTrajectory -JsonText '[{"type":"assistant","content":[{"type":"tool"}]}]'
    if ($flat.toolCalls -ne 1) { throw "Array plano: toolCalls esperado 1, got $($flat.toolCalls)" }

    # Verificacion en vivo si hay sesiones reales.
    $raw = & opencode api GET '/api/session' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $sessions = ((((($raw | Out-String).Trim()) | ConvertFrom-Json -Depth 20).data))
        $one = @($sessions) | Select-Object -First 1
        if ($one) {
            $live = Get-SessionTrajectoryStats -SessionId $one.id
            if ($live) { Write-Output "LIVE_OK session=$($one.id) assistants=$($live.assistantMessages) tools=$($live.toolCalls) dur=$($live.durationSec)s" }
        }
    }

    Write-Output 'TRAJECTORY_TEST_OK'
}
finally {
}
