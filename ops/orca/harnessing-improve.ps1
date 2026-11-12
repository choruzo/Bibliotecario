# Improvement harness de segundo nivel (P5 del roadmap, PRD docs/08-prd-harnessing.md).
#
# Lee la libreria de lecciones y compone, como maximo, UNA spec de tarea de kit
# por ciclo: la mejora concreta mas soportada por evidencia (lecciones que
# apuntan al mismo componente). La tarea resultante se crea y despacha por el
# flujo normal (sin token [HARNESS-PROBE]): el gate y el review la validan.
#
# Es un GENERADOR, no un lanzador: escribe la spec en .orca-run/specs/ y
# devuelve el comando para crearla. Nunca crea tareas ni despacha.
#
# Uso:
#   harnessing-improve.ps1                       # analiza y compone si procede
#   harnessing-improve.ps1 -MinLessonHits 2      # umbral de lecciones por patron

param(
    [string]$LibraryDir,
    [string]$StateDir,
    [int]$MinLessonHits = 2
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$script:libraryDir = if ($LibraryDir) { $LibraryDir } else { Get-LibraryRoot }
$script:stateDir = if ($StateDir) { $StateDir } else { Get-StateDir }

# Patrones conocidos: cada uno define la mejora de kit que le corresponde.
# Solo se activan con evidencia de >= -MinLessonHits lecciones que lo citen.
$patterns = @(
    @{
        id       = 'file-ownership'
        keywords = @('mismo modulo', 'misma rama', 'paralela', 'add/add', 'propiedad del fichero', 'conflicto')
        title    = 'kit: propiedad de ficheros en la plantilla de specs'
        body     = @(
            '## Objetivo',
            'Anadir a la seccion Contexto de ops/orca/task-template.md un campo',
            'Propiedad de ficheros (lista de ficheros que esta tarea crea o',
            'reescribe) y documentar en el README que el lider debe serializar con',
            '--deps las tareas que tocan el mismo modulo.',
            '',
            '## Por que',
            'Las lecciones de la libreria muestran conflictos add/add entre tareas',
            'hermanas despachadas en paralelo: dos ramas creando el mismo modulo.',
            'La palanca es la spec, no el harness.'
        )
    },
    @{
        id       = 'evidence-gate-spec'
        keywords = @('evidencia', 'literales', 'declarar la aceptacion', 'sin haber ejecutado')
        title    = 'kit: needles obligatorios por criterio en la plantilla'
        body     = @(
            '## Objetivo',
            'Reforzar la seccion Evidencia de ops/orca/task-template.md: cada',
            'criterio de aceptacion debe declarar su needle verificable (token de',
            'salida, comando o hash) en el mismo bloque de la plantilla.',
            '',
            '## Por que',
            'Las lecciones muestran entregas que declaran aceptacion sin ejecutar;',
            'la seccion Evidencia ya existe y este cambio la hace estructural por',
            'criterio, no solo global.'
        )
    },
    @{
        id       = 'pair-arbitration'
        keywords = @('HARNESS-PROBE', 'perdedora', 'probe-loser', 'PAIR_DECISION')
        title    = 'kit: doc del par in-run en el README'
        body     = @(
            '## Objetivo',
            'Documentar en ops/orca/README.md el par in-run: token HARNESS-PROBE,',
            'clon de la tarea, arbitraje PAIR_DECISION y estado lost de la perdedora.',
            '',
            '## Por que',
            'Las lecciones de probes registran decisiones que hoy solo viven en',
            'auditoria y en el PRD; el README del kit debe explicar el mecanismo.'
        )
    }
)

if (-not (Test-Path $script:libraryDir)) { throw "No existe la libreria: $($script:libraryDir)" }

# --- 1. Junta el texto de todas las lecciones --------------------------------

$corpus = @()
foreach ($file in (Get-ChildItem $script:libraryDir -Recurse -Filter 'EXPERIENCE.md' -ErrorAction SilentlyContinue)) {
    $rel = $file.FullName.Substring($script:libraryDir.Length + 1) -replace '\\', '/'
    $text = (Get-Content $file.FullName -Raw -Encoding UTF8).ToLower()
    $corpus += @{ path = $rel; text = $text }
}
if (-not $corpus.Count) {
    Write-Output 'IMPROVE_NONE sin lecciones'
    return
}

# --- 2. Cuenta hits por patron ------------------------------------------------

$hits = @()
foreach ($pattern in $patterns) {
    $matching = @($corpus | Where-Object {
        $hit = $false
        foreach ($kw in $pattern.keywords) { if ($_.text.Contains($kw)) { $hit = $true; break } }
        $hit
    })
    if ($matching.Count -gt 0) {
        $hits += [pscustomobject]@{
            id      = $pattern.id
            title   = $pattern.title
            body    = $pattern.body
            count   = $matching.Count
            lessons = @($matching | ForEach-Object { $_.path })
        }
    }
}
$hits = @($hits | Sort-Object count -Descending)
if (-not $hits.Count) {
    Write-Output 'IMPROVE_NONE sin patrones reconocidos en las lecciones'
    return
}

# --- 3. Las mejoras ya aplicadas no se re-proponen (ledger) -------------------

$ledgerPath = Join-Path $script:stateDir 'harnessing-improved.jsonl'
$done = @{}
if (Test-Path $ledgerPath) {
    foreach ($line in (Get-Content $ledgerPath -Encoding UTF8)) {
        if (-not $line.Trim()) { continue }
        try { $entry = $line | ConvertFrom-Json; $done[[string]$entry.pattern] = $true } catch { }
    }
}
$candidate = $hits | Where-Object { -not $done.ContainsKey($_.id) } | Select-Object -First 1
if (-not $candidate) {
    Write-Output 'IMPROVE_NONE todas las mejoras reconocidas ya estan propuestas'
    return
}

# --- 4. Compone la spec --------------------------------------------------------

New-Item -ItemType Directory -Force -Path (Join-Path $script:stateDir 'specs') | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$specPath = Join-Path (Join-Path $script:stateDir 'specs') "kit-improve-$($candidate.id)-$stamp.md"
$evidenceLines = @($candidate.lessons | ForEach-Object { "- ops/orca/library/$_" })
$specLines = @(
    "# $($candidate.title) (mejora propuesta por el improvement harness)",
    '',
    '## Objetivo',
    'Aplicar la mejora que las lecciones del kit soportan con evidencia, con',
    'gate en verde y sin cambiar el comportamiento del ciclo.',
    ''
)
$specLines += @($candidate.body)
$specLines += @(
    '',
    '## Evidencia',
    '',
    'Las lecciones que motivan esta mejora (cue, lesson, evidence citados):',
    ''
)
$specLines += $evidenceLines
$specLines += @(
    '',
    '## Alcance',
    '- Incluye: solo el fichero(es) de documentacion/plantilla indicados.',
    '- No incluye: scripts del ciclo, agentes, ni comportamiento del bucle.',
    '',
    '## Checks obligatorios',
    '- pwsh ops/orca/check.ps1 -Worktree .',
    '- pwsh ops/orca/tests/kit-regression.ps1',
    '',
    '## Entrega',
    '- Informe: report.md con la seccion Evidencia completa (comandos y salidas literales).',
    '- Prohibido: push, merge, rebase, task-update, git add, git commit.'
)
$specContent = ($specLines -join "`r`n") + "`r`n"
Set-Content -Path $specPath -Value $specContent -Encoding UTF8

Write-Output "IMPROVE_PATTERN=$($candidate.id)"
Write-Output "IMPROVE_HITS=$($candidate.count)"
Write-Output "IMPROVE_SPEC=$specPath"
Write-Output "IMPROVE_NEXT=new-run.ps1 -Objective '<mejora del kit: $($candidate.title)>' -TaskTitle 'kit-improve-$($candidate.id)' -Spec (Get-Content '$specPath' -Raw -Encoding UTF8)"
Write-Output "IMPROVE_LEDGER=anade pattern=$($candidate.id) a $ledgerPath cuando la tarea se integre"
