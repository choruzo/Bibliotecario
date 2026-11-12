# T2e - Informe: limpiar el énfasis en las líneas de continuación de las fórmulas

Task: `task_5b5eb9149cae` · run `run_43fca8504d61` · worktree `pdf-math-block-5b5eb9`

## Resultado

**SUCCESS.** Las marcas `_`, `**` y `~~` de las líneas de continuación de una
fórmula se limpian ahora agrupando el markdown de cada página en **bloques
matemáticos**. La fórmula de attention queda sin `_` en todas sus líneas y los
otros 15 PDF del corpus permanecen byte-idénticos al baseline de T0.

## Objetivo y alcance cumplido

`clean_math_emphasis` trabajaba línea a línea y solo limpiaba líneas con `=` o
glifo matemático propio; `_dk_` y `_V_` caían en líneas sueltas y se quedaban.
Ahora:

1. **Bloques matemáticos**: una línea matemática *fuerte* (con `=` o un glifo
   distinto del punto medio) abre un bloque; las líneas siguientes son líneas de
   continuación hasta una línea no vacía que no sea fragmento matemático (prosa,
   tabla, heading, bullet, código, enlace) — que cierra el bloque. Las líneas en
   blanco **nunca** cierran un bloque: son los huecos verticales que
   `pymupdf4llm` deja entre los fragmentos de una fórmula desplegada en dos
   columnas (la evidencia real del enunciado tiene la fórmula separada por
   líneas en blanco; un bloque que terminara en la primera línea en blanco no
   habría alcanzado `_dk_` ni `) _V_ (1)`).
2. **Continuación**: se limpia solo si TODO par de marcadores de la línea es un
   fragmento matemático (mismo `_is_math_fragment` de T2d) y todo el texto fuera
   de los pares es cáscara matemática (`CONT_SHELL`: dígitos, corchetes,
   paréntesis, operadores planos, glifos, espacios) sin puntuación de frase y
   sin palabras de prosa. La prosa de continuación no se toca.
3. **Invariante por página intacto** (T2d): mismo token-stream
   `[^\W_]+` antes/después; página revertida entera si falla. Reversiones en los
   17 PDF: **0**.
4. Fuera de alcance respetado: `pdf_audit.py`, `coverage()`, `PDF_MIN_COVERAGE`,
   `_line_missing`, `_missing_runs`, `place()` intactos; sin reconstrucción de
   sub/superíndices (T2f); sin republicar ni calibrar.

## Antes / después de la fórmula (attention, conversión real)

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

Concatenada: `Attention( Q, K, V ) = softmax( [QK] √ [T] dk ) V (1)` — sin `_`
en ninguna línea. Otros cambios (los 7 de la delta completa):

```
antes:    _[ K]_ _i_ _[, V W][ V]_ _i_     después:  [ K] i [, V W][ V] i
antes:    _[ V]_ _i_ [)]                   después:  [ V] i [)]
antes:    _i_ _[Q][, KW][ K]_ _i_          después:  i [Q][, KW][ K] i
antes:    …network with / _dk_             después:  …network with / dk   (denominador √ 1/dk)
antes:    …by √ 1 . / _dk_                 después:  …by √ 1 . / dk       (denominador √ 1/dk)
```

La prosa de continuación se conserva con sus marcas: `_dk_, the dot products
grow large in magnitude…` y `Where the projections are parameter matrices _W_
_[Q]_` quedan intactos, igual que las 11 líneas de autores/etiquetas de T2d.

## Recuentos

- Delta de attention: **exactamente 7 líneas** (2 scaled dot-product, 3
  multi-head, 2 denominadores), verificada con diff pre/post del comportamiento
  en un mismo proceso (`.orca-task/diff_all.py`): los otros 16 PDF byte-idénticos
  entre comportamiento pre y post.
- `math_pages` diagnostics: attention 10 páginas, bert 7 (bert sin delta de
  código); resto del corpus 0.
- Reversiones del invariante: 0 en los 17 PDF.

## Invariante

Mismo mecanismo de T2d: `tokens(markdown)` por página dentro de
`clean_math_emphasis`, con reversión entera y diagnóstico
`pdf_math_clean_reverted_page_N`. Los 7 cambios son eliminaciones de marcadores
que no fusionan ni mueven tokens (`dk` → `dk`, `V` → `V`); el diff de tokens es
idéntico. Test dedicado sigue en verde.

## Tabla de SHAs (arnés, 2 pasadas con `PYTHONHASHSEED=0`, `--audit-json`)

| archivo | bytes | SHA-256 (pasada 1 == pasada 2) | vs estado T2d | vs baseline T0 |
|---|---|---|---|---|
| arxiv-attention | 42 420 → 42 394 | `6af33cfea93b1f186b5b94eba8068968ff841182f0ad2123d3807ce603bd9c00` | cambia de `dcff3ea5…c9d8a441` (objetivo) | cambia (objetivo) |
| arxiv-bert | 69 709 | `61066a97d28f…` | **sin cambio de código** (variante ya documentada de su bimodalidad: `8717a1fe…`/69 705 y `61066a97…`/69 709) | cambia (T2d) |
| otros 15 (boe ×2, wiki ×13) | idénticos | idénticos a `evaluation/h3/pdf-legacy-baseline.json` | sin cambio | SAME |

Notas de medición:

- Copa Mundial mostró `8dbce921…` en una pasada auxiliar **sin semilla fija**:
  es la bimodalidad preexistente entre procesos documentada desde T2d; el diff en
  un mismo proceso (semilla idéntica para pre y post) la descarta como delta de
  esta tarea, y las dos pasadas del arnés dan el SHA del baseline `14342a0f…2c77`.
- Auditoría tras el cambio (2 pasadas, `pdf-content-audit/1`): attention y bert
  `real_prose = 0`, `real_equation = 0`, `missing_symbols = 0`;
  `duplicate_layer` 357/263 líneas — exactamente los valores documentados en
  T1/T2d (artefacto de medida por repetición de cabeceras por página), **sin
  delta**; resto del corpus sin pérdida real.

## Tiempo del arnés (2 pasadas, código final)

| pasada | baseline (s) | T2e (s) | delta |
|---|---|---|---|
| 1 | 127.872 | 119.427 (106.680 conv + 12.747 audit) | −6.6 % |
| 2 | 148.181 | 112.552 (100.416 conv + 12.136 audit) | −24.0 % |
| **total** | **276.053** | **231.979** | **−16 %** |

Muy por debajo del tope de +10 %.

## Tests y checks

- `apps/api/tests/test_pdf_math_clean.py`: **17 passed** (6 nuevos: fórmula
  multilínea con huecos en blanco, prosa de continuación intacta, tabla tras una
  ecuación cierra el bloque, heading tras una ecuación cierra el bloque,
  líneas en blanco tienden el bloque y la prosa lo cierra, fragmentos multi-head
  con `_W_ _[Q]_` conservado; todos con aserto de token-stream).
- `pwsh -NoProfile -File ops/orca/check.ps1 -Worktree .` → **CHECK_OK**
  (198 passed, 1 skipped; H0_SKIP por corpus ausente en worktree, según diseño
  del gate; typecheck web verde).
- Arnés ×2 con `--audit-json`: `.orca-task/after-pass1.json` +
  `after-audit-pass1.json` (119.427 s) y `.orca-task/after-pass2.json` +
  `after-audit-pass2.json` (112.552 s); SHAs idénticos entre pasadas,
  reversiones 0.

## Defensa encontrada y corregida (por medición, no por intuición)

El punto medio (`·`) es glifo matemático para el predicado de T2d
(`pos/ 10000 · 2 π`), pero la wiki lo usa como bullet a inicio de línea
(`·El helio pertenece al bloque`). La primera implementación abría bloques con
cualquier línea matemática y comía la `**s**` siguiente (la letra del bloque s)
en `wiki-Tabla_periódica_de_los_elementos.pdf`. El diff pre/post sobre el corpus
lo detectó; la versión final solo abre bloques con líneas matemáticas *fuertes*
(`=` o glifo ≠ `·`) y las líneas de solo-punto-medio cierran el bloque. Con esa
defensa, el diff en un mismo proceso da 16/17 archivos byte-idénticos.

## Riesgos y limitaciones

1. El alcance de un bloque cruza líneas en blanco hasta la primera prosa: una
   línea de fragmento matemático separada de una fórmula por muchas líneas en
   blanco y solo dígitos/corchetes se limpiaría. En el corpus real no ocurre
   (16/17 byte-idénticos, diff en mismo proceso); el invariante de tokens y la
   reversión entera siguen protegiendo cada página.
2. bert queda en la variante `61066a97…` de su bimodalidad documentada
   (69 709 bytes); el diff en mismo proceso confirma que la limpieza no altera
   ni un byte de bert.
3. Restos conocidos de T2d sin cambio: 11 líneas de autores/etiquetas en
   attention, `warmup _ steps` sin par, compuestos (`lefttoright`,
   `selfattention`) y `dimensionquery` — todo fuera del alcance de T2e.
4. La reconstrucción de sub/superíndices (`[QK] √ [T]` → `QK^T/√dk`) sigue
   pendiente para T2f; la fórmula queda `… [QK] √ [T] dk ) V (1)`.

## Archivos tocados

| archivo | cambio |
|---|---|
| `apps/api/bibliotecario/pdf_math_clean.py` | bloques matemáticos: `_opens_math_block` (apertura fuerte), `_clean_math_continuation` (cáscara `CONT_SHELL` + todos los pares fragmento), bucle con `in_block`; docstring actualizado |
| `apps/api/tests/test_pdf_math_clean.py` | 6 tests nuevos (17 en total) |
| `docs/h3/pdf-two-column-format.md` | sección T2e: diseño, antes/después, recuentos, SHAs, defensa del punto medio |
| `report.md` | este informe (raíz, para el review) |
| `.orca-task/report.md` | copia del informe (ruta pedida por el enunciado) |

Sin `git add` ni `git commit`: los cambios quedan sin stage para el orquestador.
