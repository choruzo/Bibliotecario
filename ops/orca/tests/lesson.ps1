# Test funcional de la libreria de lecciones (CA0.1-CA0.3 del PRD docs/08-prd-harnessing.md).
# No requiere Orca ni modelos: opera sobre estado sintetico en un directorio temporal.

$ErrorActionPreference = 'Stop'

$orcaDir = Split-Path $PSScriptRoot -Parent
$lessonScript = Join-Path $orcaDir 'lesson.ps1'

$id = [guid]::NewGuid().ToString('N').Substring(0, 8)
$root = Join-Path ([IO.Path]::GetTempPath()) "orca-lesson-test-$id"
$stateDir = Join-Path $root 'state'
$libraryDir = Join-Path $root 'library'
New-Item -ItemType Directory -Force -Path $stateDir, $libraryDir | Out-Null

$run = 'run_test_lesson'
$task1 = 'task_lesson1'
$task2 = 'task_lesson2'

# Estado sintetico: T1 con evidencia real; T2 solo con el marcador del bucle.
$audit = @(
    @{ at = '2026-11-12T10:00:00Z'; actor = 'loop'; action = 'review-changes'; taskId = $task1; dispatchId = 'ctx_a'; terminal = ''; reason = 'round=1' },
    @{ at = '2026-11-12T10:05:00Z'; actor = 'loop'; action = 'integrated'; taskId = $task1; dispatchId = 'ctx_a'; terminal = ''; reason = 'abc1234' },
    @{ at = '2026-11-12T10:05:01Z'; actor = 'loop'; action = 'lesson-candidate'; taskId = $task1; dispatchId = 'ctx_a'; terminal = ''; reason = 'integrada abc1234' },
    @{ at = '2026-11-12T10:06:00Z'; actor = 'loop'; action = 'lesson-candidate'; taskId = $task2; dispatchId = 'ctx_b'; terminal = ''; reason = 'solo marcador' }
) | ForEach-Object { $_ | ConvertTo-Json -Compress }
Set-Content -Path (Join-Path $stateDir "audit-$run.jsonl") -Value $audit -Encoding UTF8

$records = @(
    [pscustomobject]@{
        runId = $run; taskId = $task1; taskTitle = 'tarea con evidencia'; dispatchId = 'ctx_a'
        workerHandle = 'term_a'; worktree = 'w'; branch = 'refs/heads/b'; terminal = 'worker:t'
        status = 'integrated'; baseBranch = 'main'; createdAt = '2026-11-12T10:00:00Z'
    }
)
$records | ConvertTo-Json -Depth 10 | Set-Content -Path (Join-Path $stateDir "dispatches-$run.json") -Encoding UTF8

try {
    # -ListPending marca T1 y T2 antes del scaffolding.
    $pending = (& pwsh -NoProfile -File $lessonScript -ListPending -StateDir $stateDir -LibraryDir $libraryDir | Out-String)
    if ($pending -notmatch "task=$task1") { throw "ListPending no marca ${task1}: $pending" }
    if ($pending -notmatch "task=$task2") { throw "ListPending no marca ${task2}: $pending" }

    # CA0.1: scaffold con evidencia crea EXPERIENCE.md, cita los eventos y actualiza INDEX.
    $out1 = (& pwsh -NoProfile -File $lessonScript -RunId $run -TaskId $task1 -StateDir $stateDir -LibraryDir $libraryDir | Out-String)
    if ($out1 -notmatch 'LESSON_CREATED=') { throw "No se creo la leccion: $out1" }
    $lesson1Path = Join-Path $libraryDir 'default\lessons\task_lesson1\EXPERIENCE.md'
    if (-not (Test-Path $lesson1Path)) { throw "Falta $lesson1Path" }
    $lesson1 = Get-Content $lesson1Path -Raw -Encoding UTF8
    if ($lesson1 -notmatch '\[integrated\]') { throw 'La evidencia no cita el evento integrated' }
    if ($lesson1 -notmatch '\[review-changes\]') { throw 'La evidencia no cita review-changes' }
    if ($lesson1 -notmatch 'status: draft') { throw 'El borrador no esta marcado como draft' }
    if ($lesson1 -notmatch 'confidence: low') { throw 'El borrador automatico deberia nacer low' }
    $index = Get-Content (Join-Path $libraryDir 'INDEX.md') -Raw -Encoding UTF8
    if ($index -notmatch $task1) { throw 'INDEX.md no indexa la leccion' }

    # CA0.2: sin evidencia real -> NO_ENTRY, sin archivo y registro en NO_ENTRY.log.
    $out2 = (& pwsh -NoProfile -File $lessonScript -RunId $run -TaskId $task2 -StateDir $stateDir -LibraryDir $libraryDir | Out-String)
    if ($out2 -notmatch 'NO_ENTRY') { throw "T2 deberia ser NO_ENTRY: $out2" }
    if (Test-Path (Join-Path $libraryDir 'default\lessons\task_lesson2')) { throw 'NO_ENTRY no debe crear archivo' }
    $noEntryLog = Get-Content (Join-Path $libraryDir 'NO_ENTRY.log') -Raw -Encoding UTF8
    if ($noEntryLog -notmatch $task2) { throw 'NO_ENTRY.log no registra la tarea' }

    # CA0.3: -Validate falla con cue/lesson TODO...
    [void](& pwsh -NoProfile -File $lessonScript -Validate -StateDir $stateDir -LibraryDir $libraryDir 2>&1 | Out-String)
    if ($LASTEXITCODE -eq 0) { throw 'Validate deberia fallar con cue/lesson TODO' }

    # ...y pasar tras rellenar cue/lesson (-Force regenera el borrador).
    $out1b = (& pwsh -NoProfile -File $lessonScript -RunId $run -TaskId $task1 -StateDir $stateDir -LibraryDir $libraryDir -Cue 'Integracion con review-changes previos' -Lesson 'Revisar las rondas de defectos previas antes de aceptar la entrega' -Confidence medium -Force | Out-String)
    if ($out1b -notmatch 'LESSON_CREATED=') { throw "No se regenero la leccion: $out1b" }
    [void](& pwsh -NoProfile -File $lessonScript -Validate -StateDir $stateDir -LibraryDir $libraryDir | Out-String)
    if ($LASTEXITCODE -ne 0) { throw 'Validate deberia pasar tras rellenar la leccion' }
    $lesson1b = Get-Content $lesson1Path -Raw -Encoding UTF8
    if ($lesson1b -notmatch 'confidence: medium') { throw 'La confidence manual no se aplico' }

    # Tras el scaffolding, ListPending no debe volver a marcar T1.
    $pending2 = (& pwsh -NoProfile -File $lessonScript -ListPending -StateDir $stateDir -LibraryDir $libraryDir | Out-String)
    if ($pending2 -notmatch 'PENDING_NONE') { throw "ListPending deberia quedar vacio: $pending2" }

    Write-Output 'LESSON_TEST_OK'
}
finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
