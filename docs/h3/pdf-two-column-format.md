# Énfasis tipográfico inyectado en las ecuaciones del PDF (T2d, extendido en T2e; port T2c)

## Objetivo

El conversor legacy (`pymupdf4llm.to_markdown`) aplica el énfasis markdown que
sugieren los flags de fuente: las fuentes matemáticas de Computer Modern
(CMMI/CMSY/CMEX/CMR, MSAM/MSBM, STIX) llegan como spans de cursiva/negrita/tachado,
así que las líneas de ecuaciones salen envueltas en `_..._`, `**...**` y `~~...~~`:

```
antes:  Attention( _Q, K, V_ ) = softmax( _[QK]_ ~~_V_~~ _[T]_
antes:  _lrate_ = _d_ _[-]_ model [0] _[.]_ [5]
```

Las marcas envuelven glifos (no añaden contenido) pero rompen las ecuaciones para
el chunking, la recuperación y la auditoría. T2d las elimina **solo** en las líneas
claramente matemáticas, preservando cada carácter alfanumérico.

## Diseño (`apps/api/bibliotecario/pdf_math_clean.py`)

- **Predicado de línea matemática**: la línea lleva el operador `=` rodeado de
  espacios (`N = 6`), o un glifo del conjunto curado (∑ √ ≤ ≥ ∈ ∂ ∫ × · − ±,
  flechas, símbolos letterlike, ⟨⟩ ⌈⌉⌊⌋), **fuera de los destinos de enlaces**
  (`](https://...)`, porque el `=` de una query no es matemática). Las líneas
  estructurales nunca califican: tablas (`|…|`), headings (`#`), bullets (`-`/`1.`),
  código cercado/indentado. Los operadores ASCII `-` y `/` se excluyen a propósito:
  en prosa son compuestos (`self-attention`) y fechas o URLs.
- **Fragmento matemático**: un par de marcadores se quita solo si su contenido es
  un fragmento matemático: glifos, corchetes, dígitos, símbolos cortos separados
  por comas (`Q, K, V`), identificadores (`lrate`, `Pdrop`, `softmax`, `QWi`).
  Se conservan: los enlaces, los títulos de prosa de varias palabras
  (`_York Times_`), las siglas (`**BERTBASE**`), las etiquetas en negrita
  (`**Encoder:**`), los nombres de autores (`**Ashish Vaswani**`) y los
  tachados de referencia tipo wiki (`~~4~~`, `~~.~~`).
- **Invariante por página**: la secuencia de tokens alfanuméricos
  (`[^\W_]+`) del chunk limpio debe ser idéntica a la original; si alguna
  sustitución fusionara o moviera tokens, la página se revierte entera y se
  emite `pdf_math_clean_reverted_page_N`. En los 17 PDF el contador de
  reversiones es 0.
- **Cableado**: `converters.convert()` limpia el `chunk["text"]` de cada página
  justo después de `pdf_markdown_chunks()` y antes de `recover_pdf_page()`; la
  recuperación compara palabras, así que sus decisiones no cambian. Diagnóstico
  `pdf_math_emphasis_page_N` cuando la página cambió.

## Antes / después (arXiv, conversión real)

```
antes:  states _ht_, as a function of the previous hidden state _ht−_ 1 and the input for position _t_ .
después: states ht, as a function of the previous hidden state ht− 1 and the input for position t .

antes:  of continuous representations **z** = ( _z_ 1 _, ..., zn_ ). Given **z**, the decoder then generates
después: of continuous representations z = ( z 1 , ..., zn ). Given z, the decoder then generates

antes:  _PE_ ( _pos,_ 2 _i_ ) = _sin_ ( _pos/_ 10000 [2] _[i/d]_ [model] )
después: PE ( pos, 2 i ) = sin ( pos/ 10000 [2] [i/d] [model] )

antes:  Transformer (base model) 27.3 38.1 **3** _**.**_ **3** _**·**_ **10** **[18]**
después: Transformer (base model) 27.3 38.1 3 . 3 · 10 [18]

antes:  We used the Adam optimizer [20] with _β_ 1 = 0 _._ 9, _β_ 2 = 0 _._ 98 and _ϵ_ = 10 _[−]_ _[9]_ _[.]_ .
después: We used the Adam optimizer [20] with β 1 = 0 . 9, β 2 = 0 . 98 and ϵ = 10 [−] [9] .
```

## Recuentos (script `.orca-task/tokens_invariant.py` sobre la conversión real)

| archivo | líneas matemáticas con marcas | marcas en líneas matemáticas |
|---|---|---|
| arxiv-attention | 59 → 11 | 496 → 44 |
| arxiv-bert | 20 → 0 | 104 → 0 |

En todo el corpus quedan 15 líneas matemáticas con marcas (ver limitaciones).

## Invariante de tokens

`tokens(markdown)` = `re.findall(r"[^\W_]+", markdown)`:

- por página, dentro de `clean_math_emphasis` (con reversión entera si falla);
- a nivel de documento, `dry_run.py` verificó los 17 markdown ANTES/DESPUÉS
  (`pmc.tokens(antes) == pmc.tokens(despues)`), y `tokens_invariant.py`
  repitió la comprobación con la conversión real de los 2 arXiv:
  attention 6 668 tokens, bert 11 125 tokens, idénticos.

## SHAs del markdown (conversión real, 17/17)

| archivo | bytes antes → después | SHA-256 |
|---|---|---|
| arxiv-attention-is-all-you-need-en.pdf | 42 870 → 42 420 | baseline `19295e10…a03cb` → tras el cambio `dcff3ea5…c9d8a441` |
| arxiv-bert-en.pdf | 69 813 → 69 705 | baseline `3740d86f…5c8d` → tras el cambio `8717a1fe…f0e61` |
| otros 15 PDF | idénticos | SHA-256 idéntico al baseline `evaluation/h3/pdf-legacy-baseline.json` (Copa incluida, `14342a0f…2c77`) |

La bimodalidad registrada de bert (69 809/69 813 antes del cambio) persiste entre
procesos con la misma magnitud (69 705/69 709 tras el cambio): dentro de un mismo
proceso las tres pasadas son byte-idénticas; la diferencia de 4 bytes entre
procesos es el artefacto preexistente ya registrado en la tarea, no un efecto de
la limpieza (que es determinista sobre su entrada).

Los únicos archivos cuyo SHA cambia son los 2 arXiv objetivo.

## Auditoría de pérdida real (`pdf_audit`, `--audit-json`)

Para los 2 arXiv (pasada 1 del arnés tras el cambio):

| archivo | real_prose words | real_equation lines | missing_symbols | duplicate_layer |
|---|---|---|---|---|
| arxiv-attention | 0 | 0 | 0 | 357 líneas (estado T1, sin delta) |
| arxiv-bert | 0 | 0 | 0 | 263 líneas (estado T1, sin delta) |

`duplicate_layer` mide repeticiones entre bloques (cabeceras/Zotero por página):
sus valores 357/263 son exactamente los ya documentados en
`docs/h3/pdf-two-column-loss.md`, no pérdida real y sin delta de esta tarea.
Corpus completo: `real_prose_words = 0`, `real_equation_lines = 0` (17/17).

## Tiempo del arnés

| pasada | baseline (s) | T2d (s) | delta |
|---|---|---|---|
| 1 | 127.872 | 145.708 | +13.9 % |
| 2 | 148.181 | 122.231 | −17.5 % |
| total | 276.053 | 267.939 | **−2.9 %** |

El tiempo total del arnés baja un 2.9 % (dentro del objetivo <= +10 %); la
dispersión entre pasadas del baseline (±16 %) es mayor que el coste de la
limpieza, que es unas pasadas de regex por línea matemática.

## Limitaciones medidas (fuera del alcance de T2d)

1. **Restos en arxiv-attention (11 líneas)**: nombres de autores y etiquetas de
   prosa en negrita dentro de líneas con glifo (`**Ashish Vaswani** _[∗]_`,
   `**Encoder:** … _N_ = 6`, `**Label Smoothing** …`). El contenido de esos
   pares es prosa legítima, así que se conservan sus marcas (muestra y motivo).
   Además queda 1 marcador suelto sin par (`warmup _ steps = 4000`, el span
   vacío entre `_warmup_` y `_steps_`): quitar un `_` suelto podría fusionar
   identificadores como `d_model`, así que se conserva.
2. **Palabras pegadas de columna**: el pegado del sanitizador de spans del
   conversor (`dimension` + `query` → `dimensionquery`) queda igual; la
   limpieza no lo toca. Ocurre al menos en la línea del scaled dot-product de
   attention (recuento medido en T1/T2 anteriores; corregirlo requeriría
   reconstruir la línea desde los spans de la página y quedó fuera del alcance).
3. **Guionización y compuestos**: `lefttoright`, `selfattention`,
   `pretrain`, etc. siguen exactamente igual que en el baseline: la tarea
   T2d excluye explícitamente los compuestos; no se arreglan ni se meten en
   el invariante.
4. **Esta tarea no toca** `coverage()`, `PDF_MIN_COVERAGE`, `scan_tables`,
   `_line_missing`, `_missing_runs`, `place()` ni la métrica de `pdf_audit.py`.

## Tests

`apps/api/tests/test_pdf_math_clean.py` (11 tests): ecuación de attention, línea
`lrate`, prosa con `=` y énfasis legítimo, referencias wiki tachadas, etiqueta
Python bold con `:=`, autores, tabla/head/bullet/indentado/código cercado,
`d_model` preservado, marcadores flanqueados por alfanuméricos, reversión del
invariante y un caso de integración con PDF sintético (ecuación en Times-Italic
limpia sus `_`, la prosa sin operadores conserva los suyos).

---

## Bloques matemáticos y líneas de continuación (T2e)

T2d limpiaba línea a línea: solo se limpiaban las líneas que llevan `=` o un glifo
matemático propio, así que las líneas de continuación de una fórmula desplegada en
dos columnas se quedaban con sus marcas. En `Attention Is All You Need`:

```
antes:   Attention( Q, K, V ) = softmax( [QK] √ [T]
         (en blanco)
         _dk_
         (en blanco x3)
         ) _V_ (1)
```

`_dk_` y `) _V_ (1)` no llevan `=` ni glifo: caían en líneas sueltas y permanecían,
y la evaluación de cobertura no podía sostener la respuesta de la fórmula.

### Diseño T2e (`pdf_math_clean.py`)

- **Bloque matemático**: una línea matemática *fuerte* — con `=` o con un glifo
  matemático distinto del punto medio — abre un bloque. Las líneas que siguen,
  **también a través de las líneas en blanco** que pymupdf4llm deja entre los
  fragmentos de una fórmula desplegada en dos columnas, son líneas de continuación
  y se limpian cuando son fragmentos matemáticos puros.
- **Línea de continuación**: se limpia solo si TODO par de marcadores de la línea
  es un fragmento matemático y todo el texto fuera de los pares es cáscara
  matemática (dígitos, corchetes/llaves/paréntesis, operadores planos, glifos,
  espacios) sin puntuación de frase y sin palabras de prosa. Cualquier otra línea
  no vacía — prosa de continuación, tabla, heading, bullet, código, una línea con
  enlace — cierra el bloque y conserva su énfasis. Las líneas en blanco nunca
  cierran un bloque: son los huecos verticales de la fórmula.
- **Apertura fuerte (defensa contra la wiki)**: el punto medio cuenta como glifo
  matemático para el predicado de línea (`pos/ 10000 · 2 π`), pero la wiki usa
  `·` a inicio de línea como bullet (`·El helio pertenece al bloque`); esa línea
  limpia sus propias marcas (comportamiento T2d intacto) pero NO abre bloque —
  de lo contrario la `**s**` (la letra del bloque s) que le sigue se limpiaría
  como si fuera un fragmento de fórmula. Detectado y corregido midiendo el corpus:
  el diff pre/post en un mismo proceso mostró ese único falso positivo en
  `wiki-Tabla_periódica_de_los_elementos.pdf`.
- **Invariante T2d intacto**: mismo token-stream por página, con reversión entera
  si falla. Reversiones en los 17 PDF: 0.

### Antes / después (attention, conversión real)

```
antes:    Attention( Q, K, V ) = softmax( [QK] √ [T]
          (en blanco)
          _dk_
          (en blanco x3)
          ) _V_ (1)

después:  Attention( Q, K, V ) = softmax( [QK] √ [T]
          (en blanco)
          dk
          (en blanco x3)
          ) V (1)
```

Concatenada, la fórmula queda sin `_` en ninguna de sus líneas:
`Attention( Q, K, V ) = softmax( [QK] √ [T] dk ) V (1)`.

Fragmentos multi-línea de la fórmula multi-head (sección 3.2.2):

```
antes:    where headi = Attention( QWi [Q]
          (en blanco)
          _[ K]_ _i_ _[, V W][ V]_ _i_
          _[ V]_ _i_ [)]
          _i_ _[Q][, KW][ K]_ _i_

después:  where headi = Attention( QWi [Q]
          (en blanco)
          [ K] i [, V W][ V] i
          [ V] i [)]
          i [Q][, KW][ K] i
```

Los denominadores de las fracciones en prosa (`…scaling factor of √ 1 / _dk_…`,
`…we scale the dot products by √ 1 / _dk_…`) también se limpian a `dk`.

La prosa de continuación **no se toca**: `_dk_, the dot products grow large in
magnitude…` y `Where the projections are parameter matrices _W_ _[Q]_` conservan
sus marcas, igual que las 11 líneas de autores/etiquetas que T2d documentó.

### Recuentos y SHAs tras T2e

La delta de attention son exactamente 7 líneas (2 de la fórmula scaled
dot-product, 3 de la multi-head, 2 denominadores); diff pre/post en un mismo
proceso (`.orca-task/diff_all.py`): los otros 16 PDF byte-idénticos entre el
comportamiento pre y el post.

| archivo | bytes | SHA-256 | vs estado T2d |
|---|---|---|---|
| arxiv-attention | 42 420 → 42 394 | `dcff3ea5…c9d8a441` → `6af33cfe…3bd9c00` | cambia (objetivo T2e) |
| arxiv-bert | 69 709 | `61066a97…` (variante ya documentada de su bimodalidad) | sin cambio de código |
| otros 15 | idénticos | idénticos al baseline T0 (`evaluation/h3/pdf-legacy-baseline.json`) | sin cambio |

Notas:

- Copa Mundial: una pasada sin semilla fija mostró `8dbce921…`; es la bimodalidad
  preexistente entre procesos (documentada desde T2d). Con la semilla del arnés
  (`PYTHONHASHSEED=0`) ambas pasadas dan el SHA del baseline `14342a0f…2c77`.
- Auditoría tras el cambio (2 pasadas del arnés con `--audit-json`):
  `real_prose_words = 0`, `real_equation_lines = 0`, `missing_symbol_occurrences
  = 0` en los 17 PDF; reversiones del invariante: 0.
- Tiempo del arnés: 119.427 s (pasada 1) y 112.552 s (pasada 2) contra el baseline
  127.872 s / 148.181 s: **−16 %** en total, muy por debajo del tope de +10 %.

### Tests añadidos en T2e (6 nuevos, 17 en total)

Fórmula multilínea con huecos en blanco (3 líneas cambiadas), prosa de
continuación tras una ecuación (intacta), tabla tras una ecuación (cierra el
bloque; la `**26.4**` posterior no se toca), heading tras una ecuación (cierra el
bloque), líneas en blanco que tienden el bloque pero la prosa lo cierra, y los
fragmentos multi-head con la línea de prosa conservando `_W_ _[Q]_`. Todos con
aserto del token-stream.

---

## Reconstrucción por spans y palabras pegadas (port T2c)

El port manual de la implementación T2c (commits `ed1dd7f`/`8e91625`, ref
`t2c-safety/8e91625`, prohibido fusionar por la deriva del kit) convierte
`pdf_math_clean.py` en **un único pipeline de tres etapas con un invariante**:
conserva las reglas integradas (énfasis marker-only T2d/T2e) y añade lo que
midió T2c: reconstruir las líneas matemáticas desde los spans de
`page.get_text("dict")` y despegar las palabras que el conversor pega
(junction de spans entre líneas dict distintas y guion de compuesto destruido
por `replace("-\n", "")`).

### Mecanismos reales del defecto (verificados con spans)

1. **Énfasis sobre fuentes matemáticas** (CMMI/CMSY/CMEX/CMR/MSAM/STIX llevan
   flags de cursiva/negrita/tachado): `Attention( _Q, K, V_ ) = softmax( _[QK]_ ~~_V_~~ _[T]_`.
2. **Junction de spans**: el sanitizador de `pymupdf4llm` concatena spans
   solapados en X de líneas dict distintas (un `√` alto actúa de puente entre
   dos líneas visuales): `dimensionquery`, `thelues`.
3. **`replace("-\n", "")` global**: destruye el guion de compuestos
   (`self-` + `attention` → `selfattention`; `left-to-` + `right` →
   `left-toright`) aunque es correcto para cortes de sílaba
   (`representa-`/`tion`).

### Diseño (`pdf_math_clean.py`, un módulo, un cableado)

- **Puerta por documento** (`page_may_have_math`, `get_fonts`): familias
  CMMI/CMSY/CMEX/CMR/MSAM/MSBM/STIX/EUFM. Sin fuentes matemáticas las etapas
  que necesitan la página no corren y el markdown queda byte-idéntico (los
  otros 15 PDF: SHA idéntico). La pasada marker-only corre siempre, como
  antes del port.
- **1. Rebuild por spans** (`clean_math_lines`, corre primero y sobre el
  markdown tal como lo produjo el conversor): extrae los spans con los flags
  del conversor (`TEXT_MEDIABOX_CLIP | TEXT_COLLECT_STYLES`), reagrupa por
  proximidad vertical y re-renderiza cada candidato (el grupo completo o el
  tramo de columna antes/después del canal) primero como el conversor (glue
  retenido) y luego con el glue partido y las marcas fuera de los spans
  matemáticos. La línea se sustituye solo si su clave normalizada (sin
  marcas, minúsculas) coincide con **un único** candidato no ambiguo; las
  líneas de tabla/heading/bullet/enlace nunca se tocan. El orden de lectura
  de los spans no se reordena.
- **2. Pasada marker-only** (`clean_math_emphasis`, reglas T2d/T2e intactas):
  limpia el énfasis de las líneas matemáticas y de los bloques de
  continuación para toda línea que el rebuild no pudo reproducir.
- **3. Compuestos** (`compound_fixes`): restaura el guion solo con evidencia —
  la forma con guion ya usada en el documento (`document_compound_vocabulary`)
  o un fragmento que continúa una cadena (`left-to-` + `right`); nunca
  `201-`/`8` (año envuelto) ni una sílaba sin evidencia. La sustitución es
  word-bounded.
- **Invariante único por página**: `tokens_preserved` (misma secuencia de
  tokens, salvo marcas eliminadas y despegues 1→2; fusiones, borrados,
  movimientos e inserciones fallan) con reversión entera y diagnóstico
  `pdf_math_clean_reverted_page_N`.
- **Diagnósticos** (todos con prefijo `pdf_math_`): `pdf_math_emphasis_page_N`,
  `pdf_math_glue_space_page_N` (despegue por junction),
  `pdf_math_compound_hyphen_page_N` (guion restaurado),
  `pdf_math_clean_reverted_page_N`.
- **Cableado único** en `converters.convert()`: tras `pdf_markdown_chunks()`
  y antes de `recover_pdf_page()`; la recuperación compara palabras, así que
  sus decisiones no cambian.

### Antes / después (conversión real, muestras)

```
ANTES:   Attention( _Q, K, V_ ) = softmax( _[QK]_ ~~_V_~~ _[T]_
DESPUÉS: Attention( Q, K, V ) = softmax( [QK] √ [T]

ANTES:   queries and keys of dimensionquery with all keys, … the weights on thelues of dimension dv .
DESPUÉS: queries and keys of dimension query with all keys, … the weights on the lues of dimension dv .

ANTES:   less time to train. Our model achieves 28.4 BLEU on the WMT 2014 Englishto-German translation task
DESPUÉS: less time to train. Our model achieves 28.4 BLEU on the WMT 2014 English-to-German translation task

ANTES:   …the second is a simple, positionwise fully connected feed-forward network.
DESPUÉS: …the second is a simple, position-wise fully connected feed-forward network.

ANTES:   Fine-tuning is straightforward since the selfattention mechanism in the Transformer allows BERT…
DESPUÉS: Fine-tuning is straightforward since the self-attention mechanism in the Transformer allows BERT…

ANTES:   we simply plug in the taskspecific inputs and outputs into BERT and finetune all the parameters
DESPUÉS: we simply plug in the task-specific inputs and outputs into BERT and fine-tune all the parameters

ANTES:   in OpenAI GPT, the authors use a left-toright architecture
DESPUÉS: in OpenAI GPT, the authors use a left-to-right architecture
```

La prosa de la misma línea conserva sus marcas (`**Ashish Vaswani** [∗]`) y
los corchetes de superíndice `[T]` son texto: se mantienen.

### Recuentos (detector `scripts/h3/pdf_math_census.py`)

Tres etapas censadas por archivo: `raw` (conversor + recuperación, sin
limpieza — el estado T0), `text` (solo pasada marker-only — el estado de
`main` antes del port) y `full` (pipeline completo). Comando:

```
.venv/Scripts/python.exe scripts/h3/pdf_math_census.py \
  --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus \
  --files arxiv-attention-is-all-you-need-en.pdf,arxiv-bert-en.pdf \
  --json .orca-task/pdf-math-census.json
```

| defecto | attention ANTES → DESPUÉS | bert ANTES → DESPUÉS |
|---|---|---|
| líneas matemáticas con énfasis matemático | 59 → **0** | 20 → **0** |
| pares de énfasis matemático | 209 → **0** | 52 → **0** |
| palabras pegadas (junction de spans) | 2 (`dimensionquery`, `thelues`) → **0** | 0 → 0 |
| palabras pegadas (guion de compuesto) | 2 (`Englishto`, `positionwise`) → **0** | 38 ocurrencias / 17 formas (`selfattention`, `finetune`, `taskspecific`, `leftto`, `pretrain`…) → **0** |

En la etapa `text` el énfasis ya es 0 (lo limpió T2d/T2e) pero el pegado
permanece: es exactamente la parte que aporta el port. El censo original de
T2c contó 84/12 líneas matemáticas y 36 palabras pegadas con su propio detector
por spans sobre el mismo corpus; el estado DESPUÉS es 0 en ambas mediciones.

### Invariante de tokens

- Por página, dentro del pipeline, con reversión entera: **0 reversiones** en
  los 17 PDF × 2 pasadas del arnés.
- Markdown final verificado externamente (`.orca-task/verify_tokens.py`):
  attention 6 668 → 6 673 palabras (+5 despegues 1→2), bert 11 125 → 11 153
  (+38 despegues y 8 copias redundantes de recuperación dedup, el
  comportamiento preexistente de `recover_pdf_page` en p1/p2/p3/p13). Ningún
  token del ANTES queda sin correspondencia salvo las formas pegadas
  restauradas (`dimensionquery`, `selfattention`, `leftto`…): no se pierde ni
  duplica palabra; las diferencias de tipos NFKC son exactamente las formas
  pegadas que se despegan.

### SHAs del markdown (arnés, 2 pasadas, `PYTHONHASHSEED=0`)

| archivo | baseline T0 | pasada 1 == pasada 2 | veredicto |
|---|---|---|---|
| arxiv-attention-is-all-you-need-en.pdf | `19295e10…a03cb` (42 870 B) | `92c741592ba720a3d58bd9b8fb086628e2ff38aeb43297c176920b9ebc6e990b` (42 280 B) | **CAMBIA (objetivo)** |
| arxiv-bert-en.pdf | `3740d86f…5c8d` (69 813 B) | `e8b9fc5b1602964f14dcfafe79ee191ee78e3f1df37dc52a9cadf05c81fdb99d` (69 600 B) | **CAMBIA (objetivo)** |
| boe-constitucion-1978.pdf | `bfea8bb9…fd1` | igual | idéntico |
| boe-ley-propiedad-horizontal.pdf | `c1a3ba97…d8e` | igual | idéntico |
| wiki-Apis_mellifera.pdf | `de476865…8a6` | igual | idéntico |
| wiki-Café.pdf | `0124aa26…e8c` | igual | idéntico |
| wiki-Copa_Mundial_de_Fútbol.pdf | `14342a0f…2c77` (254 200 B) | igual | idéntico |
| wiki-Diabetes_mellitus.pdf | `37762fbe…0ca` | igual | idéntico |
| wiki-Dieta_mediterránea.pdf | `b6962aab…07e` | igual | idéntico |
| wiki-Fotosíntesis.pdf | `4f22e854…d25` | igual | idéntico |
| wiki-Impuesto_sobre_la_renta…pdf | `2e0164c4…668` | igual | idéntico |
| wiki-Inflación.pdf | `ebf99de8…ea7` | igual | idéntico |
| wiki-Python.pdf | `002b71de…d47` | igual | idéntico |
| wiki-Revolución_francesa.pdf | `2ffd12df…3ba` | igual | idéntico |
| wiki-Sistema_solar.pdf | `66986542…a36` | igual | idéntico |
| wiki-Tabla_periódica_de_los_elementos.pdf | `87acf721…e50` | igual | idéntico |
| wiki-Volcán.pdf | `596fb533…d7` | igual | idéntico |

Los únicos archivos cuyo SHA cambia son los 2 arXiv objetivo. La oscilación
preexistente entre procesos (Copa 254200/254203, bert ±4 B) sigue documentada;
con la semilla del arnés las dos pasadas produjeron los valores de la tabla.

### Auditoría de pérdida real (`pdf_audit`, `--audit-json`, 2 pasadas)

| archivo | real_prose | real_equation | missing_symbols | duplicate_layer |
|---|---|---|---|---|
| arxiv-attention | 0 | 0 | 0 | 357 líneas (estado T1, sin delta) |
| arxiv-bert | 0 | 0 | 0 | 263 líneas (estado T1, sin delta) |

Corpus completo: `real_prose_words = 0`, `real_equation_lines = 0`.
`pages_text_loss` baja de 26 (baseline) a 25: bert p6 mejora al restaurar los
compuestos. `tables_rebuilt = 29`, `pages_text_recovered = 95`,
`table_words_lost = 1496`: iguales al baseline.

### Tiempo del arnés

| pasada | baseline (s) | port T2c (s) | delta |
|---|---|---|---|
| 1 | 127.872 | 107.314 (94.779 conv + 12.535 audit) | −16.1 % |
| 2 | 148.181 | 109.683 (97.102 conv + 12.581 audit) | −26.0 % |
| total | 276.053 | 216.997 | **−21.4 %** |

Sin regresión (tope +10 %); el coste del rebuild por spans es de ~1 s por
archivo arXiv y la varianza del baseline lo supera.

### Limitaciones conocidas

1. **Puerta conservadora por fuentes**: un PDF con fuentes matemáticas
   renombradas (subset con nombre irreconocible) no activa las etapas que
   necesitan la página (rebuild y compuestos); la pasada marker-only sigue
   corriendo. Es un fallo conservador: no limpia en lugar de limpiar mal.
2. **Orden de lectura**: el artefacto preexistente de los glifos altos (`√`
   de puente entre dos líneas; en p5 de attention el `oftmax` de
   `pre-softmax` continúa en el borde de columna y la línea dice
   `the pre-s linear transformation` en ambos estados) permanece: los
   despegues siguen la evidencia de los spans y no reordenan nada.
3. El énfasis de prosa (autores, etiquetas) y el resto de limitaciones de
   T2d/T2e se conservan sin cambio.

### Paso T3 pendiente (fuera de esta tarea)

Republicar los 2 documentos arXiv (su SHA cambia) y recalibrar la ventana de
corpus (`agnostic-calibration-v1.jsonl`, `agnostic-validation-v1.jsonl` y
`agnostic_corpus_catalog.json`). Los otros 15 no requieren republicación.

### Tests añadidos (31 en total)

A los 17 de T2d/T2e se incorporan los 14 del original T2c: spans sintéticos
con énfasis matemático y negrita de prosa conservada, superíndice/tachado,
página de prosa intacta, cursiva de prosa con operandos intacta, junction de
spans cruzando líneas (espacio insertado), compuesto con evidencia de
documento y por cadena, `201-`/`8` sin restaurar, sílaba sin evidencia,
`tokens_preserved` (splits OK; merge/reorden/borrado/inserción NO),
`page_may_have_math`, reversión ante limpieza rota, PDF sintético de dos
columnas con ecuación en cursiva y el gate de fuentes de `convert()`.
