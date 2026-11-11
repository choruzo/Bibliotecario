# Responde una pregunta de un worker usando el subagente advisor (OpenCode).
# Lo llama loop-runner.ps1 cuando el bucle termina en LOOP=QUESTION y -AutoAnswer
# esta activo. Si el asesor no lo ve claro, no responde: escala.

param(
    [Parameter(Mandatory)][string]$RunId,
    [string]$QuestionFile,
    [string]$Agent = 'advisor',
    [int]$MaxContextChars = 12000,
    [switch]$DryRun,
    [switch]$NoReply
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib.ps1')

$stateDir = Get-StateDir
$repoRoot = Get-RepoRoot
$answersDir = Join-Path $stateDir "answers\$RunId"

function Write-Result {
    param([string]$Status, [string]$Reason = '')
    Write-Output "AUTOANSWER=$Status"
    if ($Reason) { Write-Output "AUTOANSWER_REASON=$($Reason -replace "`r?`n", ' ')" }
}

function Limit-Text {
    param([string]$Text, [int]$Max)
    if (-not $Text) { return '' }
    if ($Text.Length -le $Max) { return $Text }
    return $Text.Substring(0, $Max) + "`n...[truncado]"
}

function Quote-Arg {
    param([string]$Value)
    if ($Value -match '[\s"]') { return '"' + ($Value -replace '"', '\"') + '"' }
    return $Value
}

if ($RunId -notmatch '^run_[A-Za-z0-9_]+$') {
    Write-Result -Status 'FAILED' -Reason "RunId invalido: $RunId"
    exit 1
}

if (-not $QuestionFile) { $QuestionFile = Join-Path $stateDir "question-$RunId.json" }
if (-not (Test-Path $QuestionFile)) {
    Write-Result -Status 'FAILED' -Reason "No existe el archivo de pregunta: $QuestionFile"
    exit 1
}

try {
    $question = Get-Content $QuestionFile -Raw -Encoding UTF8 | ConvertFrom-Json
}
catch {
    Write-Result -Status 'FAILED' -Reason "No se pudo leer la pregunta: $($_.Exception.Message)"
    exit 1
}

$message = $question.message
if (-not $message) {
    Write-Result -Status 'FAILED' -Reason 'La pregunta no contiene el mensaje de Orca.'
    exit 1
}

$messageId = [string]$message.id
$body = [string]$message.body
if (-not $body -and $message.subject) { $body = [string]$message.subject }
$optionsJson = if ($null -ne $message.options) { $message.options | ConvertTo-Json -Compress -Depth 10 } else { '[]' }

$taskId = $null
$payload = $message.payload
if ($payload -is [string]) {
    try { $parsedPayload = $payload | ConvertFrom-Json } catch { $parsedPayload = $null }
    if ($parsedPayload -and $parsedPayload.taskId) { $taskId = [string]$parsedPayload.taskId }
    elseif ($payload -match 'task_[A-Za-z0-9_]+') { $taskId = $Matches[0] }
}
elseif ($payload -and $payload.taskId) {
    $taskId = [string]$payload.taskId
}

$task = $null
$worktree = $null
try {
    $tasks = @((Get-OrcaResult (Invoke-OrcaTaskList -RunId $RunId)).tasks)
    if ($taskId) { $task = @($tasks | Where-Object { $_.id -eq $taskId }) | Select-Object -First 1 }
}
catch {
    # Sin Orca accesible el asesor puede seguir con el contexto de la pregunta;
    # si no es suficiente, escalara.
}

try {
    $dispatches = @(Read-Dispatches -RunId $RunId)
    if ($taskId) {
        $record = @($dispatches | Where-Object { $_.taskId -eq $taskId }) | Select-Object -Last 1
        if ($record -and $record.worktree) { $worktree = [string]$record.worktree }
    }
}
catch { }

if (-not $worktree -or -not (Test-Path $worktree)) { $worktree = $repoRoot }

$report = ''
$reportPath = Join-Path $worktree 'report.md'
if (Test-Path $reportPath) {
    $report = Limit-Text -Text (Get-Content $reportPath -Raw -Encoding UTF8) -Max 5000
}

$statusText = ''
try {
    $statusText = (& git -C $worktree status --porcelain 2>$null | Out-String).Trim()
    $diffStat = (& git -C $worktree diff --stat 2>$null | Out-String).Trim()
    $headStat = (& git -C $worktree show --stat --oneline -1 2>$null | Out-String).Trim()
    $statusText = (@($statusText, $diffStat, $headStat) | Where-Object { $_ }) -join "`n"
}
catch { }

$spec = if ($task -and $task.spec) { [string]$task.spec } else { '(no disponible)' }
$taskTitle = if ($task -and $task.task_title) { [string]$task.task_title } else { '(no disponible)' }
$body = Limit-Text -Text $body -Max 3000
$spec = Limit-Text -Text $spec -Max 6000
$objective = '(no disponible)'
try {
    $run = Get-OrcaRun (Invoke-Orca orchestration run-show --id $RunId --json)
    if ($run -and $run.objective) { $objective = [string]$run.objective }
}
catch { }

$context = @"
# Asesor del ciclo Orca

Eres el asesor tecnico read-only del worker. No editas codigo, no ejecutas
comandos y no decides cambios de alcance. Responde en espanol y SOLO con el
bloque de formato final.

## Pregunta del worker

$body

## Opciones ofrecidas

$optionsJson

## Run

- id: $RunId
- objetivo: $objective
- tarea: $taskTitle
- task_id: $(if ($taskId) { $taskId } else { '(no identificada)' })

## Spec de la tarea

$spec

## Reporte del worker

$report

## Estado y ultimo commit del worktree

$statusText

## Reglas

1. Si la respuesta esta dentro de la spec y es reversible, decide con la opcion
   mas simple que cumpla los criterios de aceptacion.
2. Si falta evidencia, dilo; no inventes resultados de tests.
3. Escala (DECISION: ESCALATE) si la pregunta cambia el alcance, anade
   dependencias, toca secretos o datos persistentes, implica push/merge/rebase,
   o hay ambiguedad real.
4. No propongas comandos destructivos ni cambios fuera del worktree.
5. Se breve: la respuesta se enviara tal cual al worker.

## Formato obligatorio

DECISION: ANSWER
ANSWER: <decision concreta y accionable>
WHY: <una o dos frases>

o

DECISION: ESCALATE
ANSWER: <que debe decidir el humano>
WHY: <por que no puedes decidirlo tu>
"@

$context = $context -replace '(?i)((api[_-]?key|password|secret|token)\s*[:=]\s*)\S+', '$1[redactado]'

New-Item -ItemType Directory -Force -Path $answersDir | Out-Null
$safeId = if ($messageId) { $messageId -replace '[^A-Za-z0-9_.-]', '_' } else { 'question' }
$promptPath = Join-Path $answersDir "$safeId-prompt.md"
Set-Content -Path $promptPath -Value $context -Encoding UTF8

if ($DryRun) {
    Write-Result -Status 'DRYRUN' -Reason "Prompt: $promptPath"
    exit 0
}

$opencode = Get-Command opencode -ErrorAction SilentlyContinue
if (-not $opencode) {
    Write-Result -Status 'FAILED' -Reason 'No se encontro opencode en el PATH.'
    exit 1
}

$raw = ''
$stderrText = ''
$exitCode = 1
try {
    $rawPath = Join-Path $answersDir "$safeId-raw.jsonl"
    $errPath = Join-Path $answersDir "$safeId-stderr.log"
    $messageText = 'Responde solo con el formato pedido en el archivo adjunto.'
    $argsList = @(
        'run', '--agent', $Agent, '--format', 'json',
        '--title', "advisor $RunId $safeId",
        '--file', $promptPath,
        $messageText
    )
    $argLine = (@($argsList | ForEach-Object { Quote-Arg $_ }) -join ' ')
    $proc = Start-Process -FilePath $opencode.Source -ArgumentList $argLine `
        -RedirectStandardOutput $rawPath -RedirectStandardError $errPath `
        -NoNewWindow -Wait -PassThru
    $exitCode = $proc.ExitCode
    if (Test-Path $rawPath) { $raw = Get-Content $rawPath -Raw -Encoding UTF8 }
    if (Test-Path $errPath) { $stderrText = Get-Content $errPath -Raw -Encoding UTF8 }
}
catch {
    Write-Result -Status 'FAILED' -Reason "Fallo al invocar advisor: $($_.Exception.Message)"
    exit 1
}

$textParts = @()
foreach ($line in ($raw -split "`r?`n")) {
    if (-not $line.Trim()) { continue }
    try { $event = $line | ConvertFrom-Json } catch { continue }
    if ($event.type -eq 'text' -and $event.part -and $event.part.text) {
        $textParts += [string]$event.part.text
    }
}

$responseText = ($textParts -join "`n").Trim()
if (-not $responseText) {
    # Fallback por si el CLI devuelve un unico objeto JSON.
    try {
        $single = $raw | ConvertFrom-Json
        if ($single.part -and $single.part.text) { $responseText = [string]$single.part.text }
        elseif ($single.text) { $responseText = [string]$single.text }
    }
    catch { }
}
if (-not $responseText) {
    $errBrief = if ($stderrText) { ($stderrText -replace "`r?`n", ' ').Substring(0, [Math]::Min(300, ($stderrText -replace "`r?`n", ' ').Length)) } else { '' }
    Write-Result -Status 'FAILED' -Reason "advisor no devolvio texto (exit $exitCode). $errBrief"
    exit 1
}

$responseText = $responseText -replace '(?s)^```[a-zA-Z]*\r?\n', '' -replace '(?s)\r?\n```\s*$', ''
$lines = @($responseText -split "`r?`n")
$decision = $null
$decisionIndex = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*DECISION:\s*(ANSWER|ESCALATE)\b') {
        $decision = $Matches[1].ToUpperInvariant()
        $decisionIndex = $i
    }
}

$answerLines = @()
$whyLines = @()
if ($decisionIndex -ge 0) {
    $section = 'answer'
    for ($i = $decisionIndex + 1; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ($line -match '^\s*ANSWER:\s*(.*)$') {
            $section = 'answer'
            if ($Matches[1]) { $answerLines += $Matches[1] }
            continue
        }
        if ($line -match '^\s*WHY:\s*(.*)$') {
            $section = 'why'
            if ($Matches[1]) { $whyLines += $Matches[1] }
            continue
        }
        if ($section -eq 'answer') { $answerLines += $line }
        elseif ($section -eq 'why') { $whyLines += $line }
    }
}
$answer = ($answerLines -join "`n").Trim()
$why = ($whyLines -join "`n").Trim()

$log = [ordered]@{
    runId      = $RunId
    messageId  = $messageId
    taskId     = $taskId
    decision   = $decision
    answer     = $answer
    why        = $why
    agent      = $Agent
    at         = (Get-Date).ToUniversalTime().ToString('o')
    promptPath = $promptPath
    raw        = $responseText
    stderr     = Limit-Text -Text $stderrText -Max 2000
    exitCode   = $exitCode
    auto       = -not $NoReply
}
$logPath = Join-Path $answersDir "$safeId.json"
$log | ConvertTo-Json -Depth 20 | Set-Content $logPath -Encoding UTF8

if (-not $decision -or $decisionIndex -lt 0 -or -not $answer) {
    Write-Result -Status 'FAILED' -Reason "Respuesta del asesor sin formato valido: $($responseText.Substring(0, [Math]::Min(200, $responseText.Length)))"
    exit 1
}

if ($decision -eq 'ESCALATE') {
    Write-Result -Status 'ESCALATED' -Reason $answer
    exit 0
}

if ($NoReply) {
    Write-Result -Status 'NOREPLY' -Reason $answer
    exit 0
}

try {
    $coordinator = if ($question.PSObject.Properties['coordinator'] -and $question.coordinator) { [string]$question.coordinator } else { Get-Coordinator }
    $reply = Invoke-Orca orchestration reply --id $messageId --body $answer --run $RunId --from $coordinator --json
    if (-not $reply.ok) {
        Write-Result -Status 'FAILED' -Reason "Orca rechazo la respuesta: $($reply.error.message)"
        exit 1
    }
    try {
        $current = Get-Content $QuestionFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$current.message.id -eq $messageId) { Remove-Item $QuestionFile -Force }
    }
    catch { }
}
catch {
    Write-Result -Status 'FAILED' -Reason "No se pudo responder: $($_.Exception.Message)"
    exit 1
}

Write-Result -Status 'ANSWERED' -Reason $answer
