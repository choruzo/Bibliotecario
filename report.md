# T2d — Informe: quitar el énfasis de las ecuaciones (solo énfasis)

Task: `task_b2d8d2039f80` · run `run_43fca8504d61` · worktree `pdf-math-emphasis-b2d8d2`

## Resultado

**SUCCESS.** Las marcas de énfasis (`_`, `**`, `~~`) que `pymupdf4llm` inyecta en las
líneas matemáticas de `arxiv-attention-is-all-you-need-en.pdf` y `arxiv-bert-en.pdf`
se eliminan ahora durante la conversión, sin cambiar ningún token alfanumérico y sin
mover el markdown de los otros 15 PDF.

## Archivos tocados

| archivo | cambio |
|---|---|
| `apps/api/bibliotecario/pdf_math_clean.py` | **nuevo**: limpieza de énfasis solo en líneas matemáticas (predicado + fragmentos + invariante) |
| `apps/api/bibliotecario/converters.py` | rama PDF de `convert()`: limpia cada chunk tras `pdf_markdown_chunks()` y antes de `recover_pdf_page()`; diagnósticos `pdf_math_emphasis_page_N` / `pdf_math_clean_reverted_page_N` |
| `apps/api/tests/test_pdf_math_clean.py` | **nuevo**: 10 unitarios + integración con PDF sintético |
| `docs/h3/pdf-two-column-format.md` | **nuevo**: muestras antes/después, recuentos, SHAs, limitaciones |

`coverage()`, `PDF_MIN_COVERAGE`, `scan_tables`, `_line_missing`, `_missing_runs`,
`place()` y `pdf_audit.py` intactos; `apps/web` intacto; sin instalaciones nuevas.

## Diseño (resumen)

1. **Predicado de línea matemática** (por línea del chunk): `=` rodeada de espacios
   o glifo matemático curado (∑ √ ≤ ≥ ∈ ∂ ∫ × · − ± flechas letterlike ⟨⟩ ⌈⌉⌊⌋),
   **fuera de destinos de enlaces**; nunca tablas/headings/bullets/código. `-` y `/`
   ASCII excluidos a propósito (compuestos, URLs, fechas).
2. **Fragmento matemático**: el par de marcadores se quita solo si su contenido es
   matemático (glifos, corchetes, dígitos, `Q, K, V`, `lrate`, `Pdrop`, `softmax`,
   `QWi`). Se conservan enlaces (`](`), prosa multi-palabra (`_York Times_`),
   siglas (`**BERTBASE**`), etiquetas (`**Encoder:**`, `**Operador**`), autores
   (`**Ashish Vaswani**`) y tachados wiki (`~~4~~`, `~~.~~`).
3. **Invariante**: `re.findall(r"[^\W_]+", antes) == … (después)` por página; en
   caso contrario la página se revierte entera (`pdf_math_clean_reverted_page_N`).

## Medición antes → después

| medida | attention | bert |
|---|---|---|
| líneas de markdown con énfasis (cualquier línea) | 185 | 240 |
| marcas de énfasis totales | 861 | 980 |
| líneas matemáticas con énfasis | 59 → **11** | 20 → **0** |
| marcas en líneas matemáticas | 496 → **44** | 104 → **0** |

Muestras:

```
antes:  Attention( _Q, K, V_ ) = softmax( _[QK]_ ~~_V_~~ _[T]_
después: Attention( Q, K, V ) = softmax( [QK] V [T]

antes:  _lrate_ = _d_ _[-]_ model [0] _[.]_ [5]
después: lrate = d [-] model [0] [.] [5]

antes:  Transformer (base model) 27.3 38.1 **3** _**.**_ **3** _**·**_ **10** **[18]**
después: Transformer (base model) 27.3 38.1 3 . 3 · 10 [18]
```

Resto en attention (11 líneas, motivo): 8 nombres de autores (`**Ashish Vaswani**`…)
y 3 etiquetas en negrita (`**Encoder:**`, `**Decoder:**`, `**Label Smoothing**`) —
prosa legítima dentro de líneas matemáticas que la limpieza no debe tocar. Además
queda 1 marcador suelto sin par (`warmup _ steps = 4000`): quitar `_` sueltos podría
fusionar identificadores (`d_model`) y romper el invariante. En bert no queda
ninguna marca.

## Invariante de tokens (script + mecanismo)

- `.orca-task/dry_run.py`: los 17 markdown antes/después con el mismo token-stream
  (`pmc.tokens(antes) == pmc.tokens(tras)`), aserto explícito → PASS.
- `.orca-task/tokens_invariant.py` con `convert()` real: attention 6 668 tokens,
  bert 11 125 tokens, idénticos antes/después.
- Mecanismo de defensa: `clean_math_emphasis` revierte la página entera si el
  resultado altera el token-stream (test dedicado). Reversiones en el arnés: **0**.

## SHAs (tabla completa en `docs/h3/pdf-two-column-format.md`)

| archivo | markdown_bytes | SHA-256 tras el cambio | vs baseline |
|---|---|---|---|
| arxiv-attention-is-all-you-need-en.pdf | 42 420 | `dcff3ea55a56e5332f8f714c84e02964dacd9101c365407d58b0cf00c9d8a441` | cambia (objetivo) |
| arxiv-bert-en.pdf | 69 705 | `8717a1fe48ce65800c6c350c92c68cd088017401987687efa38022c7b35f0e61` | cambia (objetivo) |
| otros 15 (boe-×2, wiki-×13) | idénticos | idénticos | SHA igual al baseline T0 |

**Lista exacta de archivos cuyo SHA cambia: `arxiv-attention-is-all-you-need-en.pdf`
y `arxiv-bert-en.pdf`.** Ningún otro cambia. Nota sobre bert: entre procesos el
markdown de bert tiene una bimodalidad preexistente registrada (69 809/69 813
bytes antes; 69 705/69 709 tras el cambio, vía `8717a1fe…` o `61066a97…`); dentro
del mismo proceso tres pasadas son byte-idénticas y la limpieza es determinista.
Los "Copa 254200/254203" registrados se confirman sin delta de esta tarea
(Copa = SHA del baseline en ambas pasadas).

## Auditoría (`--audit-json` sobre los 17)

| archivo | real_prose (palabras) | real_equation (líneas) | missing_symbols | duplicate_layer |
|---|---|---|---|---|
| arxiv-attention | 0 | 0 | 0 | 357 líneas (sin delta vs T1) |
| arxiv-bert | 0 | 0 | 0 | 263 líneas (sin delta vs T1) |

Todo el corpus: `real_prose_words = 0`, `real_equation_lines = 0`.
`duplicate_layer` 357/263 = los mismos valores documentados en
`docs/h3/pdf-two-column-loss.md` (repeticiones por página, artefacto de medida;
cero pérdida real atribuible y cero delta de esta tarea).

## Tiempo del arnés (dos pasadas, código final)

| pasada | baseline (s) | T2d (s) | delta |
|---|---|---|---|
| 1 | 127.872 | 145.708 | +13.9 % |
| 2 | 148.181 | 122.231 | −17.5 % |
| **total** | **276.053** | **267.939** | **−2.9 %** |

El tiempo total baja un 2.9 %: muy por debajo del tope de +10 %. La dispersión
entre pasadas del propio baseline (127.872 → 148.181, +16 %) domina el ruido de
una pasada individual; el coste marginal de la limpieza son unas pasadas de regex
por línea matemática.

## Tests y checks

- `pytest tests` (gate): **192 passed, 1 skipped** (incluye los 11 nuevos de
  `test_pdf_math_clean.py`), typecheck web verde.
- `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .` → `CHECK_OK` (H0 SKIP
  por corpus ausente en worktree, según diseño del gate).
- Arnés ×2 con `--audit-json` (código final): `.orca-task/after-pass1.json` +
  `.orca-task/after-audit-pass1.json` (145.708 s), `.orca-task/after-pass2.json`
  + `.orca-task/after-audit-pass2.json` (122.231 s); SHAs idénticos entre ambas
  pasadas y reversiones del invariante = 0.

## Riesgos y limitaciones

1. Restos de énfasis en prosa bold dentro de líneas matemáticas de attention
   (autores/etiquetas): 11 líneas, documentadas con muestra y motivo.
2. `dimensionquery` (pegado de columna) NO se corrige: queda como limitación
   medida, fuera del alcance (verbatim del enunciado).
3. Compuestos (`lefttoright`, `selfattention`, `pretrain`) intactos, excluidos.
4. El invariante protege contra cualquier fusión/split de tokens; el coste de la
   limpieza es despreciable (−2.9 % de tiempo total del arnés).
5. `pdf_math_clean.py` es ciego a la página (solo texto): el mismo predicado se
   aplicaría a la estrategia `layout` si se usara.

## Pendientes

Ninguno bloqueante: la tarea queda implementada, medida, documentada y testeada.
