# Librería de lecciones (Fase 0 del PRD docs/08-prd-harnessing.md).
# Crea, valida y indexa lecciones EXPERIENCE.md con evidencia citada de los runs.
# No depende de Orca: opera sobre archivos locales (.orca-run y ops/orca/library).
#
# Uso:
#   lesson.ps1 -RunId <run> -TaskId <task>              # borrador con evidencia autocompletada
#   lesson.ps1 -RunId <run> -TaskId <task> -Cue "..." -Lesson "..." -Confidence medium
#   lesson.ps1 -Index                                    # regenera INDEX.md desde disco
#   lesson.ps1 -Validate                                 # falla si hay lecciones incompletas o sin evidencia
#   lesson.ps1 -ListPending                              # tareas marcadas por el bucle que aún no tienen lección

param(
    [string]$RunId,
    [string]$TaskId,
    [string]$Domain = 'default',
    [string]$Cue,
    [string]$Lesson,
    [ValidateSet('high', 'medium', 'low')]
    [string]$Confidence,
    # Overrides para tests y para operar sobre otro checkout.
    [string]$StateDir,
    [string]$LibraryDir,
    [switch]$Force,
    [switch]$Index,
    [switch]$Validate,
    [switch]$ListPending
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$script:stateDir = if ($StateDir) { $StateDir } else { Get-StateDir }
$script:libraryDir = if ($LibraryDir) { $LibraryDir } else { Get-LibraryRoot }
$script:markerAction = 'lesson-candidate'
$script:noEntryLog = Join-Path $script:libraryDir 'NO_ENTRY.log'

# --- Lectura de evidencia ---------------------------------------------------

function Get-AuditEntries {
    param([Parameter(Mandatory)][string]$RunId, [string]$ForTaskId)

    $file = Join-Path $script:stateDir "audit-$RunId.jsonl"
    if (-not (Test-Path $file)) { return @() }
    $entries = @()
    foreach ($line in (Get-Content $file -Encoding UTF8)) {
        if (-not $line.Trim()) { continue }
        try { $entry = $line | ConvertFrom-Json } catch { continue }
        if ($ForTaskId -and [string]$entry.taskId -ne $ForTaskId) { continue }
        $entries += $entry
    }
    return $entries
}

function Get-RealEvidence {
    # El marcador lesson-candidate es andamiaje del bucle, no evidencia.
    param([array]$Entries)
    return @($Entries | Where-Object { $_.action -ne $script:markerAction })
}

function Get-DispatchRecord {
    param([Parameter(Mandatory)][string]$RunId, [Parameter(Mandatory)][string]$TaskId)

    $file = Join-Path $script:stateDir "dispatches-$RunId.json"
    if (-not (Test-Path $file)) { return $null }
    try { $records = @(Get-Content $file -Raw | ConvertFrom-Json) } catch { return $null }
    return @($records | Where-Object { $_ -and [string]$_.taskId -eq $TaskId }) | Select-Object -Last 1
}

function Format-EvidenceLine {
    param($Entry)
    $reason = if ($Entry.reason) { $Entry.reason } else { '-' }
    return "- [$($Entry.action)] $($Entry.at) actor=$($Entry.actor) motivo: $reason"
}

function Get-WorkerReportSummary {
    # Primeras líneas del report.md archivado: la versión del worker, citable.
    param([Parameter(Mandatory)][string]$RunId, [Parameter(Mandatory)][string]$TaskId)

    $report = Join-Path $script:stateDir "runs\$RunId\artifacts\$TaskId\report.md"
    if (-not (Test-Path $report)) { return $null }
    $lines = @(Get-Content $report -Encoding UTF8 | Where-Object { $_.Trim() } | Select-Object -First 3)
    if (-not $lines) { return $null }
    return ($lines -join ' ')
}

# --- Escritura --------------------------------------------------------------

function New-LessonFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][hashtable]$Meta,
        [string]$CueText,
        [string]$LessonText,
        [Parameter(Mandatory)][array]$EvidenceLines,
        [string]$WorkerReport
    )

    $cue = if ($CueText) { $CueText } else { 'TODO: describe la situacion que dispara esta leccion (que reconoceria el worker antes de actuar).' }
    $lesson = if ($LessonText) { $LessonText } else { 'TODO: indica la operacion a hacer, nombrando el componente del kit al que afecta.' }

    $evidence = @($EvidenceLines)
    if ($WorkerReport) { $evidence += "- [worker-report] $WorkerReport" }

    $front = @(
        '---',
        "task: $($Meta.task)",
        "run: $($Meta.run)",
        "date: $($Meta.date)",
        "domain: $($Meta.domain)",
        "confidence: $($Meta.confidence)",
        'status: draft',
        '---',
        ''
    )
    $body = @(
        '## Cue',
        '',
        $cue,
        '',
        '## Lesson',
        '',
        $lesson,
        '',
        '## Evidence',
        '',
        ($evidence -join "`n"),
        ''
    )
    $content = ($front -join "`n") + "`n" + ($body -join "`n")
    New-Item -ItemType Directory -Force -Path (Split-Path $Path -Parent) | Out-Null
    Set-Content -Path $Path -Value $content -Encoding UTF8
}

function Add-NoEntry {
    param([Parameter(Mandatory)][string]$RunId, [Parameter(Mandatory)][string]$TaskId, [Parameter(Mandatory)][string]$Reason)

    New-Item -ItemType Directory -Force -Path $script:libraryDir | Out-Null
    $line = "{0}`trun={1}`ttask={2}`treason={3}" -f (Get-Date).ToString('o'), $RunId, $TaskId, $Reason
    Add-Content -Path $script:noEntryLog -Value $line -Encoding UTF8
}

function Update-LibraryIndex {
    $domains = @(Get-ChildItem $script:libraryDir -Directory -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'lessons') })
    $rows = @()
    foreach ($domain in $domains) {
        foreach ($lessonFile in (Get-ChildItem (Join-Path $domain.FullName 'lessons') -Recurse -Filter 'EXPERIENCE.md' -ErrorAction SilentlyContinue)) {
            $parsed = Read-LessonFile -Path $lessonFile.FullName
            $rel = $lessonFile.FullName.Substring($script:libraryDir.Length + 1) -replace '\\', '/'
            $cue = $parsed.Cue
            if ($cue -and $cue.Length -gt 60) { $cue = $cue.Substring(0, 57) + '...' }
            $rows += "| $($domain.Name) | $($parsed.Task) | $(Escape-IndexCell $cue) | $($parsed.Confidence) | $rel |"
        }
    }
    $rows = @($rows | Where-Object { $_ })
    $header = @(
        '# Indice de la libreria de lecciones',
        '',
        'Regenerado por `lesson.ps1 -Index`. No editar a mano.',
        '',
        '| Dominio | Tarea | Cue | Confidence | Ruta |',
        '|---|---|---|---|---|'
    )
    $tail = if ($rows.Count) { $rows } else { @('', '_Aun no hay lecciones. Crea la primera con `lesson.ps1 -RunId <run> -TaskId <task>`._', '') }
    Set-Content -Path (Join-Path $script:libraryDir 'INDEX.md') -Value (($header + $tail) -join "`n") -Encoding UTF8
    return $rows.Count
}

function Escape-IndexCell {
    param([string]$Text)
    if (-not $Text) { return '' }
    return ($Text -replace '\|', '\|' -replace "`r?`n", ' ')
}

# --- Lectura y validación de lecciones --------------------------------------

function Read-LessonFile {
    param([Parameter(Mandatory)][string]$Path)

    $result = @{ Task = ''; Run = ''; Date = ''; Domain = ''; Confidence = ''; Cue = ''; Lesson = ''; Evidence = '' }
    $lines = @(Get-Content $Path -Encoding UTF8)
    $inFront = $false
    $section = $null
    $sections = @{ Cue = @(); Lesson = @(); Evidence = @() }
    foreach ($line in $lines) {
        if ($line -eq '---') {
            $inFront = -not $inFront
            continue
        }
        if ($inFront) {
            if ($line -match '^(task|run|date|domain|confidence):\s*(.*)$') { $result[[string]$Matches[1]] = $Matches[2].Trim() }
            continue
        }
        if ($line -match '^##\s+(Cue|Lesson|Evidence)\s*$') { $section = $Matches[1]; continue }
        if ($section) { $sections[$section] += $line }
    }
    $result.Cue = (($sections.Cue | Where-Object { $_.Trim() }) -join ' ').Trim()
    $result.Lesson = (($sections.Lesson | Where-Object { $_.Trim() }) -join ' ').Trim()
    $result.Evidence = (($sections.Evidence | Where-Object { $_.Trim() }) -join "`n").Trim()
    return [pscustomobject]$result
}

function Test-LessonFile {
    param([Parameter(Mandatory)][string]$Path)

    $parsed = Read-LessonFile -Path $Path
    $issues = @()
    if (-not $parsed.Task) { $issues += 'front matter sin task' }
    if (-not $parsed.Cue -or $parsed.Cue -match '^TODO') { $issues += 'cue vacio o TODO' }
    if (-not $parsed.Lesson -or $parsed.Lesson -match '^TODO') { $issues += 'lesson vacio o TODO' }
    if (-not $parsed.Evidence) { $issues += 'sin evidencia citada' }
    elseif ($parsed.Evidence -notmatch '(?m)^- \[') { $issues += 'evidencia sin citas con formato - [accion]' }
    if ($parsed.Confidence -and $parsed.Confidence -notin @('high', 'medium', 'low')) { $issues += "confidence invalida: $($parsed.Confidence)" }
    return $issues
}

# --- Modos -------------------------------------------------------------------

if ($Validate) {
    $failures = @()
    $checked = 0
    if (Test-Path $script:libraryDir) {
        foreach ($file in (Get-ChildItem $script:libraryDir -Recurse -Filter 'EXPERIENCE.md' -ErrorAction SilentlyContinue)) {
            $checked++
            foreach ($issue in (Test-LessonFile -Path $file.FullName)) {
                $failures += "$($file.FullName): $issue"
            }
        }
    }
    if ($failures.Count) {
        foreach ($failure in $failures) { Write-Host "LESSON_INVALID $failure" }
        Write-Output "LESSON_VALIDATE_FAIL count=$($failures.Count) checked=$checked"
        exit 1
    }
    Write-Output "LESSON_VALIDATE_OK checked=$checked"
    return
}

if ($Index) {
    $count = Update-LibraryIndex
    Write-Output "INDEX_UPDATED lessons=$count"
    return
}

if ($ListPending) {
    if (-not (Test-Path $script:stateDir)) { Write-Output 'PENDING_NONE'; return }
    $lessons = @{}
    if (Test-Path $script:libraryDir) {
        foreach ($file in (Get-ChildItem $script:libraryDir -Recurse -Filter 'EXPERIENCE.md' -ErrorAction SilentlyContinue)) {
            $parsed = Read-LessonFile -Path $file.FullName
            if ($parsed.Task) { $lessons[[string]$parsed.Task] = $true }
        }
    }
    # Una tarea con NO_ENTRY ya fue procesada por el lider: no vuelve a pendiente.
    $noEntry = Join-Path $script:libraryDir 'NO_ENTRY.log'
    if (Test-Path $noEntry) {
        foreach ($line in (Get-Content $noEntry -Encoding UTF8)) {
            if ($line -match 'task=(task_[A-Za-z0-9_]+)') { $lessons[[string]$Matches[1]] = $true }
        }
    }
    $pending = 0
    foreach ($auditFile in (Get-ChildItem $script:stateDir -Filter 'audit-*.jsonl' -ErrorAction SilentlyContinue)) {
        $runId = $auditFile.BaseName -replace '^audit-', ''
        foreach ($entry in (Get-AuditEntries -RunId $runId)) {
            if ($entry.action -ne $script:markerAction) { continue }
            $taskId = [string]$entry.taskId
            if (-not $taskId -or $lessons.ContainsKey($taskId)) { continue }
            $pending++
            Write-Output "PENDING run=$runId task=$taskId motivo=$($entry.reason)"
        }
    }
    if (-not $pending) { Write-Output 'PENDING_NONE' }
    return
}

# Modo scaffold: -RunId [-TaskId | todas las pendientes del run]
if (-not $RunId) {
    throw 'Indica -RunId (con -TaskId opcional) o usa -Index / -Validate / -ListPending.'
}

if (-not $TaskId) {
    $candidates = @(Get-AuditEntries -RunId $RunId | Where-Object { $_.action -eq $script:markerAction } | ForEach-Object { [string]$_.taskId } | Where-Object { $_ } | Select-Object -Unique)
    $existing = @{}
    if (Test-Path $script:libraryDir) {
        foreach ($file in (Get-ChildItem $script:libraryDir -Recurse -Filter 'EXPERIENCE.md' -ErrorAction SilentlyContinue)) {
            $parsed = Read-LessonFile -Path $file.FullName
            if ($parsed.Task) { $existing[[string]$parsed.Task] = $true }
        }
    }
    $created = 0
    foreach ($candidate in $candidates) {
        if ($existing.ContainsKey($candidate)) { continue }
        # Splat condicional: ValidateSet de -Confidence rechaza cadenas vacias,
        # y -StateDir/-LibraryDir vacios son validos (fallback dentro del hijo).
        $childArgs = @('-NoProfile', '-File', $PSCommandPath, '-RunId', $RunId, '-TaskId', $candidate, '-Domain', $Domain)
        if ($StateDir) { $childArgs += @('-StateDir', $StateDir) }
        if ($LibraryDir) { $childArgs += @('-LibraryDir', $LibraryDir) }
        if ($Confidence) { $childArgs += @('-Confidence', $Confidence) }
        if ($Force) { $childArgs += '-Force' }
        & pwsh @childArgs
        if ($LASTEXITCODE -eq 0) { $created++ }
    }
    Write-Output "LESSON_SCAFFOLD_RUN created=$created"
    return
}

# Scaffold de una tarea concreta.
$entries = @(Get-AuditEntries -RunId $RunId -ForTaskId $TaskId)
$evidence = Get-RealEvidence -Entries $entries
if (-not $evidence.Count) {
    $hadMarker = @($entries | Where-Object { $_.action -eq $script:markerAction }).Count -gt 0
    $reason = if ($hadMarker) { 'solo_marcador_sin_eventos' } else { 'sin_evidencia_en_audit' }
    Add-NoEntry -RunId $RunId -TaskId $TaskId -Reason $reason
    Write-Output "NO_ENTRY task=$TaskId reason=$reason"
    return
}

$lessonPath = Join-Path (Join-Path (Join-Path $script:libraryDir $Domain) 'lessons') (Join-Path $TaskId 'EXPERIENCE.md')
if ((Test-Path $lessonPath) -and -not $Force) {
    Write-Output "LESSON_EXISTS=$lessonPath"
    return
}

$record = Get-DispatchRecord -RunId $RunId -TaskId $TaskId
$confidence = if ($Confidence) { $Confidence } else { 'low' }
$meta = @{
    task       = $TaskId
    run        = $RunId
    date       = (Get-Date).ToUniversalTime().ToString('o')
    domain     = $Domain
    confidence = $confidence
}
$evidenceLines = @($evidence | ForEach-Object { Format-EvidenceLine -Entry $_ })
$report = Get-WorkerReportSummary -RunId $RunId -TaskId $TaskId

New-LessonFile -Path $lessonPath -Meta $meta -CueText $Cue -LessonText $Lesson -EvidenceLines $evidenceLines -WorkerReport $report
Update-LibraryIndex | Out-Null

Write-Output "LESSON_CREATED=$lessonPath"
Write-Output "LESSON_NEXT=rellena Cue y Lesson, luego lesson.ps1 -Validate"
if ($record) { Write-Output "LESSON_CONTEXT task=$TaskId title=$($record.taskTitle) branch=$($record.branch) status=$($record.status)" }
