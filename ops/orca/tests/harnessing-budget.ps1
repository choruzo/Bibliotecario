# Test del decisor de presupuesto (P4): reglas diarias, cooldown, materia y
# briefing, con estado sintetico.

$ErrorActionPreference = 'Stop'

$orcaDir = Split-Path $PSScriptRoot -Parent
$budgetScript = Join-Path $orcaDir 'harnessing-budget.ps1'

$id = [guid]::NewGuid().ToString('N').Substring(0, 8)
$root = Join-Path ([IO.Path]::GetTempPath()) "orca-budget-test-$id"
$stateDir = Join-Path $root 'state'
$libraryDir = Join-Path $root 'library'
New-Item -ItemType Directory -Force -Path $stateDir, $libraryDir | Out-Null

function New-Lesson {
    param([string]$Domain, [string]$TaskId)
    $dir = Join-Path (Join-Path (Join-Path $libraryDir $Domain) 'lessons') $TaskId
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Set-Content -Path (Join-Path $dir 'EXPERIENCE.md') -Value "---`ntask: $TaskId`nconfidence: medium`n---`n`n## Cue`n`ncue`n`n## Lesson`n`nlesson`n`n## Evidence`n`n- [commit] x" -Encoding UTF8
}

function New-ProbeResult {
    param([string]$Label, [datetime]$At)
    $dir = Join-Path (Join-Path (Join-Path $libraryDir 'default') 'harnesses') $Label
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Set-Content -Path (Join-Path $dir 'RESULT.md') -Value '# probe' -Encoding UTF8
    (Get-Item (Join-Path $dir 'RESULT.md')).LastWriteTimeUtc = $At
}

function New-Briefing {
    param([string]$Domain)
    $dir = Join-Path $stateDir 'harnessing'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Set-Content -Path (Join-Path $dir "retro-$Domain-20261112.md") -Value '# briefing' -Encoding UTF8
}

try {
    # 1. Sin material: bloque.
    $out = (& pwsh -NoProfile -File $budgetScript -StateDir $stateDir -LibraryDir $libraryDir | Out-String)
    if ($out -notmatch 'BLOCK reason=no_material') { throw "Sin lecciones deberia bloquear por materia: $out" }

    # 2. Materia suficiente sin briefing: bloque.
    New-Lesson -Domain 'orchestration' -TaskId 'task_a1'
    New-Lesson -Domain 'orchestration' -TaskId 'task_a2'
    $out = (& pwsh -NoProfile -File $budgetScript -StateDir $stateDir -LibraryDir $libraryDir | Out-String)
    if ($out -notmatch 'BLOCK reason=no_briefing') { throw "Sin briefing deberia bloquear: $out" }

    # 3. Con briefing: PROCEED.
    New-Briefing -Domain 'orchestration'
    $out = (& pwsh -NoProfile -File $budgetScript -StateDir $stateDir -LibraryDir $libraryDir | Out-String)
    if ($out -notmatch 'PROCEED domain=orchestration') { throw "Con briefing deberia proceder: $out" }

    # 4. Tope diario: un probe reciente (2h) bloquea por cap y por cooldown.
    New-ProbeResult -Label 'probe-recente' -At ([datetimeoffset]::UtcNow.UtcDateTime.AddHours(-2))
    $out = (& pwsh -NoProfile -File $budgetScript -StateDir $stateDir -LibraryDir $libraryDir | Out-String)
    if ($out -notmatch 'BLOCK reason=daily_cap') { throw "Con 1 probe hoy (tope 1) deberia bloquear por cap: $out" }

    # 5. Cooldown: unico probe hace 30h (fuera de la ventana de 24h) pero dentro
    #    del cooldown de 48h.
    Remove-Item (Join-Path (Join-Path (Join-Path $libraryDir 'default') 'harnesses') 'probe-recente') -Recurse -Force
    New-ProbeResult -Label 'probe-antiguo' -At ([datetimeoffset]::UtcNow.UtcDateTime.AddHours(-30))
    $out = (& pwsh -NoProfile -File $budgetScript -StateDir $stateDir -LibraryDir $libraryDir -CooldownHours 48 | Out-String)
    if ($out -notmatch 'BLOCK reason=cooldown') { throw "Probe hace 30h con cooldown 48h deberia bloquear: $out" }

    # 6. Pasado el cooldown: PROCEED de nuevo.
    $out = (& pwsh -NoProfile -File $budgetScript -StateDir $stateDir -LibraryDir $libraryDir -CooldownHours 24 | Out-String)
    if ($out -notmatch 'PROCEED') { throw "Fuera de cooldown deberia proceder: $out" }

    Write-Output 'BUDGET_TEST_OK'
}
finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
