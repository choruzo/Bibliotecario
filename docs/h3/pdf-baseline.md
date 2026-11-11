# Baseline de la conversión PDF legacy

Fecha de la medición: 2026-11-11. Esta página congela el entorno y los números
de la conversión PDF `legacy` (la estrategia por defecto) sobre los 17 PDF del
corpus agnóstico, para que cualquier cambio posterior en la conversión se
compare contra una referencia reproducible. Los datos versionados viven en
`evaluation/h3/pdf-legacy-baseline.json`; esta página explica cómo se generaron
y cómo reproducirlos.

Esta medición **no cambia producción**: no modifica `converters.py`, ni el
arnés, ni el comportamiento por defecto.

## Método

- El arnés `scripts/h3/pdf_conversion_report.py` ejecuta el `convert()` real de
  producción del worktree (pone `apps/api` primero en `sys.path`, no usa el
  instalable editable del checkout principal) e intercepta `recover_pdf_page`
  para analizar página a página. Reporta páginas, páginas con
  `pdf_text_loss_page_*`, páginas con texto/tablas recuperadas, tablas
  detectadas/reconstruidas/correctas, palabras de tabla perdidas, cobertura
  por página, bytes/SHA-256 del Markdown y segundos de `convert()`.
- El arnés fija `PYTHONHASHSEED=0` (re-exec) porque el análisis de maquetación
  legacy de PyMuPDF depende del orden de hashing de cadenas.
- El baseline se toma con **dos procesos separados** (pasada 1 y pasada 2) sobre
  los 17 PDF. La comparación pasada 1 ↔ pasada 2 es **17/17 archivos
  byte-identicos** (mismo SHA-256 y mismo tamaño de Markdown): `unstable: false`
  para todos y `variants: []` en el JSON.
- El entorno de medición es un venv aislado (`.artifacts/measure-venv`), no el
  `.venv` compartido. `uv pip list` del `.venv` compartido es idéntico antes y
  después de la tarea.

## Entorno

| Componente | Versión |
|---|---|
| Python | 3.12.12 (CPython de `uv`, mismo 3.12.12 que el `.venv` compartido) |
| `pymupdf` | 1.28.2 |
| `pymupdf4llm` | 0.3.4 |
| `markdown-it-py` | 4.0.0 (misma que en producción; la necesita `bibliotecario.converters` y no es dependencia de `pymupdf4llm` 0.3.4) |
| `defusedxml` | 0.7.1 |
| `tabulate` | 0.10.0 |
| `mdurl` | 0.1.2 |

`pymupdf-layout` **no** está instalado en el entorno de medición (ni en el
`.venv` compartido a fecha de esta medición), así que los números son 100 %
`legacy`.

## Reproducción

Desde la raíz del checkout principal (el corpus vive en
`.artifacts/agnostic-corpus/`, fuera de Git y solo lectura):

```powershell
# 1) Entorno de medición aislado (no tocar el .venv compartido)
uv venv .artifacts/measure-venv --python 3.12.12
uv pip install --python .artifacts/measure-venv `
  "pymupdf==1.28.2" "pymupdf4llm==0.3.4" `
  "markdown-it-py==4.0.0" "defusedxml==0.7.1"

# 2) Dos pasadas en procesos separados, semilla fijada
$env:PYTHONHASHSEED = "0"
.artifacts/measure-venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py `
  --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus `
  --layout legacy --json .artifacts/legacy-pass-1.json

.artifacts/measure-venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py `
  --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus `
  --layout legacy --json .artifacts/legacy-pass-2.json

# 3) Comparar las dos pasadas: los 17 archivos deben coincidir byte a byte
```

El resultado esperado es la tabla de abajo; cualquier desviación de SHA-256 o
de bytes de Markdown debe investigarse antes de usar el baseline.

## Resultados por archivo

«Pérdida» = páginas con diagnóstico `pdf_text_loss_page_*`; «Texto rec.» =
páginas con `pdf_text_recovered_page_*`; «Tablas rec.» = páginas con
`pdf_tables_recovered_page_*`. Segundos de `convert()` de la pasada 1.

| Archivo | Páginas | Bytes PDF | Bytes MD | SHA-256 (inicio) | Pérdida | Texto rec. | Tablas rec. | Segs. |
|---|---:|---:|---:|---|---:|---:|---:|---:|
| `arxiv-attention-is-all-you-need-en.pdf` | 15 | 2.215.244 | 42.870 | `19295e103107c165…` | 3 | 8 | 1 | 9.415 |
| `arxiv-bert-en.pdf` | 16 | 775.166 | 69.813 | `3740d86f0227ad30…` | 12 | 16 | 2 | 7.158 |
| `boe-constitucion-1978.pdf` | 39 | 330.448 | 125.470 | `bfea8bb9ea6bf19e…` | 0 | 1 | 0 | 5.047 |
| `boe-ley-propiedad-horizontal.pdf` | 20 | 211.598 | 81.427 | `c1a3ba975f241023…` | 0 | 0 | 0 | 3.038 |
| `wiki-Apis_mellifera.pdf` | 11 | 711.208 | 45.343 | `de476865f8db6be8…` | 0 | 3 | 2 | 2.759 |
| `wiki-Café.pdf` | 47 | 2.792.479 | 249.050 | `0124aa266c4db19f…` | 1 | 6 | 2 | 10.586 |
| `wiki-Copa_Mundial_de_Fútbol.pdf` | 37 | 4.818.348 | 254.200 | `14342a0f822d9917…` | 2 | 13 | 13 | 19.221 |
| `wiki-Diabetes_mellitus.pdf` | 30 | 1.733.783 | 153.028 | `37762fbe2aa3c5fc…` | 0 | 5 | 0 | 9.908 |
| `wiki-Dieta_mediterránea.pdf` | 8 | 410.278 | 35.036 | `b6962aabd5d8b06d…` | 1 | 2 | 0 | 1.862 |
| `wiki-Fotosíntesis.pdf` | 22 | 1.633.461 | 92.554 | `4f22e854ed0f04fb…` | 0 | 2 | 0 | 4.066 |
| `wiki-Impuesto_sobre_la_renta_de_las_personas_físicas_España.pdf` | 26 | 635.185 | 99.898 | `2e0164c4fc2e8f2a…` | 0 | 0 | 0 | 3.547 |
| `wiki-Inflación.pdf` | 11 | 722.073 | 72.649 | `ebf99de851cf850c…` | 0 | 5 | 0 | 6.373 |
| `wiki-Python.pdf` | 24 | 1.688.765 | 78.666 | `002b71dee047ba36…` | 2 | 5 | 0 | 6.621 |
| `wiki-Revolución_francesa.pdf` | 40 | 2.947.823 | 207.946 | `2ffd12dff2836310…` | 2 | 10 | 0 | 11.356 |
| `wiki-Sistema_solar.pdf` | 15 | 1.840.585 | 103.084 | `6698654221b582c5…` | 1 | 7 | 0 | 9.172 |
| `wiki-Tabla_periódica_de_los_elementos.pdf` | 33 | 2.616.252 | 192.820 | `87acf7214e8ed160…` | 2 | 12 | 1 | 14.282 |
| `wiki-Volcán.pdf` | 18 | 1.196.336 | 72.809 | `596fb533b3c8cdc7…` | 0 | 0 | 0 | 3.461 |
| **Total (17 archivos)** | 412 | 27.279.032 | 1.976.663 | — | 26 | 95 | 21 | 127.872 |

Agregados de tablas (pasada 1): 101 tablas detectadas, 29 reconstruidas por la
recuperación, 19 con todas sus palabras, 1496 palabras de tabla perdidas.
Tiempos totales: 127,9 s (pasada 1) y 148,2 s (pasada 2); los segundos no son
parte de la identidad del baseline, solo del coste.

Los SHA-256 completos (64 hex) de cada archivo están en
`evaluation/h3/pdf-legacy-baseline.json`.

## Discrepancias con `docs/h3/pdf-conversion.md`

- **`layout` no es reproducible hoy.** Ese documento registró `pymupdf-layout
  1.28.2` instalado en el `.venv` compartido en su momento; hoy **no** está
  instalado, así que `BIB_PDF_LAYOUT=layout` cae a `legacy` con el diagnóstico
  `pdf_layout_unavailable` y las columnas `layout`/`tables-lines` de ese
  documento no se pueden reproducir sin instalar el extra. Comprobación con
  `uv pip install --dry-run "pymupdf-layout>=1.28,<2"` en el entorno de
  medición: resolvería `pymupdf-layout==1.28.2` más 7 dependencias nuevas
  (`numpy 2.5.4`, `onnxruntime 1.31.1`, `flatbuffers 25.12.19`, `networkx
  3.7`, `protobuf 7.36.2`, `pyyaml 6.0.3`, `packaging 26.3`) y **no movería**
  `pymupdf==1.28.2` ni `pymupdf4llm==0.3.4`.
- **Agregados legacy idénticos.** Las cifras `legacy` coinciden exactamente con
  la tabla de totales de ese documento: 26 páginas con pérdida, 101 tablas
  detectadas, 29 reconstruidas, 19 correctas, 1496 palabras de tabla perdidas,
  95 páginas con texto recuperado.
- **SHA-256 actuales.** Ese documento solo publica el SHA canónico de
  `wiki-Copa_Mundial_de_Fútbol.pdf`
  (`14342a0f822d99170fef20c28e9c38454741ccdb3b03910a8de106f871f82c77`,
  254.200 bytes); esta medición lo reproduce exactamente en las dos pasadas.
  El resto de SHAs (64 hex por archivo) quedan por primera vez en el JSON
  versionado. El `baseline.json` antiguo dentro de
  `.artifacts/agnostic-corpus/` usa SHA truncados a 12 hex y **no coincide con
  ningún archivo actual (0/17)**: está desfasado (es anterior a cambios en la
  recuperación) y no debe usarse como referencia.
- **Oscilaciones.** Ese documento ya señalaba que
  `wiki-Copa_Mundial_de_Fútbol.pdf` oscila entre 254.200 y 254.203 bytes en
  algunas pasadas. En este baseline las dos pasadas dieron el valor canónico
  254.200; la oscilación sigue siendo posible y, si aparece, el JSON la
  registraría en `variants` con `unstable: true`. Además, dos `convert()`
  seguidos **en el mismo proceso** no son estables (`arxiv-bert-en.pdf`:
  69.526 y 69.530 bytes); la estabilidad se da entre **procesos separados** con
  `PYTHONHASHSEED=0`, que es como se toma este baseline.
- **Tiempos.** El total de ese documento (123,5 s) frente a 127,9 s y 148,2 s
  aquí: varianza de carga de la máquina, no cambio de comportamiento. Las
  métricas de contenido son idénticas.

## Limitaciones

- Los segundos por archivo no son deterministas: no comparar tiempos entre
  ejecuciones sin repetir pasadas.
- La estabilidad verificada es entre procesos con `PYTHONHASHSEED=0`. Dentro de
  un mismo proceso, conversiones repetidas pueden divergir unos bytes.
- La métrica de tablas hereda las limitaciones documentadas en
  `pdf-conversion.md` (regiones que no son tablas, celdas repetidas contadas
  como ausentes, mide contenido conservado y no atribución fila/columna).
- El corpus agnóstico no está versionado: el baseline depende de que esos PDF
  no cambien. `evaluation/h3/agnostic_corpus_catalog.json` es la referencia de
  catálogo.
- La estrategia `layout` no se mide aquí porque `pymupdf-layout` no está
  instalado; si se instala, rehacer el baseline antes de comparar.

## Contrato del JSON versionado

`evaluation/h3/pdf-legacy-baseline.json` contiene: `generated_at` (pasada 1),
`python`, `pymupdf`, `pymupdf4llm`, `hash_seed`, `arnes` (ruta del script y
comando), `verification` (pasadas y archivos idénticos), `summary` (agregados)
y `files` con un registro por PDF: `file`, `bytes` (del PDF), `pages`, `sha256`
(64 hex del Markdown), `markdown_bytes`, `pages_text_loss`,
`pages_text_recovered`, `pages_tables_recovered`, `secs`, `variants` (lista de
`{sha256, markdown_bytes}` solo si las pasadas no coinciden) y `unstable`. No
contiene rutas absolutas de usuario ni datos de entorno.
