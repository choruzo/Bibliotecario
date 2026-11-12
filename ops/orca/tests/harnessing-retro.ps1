# Test funcional de la retro de harnessing (etapa 1 del roadmap, PRD 08).
# Biblioteca sintetica: 1 dominio con >= 2 lecciones -> briefing compuesto;
# sin dominio suficiente -> RETRO_NONE; DryRun nunca abre sesiones.

$ErrorActionPreference = 'Stop'

$orcaDir = Split-Path $PSScriptRoot -Parent
$retroScript = Join-Path $orcaDir 'harnessing-retro.ps1'

$id = [guid]::NewGuid().ToString('N').Substring(0, 8)
$root = Join-Path ([IO.Path]::GetTempPath()) "orca-retro-test-$id"
$stateDir = Join-Path $root 'state'
$libraryDir = Join-Path $root 'library'
New-Item -ItemType Directory -Force -Path $stateDir, $libraryDir | Out-Null

function New-SyntheticLesson {
    param([string]$Domain, [string]$TaskId, [string]$Cue, [string]$Lesson)
    $dir = Join-Path (Join-Path (Join-Path $libraryDir $Domain) 'lessons') $TaskId
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $content = @(
        '---',
        "task: $TaskId",
        'run: run_synth',
        'date: 2026-11-12T00:00:00.0000000Z',
        "domain: $Domain",
        'confidence: medium',
        'status: draft',
        '---',
        '',
        '## Cue',
        '',
        $Cue,
        '',
        '## Lesson',
        '',
        $Lesson,
        '',
        '## Evidence',
        '',
        '- [commit] 2026-11-12T00:00:00 actor=loop motivo: abc1234',
        ''
    ) -join "`r`n"
    Set-Content -Path (Join-Path $dir 'EXPERIENCE.md') -Value $content -Encoding UTF8
}

try {
    # 1. Un dominio con 2 lecciones (umbral por defecto) y otro con 1.
    New-SyntheticLesson -Domain 'orchestration' -TaskId 'task_aaa' -Cue 'Patron A: dos ramas paralelas crean el mismo modulo' -Lesson 'Declarar propiedad del fichero en la spec y serializar con deps.'
    New-SyntheticLesson -Domain 'orchestration' -TaskId 'task_bbb' -Cue 'Patron A: worker_done sin diff revisable' -Lesson 'Exigir FILES no vacio y integrationSha antes de dar por entregado.'
    New-SyntheticLesson -Domain 'pdf-conversion' -TaskId 'task_ccc' -Cue 'Patron B: rama bloqueada por conflicto semantico' -Lesson 'Run nuevo de port con spec autocontenida.'

    # 2. DryRun: sin -RunId (no scaffoldea nada), compone el briefing del dominio fuerte.
    $out = (& pwsh -NoProfile -File $retroScript -StateDir $stateDir -LibraryDir $libraryDir -DryRun | Out-String)
    if ($out -notmatch 'RETRO_DOMAIN=orchestration') { throw "Deberia elegir orchestration: $out" }
    if ($out -notmatch 'RETRO_BRIEF=') { throw "Falta el briefing: $out" }
    $briefPath = [regex]::Match($out, 'RETRO_BRIEF=(\S+)').Groups[1].Value
    if (-not (Test-Path $briefPath)) { throw "El briefing no existe: $briefPath" }
    $brief = Get-Content $briefPath -Raw -Encoding UTF8
    if ($brief -notmatch 'Patron A') { throw 'El briefing no incluye las lecciones del dominio' }
    if ($brief -notmatch 'harness-editor') { throw 'El briefing no encarga nada al editor' }
    if ($out -match 'sesion del editor') { throw 'Sin -CommissionEditor no debe abrir sesiones' }

    # 3. Umbral: solo un dominio con 1 leccion no alcanza.
    $single = Join-Path $root 'single'
    New-Item -ItemType Directory -Force -Path $single | Out-Null
    Copy-Item (Join-Path $libraryDir 'pdf-conversion') "$single\pdf-conversion" -Recurse
    $out2 = (& pwsh -NoProfile -File $retroScript -StateDir $stateDir -LibraryDir $single | Out-String)
    if ($out2 -notmatch 'RETRO_NONE') { throw "Con 1 leccion deberia ser RETRO_NONE: $out2" }

    # 4. -RunId con estado sintetico: scaffoldea la pendiente y sigue el analisis.
    $run = 'run_retro_test'
    $audit = @(
        @{ at = '2026-11-12T00:00:00Z'; actor = 'loop'; action = 'integrated'; taskId = 'task_ddd'; dispatchId = 'ctx_x'; terminal = ''; reason = 'abc1234' },
        @{ at = '2026-11-12T00:00:01Z'; actor = 'loop'; action = 'lesson-candidate'; taskId = 'task_ddd'; dispatchId = 'ctx_x'; terminal = ''; reason = 'integrada abc' }
    ) | ForEach-Object { $_ | ConvertTo-Json -Compress }
    Set-Content -Path (Join-Path $stateDir "audit-$run.jsonl") -Value $audit -Encoding UTF8
    $records = @([pscustomobject]@{ runId = $run; taskId = 'task_ddd'; taskTitle = 't'; dispatchId = 'ctx_x'; workerHandle = 'h'; worktree = 'w'; branch = 'refs/heads/b'; terminal = 't'; status = 'integrated'; baseBranch = 'main'; createdAt = '2026-11-12T00:00:00Z' })
    $records | ConvertTo-Json -Depth 10 | Set-Content -Path (Join-Path $stateDir "dispatches-$run.json") -Encoding UTF8
    $out3 = (& pwsh -NoProfile -File $retroScript -RunId $run -StateDir $stateDir -LibraryDir $libraryDir | Out-String)
    if ($out3 -notmatch 'scaffoldeando') { throw "Deberia scaffoldear las pendientes del run: $out3" }
    if (-not (Test-Path (Join-Path $libraryDir 'default\lessons\task_ddd\EXPERIENCE.md'))) { throw 'El scaffold de la pendiente no se creo' }

    Write-Output 'RETRO_TEST_OK'
}
finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
