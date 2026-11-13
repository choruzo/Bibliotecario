# Banco por facetas (H8)

Banco de aceptación del contrato *answer-per-facet*: preguntas de dos partes
(facetas) que el sistema debe responder **por separado**, con la evidencia de
cada una, sin afirmar relaciones entre ellas y sin rellenar lo que el corpus
no cubre.

Archivos:

- `evaluation/h3/facet-validation-v1.jsonl` — 10 casos de dos partes:
  8 `both`, 1 `partial`, 1 `none`.
- `scripts/h4/facet_acceptance.py` — aceptación en vivo del contrato
  (partes, documentos, frase de cierre, marcadores `[Cn]`, estados).
- `tests/test_facet_bank.py` — contrato del banco (6 tests, sin corpus).
- `tests/test_facet_acceptance_rules.py` — reglas puras del script (16 tests,
  sin red).

## Cómo se verificó

El corpus se convirtió con el arnés del repo (una pasada, layout `legacy`,
17 ficheros):

```sh
.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py \
  --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus \
  --layout legacy --json .orca-task/corpus.json
```

y el markdown de cada documento se leyó completo (una segunda pasada del
convertidor, guardada en `.orca-task/corpus-md/` para poder grep). Todas las
citas de la tabla son literales del texto convertido, con línea.

### Control anti-pseudo-multidocumento

Para cada par `both` se grepeó **cada documento buscando el hecho del otro**,
para garantizar que ninguna parte es respondible con el documento de la otra
parte (el modo de fallo clásico: dos documentos que dicen lo mismo).
Resultados (0 coincidencias en cada dirección salvo nota):

- FAC-VAL-001: AGN-001 no contiene «fotosíntesis», «clorofila» ni «glucosa»;
  AGN-008 no contiene «abeja» ni «polinización».
- FAC-VAL-002: «126 mg/dL» solo está en AGN-003 (AGN-013 menciona la diabetes
  como riesgo reducido por el café, nunca el umbral diagnóstico); «Brasil» no
  está en AGN-003.
- FAC-VAL-003: AGN-007 no contiene «1991» ni «Python»; AGN-010 no contiene
  «Bastilla» ni «1789».
- FAC-VAL-004: AGN-005 no contiene «heliopausa»; AGN-002 no contiene
  «Centenario» ni «Copa Mundial».
- FAC-VAL-005: AGN-012 no contiene «enseñanza» ni «Constitución»; AGN-014 no
  contiene «volcán» (su única coincidencia de «lava» es la provincia de Álava).
- FAC-VAL-006: AGN-011 no contiene «cuota de participación» ni «propiedad
  horizontal»; AGN-015 no contiene «deflación».
- FAC-VAL-007: «28.4» solo está en AGN-016; «masked language model» solo en
  AGN-017 (AGN-016 no menciona BERT).
- FAC-VAL-008: AGN-006 no contiene «aceite de oliva» ni «dieta mediterránea»;
  AGN-009 no contiene «IRPF», «impuesto» ni «1978».
- FAC-VAL-009/010 (fuera de corpus): «Quijote»/«Cervantes», «Guernica»/
  «Picasso» y «Wimbledon» tienen 0 coincidencias en los 17 ficheros; la
  «hemoglobina glucosilada» solo está en AGN-003.

## Tabla de los 10 casos

| id | tipo | parte | docs esperados | evidencia leída (texto convertido) |
|---|---|---|---|---|
| FAC-VAL-001 | both | ¿Qué hacen las abejas en la reproducción de las plantas? | AGN-001 | `wiki-Apis_mellifera.md` L19-20: «Son importantes en la polinización de un número de cosechas» y L45: «La abeja de la miel poliniza la flor de la rabina». |
| FAC-VAL-001 | both | ¿Qué produce la fotosíntesis? | AGN-008 | `wiki-Fotosíntesis.md` L204-207: «A Sachs se debe la formulación de la ecuación básica de la fotosíntesis: 6 CO2 + 6 H2O → C6H12O6 + 6 O2» (produce glucosa y oxígeno; L49: «se desprende oxígeno»). |
| FAC-VAL-002 | both | ¿A partir de qué cifra de glucosa en ayunas se diagnostica diabetes? | AGN-003 | `wiki-Diabetes_mellitus.md` L846-847: «Medición de glucosa en plasma (glucemia) en ayunas mayor o igual a 126 mg/dL (7,0 mmol/L)». |
| FAC-VAL-002 | both | ¿Qué país concentra un tercio de la producción mundial de café? | AGN-013 | `wiki-Café.md` L136: «Brasil concentra poco más de un tercio de la producción mundial». |
| FAC-VAL-003 | both | ¿En qué fecha fue tomada la Bastilla? | AGN-007 | `wiki-Revolución_francesa.md` L811: «Triunfo de la Revolución: la toma de la Bastilla (14 de julio de 1789)». |
| FAC-VAL-003 | both | ¿Quién publicó el código de Python por primera vez? | AGN-010 | `wiki-Python.md` L95: «El 20 de febrero de 1991, van Rossum publicó el código por primera vez». |
| FAC-VAL-004 | both | ¿Dónde se inauguró la primera Copa Mundial de Fútbol? | AGN-005 | `wiki-Copa_Mundial_de_Fútbol.md` L185: «La primera Copa Mundial de Fútbol se inauguró el 13 de julio de 1930 en el Estadio Centenario de Uruguay». |
| FAC-VAL-004 | both | ¿A qué distancia del Sol puede encontrarse la heliopausa? | AGN-002 | `wiki-Sistema_solar.md` L315: «La heliopausa puede encontrarse a unas 100 UA (15 000 millones de kilómetros del Sol)». |
| FAC-VAL-005 | both | ¿Es obligatoria y gratuita la enseñanza básica según la Constitución española? | AGN-014 | `boe-constitucion-1978.md` L531: «La enseñanza básica es obligatoria y gratuita». |
| FAC-VAL-005 | both | ¿Qué tipo de lava forma un volcán en escudo? | AGN-012 | `wiki-Volcán.md` L364-365: «Cuando la lava expulsada por el volcán es fluida, de tipo hawaiano…» y L372: «Un volcán en escudo está formado principalmente por lavas basálticas (ricas en hierro)». |
| FAC-VAL-006 | both | ¿Cómo se llama la variación negativa del nivel general de precios? | AGN-011 | `wiki-Inflación.md` L33: «Una variación negativa del nivel general de precios se denomina deflación». |
| FAC-VAL-006 | both | ¿Qué es la cuota de participación de un piso en la propiedad horizontal? | AGN-015 | `boe-ley-propiedad-horizontal.md` L441: «A cada piso o local se atribuirá una cuota de participación con relación al total del valor del inmueble y referida a centésimas del mismo. Dicha cuota servirá de módulo para determinar la participación en las cargas y beneficios». |
| FAC-VAL-007 | both | ¿Qué puntuación BLEU logró el Transformer en WMT 2014 inglés-alemán? | AGN-016 | `arxiv-attention-is-all-you-need-en.md` L84: «Our model achieves 28.4 BLEU on the WMT 2014 English-to-German translation task». |
| FAC-VAL-007 | both | ¿Qué objetivo de preentrenamiento usa BERT para representar el contexto izquierdo y derecho? | AGN-017 | `arxiv-bert-en.md` L14: «BERT is designed to pre-train deep bidirectional representations … by jointly conditioning on both left and right context in all layers» y L73: «using a "masked language model" (MLM) pre-training objective». |
| FAC-VAL-008 | both | ¿En qué año se instauró el actual IRPF? | AGN-006 | `wiki-Impuesto_sobre_la_renta_…España.md` L39: «El actual impuesto fue instaurado en 1978, en el ámbito de la reforma fiscal de 1977». |
| FAC-VAL-008 | both | ¿Qué aceite es la principal fuente de grasa de la dieta mediterránea? | AGN-009 | `wiki-Dieta_mediterránea.md` L18-19: «el uso de aceite de oliva virgen extra como principal fuente de grasa». |
| FAC-VAL-009 | partial | ¿Qué valor de hemoglobina glucosilada indica diabetes? | AGN-003 | `wiki-Diabetes_mellitus.md` L853: «Hemoglobina Glucosilada HbA1c con cifras mayores o iguales a 6,5 %» (únicamente en AGN-003). |
| FAC-VAL-009 | partial | ¿Quién escribió El Quijote? | — (fuera de corpus) | «Quijote»/«Cervantes»: 0 coincidencias en los 17 ficheros convertidos; el corpus no puede responder esta parte y debe abstenerse. |
| FAC-VAL-010 | none | ¿Quién pintó el cuadro El Guernica? | — (fuera de corpus) | «Guernica»/«Picasso»: 0 coincidencias en el corpus convertido. |
| FAC-VAL-010 | none | ¿Quién ganó el último torneo de Wimbledon? | — (fuera de corpus) | «Wimbledon»: 0 coincidencias en el corpus convertido. |

## Qué comprueba el script

`scripts/h4/facet_acceptance.py` recorre el banco en vivo: login según
`--scope`, conversación nueva por caso, `POST /chat/conversations/{cid}/messages`
con `{"content": <pregunta>, "mode": "explain"}`, lectura del `done.message`
(`content`, `sources`, `retrieval_run_id`) y de la traza
`GET /admin/retrieval/runs/{id}` (`result.parts` y `result.chat_outcome`).
Por caso verifica:

1. `result.parts` de longitud 2.
2. Cada parte con documentos esperados: `completed`, cita ≥ 1 documento
   esperado y ninguno fuera de su lista. La atribución de cada cita `[Cn]`
   global a una parte se hace por la traza (el pool de esa parte:
   `parts[i].results`), nunca por el texto de la respuesta; acepta además
   `chat_outcome.parts[i].document_ids` si la traza lo trae en su lugar.
3. Cada parte con `expected_documents: []`: `abstained` (nada respondido ni
   citado).
4. `status` global: `completed` en `both`/`partial`, `abstained` en `none`.
5. Frase de cierre literal `_Esta composición no afirma ninguna relación entre
   las dos partes: resume la evidencia de cada una por separado._` exactamente
   una vez cuando hay composición y ausente en `none`.
6. Marcadores `[Cn]` bidireccionales: todo marcador del contenido existe en
   `sources` y toda fuente está citada (sin huérfanos en ninguna dirección).

Resumen impreso y escrito: `passed/total`, `improper` (parte respondida cuando
debía abstenerse o cita fuera de sus documentos), `p50/p95` de
`chat_latency.total_ms`, fallos agregados y estado de cada parte. Informe
privado con textos en `.artifacts/facet-acceptance/<scope><label>.json`;
resumen público sin pasajes en `evaluation/h3/facet-acceptance-<scope>.json`.
Sale 1 si algún caso falla e imprime una línea `PASS/FAIL id …` por caso.

Los tests de reglas (`tests/test_facet_acceptance_rules.py`, fixtures a mano)
cubren los cinco fallos por separado: parte respondida sin sus documentos,
parte que debía abstenerse y respondió, cierre repetido y ausente, marcador
huérfano y `parts` con longitud 1; más el caso correcto `both`, el `partial`
correcto, el `none` correcto, el fallback de atribución por `document_ids` y
el caso no-atribuible.
