# Reporte · task_dd61ac8a9755

## Resultado

Se añadió `scripts/h3/pdf_conversion_report.py`, un arnés reproducible que mide la conversión PDF real de los 17 PDF del corpus y las tablas reconstruidas, y se limitó `page.find_tables()` en `recover_pdf_page` a las páginas que realmente han perdido texto. La captura canónica (SHA-256 del Markdown completo y diagnósticos) es **idéntica byte a byte antes y después** en los 17 archivos; el tiempo de conversión baja de 167,4 s a 110,3 s (34 % menos, 412 páginas). El gate termina en `CHECK_OK`.

## Archivos

- `scripts/h3/pdf_conversion_report.py` (nuevo) — arnés de medición: páginas, pérdidas, tablas detectadas/reconstruidas/correctas, palabras de tabla perdidas, cobertura por página, bytes/SHA-256 y segundos; `--corpus`, `--files`, `--json`.
- `apps/api/bibliotecario/converters.py` — `recover_pdf_page` calcula la cobertura antes de `find_tables()` y solo escanea tablas si la página tiene texto perdido (bloque >50 %, cobertura < `PDF_MIN_COVERAGE` o algún run de líneas perdidas).
- `apps/api/tests/test_pdf_conversion.py` (nuevo) — 4 tests: página limpia sin llamada a `find_tables`, recuperación de texto y de tabla perdida con diagnósticos, y que por documento solo se escanean las páginas con pérdida.
- `report.md` — este informe.

## Checks

| Check | Comando | Resultado |
|---|---|---|
| Gate completo | `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .` | PASS (`CHECK_OK`, 129 tests, `H0_SKIP`, typecheck web) |
| Tests nuevos | `PYTHONPATH=<worktree>/apps/api .venv/Scripts/python.exe -m pytest apps/api/tests/test_pdf_conversion.py -q` | PASS (4 passed) |
| Arnés antes | `.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus --json .orca-task/pdf-conversion-before.json` | PASS (17/17) |
| Arnés después | `.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus --json .orca-task/pdf-conversion-after.json` | PASS (17/17) |
| Comparación antes/después | campo a campo sobre los dos JSON (ignorando `secs`) | PASS (0 diferencias) |

## Identidad del Markdown y de los diagnósticos

Comparación campo a campo de `files[]` entre `.orca-task/pdf-conversion-before.json` (código original) y `.orca-task/pdf-conversion-after.json` (código nuevo), ignorando solo `secs`: **todas las claves coinciden** en los 17 archivos, incluidos `sha256`, `markdown_bytes`, `diagnostics`, `pages`, `pages_text_loss`, `tables_detected`, `tables_rebuilt`, `tables_correct`, `table_words_lost` y `coverage_min/mean`.

| Archivo | SHA-256 del Markdown (idéntico antes/después) | Diagnósticos (idénticos antes/después) |
|---|---|---|
| arxiv-attention-is-all-you-need-en.pdf | `19295e103107c16576e9ce0930858c1a859f41e78d94c2fb0a2113c2bb4a03cb` | pdf_images_omitted, pdf_text_recovered_page_1, pdf_text_recovered_page_5, pdf_text_recovered_page_6, pdf_text_recovered_page_8, pdf_text_recovered_page_9, pdf_tables_recovered_page_13, pdf_text_recovered_page_13, pdf_text_loss_page_13, pdf_text_recovered_page_14, pdf_text_loss_page_14, pdf_text_recovered_page_15, pdf_text_loss_page_15 |
| arxiv-bert-en.pdf | `3740d86f0227ad30e7c9e671a4079446ff1267a1231e613c0bf9adf7adaf5c8d` | pdf_images_omitted, pdf_text_recovered_page_1, pdf_text_loss_page_1, pdf_text_recovered_page_2, pdf_text_loss_page_2, pdf_tables_recovered_page_3, pdf_text_recovered_page_3, pdf_text_loss_page_3, pdf_text_recovered_page_4, pdf_text_loss_page_4, pdf_text_recovered_page_5, pdf_text_loss_page_5, pdf_text_recovered_page_6, pdf_text_recovered_page_7, pdf_text_loss_page_7, pdf_text_recovered_page_8, pdf_text_loss_page_8, pdf_text_recovered_page_9, pdf_text_loss_page_9, pdf_text_recovered_page_10, pdf_text_recovered_page_11, pdf_text_recovered_page_12, pdf_text_recovered_page_13, pdf_text_loss_page_13, pdf_text_recovered_page_14, pdf_text_loss_page_14, pdf_tables_recovered_page_15, pdf_text_recovered_page_15, pdf_text_loss_page_15, pdf_text_recovered_page_16, pdf_text_loss_page_16 |
| boe-constitucion-1978.pdf | `bfea8bb9ea6bf19eba83de6e20eca60ddea8cd7cf1e8ffc2ef54196ea8854fd1` | pdf_images_omitted, pdf_text_recovered_page_35 |
| boe-ley-propiedad-horizontal.pdf | `c1a3ba975f2410232bd2fbe358323a1ba717f8a6c1595d3451b859b1d9a90d8e` | pdf_images_omitted |
| wiki-Apis_mellifera.pdf | `de476865f8db6be83ab9392b754900dc4b498915bda9d2122f2e551455fc38a6` | pdf_images_omitted, pdf_text_recovered_page_1, pdf_tables_recovered_page_3, pdf_tables_recovered_page_4, pdf_text_recovered_page_5, pdf_text_recovered_page_11 |
| wiki-Café.pdf | `0124aa266c4db19fbc6a6394d59b6345f1bdd24a8af4e25ffe5e8a0f4f3ffe8c` | pdf_images_omitted, pdf_text_recovered_page_1, pdf_text_loss_page_1, pdf_text_recovered_page_2, pdf_text_recovered_page_30, pdf_text_recovered_page_35, pdf_tables_recovered_page_41, pdf_text_recovered_page_41, pdf_tables_recovered_page_46, pdf_text_recovered_page_46 |
| wiki-Copa_Mundial_de_Fútbol.pdf | `14342a0f822d99170fef20c28e9c38454741ccdb3b03910a8de106f871f82c77` | pdf_images_omitted, pdf_text_recovered_page_1, pdf_text_recovered_page_2, pdf_text_recovered_page_3, pdf_text_recovered_page_4, pdf_text_recovered_page_6, pdf_text_recovered_page_7, pdf_tables_recovered_page_12, pdf_tables_recovered_page_13, pdf_text_recovered_page_13, pdf_text_loss_page_13, pdf_tables_recovered_page_14, pdf_text_recovered_page_14, pdf_tables_recovered_page_15, pdf_tables_recovered_page_16, pdf_text_recovered_page_16, pdf_tables_recovered_page_17, pdf_text_recovered_page_17, pdf_text_loss_page_17, pdf_tables_recovered_page_18, pdf_tables_recovered_page_19, pdf_tables_recovered_page_20, pdf_tables_recovered_page_21, pdf_tables_recovered_page_22, pdf_text_recovered_page_22, pdf_tables_recovered_page_23, pdf_text_recovered_page_24, pdf_tables_recovered_page_25, pdf_text_recovered_page_27 |
| wiki-Diabetes_mellitus.pdf | `37762fbe2aa3c5fccfe48c90c4f85e9de3640e0e253455aee41158b9b86af0ca` | pdf_images_omitted, pdf_text_recovered_page_1, pdf_text_recovered_page_8, pdf_text_recovered_page_11, pdf_text_recovered_page_15, pdf_text_recovered_page_30 |
| wiki-Dieta_mediterránea.pdf | `b6962aabd5d8b06d6c6ccbea8cc95718070842a759f44df56e2ed7e260d8e07e` | pdf_images_omitted, pdf_text_recovered_page_1, pdf_text_loss_page_1, pdf_text_recovered_page_6 |
| wiki-Fotosíntesis.pdf | `4f22e854ed0f04fb9bbb891a275cd62896e610382e41a2485c1677265ea2dd25` | pdf_images_omitted, pdf_text_recovered_page_14, pdf_text_recovered_page_21 |
| wiki-Impuesto_sobre_la_renta_de_las_personas_físicas_España.pdf | `2e0164c4fc2e8f2a6ae6166624846a1f39c5233fb7dbde62a51745f38a8e4668` | pdf_images_omitted |
| wiki-Inflación.pdf | `ebf99de851cf850cc8bf51ba215eb20c62c74b5e40b10106a7eb7f23761abea7` | pdf_images_omitted, pdf_text_recovered_page_1, pdf_text_recovered_page_3, pdf_text_recovered_page_4, pdf_text_recovered_page_5, pdf_text_recovered_page_6 |
| wiki-Python.pdf | `002b71dee047ba36c7f78c6ea5ffe02abdc32ffc2cf244a3c1b0669a2fcffd47` | pdf_images_omitted, pdf_text_recovered_page_1, pdf_text_recovered_page_2, pdf_text_recovered_page_8, pdf_text_loss_page_8, pdf_text_recovered_page_13, pdf_text_loss_page_13, pdf_text_recovered_page_14 |
| wiki-Revolución_francesa.pdf | `2ffd12dff28363100705b292929aea7ee4d91d4590157ecde9a32ad27d5d33ba` | pdf_images_omitted, pdf_text_recovered_page_1, pdf_text_recovered_page_7, pdf_text_loss_page_7, pdf_text_recovered_page_9, pdf_text_recovered_page_24, pdf_text_recovered_page_26, pdf_text_recovered_page_32, pdf_text_recovered_page_36, pdf_text_recovered_page_37, pdf_text_loss_page_37, pdf_text_recovered_page_38, pdf_text_recovered_page_39 |
| wiki-Sistema_solar.pdf | `6698654221b582c54827648f858ab526c86694750689cfb6d898d58419f96a36` | pdf_images_omitted, pdf_text_recovered_page_1, pdf_text_loss_page_1, pdf_text_recovered_page_2, pdf_text_recovered_page_5, pdf_text_recovered_page_6, pdf_text_recovered_page_10, pdf_text_recovered_page_14, pdf_text_recovered_page_15 |
| wiki-Tabla_periódica_de_los_elementos.pdf | `87acf7214e8ed160da787ebe24de7dfde420f27113da3a70dcd25a62f6b5ae50` | pdf_images_omitted, pdf_tables_recovered_page_2, pdf_text_recovered_page_3, pdf_text_loss_page_3, pdf_text_recovered_page_5, pdf_text_loss_page_5, pdf_text_recovered_page_6, pdf_text_recovered_page_8, pdf_text_recovered_page_15, pdf_text_recovered_page_19, pdf_text_recovered_page_26, pdf_text_recovered_page_27, pdf_text_recovered_page_28, pdf_text_recovered_page_29, pdf_text_recovered_page_30, pdf_text_recovered_page_33 |
| wiki-Volcán.pdf | `596fb533b3c8cdc7bfc8774a04118b2042f25c5109c6e88a1d52b1c4d676b2d7` | pdf_images_omitted |

## Cobertura, pérdida y tablas por archivo

`Tablas det/rec/corr` = detectadas / reconstruidas por `pdf_table_markdown` / con 0 palabras de su `table.bbox` ausentes del Markdown final. Cobertura = palabras de `page.get_text()` presentes en el Markdown de la página (mínima/media).

| Archivo | Págs | Pérdida | Tablas det/rec/corr | Palabras tabla perdidas | Cobertura mín/media | Markdown B | s antes → después |
|---|---:|---:|---|---:|---|---:|---|
| arxiv-attention-is-all-you-need-en.pdf | 15 | 3 | 6/1/0 | 319 | 0.489/0.907 | 42870 | 8.2 → 8.0 |
| arxiv-bert-en.pdf | 16 | 12 | 19/2/6 | 38 | 0.818/0.942 | 69813 | 6.7 → 6.7 |
| boe-constitucion-1978.pdf | 39 | 0 | 0/0/0 | 0 | 0.998/1.000 | 125470 | 7.5 → 4.8 |
| boe-ley-propiedad-horizontal.pdf | 20 | 0 | 0/0/0 | 0 | 0.999/1.000 | 81427 | 5.0 → 2.9 |
| wiki-Apis_mellifera.pdf | 11 | 0 | 4/3/1 | 11 | 0.979/0.995 | 45343 | 3.2 → 2.5 |
| wiki-Café.pdf | 47 | 1 | 4/2/1 | 37 | 0.960/0.999 | 249050 | 17.6 → 11.4 |
| wiki-Copa_Mundial_de_Fútbol.pdf | 37 | 2 | 30/19/2 | 460 | 0.728/0.989 | 254200 | 27.8 → 18.7 |
| wiki-Diabetes_mellitus.pdf | 30 | 0 | 2/0/0 | 11 | 0.979/0.999 | 153028 | 11.7 → 6.0 |
| wiki-Dieta_mediterránea.pdf | 8 | 1 | 1/0/0 | 31 | 0.946/0.990 | 35036 | 2.8 → 1.5 |
| wiki-Fotosíntesis.pdf | 22 | 0 | 1/0/0 | 12 | 0.992/0.999 | 92554 | 6.3 → 3.3 |
| wiki-Impuesto_sobre_la_renta_de_las_personas_físicas_España.pdf | 26 | 0 | 2/0/0 | 88 | 0.994/1.000 | 99898 | 6.1 → 3.1 |
| wiki-Inflación.pdf | 11 | 0 | 3/0/2 | 18 | 0.978/0.998 | 72649 | 6.5 → 4.3 |
| wiki-Python.pdf | 24 | 2 | 8/0/0 | 170 | 0.827/0.988 | 78666 | 9.7 → 5.4 |
| wiki-Revolución_francesa.pdf | 40 | 2 | 1/0/0 | 8 | 0.950/0.996 | 207946 | 14.5 → 8.8 |
| wiki-Sistema_solar.pdf | 15 | 1 | 6/0/0 | 239 | 0.944/0.994 | 103084 | 10.7 → 7.3 |
| wiki-Tabla_periódica_de_los_elementos.pdf | 33 | 2 | 14/2/7 | 54 | 0.954/0.996 | 192820 | 18.3 → 13.3 |
| wiki-Volcán.pdf | 18 | 0 | 0/0/0 | 0 | 0.996/0.999 | 72809 | 4.6 → 2.4 |

### Los 5 archivos más lentos (segundos de conversión)

| Archivo | Antes | Después | Mejora |
|---|---:|---:|---:|
| wiki-Copa_Mundial_de_Fútbol.pdf | 27,8 | 18,7 | −33 % |
| wiki-Tabla_periódica_de_los_elementos.pdf | 18,3 | 13,3 | −27 % |
| wiki-Café.pdf | 17,6 | 11,4 | −35 % |
| wiki-Revolución_francesa.pdf | 14,5 | 8,8 | −39 % |
| wiki-Diabetes_mellitus.pdf | 11,7 | 6,0 | −49 % |
| **Total 17 PDF (412 páginas)** | **167,4** | **110,3** | **−34 %** |

## Decisiones

- **Puerta de detección de tablas.** Antes de `find_tables()` se calcula: (a) si algún bloque ha perdido >50 % de sus palabras, (b) la cobertura de la página (`source - available`, con el mismo `PDF_MIN_COVERAGE`), y (c) un pre-escaneo de runs de líneas perdidas. Si nada de eso ocurre, la página no tiene texto perdido y no se escanea. Justificación: una tabla con >20 % de palabras ausentes (umbral que usa el reconstruir) necesariamente tiene alguna línea con >20 % ausente, que el pre-escaneo detecta; por eso saltarse `find_tables()` no puede perder una tabla que el código original reconstruiría.
- **No se reutilizan los runs del pre-escaneo en el bucle de bloques.** La primera versión lo hacía y duplicaba un texto recuperado (p. 8 de Attention): al recuperar un bloque se actualiza `available`/`stream`, así que los bloques posteriores deben reevaluarse. El pre-escaneo solo decide si hay que escanear tablas; si probó que no falta nada y no se colocó ninguna tabla, se omite el bucle (equivalente a recorrerlo sin recuperar nada).
- **Métrica de tablas.** Por cada tabla detectada se cuentan las ocurrencias de palabras de `page.get_text("words", clip=table.bbox)` que no aparecen en el Markdown final de la página; `tables_correct` son las tablas con 0 palabras ausentes. Mide contenido conservado, no la atribución fila/columna (una tabla con todas las palabras pero mal ordenada cuenta como correcta), tal como pide el alcance.
- **Reproducibilidad del arnés.** El layout legacy de PyMuPDF depende del orden de hashing de cadenas: con `PYTHONHASHSEED` aleatorio se observaron diferencias esporádicas entre ejecuciones del **mismo** código (p. ej. Copa Mundial 254200 vs 254203, BERT 69813 vs 69811). El script fija `PYTHONHASHSEED=0` con un único re-exec si no está definido y lo registra en el JSON (`python_hash_seed`); las capturas canónicas antes/después se hicieron así. La primera captura "antes" (aleatoria) se descartó por eso; la comparación final usa las dos ejecuciones con semilla fijada.
- **`baseline.json` del corpus** guarda en `sha256` el hash del PDF de origen (12 hex), no el del Markdown; se usó solo como control de páginas/pérdidas/tablas, que coincide.
- **Reutilización**: el script usa directamente `convert()` y las utilidades existentes (`_words`, `_stream`, `_missing`, `_missing_runs`, `_block_missing`, `_center_in`, `pdf_table_markdown`); no se añadieron dependencias.

## Riesgos / pendientes

- El tiempo `secs` que publica el arnés mide solo `convert()`; la auditoría de tablas del propio script vuelve a llamar a `find_tables()` en todas las páginas para poder comparar antes/después, así que el tiempo de pared del script es mayor que la conversión medida.
- La puerta asume que el texto de una tabla aparece en los bloques de texto de la página. PDFs con tablas puramente vectoriales/sin texto podrían quedar fuera del umbral de cobertura; el corpus de 17 PDF no muestra ese caso (identidad byte a byte).
- `docs/*.md` no viaja al worktree: el gate omitió los contratos H0 (`H0_SKIP`); no se tocó nada de H0.
- No se hizo push, merge ni rebase; no se escribió en `.artifacts/` ni en `bibliotecario-data/`.

## Commit

Commit local en la rama `choruzo/pdf-conv-baseline-dd61ac-2` (sin push); el SHA se indica en el `worker_done`.
