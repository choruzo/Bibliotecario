# Auto-probe presupuestado (P4 del roadmap de auto-mejoramiento, PRD docs/08-prd-harnessing.md).
#
# Guardián del presupuesto de harnessing: decide si procede lanzar un probe de
# calibración y con qué spec. Reglas (todas verificables por test):
#   - Tope absoluto: no lanza si hay -MaxPerDay probes en las ultimas 24h.
#   - Cooldown: no lanza si el ultimo probe hizo menos de -CooldownHours horas.
#   - Materia: no lanza sin >= -MinLessons lecciones en un dominio y sin
#     briefing de retro pendiente de ejecutar (la retro ya compuso hipotesis).
#
# Es un DECISOR, no un lanzador: devuelve PROCEED/BLOCK con motivo y el comando
# exacto a ejecutar si PROCEED. El humano (o el lider) lanza el probe. Nunca
# gasta workers por su cuenta.
#
# Uso:
#   harnessing-budget.ps1 -StateDir .orca-run -LibraryDir ops/orca/library
#   harnessing-budget.ps1 -MaxPerDay 1 -CooldownHours 12 -MinLessons 2

param(
    [string]$StateDir,
    [string]$LibraryDir,
    [int]$MaxPerDay = 1,
    [int]$CooldownHours = 12,
    [int]$MinLessons = 2
)

. (Join-Path $PSScriptRoot 'lib.ps1')

$script:stateDir = if ($StateDir) { $StateDir } else { Get-StateDir }
$script:libraryDir = if ($LibraryDir) { $LibraryDir } else { Get-LibraryRoot }
$probeDir = Join-Path $script:libraryDir 'default\harnesses'
$ledgerPath = Join-Path $script:stateDir 'harnessing-budget.jsonl'

# --- Probes ya gastados (del ledger y del arbol de la libreria) --------------

function Get-ProbeHistory {
    # Devuelve todos los eventos de probe conocidos con su fecha UTC.
    param([string]$LedgerPath, [string]$ProbeDir)

    $events = @()
    if (Test-Path $LedgerPath) {
        foreach ($line in (Get-Content $LedgerPath -Encoding UTF8)) {
            if (-not $line.Trim()) { continue }
            try { $events += ($line | ConvertFrom-Json) } catch { }
        }
    }
    # Fallback honesto: los RESULT.md del arbol cuentan aunque el ledger falte.
    if (Test-Path $ProbeDir) {
        foreach ($result in (Get-ChildItem $ProbeDir -Recurse -Filter 'RESULT.md' -ErrorAction SilentlyContinue)) {
            $events += [pscustomobject]@{ at = $result.LastWriteTimeUtc.ToString('o'); kind = 'result'; path = $result.FullName }
        }
    }
    $parsed = @()
    foreach ($event in $events) {
        if (-not $event.at) { continue }
        try { $parsed += [datetimeoffset]::Parse([string]$event.at).UtcDateTime } catch { }
    }
    return @($parsed | Sort-Object -Descending)
}

$now = [datetimeoffset]::UtcNow
$probeTimes = @(Get-ProbeHistory -LedgerPath $ledgerPath -ProbeDir $probeDir)
Write-Host "[budget] probes conocidos: $($probeTimes.Count)"
if ($probeTimes.Count -gt 0) {
    $lastAt = $probeTimes[0]
    $hours = ($now.UtcDateTime - $lastAt).TotalHours
    Write-Host ("[budget] ultimo probe hace {0:N1} h" -f $hours)
    $in24h = @($probeTimes | Where-Object { ($now.UtcDateTime - $_).TotalHours -lt 24 }).Count
    Write-Host "[budget] probes en las ultimas 24h: $in24h (tope $MaxPerDay)"
    if ($in24h -ge $MaxPerDay) {
        Write-Output "BLOCK reason=daily_cap probes24h=$in24h max=$MaxPerDay"
        return
    }
    if ($hours -lt $CooldownHours) {
        Write-Output "BLOCK reason=cooldown hours=$([math]::Round($hours,1)) need=$CooldownHours"
        return
    }
}

# --- Materia: dominio con lecciones suficientes -------------------------------

$domainStats = @{}
if (Test-Path $script:libraryDir) {
    foreach ($file in (Get-ChildItem $script:libraryDir -Recurse -Filter 'EXPERIENCE.md' -ErrorAction SilentlyContinue)) {
        $rel = $file.FullName.Substring($script:libraryDir.Length + 1) -replace '\\', '/'
        $domain = ($rel -split '/')[0]
        if (-not $domainStats.ContainsKey($domain)) { $domainStats[$domain] = 0 }
        $domainStats[$domain]++
    }
}
$domain = ($domainStats.GetEnumerator() | Where-Object { $_.Value -ge $MinLessons } | Sort-Object Value -Descending | Select-Object -First 1)
if (-not $domain) {
    Write-Output "BLOCK reason=no_material need>=${MinLessons} lecciones por dominio"
    return
}
Write-Host "[budget] dominio candido: $($domain.Key) ($($domain.Value) lecciones)"

# --- Briefing de retro pendiente (hipotesis compuesta y sin ejecutar) ---------

$retroDir = Join-Path $script:stateDir 'harnessing'
$briefing = $null
if (Test-Path $retroDir) {
    $briefing = Get-ChildItem $retroDir -Filter "retro-$($domain.Key)-*.md" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
}
if (-not $briefing) {
    Write-Output "BLOCK reason=no_briefing dominio=$($domain.Key) ejecuta harnessing-retro.ps1 -CommissionEditor"
    return
}

Write-Output "PROCEED domain=$($domain.Key) lessons=$($domain.Value) briefing=$($briefing.Name)"
Write-Output "NEXT=pwsh -NoProfile -File ops/orca/harnessing-retro.ps1 -CommissionEditor  # si la variante no existe aun"
Write-Output "NEXT=pwsh -NoProfile -File ops/orca/harness-probe.ps1 -SpecFile <spec> -VariantDir .orca-run/harness-variants/<nombre> -EvidenceAudit <auditor> -SanityImport <import>"
