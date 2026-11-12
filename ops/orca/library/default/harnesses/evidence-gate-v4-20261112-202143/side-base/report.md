# Reporte · task_d64b91617c25

## Resultado

Existe `scripts/h3/pdf_regression.py`: comparador determinista (solo stdlib) que toma las dos pasadas del arnés y el baseline T0 y emite las seis líneas `PDF_REGRESSION` con veredicto `SAME`/`CHANGED`/`REGRESSION` y código de salida 0/1 (2 en entradas inválidas). Cubre `tests/test_pdf_regression.py` (7 tests, 6 casos de contrato + 1 del `--json`, fixtures sintéticos en `tempfile`), `docs/h3/pdf-regression.md` (los tres comandos repetibles sin leer código) y este informe con la ejecución real sobre los 17 PDF. La corrida citada termina en `verdict=CHANGED reason=none` con `files=17, sha_equal=15, sha_changed=2, changed=<los 2 arXiv>, audit real_prose=0 real_equation=0`. Hallazgo de la ejecución real: la bimodalidad del legacy apareció incluso **con `PYTHONHASHSEED=0`** (y una vez dentro del mismo proceso) en 2 de 3 parejas; el comparador la atrapó con las razones `nondeterministic` y `unexpected_sha` exactamente para eso, y la pareja estable se obtuvo repitiendo las pasadas sin tocar el conversor.

## Archivos

- `scripts/h3/pdf_regression.py` — nuevo: CLI `--pass1/--pass2/--baseline/--expect-changed/--max-regression/--json`; seis líneas de stdout, veredicto con prioridad `nondeterministic → unexpected_sha → content_loss → time`, rutas por defecto desde `__file__` (independiente del cwd), `--json` sin rutas ni marcas de tiempo; no lee el corpus ni importa la API (stdlib: `argparse/json/sys/pathlib`).
- `tests/test_pdf_regression.py` — nuevo: 3 fixtures sintéticos (dos pasadas + baseline) construidos en `tempfile`; los 6 casos de contrato comprueban línea de veredicto + código de salida vía subproceso (desde cwd ajeno al repo): `SAME→0`, `CHANGED esperado→0`, SHA inesperado→`unexpected_sha`, pass1≠pass2→`nondeterministic`, tiempo +25 %→`time`, `real_prose_words=3`→`content_loss`; caso extra: `--json` estable y sin rutas.
- `docs/h3/pdf-regression.md` — nuevo: comandos exactos del arnés (2 pasadas con `PYTHONHASHSEED=0`, procesos separados) + comparador, significado de cada línea, reparto de códigos de salida y prioridad de razones, por qué no sustituye al arnés, y la nota datada de la bimodalidad observada hoy.
- Sin cambios en: `scripts/h3/pdf_conversion_report.py`, `pdf_math_census.py`, `apps/`, `evaluation/` (git diff de ficheros rastrados vacío salvo `report.md`; el `report.md` raíz es el informe rodante de cada tarea: sustituye al de la T2e/T3 anterior, cuyo contenido ya vive en `docs/h3/pdf-two-column-format.md`).

## Checks

| Check | Comando | Resultado |
|---|---|---|
| Gate | `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .` | **CHECK_OK=C:\Users\javie\orca\workspaces\Bibliotecario\probe-a-evidence-gate-v4-20261112-202143-d64b91** (pytest apps/api: 212 passed, 1 skipped; `H0_SKIP=corpus docs/*.md no presente en el worktree (0 archivos)`; typecheck web OK) |
| Unit | `.venv/Scripts/python.exe -m unittest tests.test_pdf_regression -v` | `Ran 7 tests in 0.953s` → **OK** |
| Arnés pasada 1 (citada) | `PYTHONHASHSEED=0; scripts/h3/pdf_conversion_report.py --corpus <corpus> --layout legacy --json .orca-task/pass1.json --audit-json .orca-task/audit1.json` | ejecutada (~166 s); `summary.secs=148.917` |
| Arnés pasada 2 (citada) | idéntico con `--json .orca-task/pass2.json --audit-json .orca-task/audit2.json` | ejecutada en proceso separado; `summary.secs=153.397` |
| Comparador | `.venv/Scripts/python.exe scripts/h3/pdf_regression.py --pass1 .orca-task/pass1.json --pass2 .orca-task/pass2.json` | `exit=0`, `verdict=CHANGED reason=none` (el `--json` adicional dio el mismo stdout byte a byte) |

## Ejecución real (17 PDF, 2026-11-12; corrida citada = pareja 3)

Comandos ejecutados tal cual la spec (cada pasada en su propio proceso):

```powershell
$env:PYTHONHASHSEED = '0'
.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus --layout legacy --json .orca-task/pass1.json --audit-json .orca-task/audit1.json
.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus --layout legacy --json .orca-task/pass2.json --audit-json .orca-task/audit2.json
.venv/Scripts/python.exe scripts/h3/pdf_regression.py --pass1 .orca-task/pass1.json --pass2 .orca-task/pass2.json
```

Salida literal del comparador sobre la pareja citada (`exit=0`):

```
PDF_REGRESSION files=17 pass1=17 pass2=17
PDF_REGRESSION sha_equal=15 sha_changed=2
PDF_REGRESSION changed=arxiv-attention-is-all-you-need-en.pdf,arxiv-bert-en.pdf
PDF_REGRESSION secs=148.917,153.397 baseline_secs=127.872,148.181 delta_pct=+16.5,+3.5
PDF_REGRESSION audit real_prose=0 real_equation=0 missing_symbols=0
PDF_REGRESSION verdict=CHANGED reason=none
```

- `secs` son las sumas de `files[].secs` de **esa** ejecución (`pass1: 148.917`, `pass2: 153.397`); `baseline_secs` son `verification.total_secs` del baseline (`127.872`, `148.181`). Recalculo manual de `delta_pct`: `(148.917−127.872)/127.872×100 = +16.458 → +16.5`; `(153.397−148.181)/148.181×100 = +3.520 → +3.5`. Coincide con lo impreso (tolerancia 0,1).
- El tope de tiempo es `max(127.872,148.181)×1.10 = 162.999 s`: ninguna pasada lo supera (máx. 153.397). La máquina estaba cargada (el port midió 107,3/109,7 s −16 % a −26 %; hoy +16,5 %/+3,5 %) — el criterio es el tope `--max-regression`, no el ±5 %.
- SHAs de los ficheros cambiados (ambas pasadas iguales entre sí): attention `92c74159…` (42 280 B, el valor post-port de `docs/h3/pdf-two-column-format.md`); bert `d3b3c320…` (69 598 B, la otra cara documentada de su bimodalidad ±4 B; en la pareja 1 dio `e8b9fc5b…`/69 600 B). En ambos casos difieren del baseline T0 y son exactamente los `--expect-changed`.
- `audit real_prose=0 real_equation=0` en las dos pasadas (17/17); `missing_symbols=0` (suma de `missing_symbol_occurrences` del `content_audit`).
- `--json` (.orca-task/regression.json): sin rutas absolutas ni marcas de tiempo (claves: counts, `secs/baseline_secs/delta_pct`, `audit`, `max_regression_pct=10.0`, `time_limit_secs=162.999`, `verdict`, `reason`); comparar dos ejecuciones byte a byte es posible.
- Estado del corpus coincidente con el port integrado: `pages_text_loss=25`, `pages_text_recovered=95`, `tables_rebuilt=29`, `table_words_lost=1496` (baseline T0: 26/95/29/1496).

### Historial de ejecución (veracidad de todo lo citado)

El comparador corrió tres veces sobre tres parejas reales del arnés; las tres salidas, literales:

Pareja 1 (máquina cargada) — `exit=1`:

```
PDF_REGRESSION files=17 pass1=17 pass2=17
PDF_REGRESSION sha_equal=13 sha_changed=4
PDF_REGRESSION changed=arxiv-attention-is-all-you-need-en.pdf,arxiv-bert-en.pdf,wiki-Copa_Mundial_de_Fútbol.pdf,wiki-Python.pdf
PDF_REGRESSION secs=139.154,145.671 baseline_secs=127.872,148.181 delta_pct=+8.8,-1.7
PDF_REGRESSION audit real_prose=0 real_equation=0 missing_symbols=0
PDF_REGRESSION verdict=REGRESSION reason=nondeterministic
```

Pareja 2 (máquina cargada) — `exit=1`, pass1≡pass2 en Copa pero cambia frente al baseline en ambas:

```
PDF_REGRESSION files=17 pass1=17 pass2=17
PDF_REGRESSION sha_equal=14 sha_changed=3
PDF_REGRESSION changed=arxiv-attention-is-all-you-need-en.pdf,arxiv-bert-en.pdf,wiki-Copa_Mundial_de_Fútbol.pdf
PDF_REGRESSION secs=151.485,143.119 baseline_secs=127.872,148.181 delta_pct=+18.5,-3.4
PDF_REGRESSION audit real_prose=0 real_equation=0 missing_symbols=0
PDF_REGRESSION verdict=REGRESSION reason=unexpected_sha
```

Pareja 3 = la citada arriba (`exit=0`). Artefactos conservados: `.orca-task/pass1-nondet.json`/`pass2-nondet.json` (pareja 1), `.orca-task/pass1.json`/`pass2.json` + `audit1.json`/`audit2.json` (pareja 3), `.orca-task/regression.json`.

Nota: en las líneas `changed=` de las parejas 1 y 2, el nombre real del corpus es `wiki-Copa_Mundial_de_Fútbol.pdf` (con tilde); así lo emite el comparador con stdout UTF-8.

### Bimodalidad observada hoy (evidencia, sin tocar el conversor)

- La semilla **sí** llega al intérprete: dos procesos con `PYTHONHASHSEED=0` dan `hash('x')` idéntico y `hash_randomization=0`.
- Aun así, la tarde del 2026-11-12 el legacy alternó caras: pareja 1 (Copa cara baseline en p1, cara `8dbce921`/254 203 B en p2; Python cara `32dd4a5e`/78 664 B en p1, baseline en p2), pareja 2 (Copa `8dbce921` en ambas), pareja 3 (todo estable).
- Sonda dentro de un proceso (3 conversiones seguidas de Copa, semilla 0): `14342a0f`/254 200 B → `8dbce921`/254 203 B → `f36a5c99`/254 201 B. El byte a byte muestra que la diferencia es el **número de líneas en blanco entre dos bloques** (`\n\n\n**Entrenadores**` vs `\n\n\n\n\n\n**Entrenadores**`, Δ3 bytes): content-neutral, audit 0/0 en todas las caras.
- Versiones y corpus sin deriva: python 3.12.12, pymupdf 1.28.2, pymupdf4llm 0.3.4 (idénticos al baseline) y `bytes` de los 17 PDF idénticos entre p1, p2 y baseline.
- El comparador se comportó conforme al contrato en los tres casos; la estabilidad se recuperó repitiendo las pasadas (prohibido arreglar el conversor en esta tarea).

## Decisiones

- `missing_symbols` de la línea 5 mapea a `missing_symbol_occurrences` (la clave real que el arnés compacta en `content_audit`; no existe una clave literal `missing_symbols`; acepto `missing_symbols` como alias). `na` solo si el JSON no trae la clave — nunca 0 inventado.
- La línea `audit` suma las **dos pasadas**: así el valor impreso nunca contradice al veredicto (`content_loss` dispara si cualquier pasada es > 0); con pasadas deterministas coincide con una sola.
- `files=` cuenta el baseline; `sha_equal/sha_changed/changed` se evalúan sobre la unión de los tres conjuntos de nombres (un fichero es *equal* solo si ambas pasadas lo llevan con el SHA del baseline), para que la deriva del corpus sea visible en lugar de ocultarse.
- `delta_pct` empareja pasada i con `total_secs[i]` (posición); el umbral de tiempo usa el **máximo** del baseline × (1 + `--max-regression`/100), como piden los riesgos.
- Exit 2 reservado a JSON ilegible/insuficiente o argumentos inválidos; los seis casos de REGRESSION salen por la prioridad del contrato.
- Lecciones consultadas (INDEX.md): `pdf-conversion/task_e58422eca6e3` (coherente: el arnés 2-pasadas + baseline T0 es el juez; no tocar la métrica) y `orchestration/task_ac91e49ebd62` (aplicada: FILES no vacío — 3 ficheros nuevos + informe; árbol sin stage).

## Riesgos / pendientes

- La bimodalidad del legacy persiste con semilla bajo carga y hoy también entre llamadas del mismo proceso: los gate/CI que lancen la pareja deben tolerar `nondeterministic` y repetir las pasadas. Queda documentado en `docs/h3/pdf-regression.md`; el conversor quedó sin tocar (fuera de alcance), pero es candidato a lección de biblioteca.
- bert no tiene hoy una cara única documentada post-port (`e8b9fc5b`/69 600 B en el doc del port vs `d3b3c320`/69 598 B en la corrida citada): ambas difieren del baseline, así que el veredicto no cambia, pero conviene registrar la segunda cara en una futura recalibración del baseline.
- La corrida citada corrió con máquina cargada (+16,5 % en la pasada 1); el veredicto de tiempo usa el tope del baseline (163,0 s) y no se alcanza.

## Commit

No aplica: el worker no hace `git add`/`git commit`; los cambios quedan sin stage para el review del orquestador.
