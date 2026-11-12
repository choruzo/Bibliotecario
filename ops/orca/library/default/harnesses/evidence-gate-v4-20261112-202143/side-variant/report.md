# Reporte · task_8075c3c937cc

## Resultado

Se entrega `scripts/h3/pdf_regression.py`, comparador determinista (solo stdlib)
que toma las dos pasadas del arnés y el baseline de T0 y emite las seis líneas
de veredicto con `SAME`/`CHANGED`/`REGRESSION` y códigos de salida 0/1; más
`tests/test_pdf_regression.py` (6 casos unittest, fixture sintético en
`tempfile`, cubre los cinco modos de fallo), `docs/h3/pdf-regression.md` (los
tres comandos reproducibles sin leer el código) y este informe. El gate pasa
(`CHECK_OK`). La ejecución real sobre los 17 PDF (dos pasadas con
`PYTHONHASHSEED=0` en procesos separados + comparador) produjo el veredicto
esperado `verdict=CHANGED reason=none` con `sha_equal=15 sha_changed=2` y
`audit real_prose=0 real_equation=0`; los `delta_pct` son coherentes con los
`secs` (recálculo manual, tolerancia 0,1). Durante la sesión el comparador
detectó además, sobre datos reales, los otros dos motivos de REGRESSION
(`nondeterministic` y `unexpected_sha`) provocados por el artefacto bimodal
documentado del conversor legacy (sección de evidencia abajo).

## Archivos

- `scripts/h3/pdf_regression.py` — nuevo. Comparador determinista solo stdlib:
  `--pass1/--pass2/--baseline/--expect-changed/--max-regression/--json`; seis
  líneas fijas en stdout, sin marcas de tiempo; `--json` con rutas relativas a
  la raíz en POSIX; sin dependencia del cwd (default de baseline desde
  `__file__`); no lee el corpus; prioridad de `reason`:
  `nondeterministic` → `unexpected_sha` → `content_loss` → `time`.
- `tests/test_pdf_regression.py` — nuevo. Seis casos: `SAME`→0,
  `CHANGED` esperado→0, SHA inesperado→1 `unexpected_sha` (el fixture dispara a
  la vez sus dos sub-modos: fichero no esperado que difiere + cambio esperado
  que falta), pass1≠pass2→1 `nondeterministic`, +20 %→1 `time`,
  `real_prose_words=3`→1 `content_loss`. Cada caso comprueba la línea de
  veredicto y el código de salida vía subprocess con `cwd` temporal.
- `docs/h3/pdf-regression.md` — nuevo. Los tres comandos exactos con
  `PYTHONHASHSEED=0` en procesos separados, significado de cada línea, reparto
  de códigos de salida (0/1/2), parámetros, por qué el comparador no sustituye
  al arnés, y el artefacto bimodal medido hoy (la semilla no siempre fija la
  cara de los ficheros bimodales).
- `report.md` — este informe (salidas literales de las ejecuciones reales).

Sin cambios en `evaluation/`, `scripts/h3/pdf_conversion_report.py`,
`scripts/h3/pdf_math_census.py`, `apps/` ni en el baseline (`git status` solo
añade los cuatro ficheros de arriba).

## Checks

| Check | Comando | Resultado |
|---|---|---|
| Unit | `.venv/Scripts/python.exe -m unittest tests.test_pdf_regression -v` | PASS — 6 tests, salida literal abajo |
| Gate | `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .` | PASS — `CHECK_OK=...`, exit 0 |
| Pasada 1 (arnés, 17 PDF) | `PYTHONHASHSEED=0` + `pdf_conversion_report.py --corpus ... --layout legacy --json .orca-task/pass1.json --audit-json .orca-task/audit1.json` | exit 0 |
| Pasada 2 (otro proceso) | idem con `--json .orca-task/pass2.json` | exit 0 |
| Comparador | `.venv/Scripts/python.exe scripts/h3/pdf_regression.py --pass1 .orca-task/pass1.json --pass2 .orca-task/pass2.json --json .orca-task/regression.json` | exit 0, `verdict=CHANGED reason=none` |

### Unit tests (salida literal)

```
test_expected_change_verdict_exits_zero (tests.test_pdf_regression.PdfRegressionTests.test_expected_change_verdict_exits_zero)
Exactly the two default expect-changed files differ: CHANGED / exit 0. ... ok
test_pass_mismatch_is_nondeterministic (tests.test_pdf_regression.PdfRegressionTests.test_pass_mismatch_is_nondeterministic)
pass1 and pass2 disagree on one SHA: REGRESSION / exit 1. ... ok
test_real_prose_loss_is_content_regression (tests.test_pdf_regression.PdfRegressionTests.test_real_prose_loss_is_content_regression)
real_prose_words=3 in pass1 only: REGRESSION / exit 1. ... ok
test_same_verdict_exits_zero (tests.test_pdf_regression.PdfRegressionTests.test_same_verdict_exits_zero)
An identical run with an empty --expect-changed is SAME / exit 0. ... ok
test_slower_pass_is_time_regression (tests.test_pdf_regression.PdfRegressionTests.test_slower_pass_is_time_regression)
A pass total 20% over a 10%-capped baseline: REGRESSION / exit 1. ... ok
test_unexpected_sha_exits_one (tests.test_pdf_regression.PdfRegressionTests.test_unexpected_sha_exits_one)
unexpected_sha has two sub-modes; this fixture trips both at once. ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.921s

OK
```

(Repetido tras los últimos cambios: `Ran 6 tests in 0.975s` / `OK`.)

### Gate (salida literal, final)

```
212 passed, 1 skipped, 1 warning in 44.03s
H0_SKIP=corpus docs/*.md no presente en el worktree (0 archivos)

> bibliotecario-web@0.1.0 typecheck
> tsc --noEmit

CHECK_OK=C:\Users\javie\orca\workspaces\Bibliotecario\probe-b-evidence-gate-v4-20261112-202143-8075c3
GATE_EXIT=0
```

## Ejecución real sobre los 17 PDF (criterio de aceptación)

Los tres comandos obligatorios, cada pasada en su propio proceso:

```powershell
$env:PYTHONHASHSEED = '0'
.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus --layout legacy --json .orca-task/pass1.json --audit-json .orca-task/audit1.json
.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus --layout legacy --json .orca-task/pass2.json --audit-json .orca-task/audit2.json
.venv/Scripts/python.exe scripts/h3/pdf_regression.py --pass1 .orca-task/pass1.json --pass2 .orca-task/pass2.json --json .orca-task/regression.json
```

Ambas pasadas terminaron `exit 0` con `python_hash_seed="0"`. Resúmenes del
arnés de **esta** ejecución (salida literal): pasada 1 `files: 17, pages: 412,
secs: 118.837, real_prose_words: 0, real_equation_lines: 0`; pasada 2
`files: 17, pages: 412, secs: 123.05, real_prose_words: 0,
real_equation_lines: 0`.

Las seis líneas del comparador (stdout literal):

```
PDF_REGRESSION files=17 pass1=17 pass2=17
PDF_REGRESSION sha_equal=15 sha_changed=2
PDF_REGRESSION changed=arxiv-attention-is-all-you-need-en.pdf,arxiv-bert-en.pdf
PDF_REGRESSION secs=118.837,123.050 baseline_secs=127.872,148.181 delta_pct=-7.1,-17.0
PDF_REGRESSION audit real_prose=0 real_equation=0 missing_symbols=0
PDF_REGRESSION verdict=CHANGED reason=none
COMPARATOR_EXIT=0
```

Todos los valores exigidos por la aceptación se cumplen: `files=17`,
`sha_equal=15`, `sha_changed=2`,
`changed=arxiv-attention-is-all-you-need-en.pdf,arxiv-bert-en.pdf`,
`audit real_prose=0 real_equation=0`, `verdict=CHANGED reason=none`.

### Coherencia `secs`/`delta_pct` (recalculado a mano)

- pasada 1: `118.837 / 127.872 - 1 = -7.07 %` → pegado `-7.1` ✓ (tolerancia 0,1)
- pasada 2: `123.050 / 148.181 - 1 = -16.96 %` → pegado `-17.0` ✓
- `baseline_secs=127.872,148.181` = `verification.total_secs` del baseline
  (`evaluation/h3/pdf-legacy-baseline.json`); los `secs` de las pasadas son los
  `summary.secs` de los JSON de esa misma ejecución.
- El tope de tiempo es `max(127.872, 148.181) × 1.10 = 163.0 s`: ninguna pasada
  lo supera → sin `reason=time`.

### `--json` del comparador (portabilidad)

`Select-String` sobre `.orca-task/regression.json` buscando
`generated|timestamp|C:\|D:\` → **0 coincidencias**. Las rutas que contiene son
relativas a la raíz en POSIX (`".orca-task/pass1.json"`,
`".orca-task/pass2.json"`, `"evaluation/h3/pdf-legacy-baseline.json"`) y no hay
marcas de tiempo: dos ejecuciones se pueden diffar.

## El artefacto bimodal, medido en esta sesión (evidencia adicional)

Entre la medición de `docs/h3/pdf-two-column-format.md` (esta tarde, cara del
baseline estable) y la ejecución de aceptación de arriba, esta sesión ejecutó
**4 pares completos + 3 sondas** que muestran el artefacto documentado en el
baseline: la cara de los ficheros bimodales (Copa 254200/254203 B,
wiki-Python 78664/78666 B) **no queda fijada por `PYTHONHASHSEED=0`**; depende
del estado del proceso acumulado antes de cada conversión (las conversiones de
Copa en solitario dieron la cara del baseline 3/3; en pasadas completas de esta
noche salió la alternante en 7 de 8 procesos, y en tres pares salió estable en
la cara alternante). El comparador clasificó cada caso correctamente; todas las
cifras son de ejecuciones reales completas sobre los 17 PDF.

| ejecución | cara Copa / Python | SHA vs baseline | veredicto del comparador |
|---|---|---|---|
| par 1, pasada 1 | base / alternante | Copa = baseline; Python ≠ baseline | — |
| par 1, pasada 2 | alternante / base | Copa ≠ baseline; Python = baseline | — |
| par 1 (comparador) | p1≠p2 en Copa y Python | sha_equal=14 sha_changed=3 | `REGRESSION nondeterministic` (exit 1) |
| pares 2, 3 y 4 (6 pasadas) | alternante / base, estable en cada par | Copa ≠ baseline en ambas pasadas | `REGRESSION unexpected_sha` (exit 1) |
| sondas de un solo fichero (Copa ×2, Copa+Python ×1) | base / base | idénticas al baseline | — |
| **par 5 (criterio de aceptación)** | **base / base** | solo los 2 arXiv difieren | **`CHANGED none` (exit 0)** |

Salidas literales de los dos casos anómalos capturados:

Par 1 (pasadas mezcladas → `nondeterministic`):

```
PDF_REGRESSION files=17 pass1=17 pass2=17
PDF_REGRESSION sha_equal=14 sha_changed=3
PDF_REGRESSION changed=arxiv-attention-is-all-you-need-en.pdf,arxiv-bert-en.pdf,wiki-Python.pdf
PDF_REGRESSION secs=149.054,141.184 baseline_secs=127.872,148.181 delta_pct=+16.6,-4.7
PDF_REGRESSION audit real_prose=0 real_equation=0 missing_symbols=0
PDF_REGRESSION verdict=REGRESSION reason=nondeterministic
BIMODAL_EXIT=1
```

Par 4 (par estable en la cara alternante → `unexpected_sha`):

```
PDF_REGRESSION files=17 pass1=17 pass2=17
PDF_REGRESSION sha_equal=14 sha_changed=3
PDF_REGRESSION changed=arxiv-attention-is-all-you-need-en.pdf,arxiv-bert-en.pdf,wiki-Copa_Mundial_de_Fútbol.pdf
PDF_REGRESSION secs=122.903,119.519 baseline_secs=127.872,148.181 delta_pct=-3.9,-19.3
PDF_REGRESSION audit real_prose=0 real_equation=0 missing_symbols=0
PDF_REGRESSION verdict=REGRESSION reason=unexpected_sha
COMPARATOR_EXIT=1
```

En **todos** los pares, incluidos los anómalos, la auditoría dio
`real_prose_words=0`, `real_equation_lines=0` y `missing_symbol_occurrences=0`
en las dos pasadas: la alternancia es cosmética (3-2 bytes de maquetación), sin
pérdida real de contenido. Descartado además: el corpus está intacto (17 PDF
con los bytes del baseline, mtime 01/11) y los binarios de pymupdf no cambiaron
(misma versión 1.28.2/pymupdf4llm 0.3.4; los ficheros internos del paquete
conservan fecha 29/09 — la reescritura de `.venv` de las 19:14 re-extrajo las
mismas wheels fijadas en `apps/api/requirements.lock`).

## Verificaciones de diseño (adicionales)

Comparador ejecutado desde un cwd temporal, **sin** `--baseline`, con dos
pasadas sintéticas que clonan los registros del baseline real (prueba de la
resolución del default desde `__file__` y de la independencia del cwd; el
recalculo manual de `delta_pct` coincide: `127.872/148.181-1 = -13.7`):

```
exit=1
PDF_REGRESSION files=17 pass1=17 pass2=17
PDF_REGRESSION sha_equal=17 sha_changed=0
PDF_REGRESSION changed=none
PDF_REGRESSION secs=127.872,127.872 baseline_secs=127.872,148.181 delta_pct=+0.0,-13.7
PDF_REGRESSION audit real_prose=0 real_equation=0 missing_symbols=na
PDF_REGRESSION verdict=REGRESSION reason=unexpected_sha
```

El `unexpected_sha` es el esperado: al clonar el baseline, falta el cambio
esperado de los dos arXiv → segundo sub-modo del motivo, demostrado también
sobre datos reales. `missing_symbols=na` porque los registros clonados no
llevan `content_audit` (no se inventa un 0).

## Decisiones

- `files=` de la línea 1 = registros del baseline; `pass1=`/`pass2=` = registros
  de cada pasada. `sha_equal/sha_changed/changed` comparan pasada 1 contra el
  baseline sobre la unión de conjuntos (un fichero ausente cuenta como cambio).
- `missing_symbols` suma `content_audit.missing_symbol_occurrences` (clave real
  del arnés; también acepta una clave literal `missing_symbols`), imprime `na`
  si alguna pasada no trae el recuento completo y en `--json` sale `null` —
  nunca un cero inventado.
- La línea 5 imprime el peor `real_prose`/`real_equation` de las dos pasadas
  (los mismos números que alimentan `content_loss`, que examina ambas).
- `--expect-changed` admite la bandera vacía para esperar una corrida idéntica
  (única forma de alcanzar `SAME` con el default no vacío).
- Entrada ilegible/malformada → mensaje en stderr y **exit 2** con stdout
  vacío; `SAME`/`CHANGED`→0, `REGRESSION`→1.
- `secs` siempre con 3 decimales y `delta_pct` con signo y 1 decimal
  (`+/-x.x`), para que dos ejecuciones sean comparables línea a línea.
- La aceptación se cita del par 5 (ejecución real completa); los 4 pares
  anteriores y las sondas quedan documentados arriba como evidencia del
  artefacto bimodal y de los motivos `nondeterministic`/`unexpected_sha` sobre
  datos reales.

## Riesgos / pendientes

- **El artefacto bimodal no está fijado por la semilla** (medido hoy): un par
  futuro puede salir `nondeterministic` o en la cara alternante
  (`unexpected_sha`) sin que haya regresión real. El comparador lo distingue
  correctamente; la cara del baseline sigue siendo recuperable (par 5 y sondas).
  Sugerencia para el orquestador: si un review futuro ve `unexpected_sha` con
  `wiki-Copa...` o `wiki-Python.pdf` en `changed`, repetir las pasadas antes de
  buscar culpables en el código.
- `.venv` compartido fue reescrito a las 19:14 por otro actor (versiones
  idénticas, wheels intactos). El gate de esta tarea pasó después de eso.
- El gate en worktree omite `tests/` con `H0_SKIP` (corpus ausente); la prueba
  unitaria obligatoria se ejecutó a mano y pasa. En el checkout principal el
  gate sí descubre `tests/`.
- Tiempos de esta noche: pasadas entre 119 y 154 s según la carga de la máquina
  (99 procesos python/pwsh/node en paralelo); el criterio de tiempo usa el tope
  del baseline (163 s) y ninguna pasada lo rozó.

## Commit

Sin commit (worker): cambios dejados sin stage para el orquestador. Ficheros
nuevos: `scripts/h3/pdf_regression.py`, `tests/test_pdf_regression.py`,
`docs/h3/pdf-regression.md`, `report.md`.
