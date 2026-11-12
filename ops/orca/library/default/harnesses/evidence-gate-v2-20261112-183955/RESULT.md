# Probe de harness: evidence-gate-v2-20261112-183955  - Run: `run_d6862611c96e` - Rama base: `main` - Variante: `D:\Archivos\Javier\Proyectos\Bibliotecario\.orca-run\harness-variants\evidence-gate` - Tareas: base `task_293aeeb977ad` / variante `task_e5c16b6c7d68` - Decision: **none** - sin contraste medible  | Lado | Terminada | Veredicto | Defectos | Archivos | Evidencia | |---|---|---|---|---|---| | base | True | ACEPTADO | 0 | 4 | sin medir | | variante | True | ACEPTADO | 0 | 7 | sin medir |  La columna Evidencia cuenta needles MISSING segun el auditor offline aplicado igual a los dos lados; `sin medir` = no se pidio auditoria. Los artefactos de cada lado (`report.md`, `review.json`) quedan en `side-base/` y `side-variant/` junto a este fichero.  ## Spec de calibracion  # Inventario reproducible de los bancos H3 y sus catálogos

## Objetivo
Que exista `scripts/h3/bank_inventory.py` y un `evaluation/h3/bank-inventory.json` versionado que describan, de forma determinista y verificable, los cuatro bancos H3 y los dos catálogos: cuántos casos tiene cada banco, su reparto por `kind`, sus grupos de conversación, sus idiomas y el SHA-256 de cada fichero; con `--check` en el gate para detectar deriva.

## Contexto
- Repo `D:/Archivos/Javier/Proyectos/Bibliotecario`: API FastAPI, web Next.js, gate en `ops/orca/check.ps1`.
- Bancos H3 (JSONL, una línea por caso):
  - `evaluation/h3/agnostic-calibration-v1.jsonl`
  - `evaluation/h3/agnostic-validation-v1.jsonl`
  - `evaluation/h3/colloquial-calibration-v1.jsonl`
  - `evaluation/h3/colloquial-validation-v1.jsonl`
- Catálogos (`{"documents": [...]}` con `id`, `file`, `sha256`, `bytes`):
  - `evaluation/h0/corpus_catalog.json`
  - `evaluation/h3/agnostic_corpus_catalog.json`
- Cada caso tiene al menos `id`, `kind`, `language`, `query`, `expected_documents`, `expected_sections`, `tags`; los de `kind: conversation` añaden `conversation_id`, `turn` y, a partir del segundo turno, `subject`. Hay dos tests de contrato que ya cubren el banco agnóstico (`tests/test_agnostic_banks.py`): no los dupliques ni los sustituyas.
- Gate: `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .` (~90 s; en worktree los contratos H0 se omiten con `H0_SKIP`). Ejecuta `git diff --check`, los tests de `apps/api/tests`, los de `tests/` y el typecheck de la web. El `.venv` es compartido: no instales ni actualices paquetes.
- No hay Docker, Postgres, LLM ni red en esta tarea: todo se lee del árbol de trabajo.

## Alcance
- Incluye:
  1. `scripts/h3/bank_inventory.py` (nuevo, solo stdlib) con este contrato de CLI:
     - `--banks <path...>` (por defecto los cuatro de arriba) y `--catalogs <path...>` (por defecto los dos de arriba).
     - `--inventory <path>` (por defecto `evaluation/h3/bank-inventory.json`).
     - Sin modo: imprime el inventario JSON en stdout y sale 0.
     - `--write`: escribe el inventario en `--inventory` y sale 0 con una única línea `BANK_INVENTORY_WRITTEN path=<ruta> banks=<n> cases=<n>`.
     - `--check`: regenera en memoria y compara con el fichero del disco. Si coincide, sale 0 con `BANK_INVENTORY_OK banks=<n> cases=<n> catalogs=<n>`; si difiere, sale 1 con una línea `BANK_INVENTORY_DRIFT path=<ruta> field=<campo>` por cada diferencia (máximo 20) y nada más.
     - Un banco que no parsea (JSON inválido, línea vacía con contenido, `kind` desconocido, `id` duplicado entre bancos) sale 1 con `BANK_INVALID <ruta>:<línea> <motivo>` y no escribe nada.
     - Ninguna ruta se resuelve por `cwd`: desde `__file__` hasta la raíz del repo, y las rutas del inventario se emiten relativas a la raíz en POSIX.
  2. Forma del inventario (exacta; el orden de claves es el que produce `json.dumps(..., sort_keys=True)`):
     ```json
     {
       "schema_version": 1,
       "banks": {
         "evaluation/h3/agnostic-calibration-v1.jsonl": {
           "cases": 0,
           "by_kind": {"ambiguous": 0, "answerable": 0, "conversation": 0, "unanswerable": 0},
           "conversations": ["AGN-CAL-CONV-001"],
           "languages": ["de", "en", "es", "fr", "it"],
           "sha256": "..."
         }
       },
       "catalogs": {
         "evaluation/h3/agnostic_corpus_catalog.json": {"documents": 0, "sha256": "..."}
       }
     }
     ```
     `by_kind` incluye siempre las cuatro claves (0 cuando no hay casos), con los `kind` presentes y ninguna otra; `conversations` y `languages` van ordenadas y sin duplicados; el JSON se escribe con `indent=2`, `ensure_ascii=False`, claves ordenadas y salto de línea final. Sin marcas de tiempo, sin rutas absolutas y sin nada que dependa del entorno: dos ejecuciones sobre el mismo árbol deben ser byte-idénticas.
  3. `evaluation/h3/bank-inventory.json` versionado, generado **ejecutando** el script sobre el árbol real. No se escribe a mano ni se rellena con cifras supuestas.
  4. `tests/test_bank_inventory.py` (unittest, sin red ni Docker) con cuatro pruebas:
     - `--check` sobre el repo sale 0 e imprime `BANK_INVENTORY_OK`;
     - el inventario regenerado en memoria es igual al fichero versionado (cobertura de los 4 bancos y los 2 catálogos incluida);
     - un banco copiado a un directorio temporal y mutado (por ejemplo, `id` duplicado o `kind` inválido) hace salir al script con código 1 y mensaje `BANK_INVALID`;
     - un inventario temporal con un `cases` alterado hace salir `--check` con código 1 y `BANK_INVENTORY_DRIFT`.
  5. `docs/h3/bank-inventory.md` (nuevo): qué mide, el contrato de CLI, por qué lleva SHA-256 y cómo se regenera (`--write`) y se verifica (`--check`).
  6. `report.md` con la plantilla de `ops/orca/report-template.md`.
- No incluye:
  - tocar los bancos, los catálogos, `tests/test_agnostic_banks.py`, `check.ps1` ni `apps/`;
  - cambiar reglas de validación de casos existentes (esta tarea describe, no juzga la calidad de los casos);
  - Docker, Postgres, LLM, red, `.artifacts/` ni `bibliotecario-data/`;
  - recalibrar ni aceptar nada.

## Archivos probablemente afectados
- `scripts/h3/bank_inventory.py` (nuevo)
- `evaluation/h3/bank-inventory.json` (nuevo, generado)
- `tests/test_bank_inventory.py` (nuevo)
- `docs/h3/bank-inventory.md` (nuevo)
- `report.md`

## Dependencias
- Ninguna.

## Criterios de aceptación
- [ ] `BANK_INVENTORY_OK` con `--check` sobre el árbol limpio y código de salida 0.
- [ ] `python scripts/h3/bank_inventory.py --write` dos veces seguidas no produce ningún diff en `evaluation/h3/bank-inventory.json` (`git status --porcelain evaluation/h3/bank-inventory.json` vacío tras la segunda).
- [ ] El inventario versionado cubre exactamente los 4 bancos y los 2 catálogos, con los totales y el reparto por `kind` que el script calcula del árbol real.
- [ ] Las cuatro pruebas de `tests/test_bank_inventory.py` pasan, incluidas las dos de fallo (banco mutado y deriva de inventario).
- [ ] `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .` termina en `CHECK_OK=...` con los tests nuevos incluidos.
- [ ] Ningún fichero de `evaluation/h3/*.jsonl`, `evaluation/*/corpus_catalog.json`, `tests/test_agnostic_banks.py` ni `ops/orca/check.ps1` aparece en el diff.
- [ ] `report.md` cita evidencia literal: el comando y la línea `BANK_INVENTORY_OK …`, el SHA-256 de `evaluation/h3/bank-inventory.json`, la línea `CHECK_OK=…` del gate y el resultado de los cuatro tests. Sin esas salidas, el informe no cumple.
- [ ] `docs/h3/bank-inventory.md` permite a otra persona regenerar y verificar el inventario sin leer el código.

## Checks obligatorios
- `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .`
- `.venv/Scripts/python.exe scripts/h3/bank_inventory.py --check`
- `.venv/Scripts/python.exe -m unittest tests.test_bank_inventory -v`
- `.venv/Scripts/python.exe scripts/h3/bank_inventory.py --write` seguido de `git status --porcelain evaluation/h3/bank-inventory.json` (debe salir vacío)

## Entrega
- Worktree: el que asigne Orca. Rama: la que cree Orca.
- Informe: `report.md` con `ops/orca/report-template.md`, con las salidas **pegadas** (no resumidas ni parafraseadas).
- Deja los cambios sin stage; envía un único `worker_done` con `taskId` y `dispatch_id`.
- Prohibido: push, merge, rebase, `orca orchestration task-update`, `git add`, `git commit`, tocar otros worktrees.
- Si un comando no lo has ejecutado, no escribas que pasó: escribe que no lo ejecutaste y por qué. Un dato inventado invalida la entrega completa.

## Riesgos / notas
- **Deriva del propio inventario**: si el script y el fichero se generan con distinto orden de claves o distinto salto de línea, `--check` dará falso positivo. Fija el formato una sola vez (`sort_keys=True`, `indent=2`, `ensure_ascii=False`, `\n` final) y pruébalo con la doble ejecución.
- **Falsos positivos de `BANK_INVALID`**: `expected_documents` vacío es válido en `unanswerable` y `ambiguous`, y las claves extra (`conversation_id`, `turn`, `subject`) son legítimas. No valides la forma con un esquema cerrado.
- No metas cifras a mano: el valor de este inventario es que se regenera. Si el árbol cambia, `--check` debe fallar y el arreglo es `--write` con revisión, no editar el JSON.
- `tests/` se ejecuta con `unittest discover` en el gate: el fichero nuevo debe importarse sin efectos secundarios y sin rutas absolutas.

