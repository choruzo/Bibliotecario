# Conversión PDF: comparación de estrategias

## Resumen

La conversión PDF usaba siempre la ruta clásica de `pymupdf4llm` (modo legacy)
más la recuperación heurística de `recover_pdf_page`. Esta tarea la convierte en
una estrategia seleccionable (`BIB_PDF_LAYOUT`) y mide dos alternativas sobre
los 17 PDF del corpus agnóstico.

La nueva estrategia `layout` (analizador de maquetación de `pymupdf-layout`)
reduce las páginas con pérdida de texto de 26 a 19 y mejora la cobertura en casi
todos los documentos, pero **empeora** la métrica de tablas (19 → 13 tablas con
todas sus palabras; 1496 → 4983 palabras de tabla ausentes) y tarda un 40,6 %
más (173,6 s frente a 123,5 s). No cumple el criterio de adopción, así que el
valor por defecto sigue siendo `legacy`. La variante de medición
`tables-lines` también se midió; queda documentada pero no se adopta.

## Estrategias

`Settings.pdf_layout` (entorno `BIB_PDF_LAYOUT`, valores `legacy` y `layout`,
por defecto `legacy`) elige el conversor de la rama PDF de
`apps/api/bibliotecario/converters.py`:

| Estrategia | Conversor | Configurable | Descripción |
|---|---|---|---|
| `legacy` | `pymupdf4llm.to_markdown` (modo clásico) | sí (defecto) | Comportamiento histórico byte a byte, incluida la recuperación de texto y tablas. |
| `layout` | `pymupdf.layout` + `pymupdf4llm.helpers.document_layout` | sí | Analizador ONNX de maquetación; detecta columnas y ordena bloques. |
| `tables-lines` | `pymupdf4llm.to_markdown(table_strategy="lines")` | solo arnés | Variante de medición de `to_markdown`; no se expone en `Settings`. |

Detalles de implementación:

- Los imports de `layout` son diferidos dentro de `_layout_pdf_chunks()`. Si
  `pymupdf.layout` no está instalado, o el analizador falla, `convert()` vuelve
  a `legacy` y añade el diagnóstico `pdf_layout_unavailable`.
- `pymupdf-layout` se declara como extra opcional `layout` en
  `apps/api/pyproject.toml`; no es dependencia por defecto.
- El resultado de `convert()` para PDF incluye `pdf_layout` con la estrategia
  realmente usada (útil para el arnés y para diagnosticar caídas a `legacy`).

## Entorno

- `pymupdf 1.28.2`, `pymupdf4llm 0.3.4`, Python 3.12.12 (`.venv` compartido).
- **`pymupdf-layout` NO está instalado** en el `.venv` compartido (comprobado
  en la tarea de baseline, `docs/h3/pdf-baseline.md`, con `uv pip list` antes y
  después). Las columnas `layout`/`tables-lines` de este documento **no son
  reproducibles** hoy: con `BIB_PDF_LAYOUT=layout` la conversión cae a `legacy`
  con el diagnóstico `pdf_layout_unavailable`. El dry-run de la tarea de
  baseline confirma que instalar el extra no movería `pymupdf` ni
  `pymupdf4llm`; no se instaló.
- El paquete de distribución se llama `pymupdf-layout`; el módulo que se
  importa es `pymupdf.layout`.

## Método de medida

`scripts/h3/pdf_conversion_report.py` ejecuta el `convert()` de producción de
este worktree (no el editable del checkout principal) y mide, por PDF:

- páginas y páginas con diagnóstico `pdf_text_loss_page_*`;
- tablas detectadas por `page.find_tables()`, reconstruidas por
  `pdf_table_markdown()` y «correctas» (0 palabras de su `bbox` ausentes del
  Markdown final de la página);
- palabras de tabla perdidas (ocurrencias de `get_text("words")` dentro de la
  tabla ausentes del Markdown final);
- cobertura de palabras por página (mínima y media);
- bytes y SHA-256 del Markdown completo y segundos de `convert()`.

El script fija `PYTHONHASHSEED=0` con un re-exec para reducir la dependencia del
orden de hashing de PyMuPDF. Aun así, `wiki-Copa_Mundial_de_Fútbol.pdf` oscila
entre dos Markdown de 254.200 y 254.203 bytes (3 bytes, ya observado en la tarea
`pdf-conv-baseline`); el resto de archivos es estable dentro de un proceso.
Desde la tarea del censo de pérdida el arnés añade el bloque `content_audit`
(auditoría de pérdida real vs artefactos, `docs/h3/pdf-two-column-loss.md`).

## Resultados por archivo

`L` = `legacy`, `Y` = `layout`, `T` = `tables-lines`. Tablas como
`detectadas/reconstruidas/correctas`. Tiempos en segundos de `convert()`.

| arxiv-attention-is-all-you-need-en.pdf | 15 | 3/1/1 | 6/1/0 | 4/0/0 | 6/1/0 | 319/206/192 | 0.489/0.969 | 8,6/8,7/9,6 |
| arxiv-bert-en.pdf | 16 | 12/14/12 | 19/2/6 | 9/0/0 | 19/1/6 | 38/307/38 | 0.818/0.927 | 7,2/14,4/6,1 |
| boe-constitucion-1978.pdf | 39 | 0/0/0 | 0/0/0 | 2/0/0 | 0/0/0 | 0/1275/0 | 0.998/1.000 | 4,8/8,1/4,4 |
| boe-ley-propiedad-horizontal.pdf | 20 | 0/0/0 | 0/0/0 | 2/0/0 | 0/0/0 | 0/2110/0 | 0.999/1.000 | 3,4/5,3/3,6 |
| wiki-Apis_mellifera.pdf | 11 | 0/0/0 | 4/3/1 | 3/0/1 | 4/0/1 | 11/14/14 | 0.979/0.997 | 2,9/3,7/1,7 |
| wiki-Café.pdf | 47 | 1/0/1 | 4/2/1 | 3/0/1 | 4/0/1 | 37/57/44 | 0.960/0.992 | 12,4/14,0/9,9 |
| wiki-Copa_Mundial_de_Fútbol.pdf | 37 | 2/2/1 | 30/19/2 | 24/0/2 | 30/0/2 | 460/417/433 | 0.728/0.873 | 20,5/26,5/15,7 |
| wiki-Diabetes_mellitus.pdf | 30 | 0/0/0 | 2/0/0 | 3/0/0 | 2/0/0 | 11/32/11 | 0.979/0.987 | 7,2/10,8/6,0 |
| wiki-Dieta_mediterránea.pdf | 8 | 1/0/1 | 1/0/0 | 2/0/0 | 1/0/0 | 31/38/31 | 0.946/0.983 | 2,0/3,0/1,8 |
| wiki-Fotosíntesis.pdf | 22 | 0/0/0 | 1/0/0 | 1/0/0 | 1/0/0 | 12/12/12 | 0.992/0.992 | 3,8/6,7/3,3 |
| wiki-Impuesto_sobre_la_renta_de_las_personas_físicas_España.pdf | 26 | 0/0/0 | 2/0/0 | 2/0/0 | 2/0/0 | 88/88/88 | 0.994/0.982 | 3,5/6,2/3,2 |
| wiki-Inflación.pdf | 11 | 0/0/0 | 3/0/2 | 3/0/2 | 3/0/2 | 18/8/18 | 0.978/0.994 | 5,3/5,3/4,1 |
| wiki-Python.pdf | 24 | 2/1/2 | 8/0/0 | 2/0/0 | 8/0/0 | 170/55/170 | 0.827/0.954 | 6,6/10,3/5,6 |
| wiki-Revolución_francesa.pdf | 40 | 2/1/2 | 1/0/0 | 1/0/0 | 1/0/0 | 8/3/8 | 0.950/0.967 | 10,0/14,9/8,4 |
| wiki-Sistema_solar.pdf | 15 | 1/0/1 | 6/0/0 | 7/0/0 | 6/0/0 | 239/265/237 | 0.944/0.993 | 7,9/12,1/5,9 |
| wiki-Tabla_periódica_de_los_elementos.pdf | 33 | 2/0/2 | 14/2/7 | 12/0/7 | 14/0/7 | 54/96/55 | 0.954/0.984 | 14,7/19,3/11,4 |
| wiki-Volcán.pdf | 18 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 | 0/0/0 | 0.996/0.985 | 2,7/4,2/3,1 |

### Totales (17 PDF, 412 páginas)

| Métrica | legacy | layout | tables-lines |
|---|---:|---:|---:|
| Páginas con `pdf_text_loss` | 26 | **19** | 23 |
| Tablas detectadas | 101 | 80 | 101 |
| Tablas reconstruidas por la recuperación | 29 | 0 | 2 |
| Tablas con todas sus palabras | **19** | 13 | **19** |
| Palabras de tabla perdidas | **1496** | 4983 | 1351 |
| Páginas con texto recuperado | 95 | 151 | 89 |
| Segundos de `convert()` | **123,5** | 173,6 | 103,9 |

## Decisión

Se mantiene **`legacy`** como valor por defecto (`BIB_PDF_LAYOUT=legacy`).

- `layout` sí reduce las páginas con pérdida (26 → 19) y mejora la cobertura,
  sobre todo en `arxiv-attention-is-all-you-need-en.pdf` (pérdida 3 → 1;
  cobertura mínima 0,489 → 0,969), `wiki-Python.pdf` (2 → 1), `wiki-Sistema_solar.pdf`
  (1 → 0) y `wiki-Tabla_periódica_de_los_elementos.pdf` (2 → 0). Pero
  `arxiv-bert-en.pdf` empeora (12 → 14), justo el caso a dos columnas que
  motivaba la prueba.
- En tablas no gana: 13 tablas correctas frente a 19 y 4983 palabras perdidas
  frente a 1496. Parte de la diferencia es un artefacto de la métrica (ver
  abajo), pero el criterio acordado es el número, no una interpretación
  favorable.
- El tiempo total empeora un **40,6 %** (173,6 s frente a 123,5 s), por encima
  del 20 % admitido.

Por tanto no se cumple la condición de adopción («reduce pérdida y tablas mal
reconstruidas y no empeora el tiempo más de un 20 %»). La estrategia queda
disponible y probada, pero desactivada. Cambiar el defecto alteraría lo
indexado y exigiría reindexar, que queda fuera de esta tarea.

`tables-lines` se midió como variante de `to_markdown`: mejora algo la pérdida
(26 → 23) y las palabras de tabla perdidas (1496 → 1351), y es algo más rápida
(103,9 s), pero cambia el Markdown y la detección de tablas (`tablas
reconstruidas` 29 → 2 porque `pymupdf4llm` ya las renderiza). No se adopta como
defecto: la tarea solo contempla `layout` como alternativa configurable y este
cambio también alteraría el corpus indexado sin reindexado.

### Limitaciones de la métrica de tablas

- `find_tables()` puede devolver como tabla regiones que no lo son. En los dos
  BOE detecta una tabla que cubre el índice con líneas de puntos; `layout`
  colapsa esos puntos en su escritura de tablas y la métrica las cuenta como
  «perdidas» (1275 y 2110 palabras). Es una mejora de limpieza, no una pérdida
  real de contenido, pero la métrica no lo distingue.
- Las palabras de una tabla se cuentan por ocurrencia dentro del `bbox`; si el
  conversor deduplica celdas repetidas (frecuente en `layout`), se contabilizan
  como ausentes.
- La métrica mide contenido conservado, no la atribución fila/columna: una
  tabla con todas sus palabras mal ordenada cuenta como correcta.

## Reproducción

```powershell
# Estrategia por defecto (debe reproducir el baseline versionado:
# evaluation/h3/pdf-legacy-baseline.json)
.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py `
  --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus `
  --layout legacy --json .orca-task/results-legacy.json

# Nueva estrategia de maquetación (requiere el extra `layout`; sin él cae a legacy
# con pdf_layout_unavailable, ver Entorno)
.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py `
  --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus `
  --layout layout --json .orca-task/results-layout.json

# Variante de medición de pymupdf4llm
.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py `
  --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus `
  --layout tables-lines --json .orca-task/results-tables-lines.json

# Censo de pérdida real vs artefactos (bloque content_audit; censo completo con
# --audit-json; --no-audit para medir sin la auditoría)
.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py `
  --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus `
  --layout legacy --json .orca-task/results-legacy.json `
  --audit-json .orca-task/results-content-audit.json
```

Para iterar sobre pocos archivos, añadir `--files nombre1.pdf,nombre2.pdf`.

## Identidad del comportamiento por defecto

La referencia versionada del comportamiento `legacy` es el baseline de la tarea
`pdf-env-baseline` (`evaluation/h3/pdf-legacy-baseline.json`, método en
`docs/h3/pdf-baseline.md`): dos pasadas completas en procesos separados con
`PYTHONHASHSEED=0` produjeron Markdown **byte-idéntico en 17/17 archivos**, y
esos SHA-256 son la referencia de no regresión.

Observaciones posteriores sobre el mismo corpus:

- `wiki-Copa_Mundial_de_Fútbol.pdf` sigue oscilando entre 254.200 (canónico,
  SHA `14342a0f822d99170fef20c28e9c38454741ccdb3b03910a8de106f871f82c77`,
  reproducido ejecutándolo solo) y 254.203 bytes en pasadas completas.
- `arxiv-bert-en.pdf` tiene variantes entre procesos (69.809/69.813/69.815
  bytes observados) según el estado global de PyMuPDF arrastrado por los
  archivos previos; la conversión aislada reproduce el SHA del baseline
  (`3740d86f…`). Es la inestabilidad intra-proceso ya documentada en la tarea
  del baseline.

## Tests

`apps/api/tests/test_pdf_conversion.py` añade cuatro pruebas:

- `pdf_layout` vale `legacy` por defecto y `layout` con `BIB_PDF_LAYOUT=layout`;
- el ajuste implícito y `legacy` explícito producen el mismo Markdown y
  diagnósticos;
- si `pymupdf.layout` no se puede importar, la conversión cae a `legacy` y
  añade `pdf_layout_unavailable`;
- la rama `layout` convierte un PDF pequeño de dos columnas generado en el test
  (se omite si el extra no está instalado).
