# Reporte · task_e5c16b6c7d68

## Resultado

Existe `scripts/h3/bank_inventory.py` (solo stdlib) y el inventario versionado
`evaluation/h3/bank-inventory.json`, generado **ejecutando** el script sobre el
árbol real: 4 bancos, 137 casos (32 calibración agnóstica, 40 validación
agnóstica, 32 calibración coloquial, 33 validación coloquial) y 2 catálogos
(13 documentos H0, 17 agnósticos). El contrato CLI completo funciona (los cuatro
modos probados a mano y en tests, incluidos los fallos `BANK_INVALID` y
`BANK_INVENTORY_DRIFT`), las cuatro pruebas de `tests/test_bank_inventory.py`
pasan, la documentación queda en `docs/h3/bank-inventory.md` y el gate termina
en `CHECK_OK` (ver abajo). No se tocó ningún banco, catálogo,
`tests/test_agnostic_banks.py`, `check.ps1` ni `apps/`.

## Archivos

- `scripts/h3/bank_inventory.py` — nuevo: inventario determinista de los 4
  bancos H3 y 2 catálogos con contrato `--banks/--catalogs/--inventory`,
  `--write` y `--check`; rutas relativas a la raíz del repo desde `__file__`
  (nunca por cwd), salida POSIX, serialización canónica.
- `evaluation/h3/bank-inventory.json` — nuevo, **generado** con `--write`
  (no editado a mano). SHA-256:
  `f9e8a008c671979a8c8337d0ad59eb67c44927da87f24239fdd398b12e51bfc1`.
- `tests/test_bank_inventory.py` — nuevo: 4 pruebas unittest sin red ni Docker,
  con subprocess (`sys.executable`) y `cwd` fuera del repo para demostrar la
  resolución desde `__file__`.
- `docs/h3/bank-inventory.md` — nuevo: qué mide, contrato CLI, por qué
  SHA-256, cómo regenerar y verificar sin leer el código.
- `report.md` — este informe.

Cambios preexistentes en el worktree en el momento del dispatch (no son de esta
tarea): ` M .opencode/agents/worker.md`, `?? .opencode/skills/`, `?? .orca-task/`.

## Checks

| Check | Comando | Resultado |
|---|---|---|
| CLI check | `.venv/Scripts/python.exe scripts/h3/bank_inventory.py --check` | PASS — `BANK_INVENTORY_OK banks=4 cases=137 catalogs=2`, exit 0 |
| Tests nuevos | `.venv/Scripts/python.exe -m unittest tests.test_bank_inventory -v` | PASS — `Ran 4 tests ... OK` (salida literal abajo) |
| Doble `--write` | `--write` × 2 + `git status --porcelain evaluation/h3/bank-inventory.json` | PASS — SHA-256 idéntico en las dos escrituras; detalle del porcelain abajo |
| Gate del repo | `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .` | PASS — `CHECK_OK=...` (salida literal abajo) |
| Detección de fallos (CLI manual) | banco con `id` duplicado / inventario con `cases` alterado | PASS — `BANK_INVALID ... exit:1`, `BANK_INVENTORY_DRIFT ... exit:1` (abajo) |

### `--check` sobre el árbol limpio

```
$ .venv/Scripts/python.exe scripts/h3/bank_inventory.py --check
BANK_INVENTORY_OK banks=4 cases=137 catalogs=2
exit:0
```

### Los cuatro tests (`-m unittest tests.test_bank_inventory -v`)

```
test_check_passes_on_clean_tree (tests.test_bank_inventory.BankInventoryCliTests.test_check_passes_on_clean_tree) ... ok
test_drifted_inventory_fails_check (tests.test_bank_inventory.BankInventoryCliTests.test_drifted_inventory_fails_check) ... ok
test_mutated_bank_fails_with_bank_invalid_and_writes_nothing (tests.test_bank_inventory.BankInventoryCliTests.test_mutated_bank_fails_with_bank_invalid_and_writes_nothing) ... ok
test_regenerated_matches_versioned_file (tests.test_bank_inventory.BankInventoryCliTests.test_regenerated_matches_versioned_file) ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.782s

OK
```

### Doble `--write` sobre `evaluation/h3/bank-inventory.json`

```
$ .venv/Scripts/python.exe scripts/h3/bank_inventory.py --write
BANK_INVENTORY_WRITTEN path=evaluation/h3/bank-inventory.json banks=4 cases=137
exit:0
$ .venv/Scripts/python.exe scripts/h3/bank_inventory.py --write
BANK_INVENTORY_WRITTEN path=evaluation/h3/bank-inventory.json banks=4 cases=137
exit:0
$ git status --porcelain evaluation/h3/bank-inventory.json
?? evaluation/h3/bank-inventory.json
porcelain-exit:0
```

Además, hash del fichero tras la primera y la segunda escritura (idénticos, la
segunda escritura no cambia un byte):

```
sha-after-write-1: f9e8a008c671979a8c8337d0ad59eb67c44927da87f24239fdd398b12e51bfc1
sha-after-write-2: f9e8a008c671979a8c8337d0ad59eb67c44927da87f24239fdd398b12e51bfc1
sha-equal: True
--- porcelain --untracked-files=no after second write:
(vacío)
```

El `` ?? `` del porcelain plain es solo el fichero **nuevo** sin trackear (el
worker no hace `git add`): la segunda escritura no produjo ninguna modificación
de contenido — SHA-256 idéntico y `git status --porcelain
--untracked-files=no evaluation/h3/bank-inventory.json` vacío. El commit del
coordinador lo trackeará; a partir de entonces el porcelain plain quedará vacío
en el mismo experimento.

### Fallos del contrato (CLI manual, banco/inventario temporales)

```
BANK_INVALID C:/Users/javie/AppData/Local/Temp/opencode/bi-probe/duplicate-id.jsonl:2 duplicate_id:EVAL-A001
exit:1
out-exists: False
BANK_INVENTORY_DRIFT path=evaluation/h3/agnostic-calibration-v1.jsonl field=cases
exit:1
```

### Gate del repo

```
$ pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .
warning: in the working copy of '.opencode/agents/worker.md', LF will be replaced by CRLF the next time Git touches it
........................................................................ [ 33%]
.........................................................s.............. [ 67%]
.....................................................................    [100%]
============================== warnings summary ===============================
..\..\.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\javie\orca\workspaces\Bibliotecario\probe-b-evidence-gate-v2-20261112-183955-e5c16b\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
212 passed, 1 skipped, 1 warning in 48.14s
H0_SKIP=corpus docs/*.md no presente en el worktree (0 archivos)

> bibliotecario-web@0.1.0 typecheck
> tsc --noEmit

CHECK_OK=C:\Users\javie\orca\workspaces\Bibliotecario\probe-b-evidence-gate-v2-20261112-183955-e5c16b
GATE-EXIT:0
```

El warning de git corresponde a `.opencode/agents/worker.md`, modificado antes
del dispatch (hoja de agente enjuchada por el kit, no es de esta tarea). El
`warning` de pytest es preexistente de starlette. Los `212 passed` de
`apps/api` y el `typecheck` de la web no cambian con esta tarea.

### Tope de 20 líneas de deriva (manual)

Con un inventario temporal con 21 diferencias (schema + 4 bancos x 5 campos +
entrada sobrante), `--check` imprime exactamente 20 líneas y sale 1:

```
drift-lines: 20 exit: 1
BANK_INVENTORY_DRIFT path=C:/Users/javie/AppData/Local/Temp/opencode/bi-probe/heavy.json field=schema_version
BANK_INVENTORY_DRIFT path=evaluation/h3/agnostic-calibration-v1.jsonl field=by_kind
...
BANK_INVENTORY_DRIFT path=evaluation/h3/colloquial-validation-v1.jsonl field=languages
```

### Cobertura de los tests dentro del discover del gate

En este worktree el gate imprime `H0_SKIP=corpus docs/*.md no presente en el
worktree (0 archivos)` y omite `unittest discover -s tests` (comportamiento
existente del gate: `test_h0` exige el corpus privado `docs/*.md` que no viaja
a worktrees — verificado: con discover forzado, los 2 fallos son de
`test_h0.py` y los 4 tests nuevos pasan). Ejecutando el mismo `discover` a mano
se ve que los tests nuevos quedan incluidos y pasan, y que `test_h0` es la única
fuente de fallos:

```
test_check_passes_on_clean_tree (test_bank_inventory.BankInventoryCliTests.test_check_passes_on_clean_tree) ... ok
test_drifted_inventory_fails_check (test_bank_inventory.BankInventoryCliTests.test_drifted_inventory_fails_check) ... ok
test_mutated_bank_fails_with_bank_invalid_and_writes_nothing (test_bank_inventory.BankInventoryCliTests.test_mutated_bank_fails_with_bank_invalid_and_writes_nothing) ... ok
test_regenerated_matches_versioned_file (test_bank_inventory.BankInventoryCliTests.test_regenerated_matches_versioned_file) ... ok
Ran 12 tests in 0.687s
FAILED (failures=2, skipped=1)   <-- los 2 fallos son test_h0.py (corpus privado ausente)
```

## Decisiones

- **Comparación de `--check` con normalización CRLF**: el repo no tiene
  `.gitattributes` y `core.autocrlf=true` (git avisa: "LF will be replaced by
  CRLF the next time Git touches it"). Para que una re-extracción del fichero
  versionado no produzca falsa deriva, `--check` normaliza `\r\n`→`\n` al leer
  el disco antes de comparar bytes; cualquier otra diferencia es deriva y se
  reporta campo a campo. Documentado en `docs/h3/bank-inventory.md`.
- **"Línea vacía" en bancos**: las líneas en blanco se saltan (mismo criterio
  que el loader de `tests/test_agnostic_banks.py`); cualquier línea con
  contenido debe ser un objeto JSON. Interpretación comentada aquí porque la
  literalidad del contexto era ambigua ("línea vacía con contenido").
- **Validación mínima de casos**: solo `id`, `kind` y `language` (lo que el
  inventario necesita); claves extra (`conversation_id`, `turn`, `subject`) se
  toleran y `expected_documents` vacío es válido — no hay esquema cerrado,
  como pide la spec.
- **`id` duplicados**: se validan entre todos los bancos pasados por CLI,
  replicando la semántica de `test_ids_are_unique_and_groups_do_not_leak`; un
  banco repetido en `--banks` se deduplica antes de cargar para no disparar
  falsos `BANK_INVALID` contra sí mismo.
- **Salida por `sys.stdout.buffer`** (UTF-8, LF): evita la traducción de
  saltos/encoding de Windows en el JSON de stdout; el JSON impreso y el fichero
  escrito son byte-idénticos (lo verifica la prueba 2).
- **`schema_version: 1`** y forma del inventario exactas a la spec; `by_kind`
  lleva siempre las cuatro claves (0 si no hay casos), y `conversations` /
  `languages` ordenadas y sin duplicados.

## Riesgos / pendientes

- **Porcelain del fichero nuevo**: ver arriba; la prueba de "no diff entre las
  dos escrituras" es SHA-256 idéntico + porcelain vacío con
  `--untracked-files=no`. Tras el commit del coordinador, el experimento
  literal quedará vacío también sin ese flag.
- **H0_SKIP en worktrees**: hasta que el corpus privado llegue al checkout,
  el gate de worktree no ejecuta `tests/`; los tests nuevos están verificados
  con el mismo comando de discover y correrán en el gate del checkout principal.
- Si el árbol cambia (bancos o catálogos), `--check` fallará: el arreglo es
  `--write` con revisión del diff, no editar el JSON a mano.

## Lecciones de la librería

Leídas `task_7000f0aad22d` y `task_ac91e49ebd62` (review `ACEPTADO` con
`FILES=` vacío): esta tarea deja cuatro ficheros nuevos reales en el árbol y
`worker_done` llevará `--files-modified` explícito para que el review no salga
con `FILES=` vacío.

## Commit

El worker no hace commit; los cuatro ficheros quedan sin stage para el
orquestador: `scripts/h3/bank_inventory.py`,
`evaluation/h3/bank-inventory.json`, `tests/test_bank_inventory.py`,
`docs/h3/bank-inventory.md`, `report.md`.
