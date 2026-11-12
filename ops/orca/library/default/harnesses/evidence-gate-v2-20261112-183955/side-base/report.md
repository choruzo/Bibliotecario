# Reporte task_293aeeb977ad

## Resultado

**SUCCESS.** Existe `scripts/h3/bank_inventory.py` (solo stdlib) y el inventario versionado
`evaluation/h3/bank-inventory.json`, generado **ejecutando** el script sobre el árbol real:
describe los 4 bancos H3 (137 casos en total) y los 2 catálogos, con reparto por `kind`,
grupos de conversación, idiomas y SHA-256 de cada fichero. `--check` sale 0 con
`BANK_INVENTORY_OK` sobre el árbol limpio, dos `--write` consecutivos son byte-idénticos y
las cuatro pruebas de `tests/test_bank_inventory.py` pasan (incluidas las dos de fallo:
banco mutado y deriva de inventario). El gate termina en `CHECK_OK`.

## Archivos

- `scripts/h3/bank_inventory.py` - nuevo. CLI `--banks/--catalogs/--inventory` con tres
  modos (stdout JSON / `--write` / `--check`), rutas resueltas desde `__file__` hasta la
  raíz del repo (nunca desde el cwd), claves del inventario relativas a la raíz en POSIX,
  y `BANK_INVALID <ruta>:<línea> <motivo>` fail-fast sin escribir nada.
- `evaluation/h3/bank-inventory.json` - nuevo, generado con `--write` (no editado a mano).
- `tests/test_bank_inventory.py` - nuevo, 4 pruebas unittest sin red ni Docker, importable
  por `unittest discover` sin efectos secundarios.
- `docs/h3/bank-inventory.md` - nuevo: qué mide, contrato de CLI, por qué lleva SHA-256 y
  cómo regenerar/verificar sin leer el código.
- `report.md` - este informe, con la plantilla de `ops/orca/report-template.md`. Sustituye
  al informe anterior (T2e) que estaba trackeado en `main` por el commit `7ffbd9c`.

## Checks

| Check | Comando | Resultado |
|---|---|---|
| Verificación | `.venv/Scripts/python.exe scripts/h3/bank_inventory.py --check` | PASS (exit 0) |
| Unit nuevos | `.venv/Scripts/python.exe -m unittest tests.test_bank_inventory -v` | PASS (4 tests) |
| Determinismo | `.venv/Scripts/python.exe scripts/h3/bank_inventory.py --write` ×2 + sha256 | PASS (idéntico) |
| Gate | `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .` | PASS (`CHECK_OK`) |
| Descubrimiento | `.venv/Scripts/python.exe -m unittest discover -s tests -p test_bank_inventory.py` | PASS (4 tests) |

**Evidencia literal 1 — `--check` sobre el árbol limpio:**

```
$ .venv/Scripts/python.exe scripts/h3/bank_inventory.py --check
BANK_INVENTORY_OK banks=4 cases=137 catalogs=2
exit=0
```

**Evidencia literal 2 — los cuatro tests (y el descubrimiento, que el gate usa):**

```
$ .venv/Scripts/python.exe -m unittest tests.test_bank_inventory -v
test_check_detects_drift_in_modified_inventory (tests.test_bank_inventory.BankInventoryTests.test_check_detects_drift_in_modified_inventory) ... ok
test_check_reports_ok_on_the_versioned_tree (tests.test_bank_inventory.BankInventoryTests.test_check_reports_ok_on_the_versioned_tree) ... ok
test_mutated_bank_is_rejected_as_invalid (tests.test_bank_inventory.BankInventoryTests.test_mutated_bank_is_rejected_as_invalid) ... ok
test_regenerated_inventory_matches_versioned_file (tests.test_bank_inventory.BankInventoryTests.test_regenerated_inventory_matches_versioned_file) ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.598s

OK
```

(la última ejecución tras el cambio final de stdout dio `Ran 4 tests in 0.564s / OK`;
`unittest discover -s tests -p test_bank_inventory.py` también: `Ran 4 tests in 0.565s / OK`)

**Evidencia literal 3 — SHA-256 de `evaluation/h3/bank-inventory.json` y doble `--write`:**

```
$ .venv/Scripts/python.exe scripts/h3/bank_inventory.py --write
BANK_INVENTORY_WRITTEN path=evaluation/h3/bank-inventory.json banks=4 cases=137
$ .venv/Scripts/python.exe scripts/h3/bank_inventory.py --write
BANK_INVENTORY_WRITTEN path=evaluation/h3/bank-inventory.json banks=4 cases=137
$ .venv/Scripts/python.exe -c "import hashlib;print(hashlib.sha256(open('evaluation/h3/bank-inventory.json','rb').read()).hexdigest())"
f9e8a008c671979a8c8337d0ad59eb67c44927da87f24239fdd398b12e51bfc1
$ git status --porcelain evaluation/h3/bank-inventory.json
?? evaluation/h3/bank-inventory.json
```

El hash es idéntico antes y después de cada `--write` (se midió tres veces:
`f9e8a008c671979a8c8337d0ad59eb67c44927da87f24239fdd398b12e51bfc1`), es decir, la segunda
escritura no altera ningún byte. El `porcelain` muestra `??` porque el fichero aún es
**untracked**: los workers tienen prohibido `git add`/`git commit`, así que el criterio
«vacío tras la segunda» solo puede cumplirse tras el commit del orquestador; la
no-modificación queda probada por el SHA-256 idéntico entre escrituras.

**Evidencia literal 4 — rutas de fallo** (copia temporal del inventario con `cases+1` en el
primer banco; copia temporal del banco agnóstico de calibración con la línea 1 duplicada;
salidas literales):

```
$ .venv/Scripts/python.exe scripts/h3/bank_inventory.py --check --inventory <temp>/bi-drift-test.json
BANK_INVENTORY_DRIFT path=evaluation/h3/agnostic-calibration-v1.jsonl field=cases
drift exit=1
$ .venv/Scripts/python.exe scripts/h3/bank_inventory.py --banks <temp>/bi-dup.jsonl
BANK_INVALID C:/Users/javie/AppData/Local/Temp/bi-dup.jsonl:2 id duplicado: AGN-CAL-A001
invalid exit=1
```

**Evidencia literal 5 — gate** (salida truncada a las líneas finales; el bloque es literal):

```
212 passed, 1 skipped, 1 warning in 51.46s
H0_SKIP=corpus docs/*.md no presente en el worktree (0 archivos)

> bibliotecario-web@0.1.0 typecheck
> tsc --noEmit

CHECK_OK=C:\Users\javie\orca\workspaces\Bibliotecario\probe-a-evidence-gate-v2-20261112-183955-293aee
gate exit=0
```

`git status --porcelain` completo: solo los 5 ficheros nuevos de esta tarea (más
`.orca-task/`, que ya estaba). **No** aparece ningún `evaluation/h3/*.jsonl`, ningún
`evaluation/*/corpus_catalog.json`, ni `tests/test_agnostic_banks.py`, ni
`ops/orca/check.ps1`:

```
?? .orca-task/
?? docs/h3/bank-inventory.md
?? evaluation/h3/bank-inventory.json
?? scripts/h3/bank_inventory.py
?? tests/test_bank_inventory.py
```

## Cifras del árbol real (calculadas por el script, no a mano)

| Banco | cases | by_kind (a/u/amb/conv) | languages | conversations |
|---|---|---|---|---|
| `agnostic-calibration-v1.jsonl` | 32 | 16/6/3/7 | en, es | 3 |
| `agnostic-validation-v1.jsonl` | 40 | 22/8/3/7 | de, en, es, fr, it | 3 |
| `colloquial-calibration-v1.jsonl` | 32 | 18/5/3/6 | es | 2 |
| `colloquial-validation-v1.jsonl` | 33 | 19/5/3/6 | en, es, fr | 2 |

Catálogos: `evaluation/h0/corpus_catalog.json` = 13 documentos; `evaluation/h3/agnostic_corpus_catalog.json` = 17 documentos. Total: 137 casos.

## Decisiones

- **Comparación de `--check` textual con newlines normalizados**: se compara el texto del
  fichero en disco (leído con newlines universales) contra el regenerado. Así se detectan
  cambios de orden de claves, indentación o salto final, pero no hay falso positivo por
  `core.autocrlf=true` al hacer checkout en otro worktree. La igualdad de contenido con
  formato distinto se reporta como `field=format`.
- **`by_kind` cerrado a las cuatro clases, esquema de caso abierto**: `by_kind` lleva
  siempre `ambiguous/answerable/conversation/unanswerable` (0 si no hay casos) y ninguna
  clave más; el caso no se valida con esquema cerrado (claves extra como
  `conversation_id`/`turn`/`subject` y `expected_documents` vacío en
  `unanswerable`/`ambiguous` son legítimos), siguiendo la nota de riesgos de la spec.
- **Solo se valida lo que el inventario necesita**: JSON por línea, `id` único entre todos
  los bancos, `kind` conocido; falta de `id`/`kind` también es `BANK_INVALID` para no
  fallar con traceback. Fail-fast en la primera línea inválida, un solo mensaje y ninguna
  escritura.
- **stdout determinista**: el modo sin flags escribe exactamente los mismos bytes que
  `--write` (se fijó `newline="\n"` en stdout; verificado: `stdout_bytes==disk_bytes: True`).
- **El objetivo dice «con `--check` en el gate», pero el alcance prohíbe tocar
  `check.ps1`**: el modo `--check` queda implementado, probado y documentado (con el
  comando sugerido en `docs/h3/bank-inventory.md`); su cableado en el gate es un paso
  posterior que no cabe en esta tarea.
- `report.md` previo: el worktree traía un `report.md` trackeado en `main` (informe T2e del
  commit `7ffbd9c`); se sustituye por este informe, que es el que exige la entrega.

## Riesgos / pendientes

- **El gate de este worktree no ejecutó los tests nuevos**: con 0 `docs/*.md` de primer
  nivel, `check.ps1` omite `unittest discover` (`H0_SKIP=...`, comportamiento documentado
  en AGENTS.md). Los cuatro tests se ejecutaron directamente (evidencia 2 y fila
  «Descubrimiento»); en el checkout principal, donde el corpus sí está, el gate los
  ejecutará vía `unittest discover`.
- **SHA-256 y EOL del checkout**: los hashes de bancos/catálogos se calculan sobre los
  bytes en disco. Con `core.autocrlf=true` los `.jsonl` bajan como CRLF en todos los
  worktrees de este repo, así que los hashes coinciden entre ellos; un checkout con otra
  configuración de EOL produciría deriva de hashes, y el arreglo documentado es
  `--write` con revisión.
- **Pendiente (fuera de alcance)**: añadir la invocación `--check` al final de
  `ops/orca/check.ps1` para que el gate detecte deriva automáticamente.

## Commit

Sin commit: los cambios quedan **sin stage** para que el orquestador revise y commite
exactamente estos ficheros. El worker no hace push.
