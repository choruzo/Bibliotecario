# Pérdida real de contenido en la conversión PDF (prosa y ecuaciones)

El diagnóstico previo (`docs/h3/pdf-conversion.md`) decía que los arXiv a dos
columnas «pierden texto y ecuaciones». Esta tarea separa la pérdida **real** de
contenido de los **artefactos de medición** con una métrica pura y versionada
(`bibliotecario.pdf_audit`, `METRIC_VERSION = pdf-content-audit/1`) y un censo
de los 17 PDF del corpus agnóstico. Conclusión en una línea: **en los 17
archivos la pérdida real es cero** — ni una palabra de prosa ni una línea de
ecuación falta de verdad en el markdown final de `convert()`; todo lo que los
diagnósticos marcan como pérdida son artefactos de medición.

## Método

`scripts/h3/pdf_conversion_report.py` convierte cada PDF con el `convert()` de
producción, reconstruye el markdown final de cada página (chunk + recuperación,
mismo ensamblado que `recover_pdf_page`) y ejecuta el censo del nuevo módulo
`apps/api/bibliotecario/pdf_audit.py` (sin efectos, sin BD, sin red; el bloque
`content_audit` sale por defecto y `--audit-json` escribe el censo completo con
evidencia). La métrica está testeada en `apps/api/tests/test_pdf_audit.py` con
un caso sintético por categoría más el caso de control (texto correctamente
convertido no se marca).

Normalización compartida por ambas partes de cada comparación: NFKC (las
ligaduras `ﬁ` se expanden, igual que hace `pymupdf4llm` al escribir markdown),
unión de guiones de corte letra-letra (`pre-\ntrain` → `pretrain`), espacios
colapsados y `casefold`. Tokens de palabra `[^\W_]+` (mismo patrón que
`WORD` en `converters.py`) y tokenizador aparte para símbolos matemáticos
(`∑ √ ≤ ≥ ∈ ∂ − ± × ÷ · ′ …`); `WORD` es ciego a ellos.

Las líneas se auditan en dos formas: **crudas** (como las emite
`page.get_text("dict")` — ahí viven los fragmentos de guion) y **lógicas**
(líneas unidas cuando un guion corta una palabra — la línea del lector).
Categorías, en orden de prioridad para cada línea cuya secuencia de palabras no
aparece en el markdown:

| Categoría | Definición |
|---|---|
| `duplicate_layer` | línea presente en el markdown (≥ 1 ocurrencia) que el PDF repite en bloques distintos: `place()` deduplica y la cobertura cuenta multiset |
| `hyphen_fragment` | fragmentos de guion ausentes del multiset cuya palabra unida está en el markdown (`representa-` + `tion` → `representation`), tanto en el lado PDF como dentro del propio markdown |
| `reflow` | secuencia ausente pero ≥ 0,8 del multiset de palabras presente (mismas palabras, otros saltos de línea o sub/superíndices tokenizados distinto) |
| `figure_label` | línea dentro de una región de dibujo/imagen (`get_drawings()`/`get_image_info()`; celdas de tabla incluidas) o de ≤ 3 tokens sin puntuación de frase |
| `non_text_glyph` | línea con símbolos matemáticos y sin palabra de ≥ 2 caracteres |
| `real_equation` | línea con símbolos donde ≥ 50 % de sus tokens (palabra+símbolo) faltan en el markdown |
| `real_prose` | línea de ≥ 4 tokens con solape multiset < 0,8 |
| `real_short` | residual: 1-3 tokens con puntuación de frase ausentes de verdad |
| `coverage_residual` | excedente multiset de página que ninguna línea explica (celdas de tabla repetidas cuyo renderizado markdown conserva menos copias); no es por líneas, `lines` siempre 0 |

El veredicto por archivo informa pérdida real (palabras de prosa, líneas de
ecuación), el desglose de artefactos con evidencia de ejemplo, los glifos
matemáticos presentes en las páginas pero ausentes del markdown, y un
contraste con producción: cuántas líneas con secuencia ausente marca
`_line_missing` como pérdida.

## Censo por archivo (17 PDF, 412 páginas)

Prosa real = palabras ausentes en líneas `real_prose`/`real_short`;
ecuaciones reales = líneas `real_equation`/`non_text_glyph`. Artefactos en
palabras salvo indicación. `dup` = `duplicate_layer`, `guion` =
`hyphen_fragment`, `resid.` = `coverage_residual`.

| Archivo | Líneas | Prosa real | Ecuac. reales | dup (lín/pal) | guion (unión/pal) | reflow (lín/pal) | figure (lín) | resid. | Glifos faltantes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| arxiv-attention-is-all-you-need-en | 1048 | **0** | **0** | 357/162 | 8/12 | 26/18 | 0 | 43 | 0 |
| arxiv-bert-en | 2069 | **0** | **0** | 263/101 | 200/314 | 33/7 | 2 | 165 | 0 |
| boe-constitucion-1978 | 1931 | **0** | **0** | 25/0 | 0/0 | 1/0 | 0 | 1 | 0 |
| boe-ley-propiedad-horizontal | 1073 | **0** | **0** | 36/0 | 0/0 | 3/0 | 0 | 3 | 0 |
| wiki-Apis_mellifera | 506 | **0** | **0** | 11/0 | 0/0 | 14/0 | 0 | 17 | 0 |
| wiki-Café | 2928 | **0** | **0** | 83/10 | 1/2 | 17/10 | 3 | 11 | 0 |
| wiki-Copa_Mundial_de_Fútbol | 3719 | **0** | **0** | 878/160 | 1/1 | 3/2 | 32 | 70 | 0 |
| wiki-Diabetes_mellitus | 1863 | **0** | **0** | 57/1 | 1/2 | 8/3 | 1 | 14 | 0 |
| wiki-Dieta_mediterránea | 546 | **0** | **0** | 17/0 | 4/7 | 2/2 | 2 | 23 | 0 |
| wiki-Fotosíntesis | 1151 | **0** | **0** | 43/1 | 1/2 | 5/1 | 0 | 6 | 0 |
| wiki-Impuesto…_España | 1145 | **0** | **0** | 41/0 | 0/0 | 2/0 | 1 | 2 | 0 |
| wiki-Inflación | 685 | **0** | **0** | 2/0 | 0/0 | 6/6 | 0 | 11 | 0 |
| wiki-Python | 1392 | **0** | **0** | 122/18 | 0/0 | 11/11 | 6 | 51 | 0 |
| wiki-Revolución_francesa | 2498 | **0** | **0** | 99/5 | 1/1 | 21/4 | 7 | 76 | 0 |
| wiki-Sistema_solar | 1329 | **0** | **0** | 94/6 | 1/2 | 8/8 | 9 | 49 | 0 |
| wiki-Tabla_periódica… | 3704 | **0** | **0** | 777/9 | 1/2 | 24/22 | 2 | 42 | 0 |
| wiki-Volcán | 893 | **0** | **0** | 19/0 | 0/0 | 6/3 | 1 | 2 | 0 |
| **Total (17)** | 28480 | **0** | **0** | 2924/473 | 218/345 | 190/97 | 66 | 586 | **0** |

Totales de artefactos en palabras: 473 (capas duplicadas) + 345 (fragmentos de
guion) + 97 (reflujo) + 586 (excedente multiset) ≈ 1 501 — el mismo orden que
las «1 496 palabras de tabla perdidas» y las 26 páginas con `pdf_text_loss` del
arnés: toda esa cifra se explica como artefactos.

## Los dos arXiv, en números

- **`_line_missing` marca 0** de las líneas con secuencia de palabras ausente
  del markdown final: 47 candidatas en `arxiv-attention-is-all-you-need-en.pdf`
  y 448 en `arxiv-bert-en.pdf`, 0 marcadas en ambos (contraste calculado por el
  arnés sobre las mismas líneas del censo, con el `stream` y el multiset de
  `converters._words`). En bert las 448 se explican: 200 uniones de fragmentos
  de guion (314 palabras fragmento), 33 reflujo y 263 líneas duplicadas; en
  atención, 8 uniones de guion, 26 reflujo y 357 duplicadas.
- **Los pies de figura ya están**: `Figure 1:` … `Figure 5:` aparece en el
  markdown de los dos archivos (verificado por subcadena sobre el markdown
  final). El contenido de los pies está en el markdown; lo que difiere a veces
  es el salto de línea (el pie crudo del PDF es una línea larga que el markdown
  corta distinto), no el contenido.
- Las ecuaciones: 46 líneas con operadores en atención y 18 en bert llevan
  ≥ 1 glifo matemático; todas llegan al markdown con sus glifos
  (`missing_symbols = 0`: el multiset de símbolos de cada página está cubierto).
  Las 6 «ecuaciones perdidas» del diagnóstico previo son líneas cuya secuencia
  se rompe por sub/superíndices (`(x1, ..., xn)` → `( x 1, ..., x n )` en el
  markdown, marcadores `_x_1`): reflujo, no pérdida.
- Las páginas 14-15 de atención (cobertura 0,489): 112 líneas crudas cada una,
  92 dentro de `duplicate_layer` (las palabras de la «tabla» renderizada como
  bloques de una palabra, repetidas 4-8 veces: `place()` deduplica y la
  cobertura multiset las cuenta como perdidas), ~64 palabras de excedente y
  **0 palabras reales ausentes**.

Evidencia típica (censo completo con muestras por categoría en
`.orca-task/t1-audit1.json`): `transduc+tion=transcription` y
`representa+tion=representation` (guion); `(x1, ..., xn) to a sequence`
(reflujo por subíndices); `google brain` ×3 en el PDF con 4 copias en el
markdown (duplicadas); la leyenda de foto de Copa p2 dentro de la región de
imagen (`figure_label`, definición de la spec).

## No regresión de `convert()`

Comando y comparación contra el baseline de T0
(`evaluation/h3/pdf-legacy-baseline.json`, rama `choruzo/pdf-env-baseline-9f52de`,
solo lectura): dos pasadas completas del arnés en procesos separados con
`PYTHONHASHSEED=0` dan **SHA-256 idénticos entre sí en 17/17** y **15/17
iguales al baseline de T0**:

- `wiki-Copa_Mundial_de_Fútbol.pdf`: 254 203 bytes frente al canónico
  254 200 — la oscilación documentada desde `pdf-conv-baseline`; ejecutado solo
  reproduce el SHA canónico `14342a0f…f82c77`.
- `arxiv-bert-en.pdf`: 69 809 bytes frente a 69 813 — la inestabilidad
  documentada de este archivo (T0 ya registró variantes intra-proceso
  69 526/69 530). En esta medición se observaron 69 809, 69 813 y 69 815
  según el estado global de PyMuPDF arrastrado por los archivos previos del
  mismo proceso; conversión aislada (y también tras el prefijo del corpus)
  reproduce el SHA canónico de T0 `3740d86f…`. La variación es de proceso, no
  de código: `converters.py` no se ha tocado.

El resto de métricas del arnés coincide con el baseline de T0: 26 páginas con
`pdf_text_loss`, 101/29/19 tablas, 1 496 palabras de tabla perdidas.

## Coste del arnés

Misma sesión, 17 archivos, `--layout legacy` (wall-clock incluye el arranque):

| Pasada | Wall | `convert()` | Auditoría |
|---|---:|---:|---:|
| Sin auditoría (`--no-audit`) | 220,2 s | 133,4 s | 0 s |
| Con auditoría (defecto) | 239,9 s | 139,2 s | 16,0 s |

La auditoría añade **16,0 s = 12,0 %** del tiempo de `convert()` (por debajo
del umbral del 20 %), por eso el bloque `content_audit` sale por defecto;
`--no-audit` lo apaga y `--audit-json` escribe el censo completo. Dos pasadas
con auditoría en procesos separados produjeron censos **idénticos 17/17**
(determinista; solo varía `generated_at` y `audit_secs`).

## Recomendación para T2

**No hay pérdida real que recuperar: ninguna de las dos opciones recupera
contenido.** La decisión debe tomarse por calidad de orden de lectura y coste
de corpus, no por recuperación:

- **T2a (orden de columnas)**: arreglaría el orden de lectura en los dos arXiv
  a dos columnas. Beneficio medible: 59 líneas de reflujo (26+33) y sus
  secuencias rotas por intercalado — pero solo **97 palabras** en todo el
  corpus quedan «mal ordenadas» y **0 ausentes**. El markdown cambiaría en
  los dos arXiv (y en cualquier archivo que el reordenador toque), lo que
  fuerza reindexado de los documentos afectados: coste de corpus = reindexar
  los 2 arXiv (~113 KB de markdown) si el cambio queda acotado a detección de
  dos columnas, o los 17 (~1,98 MB) si toca el pipeline común. Riesgo: el
  reordenador puede mover texto correctamente ordenado; el censo sirve de
  verificación (prosa real debe seguir en 0).
- **T2b (fidelidad de glifos)**: sin objetivo medible — los glifos que llegan
  a la capa de texto ya llegan al markdown (`missing_symbols = 0` en los 17).
  Los símbolos de las ecuaciones «perdidas» del diagnóstico (∑ ≤ ≥ ∂) ni
  siquiera aparecen en el texto extraíble: son dibujos de fuentes sin mapeo
  Unicode, y recuperarlos exigiría OCR o tablas de fuentes, fuera del alcance
  de `convert()`. Coste de corpus de tocar la tokenización compartida: el
  propio contexto de la tarea midió que endurecer la regla añadiría 698
  elementos en los 17 archivos.

**Recomendación**: descartar T2b (objetivo vacío) y no abordar T2a por
recuperación — si se quiere mejorar el orden de lectura, hacerla como tarea
propia acotada a los dos arXiv con reindexado de esos 2 documentos y el censo
de esta métrica como gate de no-regresión (prosa real = 0, ecuaciones reales =
0 antes y después).

## Reproducción

```powershell
$env:PYTHONHASHSEED = "0"
.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py `
  --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus `
  --layout legacy --json .orca-task/t1-run1.json `
  --audit-json .orca-task/t1-audit1.json
# segunda pasada en otro proceso para comparar determinismo
```
