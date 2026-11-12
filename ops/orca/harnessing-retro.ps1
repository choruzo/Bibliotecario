# Retro de harnessing al cierre de un bucle (camino hacia el auto-mejoramiento,
# PRD docs/08-prd-harnessing.md, etapa 1 del roadmap).
#
# Encadena lo que hoy se hace a mano tras LOOP=DONE:
#   1. Recoge lecciones pendientes del run (-RunId) con lesson.ps1.
#   2. Analiza la libreria: dominio con >= -MinLessons lecciones.
#   3. Compone un briefing de hipotesis para el agente harness-editor.
#   4. (-CommissionEditor) Abre la sesion del editor y le encarga la variante.
# Nunca lanza el probe ni adopta nada: deja TODO listo y devuelve el comando
# que el humano debe aprobar y ejecutar.
#
# Uso:
#   harnessing-retro.ps1 -RunId <run>                    # lecciones + analisis + briefing
#   harnessing-retro.ps1 -RunId <run> -CommissionEditor  # ademas abre el editor
#   harnessing-retro.ps1                                 # solo analisis de la libreria

param(
    [string]$RunId,
    [string]$LibraryDir,
    [string]$StateDir,
    [int]$MinLessons = 2,
    [switch]$CommissionEditor,
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$script:stateDir = if ($StateDir) { $StateDir } else { Get-StateDir }
$script:libraryDir = if ($LibraryDir) { $LibraryDir } else { Get-LibraryRoot }
$script:retroDir = Join-Path $script:stateDir 'harnessing'

# --- 1. Lecciones pendientes del run -----------------------------------------

$pendingCount = 0
if ($RunId) {
    $pending = (& pwsh -NoProfile -File (Join-Path $PSScriptRoot 'lesson.ps1') -ListPending -StateDir $script:stateDir -LibraryDir $script:libraryDir | Out-String)
    if ($pending -match 'task=task_') {
        Write-Host "[retro] lecciones pendientes; scaffoldeando"
        if (-not $DryRun) {
            $scaffold = (& pwsh -NoProfile -File (Join-Path $PSScriptRoot 'lesson.ps1') -RunId $RunId -StateDir $script:stateDir -LibraryDir $script:libraryDir | Out-String)
            Write-Host $scaffold.TrimEnd()
        }
    }
    else {
        Write-Host '[retro] sin lecciones pendientes en el run'
    }
}

# --- 2. Analisis de la libreria ----------------------------------------------

if (-not (Test-Path $script:libraryDir)) { throw "No existe la libreria: $($script:libraryDir)" }
# Parse directo de las lecciones (cue/lesson/confidence por fichero).
$domainStats = @{}
foreach ($file in (Get-ChildItem $script:libraryDir -Recurse -Filter 'EXPERIENCE.md' -ErrorAction SilentlyContinue)) {
    $rel = $file.FullName.Substring($script:libraryDir.Length + 1) -replace '\\', '/'
    $domain = ($rel -split '/')[0]
    if (-not $domainStats.ContainsKey($domain)) { $domainStats[$domain] = @() }
    $text = Get-Content $file.FullName -Raw -Encoding UTF8
    $cue = if ($text -match '(?ms)## Cue\r?\n\r?\n(.+?)\r?\n\r?\n## Lesson') { $Matches[1].Trim() } else { '' }
    $lesson = if ($text -match '(?ms)## Lesson\r?\n\r?\n(.+?)\r?\n\r?\n## Evidence') { $Matches[1].Trim() } else { '' }
    $confidence = if ($text -match 'confidence:\s*(\w+)') { $Matches[1] } else { 'low' }
    $domainStats[$domain] += @{ path = $rel; cue = $cue; lesson = $lesson; confidence = $confidence }
}

Write-Host '[retro] lecciones por dominio:'
$candidate = $null
foreach ($domain in ($domainStats.Keys | Sort-Object)) {
    $count = @($domainStats[$domain]).Count
    Write-Host ("  {0}: {1} leccion(es)" -f $domain, $count)
    if ($count -ge $MinLessons -and -not $candidate) { $candidate = $domain }
}

if (-not $candidate) {
    Write-Output "RETRO_NONE need>=${MinLessons} lecciones por dominio"
    return
}
Write-Host "[retro] dominio candido: ${candidate}"

# --- 3. Briefing de hipotesis para el editor ----------------------------------

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
New-Item -ItemType Directory -Force -Path $script:retroDir | Out-Null
$briefPath = Join-Path $script:retroDir "retro-${candidate}-${stamp}.md"
$runNote = ''
if ($RunId) { $runNote = " tras el run ``$RunId``" }
$briefLines = @(
    "# Retro de harnessing - dominio ``${candidate}``",
    '',
    ("- Generada: " + (Get-Date -Format 'yyyy-MM-dd HH:mm') + $runNote),
    "- Umbral aplicado: >= ${MinLessons} lecciones en el dominio.",
    '',
    '## Lecciones del dominio (cue, lesson, confidence)',
    ''
)
foreach ($entry in $domainStats[$candidate]) {
    $briefLines += ("### $($entry.path) [confidence: $($entry.confidence)]")
    $briefLines += ''
    $briefLines += ("- **Cue**: $($entry.cue)")
    $briefLines += ("- **Lesson**: $($entry.lesson)")
    $briefLines += ''
}
$briefLines += @(
    '## Encargo para el harness-editor',
    '',
    'Analiza las lecciones de arriba: si comparten un patron de fallo que un cambio',
    'del harness del worker podria prevenir, propone UNA variante minima',
    '(`.orca-run/harness-variants/<nombre>/` con RATIONALE citando las lecciones).',
    'Si las lecciones apuntan a que el problema es de especificacion (criterios',
    'ambiguos, sin needles verificables), NO propongas variante: respondelo y',
    'propón la mejora de spec. El contraste decide, no la opinion.',
    '',
    'Recordatorio de reglas: solo superficies del worker (worker.md, AGENTS.md,',
    'skills), denegaciones intactas, tope always-on 24000, un cambio una hipotesis.'
)
Set-Content -Path $briefPath -Value (($briefLines -join "`r`n") + "`r`n") -Encoding UTF8
Write-Host "[retro] briefing: ${briefPath}"

# --- 4. Comision del editor (opt-in) -----------------------------------------

$editorSession = $null
if ($CommissionEditor) {
    if ($DryRun) {
        Write-Host '[retro] -DryRun: no abro la sesion del editor'
    }
    else {
        $body = @{
            title    = "harness-editor: retro ${candidate}"
            agent    = 'harness-editor'
            location = @{ directory = ((Get-RepoRoot) -replace '\\', '/') }
        } | ConvertTo-Json -Compress -Depth 10
        $escaped = $body -replace '"', '\"'
        $raw = & opencode api POST /api/session --data $escaped 2>&1
        if ($LASTEXITCODE -ne 0) { throw "No se pudo crear la sesion del editor: $($raw | Out-String)" }
        $editorSession = (((($raw | Out-String).Trim() | ConvertFrom-Json).data).id)
        Write-Host "[retro] sesion del editor: ${editorSession}"
        $oneLine = "Encargo nuevo: leelo en ${briefPath} y ejecutalo. Responde con la ruta de la variante y la hipotesis medible, o con la mejora de spec si las lecciones apuntan a la especificacion."
        $editorOut = (& opencode run --session $editorSession $oneLine 2>&1 | Out-String)
        Write-Host $editorOut.TrimEnd()
    }
}

Write-Output "RETRO_DIR=$script:retroDir"
Write-Output "RETRO_BRIEF=$briefPath"
Write-Output "RETRO_DOMAIN=$candidate"
Write-Output "RETRO_EDITOR=$(if ($editorSession) { $editorSession } else { '-' })"
Write-Output "RETRO_NEXT=pwsh -NoProfile -File ops/orca/harness-probe.ps1 -SpecFile <spec> -VariantDir <variante> -EvidenceAudit <auditor> -SanityImport <import>"
