# Test de las funciones de par in-run (RF1.1, PRD 08): token, hermano, listos
# y arbitraje con review.json sinteticos en worktrees temporales.

$ErrorActionPreference = 'Stop'

$orcaDir = Split-Path $PSScriptRoot -Parent
. (Join-Path $orcaDir 'lib.ps1')

$id = [guid]::NewGuid().ToString('N').Substring(0, 8)
$root = Join-Path ([IO.Path]::GetTempPath()) "orca-pair-test-$id"
New-Item -ItemType Directory -Force -Path $root | Out-Null

function New-WorktreeWithReview {
    param([string]$Name, [string]$Verdict, [string[]]$Defects)
    $wt = Join-Path $root $Name
    New-Item -ItemType Directory -Force -Path (Join-Path $wt '.orca-task') | Out-Null
    $review = [ordered]@{ taskId = $Name; verdict = $Verdict; defects = $Defects; files = @('a.txt'); round = 1 }
    $review | ConvertTo-Json -Depth 10 | Set-Content -Path (Join-Path $wt '.orca-task\review.json') -Encoding UTF8
    return $wt
}

function New-PairRecord {
    param([string]$TaskId, [string]$Side, [string]$Status, [string]$Worktree)
    return [pscustomobject]@{
        runId = 'run_x'; taskId = $TaskId; taskTitle = "probe-$Side"; dispatchId = "ctx_$Side"
        workerHandle = 'h'; worktree = $Worktree; branch = "refs/heads/b-$Side"; terminal = 't'
        status = $Status; baseBranch = 'main'; createdAt = '2026-11-12T00:00:00Z'
        pairId = 'pair1'; side = $Side
    }
}

try {
    # 1. Token en spec.
    if (-not (Test-HarnessProbeSpec -Spec 'Tarea [HARNESS-PROBE] de calibracion')) { throw 'El token [HARNESS-PROBE] debe detectarse' }
    if (Test-HarnessProbeSpec -Spec 'Tarea normal sin token') { throw 'No debe detectarse sin token' }
    if (Test-HarnessProbeSpec -Spec $null) { throw 'Spec null no debe detectarse' }

    # 2. Hermano por pairId.
    $a = New-PairRecord -TaskId 'task_a' -Side 'a' -Status 'completed' -Worktree 'w'
    $b = New-PairRecord -TaskId 'task_b' -Side 'b' -Status 'completed' -Worktree 'w'
    $sib = Get-PairSibling -Records @($a, $b, [pscustomobject]@{ taskId = 'task_z'; pairId = $null }) -Record $a
    if (-not $sib -or $sib.taskId -ne 'task_b') { throw 'El hermano no se resuelve por pairId' }
    if (Get-PairSibling -Records @($a) -Record $a) { throw 'Sin hermano no debe resolverse' }

    # 3. Listos para arbitrar: estados frescos de ORCA (no records).
    if (-not (Test-HarnessPairReady -SelfStatus 'completed' -SiblingStatus 'completed')) { throw 'Ambos completed deben estar listos' }
    if (-not (Test-HarnessPairReady -SelfStatus 'completed' -SiblingStatus 'failed')) { throw 'Terminal+failed debe estar listo' }
    if (Test-HarnessPairReady -SelfStatus 'completed' -SiblingStatus 'dispatched') { throw 'Con la hermana en vuelo no se arbitra' }
    if (Test-HarnessPairReady -SelfStatus 'dispatched' -SiblingStatus 'dispatched') { throw 'Ambos en vuelo no se arbitran' }

    # 4. Arbitraje: variante aceptada y base con cambios -> variante.
    $wtA1 = New-WorktreeWithReview -Name 'a-cambios' -Verdict 'CAMBIOS' -Defects @('x', 'y')
    $wtB1 = New-WorktreeWithReview -Name 'b-aceptada' -Verdict 'ACEPTADO' -Defects @()
    $a1 = New-PairRecord -TaskId 'task_a' -Side 'a' -Status 'completed' -Worktree $wtA1
    $b1 = New-PairRecord -TaskId 'task_b' -Side 'b' -Status 'completed' -Worktree $wtB1
    $d = Resolve-HarnessPairWinner -Record $a1 -Sibling $b1
    if ($d.winner -ne 'variant') { throw "Variante aceptada deberia ganar: $($d.winner) ($($d.reason))" }

    # 5. Empate -> base (nunca sin integracion).
    $wtA2 = New-WorktreeWithReview -Name 'a-aceptada' -Verdict 'ACEPTADO' -Defects @()
    $wtB2 = New-WorktreeWithReview -Name 'b-aceptada2' -Verdict 'ACEPTADO' -Defects @()
    $a2 = New-PairRecord -TaskId 'task_a' -Side 'a' -Status 'completed' -Worktree $wtA2
    $b2 = New-PairRecord -TaskId 'task_b' -Side 'b' -Status 'completed' -Worktree $wtB2
    $d2 = Resolve-HarnessPairWinner -Record $a2 -Sibling $b2
    if ($d2.winner -ne 'base') { throw "Empate deberia integrar la base: $($d2.winner)" }

    # 6. Variante fallida -> base.
    $a3 = New-PairRecord -TaskId 'task_a' -Side 'a' -Status 'completed' -Worktree $wtA2
    $b3 = New-PairRecord -TaskId 'task_b' -Side 'b' -Status 'failed' -Worktree $null
    $d3 = Resolve-HarnessPairWinner -Record $a3 -Sibling $b3
    if ($d3.winner -ne 'base') { throw "Variante fallida deberia integrar la base: $($d3.winner)" }

    # 7. La vista no depende de que lado sea el record actual.
    $d4 = Resolve-HarnessPairWinner -Record $b1 -Sibling $a1
    if ($d4.winner -ne 'variant') { throw "El arbitraje no debe depender del lado consultado: $($d4.winner)" }

    Write-Output 'PAIR_TEST_OK'
}
finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
