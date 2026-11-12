# Test del guard anti-junction (incidencia del 12-11: `git worktree remove
# --force` atraveso la junction de un worktree y vacio el .venv principal).
# Verifica que Remove-SharedLinks desmonta el enlace SIN tocar el destino.

$ErrorActionPreference = 'Stop'

$orcaDir = Split-Path $PSScriptRoot -Parent
. (Join-Path $orcaDir 'lib.ps1')

$id = [guid]::NewGuid().ToString('N').Substring(0, 8)
$root = Join-Path ([IO.Path]::GetTempPath()) "orca-junction-test-$id"
$decoy = Join-Path $root 'venv-principal'
$worktree = Join-Path $root 'worktree-falso'
New-Item -ItemType Directory -Force -Path $decoy, (Join-Path $worktree 'Scripts') | Out-Null
Set-Content -Path (Join-Path $decoy 'tesoro.txt') -Value 'no se borra' -Encoding UTF8
Set-Content -Path (Join-Path $decoy 'Scripts\python.exe') -Value 'binario simulado' -Encoding UTF8

try {
    # Junction del worktree apuntando al directorio señuelo (como Orca la crea).
    New-Item -ItemType Junction -Path (Join-Path $worktree '.venv') -Target $decoy | Out-Null
    if (-not (Test-Path (Join-Path $worktree '.venv\Scripts\python.exe'))) { throw 'La junction no esta operativa' }

    $before = @(Get-ChildItem $decoy -Recurse -File | Measure-Object).Count
    if ($before -ne 2) { throw "El señuelo deberia tener 2 ficheros, tiene $before" }

    # El camino destructivo REAL que destruyo el .venv (comprobacion de que sin
    # guard el dano ocurre, para que el test no pierda sentido): Remove-Item
    # -Recurse sobre la junction sigue el destino. Aqui NO lo ejecutamos; solo
    # verificamos el guard.

    $detached = @(Remove-SharedLinks -Path $worktree)
    if ($detached.Count -ne 1) { throw "Remove-SharedLinks deberia desmontar 1 enlace, desmonto $($detached.Count)" }
    if (Test-Path (Join-Path $worktree '.venv')) { throw 'La junction sigue montada tras Remove-SharedLinks' }
    $after = @(Get-ChildItem $decoy -Recurse -File | Measure-Object).Count
    if ($after -ne 2) { throw "El señuelo quedo danado: $after ficheros (esperados 2)" }
    if (-not (Test-Path (Join-Path $decoy 'tesoro.txt'))) { throw 'El fichero señuelo desaparecio' }

    # Y la funcion de cleanup usa la de lib (invariante estatico cubierto por
    # kit-regression); aqui garantizamos que re-ejecutar no revienta.
    $again = @(Remove-SharedLinks -Path $worktree)
    if ($again.Count -ne 0) { throw 'Segunda pasada no debe desmontar nada' }

    Write-Output 'JUNCTION_SAFETY_OK'
}
finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
