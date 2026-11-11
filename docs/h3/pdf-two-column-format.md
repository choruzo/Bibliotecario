# Énfasis tipográfico inyectado en las ecuaciones del PDF (T2d)

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
