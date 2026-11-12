# Test unitario del nucleo de harness probing (Fase 1, PRD docs/08-prd-harnessing.md).
# No requiere Orca ni modelos: valida la variante, la materializacion y el contraste.

$ErrorActionPreference = 'Stop'

$orcaDir = Split-Path $PSScriptRoot -Parent
. (Join-Path $orcaDir 'lib.ps1')

$id = [guid]::NewGuid().ToString('N').Substring(0, 8)
$root = Join-Path ([IO.Path]::GetTempPath()) "orca-harness-test-$id"
$variant = Join-Path $root 'variant'
$worktree = Join-Path $root 'worktree'
New-Item -ItemType Directory -Force -Path $variant, $worktree | Out-Null

try {
    # 1. Variante valida: worker.md completo con una linea extra de guardrail.
    $worker = Get-Content (Join-Path (Split-Path (Split-Path $orcaDir -Parent) -Parent) '.opencode\agents\worker.md') -Raw -Encoding UTF8
    New-Item -ItemType Directory -Force -Path (Join-Path $variant '.opencode\agents') | Out-Null
    Set-Content -Path (Join-Path $variant '.opencode\agents\worker.md') -Value ($worker + "`r`n- Antes de terminar, verifica que report.md menciona el check ejecutado.") -Encoding UTF8 -Force
    $issues = @(Test-HarnessVariant -VariantDir $variant)
    if ($issues.Count) { throw "La variante valida deberia pasar: $($issues -join '; ')" }

    # 2. Ruta prohibida: tocar scripts del kit invalida la variante.
    $bad = Join-Path $root 'bad-path'
    New-Item -ItemType Directory -Force -Path (Join-Path $bad 'ops\orca'), (Join-Path $bad '.opencode\agents') | Out-Null
    Copy-Item (Join-Path $variant '.opencode\agents\worker.md') (Join-Path $bad '.opencode\agents\worker.md') -Force
    Set-Content -Path (Join-Path $bad 'ops\orca\orchestrate.ps1') -Value 'evil' -Encoding UTF8
    $issues = @(Test-HarnessVariant -VariantDir $bad)
    if (-not ($issues | Where-Object { $_ -match 'ruta no editable' })) { throw "La ruta prohibida deberia invalidar la variante: $($issues -join '; ')" }

    # 3. Perdida de denegaciones: worker.md sin 'git commit *' se rechaza.
    $noDeny = Join-Path $root 'no-deny'
    New-Item -ItemType Directory -Force -Path (Join-Path $noDeny '.opencode\agents') | Out-Null
    Set-Content -Path (Join-Path $noDeny '.opencode\agents\worker.md') -Value ($worker -replace 'resource: "git commit \*"', 'resource: "git commit x"') -Encoding UTF8
    $issues = @(Test-HarnessVariant -VariantDir $noDeny)
    if (-not ($issues | Where-Object { $_ -match 'git commit' })) { throw "Perder la denegacion de git commit deberia invalidar: $($issues -join '; ')" }

    # 4. Tope always-on: worker.md inflado por encima de 24k se rechaza.
    $fat = Join-Path $root 'fat'
    New-Item -ItemType Directory -Force -Path (Join-Path $fat '.opencode\agents') | Out-Null
    Set-Content -Path (Join-Path $fat '.opencode\agents\worker.md') -Value ($worker + ('x' * 25000)) -Encoding UTF8
    $issues = @(Test-HarnessVariant -VariantDir $fat)
    if (-not ($issues | Where-Object { $_ -match '24000' })) { throw "El tope always-on deberia invalidar: $($issues -join '; ')" }

    # 5. Variante vacia: se rechaza.
    $void = Join-Path $root 'void'
    New-Item -ItemType Directory -Force -Path $void | Out-Null
    $issues = @(Test-HarnessVariant -VariantDir $void)
    if (-not ($issues | Where-Object { $_ -match 'vacia' })) { throw 'Una variante vacia deberia invalidarse' }

    # 5b. RATIONALE.md en la raiz es metadato: se ignora al validar y no se materializa.
    Set-Content -Path (Join-Path $variant 'RATIONALE.md') -Value 'rationale de prueba' -Encoding UTF8
    $issues = @(Test-HarnessVariant -VariantDir $variant)
    if ($issues.Count) { throw "RATIONALE.md en la raiz no deberia invalidar la variante: $($issues -join '; ')" }
    $applied = @(Copy-HarnessVariant -VariantDir $variant -Worktree $worktree)
    if ($applied -contains 'RATIONALE.md') { throw 'RATIONALE.md no debe materializarse en el worktree' }

    # 6. Materializacion: sobrescribe lo incluido, hereda lo ausente.
    Set-Content -Path (Join-Path $worktree 'AGENTS.md') -Value 'heredado' -Encoding UTF8
    $applied = @(Copy-HarnessVariant -VariantDir $variant -Worktree $worktree)
    if ($applied -notcontains '.opencode/agents/worker.md') { throw "La lista aplicada no incluye worker.md: $($applied -join ', ')" }
    $target = Get-Content (Join-Path $worktree '.opencode\agents\worker.md') -Raw -Encoding UTF8
    if ($target -notmatch 'Antes de terminar, verifica que report\.md') { throw 'La variante no se materializo' }
    if ((Get-Content (Join-Path $worktree 'AGENTS.md') -Raw) -notmatch 'heredado') { throw 'Copy-HarnessVariant no debe tocar lo que la variante omite' }

    # 7. Contraste: solo se adopta con diferencia medible (RF1.6).
    $cases = @(
        @{ base = @{ finished = $true; verdict = 'ACEPTADO'; defects = @() }; variant = @{ finished = $true; verdict = 'ACEPTADO'; defects = @() }; expected = 'none' },
        @{ base = @{ finished = $true; verdict = 'CAMBIOS'; defects = @('a') }; variant = @{ finished = $true; verdict = 'ACEPTADO'; defects = @() }; expected = 'variant' },
        @{ base = @{ finished = $true; verdict = 'ACEPTADO'; defects = @() }; variant = @{ finished = $true; verdict = 'CAMBIOS'; defects = @('a') }; expected = 'base' },
        @{ base = @{ finished = $true; verdict = 'CAMBIOS'; defects = @('a', 'b', 'c', 'd', 'e') }; variant = @{ finished = $true; verdict = 'CAMBIOS'; defects = @('a', 'b') }; expected = 'variant' },
        @{ base = @{ finished = $true; verdict = 'CAMBIOS'; defects = @('a') }; variant = @{ finished = $true; verdict = 'CAMBIOS'; defects = @('a') }; expected = 'none' },
        @{ base = @{ finished = $false; verdict = 'CAMBIOS'; defects = @() }; variant = @{ finished = $true; verdict = 'ACEPTADO'; defects = @() }; expected = 'variant' },
        @{ base = @{ finished = $true; verdict = 'ACEPTADO'; defects = @() }; variant = @{ finished = $false; verdict = 'CAMBIOS'; defects = @() }; expected = 'base' },
        @{ base = @{ finished = $false; verdict = 'CAMBIOS'; defects = @() }; variant = @{ finished = $false; verdict = 'CAMBIOS'; defects = @() }; expected = 'none' }
    )
    foreach ($case in $cases) {
        $decision = Test-HarnessContrast -Base $case.base -Variant $case.variant
        if ($decision.winner -ne $case.expected) { throw "Contraste inesperado: esperado=$($case.expected) obtenido=$($decision.winner) ($($decision.reason))" }
    }

    # 8. Composicion: RESULT.md + arbol adoptado + proposal.diff (RF1.4).
    $composeDir = Join-Path $root 'compose'
    $repoFake = Join-Path $root 'fake-repo'
    New-Item -ItemType Directory -Force -Path (Join-Path $repoFake '.opencode\agents'), $composeDir | Out-Null
    Set-Content -Path (Join-Path $repoFake '.opencode\agents\worker.md') -Value 'base worker' -Encoding UTF8
    $variant2 = Join-Path $root 'variant2'
    New-Item -ItemType Directory -Force -Path (Join-Path $variant2 '.opencode\skills\nueva'), (Join-Path $variant2 '.opencode\agents') | Out-Null
    Set-Content -Path (Join-Path $variant2 '.opencode\agents\worker.md') -Value 'worker variante' -Encoding UTF8
    Set-Content -Path (Join-Path $variant2 '.opencode\skills\nueva\SKILL.md') -Value "---`nname: nueva`ndescription: prueba`n---`nCuerpo de la skill de prueba." -Encoding UTF8
    $decisionWin = @{ winner = 'variant'; reason = 'variante aceptada y base con cambios' }
    [void](Write-ProbeResultDir -Dir $composeDir `
        -BaseResult @{ finished = $true; verdict = 'CAMBIOS'; defects = @('x'); files = @('a.txt') } `
        -VariantResult @{ finished = $true; verdict = 'ACEPTADO'; defects = @(); files = @('a.txt') } `
        -Decision $decisionWin -SpecText 'spec de prueba' -RunId 'run_probe_test' -Label 'probe-compose' `
        -VariantDir $variant2 -BaseBranch 'main' -TaskBase 'task_a' -TaskVariant 'task_b' -RepoRoot $repoFake)
    if (-not (Test-Path (Join-Path $composeDir 'RESULT.md'))) { throw 'Falta RESULT.md' }
    $resultMd = Get-Content (Join-Path $composeDir 'RESULT.md') -Raw -Encoding UTF8
    if ($resultMd -notmatch 'Decision: \*\*variant\*\*') { throw 'RESULT.md no recoge la decision' }
    if (-not (Test-Path (Join-Path $composeDir 'variant\.opencode\skills\nueva\SKILL.md'))) { throw 'Falta el arbol adoptado variant/' }
    $proposal = Get-Content (Join-Path $composeDir 'proposal.diff') -Raw -Encoding UTF8
    if ($proposal -notmatch '### \.opencode/agents/worker\.md') { throw 'proposal.diff no incluye el worker.md modificado' }
    if ($proposal -notmatch '### \.opencode/skills/nueva/SKILL\.md') { throw 'proposal.diff no incluye la skill nueva' }
    if ($proposal -notmatch 'worker variante') { throw 'el diff no muestra el contenido de la variante' }

    # 9. Sin contraste no hay adopcion ni proposal.diff (RF1.6).
    $composeDir2 = Join-Path $root 'compose-none'
    [void](Write-ProbeResultDir -Dir $composeDir2 `
        -BaseResult @{ finished = $true; verdict = 'ACEPTADO'; defects = @(); files = @() } `
        -VariantResult @{ finished = $true; verdict = 'ACEPTADO'; defects = @(); files = @() } `
        -Decision @{ winner = 'none'; reason = 'sin contraste medible' } -SpecText 'spec de prueba' `
        -RunId 'run_probe_test' -Label 'probe-none' -VariantDir $variant2 -BaseBranch 'main' `
        -TaskBase 'task_a' -TaskVariant 'task_b' -RepoRoot $repoFake)
    if (Test-Path (Join-Path $composeDir2 'variant')) { throw 'Sin contraste no debe haber adopcion' }
    if (Test-Path (Join-Path $composeDir2 'proposal.diff')) { throw 'Sin contraste no debe haber proposal.diff' }

    Write-Output 'HARNESS_TEST_OK'
}
finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
