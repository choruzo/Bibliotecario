# Probe de harness: evidence-gate-v4-20261112-202143  - Run: `run_b9b0ccdd5773` - Rama base: `main` - Variante: `D:\Archivos\Javier\Proyectos\Bibliotecario\.orca-run\harness-variants\evidence-gate` - Tareas: base `task_d64b91617c25` / variante `task_8075c3c937cc` - Decision: **none** - sin contraste medible - Nota: -  - ``side=base`` delivered=True started_at=11/12/2026 20:22:24 ended_at=2026-11-12T20:39:39.0907053Z - ``side=variante`` delivered=True started_at=11/12/2026 20:22:43 ended_at=2026-11-12T20:40:27.2651191Z  | Lado | Terminada | Veredicto | Defectos | Archivos | Evidencia | |---|---|---|---|---|---| | base | True | ACEPTADO | 0 | 3 (3 sin harness) | sin medir | | variante | True | ACEPTADO | 0 | 6 (6 sin harness) | sin medir |  La columna Evidencia cuenta needles MISSING segun el auditor offline aplicado igual a los dos lados; `sin medir` = no se pidio auditoria. Los artefactos de cada lado (`report.md`, `review.json`) quedan en `side-base/` y `side-variant/` junto a este fichero.  ## Spec de calibracion  # Comparador reproducible de la conversión PDF: dos pasadas frente al baseline

## Objetivo
Que exista `scripts/h3/pdf_regression.py`, un comparador determinista que tome las dos pasadas del arnés de conversión y el baseline de T0, y emita un veredicto verificable (`SAME` / `CHANGED` / `REGRESSION`) sobre SHAs, tiempos y pérdida real de contenido; con tests que cubran los cinco modos de fallo y un informe que cite las cifras de una ejecución real.

## Contexto
- Repo `D:/Archivos/Javier/Proyectos/Bibliotecario`: API FastAPI, web Next.js, gate en `ops/orca/check.ps1`.
- El arnés ya existe y **no se modifica**: `scripts/h3/pdf_conversion_report.py --corpus <ruta> --layout legacy --json <salida> --audit-json <salida>`. Cada pasada tarda ~107 s sobre 17 PDF y escribe un JSON con esta forma (claves reales del fichero, no inventadas):
  - raíz: `corpus`, `generated_at`, `python_hash_seed`, `converter_module`, `files[]`, `summary`;
  - `files[]`: `file`, `pages`, `sha256` (del markdown convertido), `secs`, `pdf_layout`, `diagnostics`, `content_audit` con `real_prose_words` y `real_equation_lines` (y las claves que el arnés añada; no las supongas de memoria);
  - `summary`: totales (`files`, `pages`, `pages_text_loss`, `pages_text_recovered`, `tables_*`, `real_prose_words`, `real_equation_lines`, `slowest`).
- Baseline de T0: `evaluation/h3/pdf-legacy-baseline.json`. Tiene la misma forma (`files[]` con `sha256` y `secs`, `summary`, `verification.total_secs`), `hash_seed: "0"` y una nota de **bimodalidad documentada** del conversor legacy (Copa 254200/254203 B, bert ±4 B): por eso las pasadas se lanzan con `PYTHONHASHSEED=0` y en procesos separados.
- Estado de partida medido el 2026-11-12 (`docs/h3/pdf-two-column-format.md`): 2 ficheros cambian de SHA respecto al baseline (los dos arXiv) y 15 son byte-idénticos; la pérdida real de prosa y ecuaciones es 0; el corpus tarda ~217 s en dos pasadas frente a 276 s del baseline.
- El corpus vive en `.artifacts/agnostic-corpus` (17 PDF, ruta absoluta del checkout principal, no viaja al worktree). **Solo lectura**: no escribas en `.artifacts/` ni en `bibliotecario-data/`.
- Gate: `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .` (~90 s; en worktree los contratos H0 se omiten con `H0_SKIP`; ejecuta `tests/` y `apps/api/tests`). El `.venv` es compartido: no instales ni actualices paquetes.
- **El gate no ejecuta el arnés** (necesita corpus y ~4 min). Por eso la comparación real de esta tarea solo puede demostrarse con la salida que pegues en `report.md`.

## Alcance
- Incluye:
  1. `scripts/h3/pdf_regression.py` (nuevo, solo stdlib) con este contrato:
     - `--pass1 <path>` y `--pass2 <path>` (obligatorios, JSON del arnés), `--baseline <path>` (por defecto `evaluation/h3/pdf-legacy-baseline.json`), `--expect-changed <file...>` (por defecto `arxiv-attention-is-all-you-need-en.pdf` y `arxiv-bert-en.pdf`), `--max-regression <pct>` (por defecto 10), `--json <path>` (opcional, resultado compacto).
     - Salida en stdout, siempre las mismas seis líneas y en este orden:
       ```
       PDF_REGRESSION files=<n> pass1=<n> pass2=<n>
       PDF_REGRESSION sha_equal=<n> sha_changed=<n>
       PDF_REGRESSION changed=<a,b|none>
       PDF_REGRESSION secs=<p1,p2> baseline_secs=<b1,b2> delta_pct=<d1,d2>
       PDF_REGRESSION audit real_prose=<n> real_equation=<n> missing_symbols=<n|na>
       PDF_REGRESSION verdict=<SAME|CHANGED|REGRESSION> reason=<none|unexpected_sha|nondeterministic|time|content_loss>
       ```
       `sha_equal` cuenta ficheros cuyo SHA coincide con el baseline; `changed` va ordenado alfabéticamente; `delta_pct` es el porcentaje de cada pasada sobre su total de baseline correspondente, con un decimal y signo; `missing_symbols` es `na` si el JSON no trae esa clave en `content_audit` (no se inventa ni se convierte en fallo).
     - Veredicto y código de salida:
       - `SAME` (todo igual al baseline) o `CHANGED` (los ficheros que difieren son exactamente los de `--expect-changed`) → **0**;
       - `REGRESSION` → **1**, con `reason` priorizada así: `nondeterministic` (pass1 y pass2 no coinciden en conjunto de ficheros o en SHA), `unexpected_sha` (difiere un fichero no esperado, o falta el cambio esperado de uno de `--expect-changed`), `content_loss` (`real_prose_words > 0` o `real_equation_lines > 0` en cualquier pasada), `time` (total de una pasada > total máximo del baseline × (1 + `--max-regression`/100)).
     - No depende de `cwd`: rutas desde `__file__` cuando son relativas, y las que emite `--json` van relativas a la raíz en POSIX. Sin marcas de tiempo en stdout (sí pueden ir en el `--json`).
  2. `tests/test_pdf_regression.py` (unittest, sin corpus ni red) con un fixture mínimo construido en el test (dos JSON de pasada y un baseline sintéticos) y seis casos: `SAME` → 0; `CHANGED` esperado → 0; SHA inesperado → 1 `unexpected_sha`; pass1 ≠ pass2 → 1 `nondeterministic`; tiempo +20 % → 1 `time`; `real_prose_words=3` → 1 `content_loss`. Cada caso comprueba la línea de veredicto y el código de salida.
  3. `docs/h3/pdf-regression.md` (nuevo): los dos comandos exactos del arnés con `PYTHONHASHSEED=0` en procesos separados, el comando del comparador, el significado de cada línea, el reparto de códigos de salida y por qué el comparador no sustituye al arnés.
  4. `report.md` con la plantilla de `ops/orca/report-template.md`, incluyendo las seis líneas **literales** de una ejecución real sobre los 17 PDF y el `CHECK_OK=…` del gate.
- No incluye:
  - tocar `scripts/h3/pdf_conversion_report.py`, `scripts/h3/pdf_math_census.py`, `apps/api/bibliotecario/converters.py` ni `pdf_math_clean.py`;
  - recalibrar, republicar, tocar `evaluation/h3/*acceptance*` o `*calibration*`, ni `evaluation/h3/pdf-legacy-baseline.json`;
  - Docker, Postgres, LLM, red, escritura en `.artifacts/` o `bibliotecario-data/`;
  - fijar en el código los tiempos de una máquina concreta.

## Archivos probablemente afectados
- `scripts/h3/pdf_regression.py` (nuevo)
- `tests/test_pdf_regression.py` (nuevo)
- `docs/h3/pdf-regression.md` (nuevo)
- `report.md`

## Dependencias
- Ninguna.

## Criterios de aceptación
- [ ] Los seis casos de `tests/test_pdf_regression.py` pasan y cubren los cinco motivos de `REGRESSION`.
- [ ] `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .` termina en `CHECK_OK=...`.
- [ ] Ejecución real sobre los 17 PDF: dos pasadas del arnés con `PYTHONHASHSEED=0` en procesos separados y el comparador sobre ellas; en `report.md` aparecen las seis líneas literales, con `files=17`, `sha_equal=15`, `sha_changed=2`, `changed=arxiv-attention-is-all-you-need-en.pdf,arxiv-bert-en.pdf`, `audit real_prose=0 real_equation=0` y `verdict=CHANGED reason=none`.
- [ ] Los `secs=` y `delta_pct=` del informe son de **esa** ejecución y son coherentes entre sí: `delta_pct` recalculado a mano desde `secs` y `baseline_secs` coincide con el pegado (tolerancia 0,1).
- [ ] El `--json` que produzca el comparador no contiene rutas absolutas del entorno ni marcas de tiempo que impidan comparar dos ejecuciones.
- [ ] `docs/h3/pdf-regression.md` permite repetir los tres comandos sin leer el código.
- [ ] Sin cambios en `evaluation/`, `scripts/h3/pdf_conversion_report.py`, `apps/` ni en el baseline.

## Checks obligatorios
- `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .`
- `.venv/Scripts/python.exe -m unittest tests.test_pdf_regression -v`
- Las dos pasadas reales y el comparador (pegar salida en `report.md`):
  ```powershell
  $env:PYTHONHASHSEED = '0'
  .venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus --layout legacy --json .orca-task/pass1.json --audit-json .orca-task/audit1.json
  .venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus --layout legacy --json .orca-task/pass2.json --audit-json .orca-task/audit2.json
  .venv/Scripts/python.exe scripts/h3/pdf_regression.py --pass1 .orca-task/pass1.json --pass2 .orca-task/pass2.json
  ```
  (cada pasada en su propio proceso; no las encadenes en el mismo `python -c`)

## Entrega
- Worktree: el que asigne Orca. Rama: la que cree Orca.
- Informe: `report.md`, con las salidas pegadas tal cual, no resumidas ni parafraseadas. Si un comando no lo has ejecutado, escríbelo; **un dato que no salga de una ejecución invalida la entrega**.
- Deja los cambios sin stage; envía un único `worker_done` con `taskId` y `dispatch_id`.
- Prohibido: push, merge, rebase, `orca orchestration task-update`, `git add`, `git commit`, tocar otros worktrees.

## Riesgos / notas
- **Bimodalidad**: sin `PYTHONHASHSEED=0` el conversor legacy alterna caras (Copa 254200/254203 B, bert ±4 B) y el comparador dirá `nondeterministic`. Es un artefacto conocido, documentado en el baseline: no lo arregles en el conversor, ejecuta con la semilla.
- **Tiempos**: la primera pasada en frío suele ser más lenta. Compara con el máximo del baseline, no con el mínimo, y no persigas el ±5 %: el criterio es el tope de `--max-regression`.
- `missing_symbols` puede no existir en `content_audit`; en ese caso `na`, no `0` (un cero inventado es peor que un dato ausente).
- El comparador no debe leer el corpus: si necesita el corpus para algo, está mal diseñado.
- `tests/` corre con `unittest discover` en el gate: los fixtures van dentro del test, en `tempfile`, sin rutas del repo.

