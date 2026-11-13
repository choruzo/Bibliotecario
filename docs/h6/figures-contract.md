# Contrato de figuras declarativas (H6, congelado)

Estado: **congelado**. Este documento describe exactamente lo que valida
`apps/api/bibliotecario/figures.py` (modelos pydantic cerrados + `validate_figure`).
Cualquier cambio de nombre o límite exige una revisión de este contrato.

## Por qué no hay HTML

El modelo **no produce HTML**. Produce una figura tipada (tabla, línea de
tiempo, barras o pasos) que la web renderiza con componentes fijos. Un HTML
generado por el modelo obligaría a un sanitizador o a un `iframe` con
`sandbox`, con riesgo de XSS, inyección de CSS/layout y problemas de
accesibilidad, y no aporta nada que no den cuatro componentes deterministas.
El contrato es **texto plano**: los campos de texto no pueden contener
marcado, caracteres de control ni caracteres de ancho cero; el render
(React) escapa el texto de forma natural y no existe ningún campo `html`,
`css`, `script`, `href`, `src`, `url` ni `style`.

## Forma general

Un payload de figura es un objeto con exactamente estas claves: `kind`,
`title`, `source_citations`, opcionalmente `caption`, y **exactamente** la
clave de datos correspondiente a `kind` (`table`, `timeline`, `bars` o
`steps`) y ninguna otra. Toda clave no declarada se rechaza con
`extra_field`, en la raíz y en cada nivel anidado (los modelos son
`extra="forbid"` en todos los niveles).

```json
{
  "kind": "table|timeline|bars|steps",
  "title": "texto de 1 a 120 caracteres",
  "caption": "texto opcional de hasta 240 caracteres",
  "source_citations": ["C1"],
  "<kind>": { "...": "según kind" }
}
```

`source_citations` son `citation_id` de las fuentes del turno (1..4,
distintas). Cada dato anidado cita con `citations` (1..3) los mismos
`citation_id`.

## Los cuatro tipos

### table

```json
{
  "kind": "table",
  "title": "Ciclo de desarrollo de las castas",
  "source_citations": ["C1"],
  "table": {
    "columns": ["Casta", "Días de desarrollo"],
    "rows": [["Reina", "16 días"], ["Obrera", "21 días"]]
  }
}
```

### timeline

```json
{
  "kind": "timeline",
  "title": "Cronología del traslado",
  "caption": "Fechas del apéndice B",
  "source_citations": ["C1"],
  "timeline": {
    "events": [
      {"when": "12 de mayo", "label": "Llegada de la colmena", "citations": ["C1"]},
      {"when": "20 de mayo", "label": "Primera revisión", "citations": ["C1"]}
    ]
  }
}
```

### bars

```json
{
  "kind": "bars",
  "title": "Cuadros por colmena",
  "source_citations": ["C1"],
  "bars": {
    "unit": "cuadros",
    "series": [
      {"label": "Cámara de cría", "value": 5, "citations": ["C1"]},
      {"label": "Alza melaria", "value": 2, "citations": ["C1"]}
    ]
  }
}
```

### steps

```json
{
  "kind": "steps",
  "title": "Alimentación de una colonia",
  "source_citations": ["C2"],
  "steps": {
    "items": [
      {"label": "Colocar el alimentador", "detail": "Añadir 1 litro", "citations": ["C2"]},
      {"label": "Reponer cada semana", "citations": ["C2"]}
    ]
  }
}
```

## Tabla de límites

| Campo | Límite | Motivo al superarlo |
|---|---|---|
| `title` | 1..120 caracteres | `too_large` (vacío: `invalid_text`) |
| `caption` | ≤ 240 caracteres, opcional | `too_large` |
| `source_citations` | 1..4, únicas, presentes en el turno | `too_large` / `citation_unknown` |
| `table.columns` | 2..6 cadenas de ≤ 80 caracteres | `too_large`; < 2: `missing_payload` |
| `table.rows` | 1..12 | `too_large` |
| celda | ≤ 240 caracteres, longitud = `columns` | `too_large` / `missing_payload` |
| `timeline.events` | 1..12 | `too_large` |
| `when` | ≤ 40 caracteres | `too_large` |
| `label` (evento) | ≤ 160 caracteres | `too_large` |
| `bars.unit` | ≤ 16 caracteres | `too_large` |
| `bars.series` | 1..12 | `too_large` |
| `label` (serie/paso) | ≤ 80 / ≤ 120 caracteres | `too_large` |
| `value` | número finito ≥ 0 | `not_number` / `negative_value` |
| `steps.items` | 1..8 | `too_large` |
| `detail` | ≤ 240 caracteres, opcional | `too_large` |
| `citations` (por dato) | 1..3 | `too_large` / `citation_unknown` |

Todo texto se comprueba antes de las longitudes: sin caracteres de control
ni de ancho cero, sin saltos de línea y no vacío tras `strip()`; si no,
`invalid_text`. El texto almacenado es el texto saneado con `strip()`; las
longitudes se miden sobre él y nunca se trunca en silencio. Una colección
por debajo de su mínimo (0 filas, 1 columna, sin eventos, falta de una
clave requerida, celda con longitud distinta de `columns`) es estructura
incompleta: `missing_payload`.

## Regla numérica

Cada número presente en un `value`, en una celda, en un `when`, en un
`label` o en un `detail` debe estar en la unión de `allowed_numbers` de las
citas **de su propio dato** (para las celdas, `source_citations` de la
figura). `allowed_numbers` es `dict[citation_id, set[float]]`, precomputado
por el llamador con la misma extracción (`textnums.numbers`) que usa el
grounding de respuestas. Un número no soportado se rechaza con
`unsupported_number`, aunque exista en otra cita del turno que el dato no
cita.

Ejemplo **aceptado** — la celda dice `16 días` y cita `C1`, cuyo pasaje
contiene 16:

```json
{"kind": "table", "title": "Ciclo", "source_citations": ["C1"],
 "table": {"columns": ["Casta", "Días"], "rows": [["Reina", "16 días"]]}}
```

```python
validate_figure(payload, {"C1", "C2"}, {"C1": {16.0}, "C2": {24.0}})
# -> ({...}, None)
```

Ejemplo **rechazado** — la celda dice `24 cuadros` y cita `C1`, pero 24 solo
aparece en el pasaje de `C2`, que la celda no cita:

```json
{"kind": "table", "title": "Cuadros", "source_citations": ["C1"],
 "table": {"columns": ["Colmena", "Cuadros"], "rows": [["A", "24 cuadros"]]}}
```

```python
validate_figure(payload, {"C1", "C2"}, {"C1": {16.0}, "C2": {24.0}})
# -> (None, "unsupported_number")
```

Nota: "treinta y dos" declara 2, 30 y 32 a la vez (`textnums.numbers`);
un pasaje que diga exactamente eso soporta los tres, uno que diga "32" solo
el 32.

## Motivos de rechazo

| Motivo | Significado |
|---|---|
| `unknown_kind` | `kind` ausente, no es cadena o no es uno de los cuatro |
| `extra_field` | clave no declarada en cualquier nivel (raíz, payload, dato), incluidas `html`, `css`, `script`, `href`, `src`, `url`, `style`, `timestamp` |
| `missing_payload` | falta la clave de `kind`, una clave requerida o una colección por debajo de su mínimo; celda con longitud distinta de `columns` |
| `citation_unknown` | cita que no está en las fuentes del turno, lista vacía o marcador repetido |
| `too_large` | cualquier límite de tamaño superado |
| `invalid_text` | texto no cadena, con caracteres de control/ancho cero/salto de línea, o vacío tras `strip()` |
| `negative_value` | `value` < 0 |
| `not_number` | `value` no numérico, booleano o no finito |
| `unsupported_number` | número no presente en la unión de `allowed_numbers` de las citas de su dato |

## Generación en modo explicar

El modo `explain` genera **una** respuesta JSON que contiene la síntesis y,
opcionalmente, una figura: la figura viaja en la misma generación (cero
llamadas extra al modelo) y nunca es un documento aparte.

### Orden de validación

1. `validate_synthesis` valida el sobre completo: `sections` siempre y
   `figure` opcional, **solo como objeto**. Un `figure` que no sea objeto
   (`figure: []`, una lista con dos figuras) o una segunda figura bajo otra
   clave raíz (`figures`) viola el esquema entero → `invalid_synthesis` →
   extracto: no es un motivo de figura, es un fallo del sobre.
2. `verify_synthesis` audita cada frase contra la unión de sus citas.
3. Solo si el texto se mantiene (`grounded`), `validate_figure` valida la
   figura contra las fuentes del turno: `source_citations` deben existir entre
   las `sources` y cada dato se comprueba con las cifras de **sus** citas
   (`allowed_numbers` por cita: pasaje + título + `section_path`, extraído con
   `textnums.numbers`).
4. Publicación: la figura válida se guarda en `Message.figures` (lista de
   exactamente uno) y viaja en el evento `done` dentro de `message_json`.

### Política de descarte

- Una figura inválida **nunca** cambia el destino del turno: la respuesta se
  publica `completed` con su texto y el motivo queda en
  `chat_outcome.figure_rejected` (`unsupported_number`, `citation_unknown`,
  `extra_field`, `too_large`, …). La figura se descarta entera: no se trunca
  ni se repara. `chat_outcome.figure` documenta la ranura como
  `{"present": bool, "kind": str|null}`, y solo se escribe cuando el modelo
  produjo figura: un turno sin figura mantiene el resultado anterior.
- Si el texto cae a `grounded_extract` (rechazo de `validate_synthesis` o del
  verificador), la figura cae con él: `figure_rejected = "text_fallback"`. El
  extracto literal no sostiene la síntesis y tampoco su figura, aunque la
  figura en sí fuera válida.
- El modo `answer` no cambia: su esquema cerrado `{"evidence":[…]}` no admite
  `figure` ni siquiera opcional; si el modelo la devuelve, el turno cae por
  `invalid_answer` como con cualquier campo extra (abstinencia) y no se
  publica ninguna figura.

### Ejemplo aceptado

El pasaje `C1` dice «El sistema tiene 3 módulos.» y la síntesis ya explicó
esa comparación; la figura la apoya visualmente:

```json
{"kind": "bars", "title": "Composición del sistema", "source_citations": ["C1"],
 "bars": {"unit": "módulos", "series": [{"label": "Sistema", "value": 3, "citations": ["C1"]}]}}
```

`value: 3` está en las cifras de `C1` y la cita existe en el turno → se
guarda tal cual (con `value` normalizado a `3.0`) en `Message.figures`,
`chat_outcome.figure = {"present": true, "kind": "bars"}` y sin
`figure_rejected`.

### Ejemplo rechazado

El pasaje `C2` dice «Requiere 4 sensores.», pero el dato cita `C1`, cuyo
pasaje solo contiene 3:

```json
{"kind": "bars", "title": "Comparativa de piezas", "source_citations": ["C1"],
 "bars": {"unit": "piezas", "series": [{"label": "Sensores requeridos", "value": 4, "citations": ["C1"]}]}}
```

→ `(None, "unsupported_number")`; el turno sigue `completed` con el texto
intacto y `chat_outcome` registra
`{"figure": {"present": false, "kind": null}, "figure_rejected": "unsupported_number"}`.

## Persistencia

`messages.figures` es JSON NOT NULL con `server_default='[]'` (migración
`0007_h6`, reversible). Los mensajes antiguos devuelven `[]` en
`message_json`. Una figura validada se guarda tal cual la devuelve
`validate_figure`; no se recalcula al leer.
