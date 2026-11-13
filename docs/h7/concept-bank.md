# Banco de preguntas de concepto (H7)

Este banco mide lo que los bancos `agnostic-*` y `colloquial-*` no miden:

1. **Preguntas multi-documento**: solo se responden juntando evidencia de dos
   o más documentos del corpus (por yuxtaposición de dos pasajes —ordenaciones,
   comparaciones de magnitudes, una entidad compartida—, nunca por una relación
   causal que el corpus no afirma).
2. **Preguntas con datos graficables** dentro del documento correcto: años y
   magnitudes con unidad que se pueden representar en una gráfica.

Archivos:

- `evaluation/h3/concept-calibration-v1.jsonl` — 12 casos.
- `evaluation/h3/concept-validation-v1.jsonl` — 12 casos.
- `tests/test_concept_banks.py` — contrato y mínimos (unittest, sin corpus).

## Cómo se generó

El corpus se convirtió con el arnés del repo (una pasada, layout `legacy`):

```sh
.venv/Scripts/python.exe scripts/h3/pdf_conversion_report.py \
  --corpus D:/Archivos/Javier/Proyectos/Bibliotecario/.artifacts/agnostic-corpus \
  --layout legacy --json .orca-task/corpus.json --audit-json .orca-task/corpus-audit.json
```

y el markdown resultante se leyó completo para extraer cada hecho. Todas las
citas de la tabla siguiente son literales del texto convertido. Las
`expected_sections` quedan **vacías en los 24 casos**: el foco de este banco es
el documento correcto, y solo se hubieran rellenado con un `section_path`
verificado literalmente.

### Control anti-pseudo-multidocumento

Para cada par se grepeó **cada documento buscando el hecho del otro**, para
garantizar que ninguna pregunta es respondible con un solo documento (el modo
de fallo clásico: dos documentos que dicen lo mismo). Resultados: AGN-007 no
contiene «Unesco» ni «dieta»; AGN-009 no contiene «Bastilla», «1789» ni
«revolución»; AGN-010 no contiene «Constitución» ni «1978»; AGN-014 no contiene
«Python», «1991» ni «1930»; AGN-004 no contiene «planeta»; AGN-002 no contiene
«fotosíntesis» ni «118 elementos»; AGN-013 no contiene «Copa Mundial» ni
«fútbol»; AGN-005 no contiene «café», «Bastilla» ni «1789»; AGN-015 no contiene
«IRPF» ni «1978» (sus 9 menciones de «constitución» son «constitución del
régimen de propiedad horizontal»); AGN-006 no contiene «propiedad horizontal»;
AGN-016 no contiene «Python» ni «1991»; AGN-017 no contiene «213» (los
parámetros del Transformer solo están en AGN-016).

## `concept-calibration-v1.jsonl`

| id | tipo | docs esperados | evidencia leída (texto convertido) |
|---|---|---|---|
| CON-CAL-A001 | answerable (multi-doc) | AGN-007, AGN-009 | AGN-007: «Triunfo de la Revolución: la toma de la Bastilla (14 de julio de 1789)». AGN-009: «Inscripción 2010 (V sesión)» y «El 16 de noviembre de 2013 fue declarada Patrimonio Cultural Inmaterial de la Humanidad». → Respuesta: la Bastilla (1789), con independencia de 2010 o 2013. |
| CON-CAL-A002 | answerable (multi-doc) | AGN-010, AGN-014 | AGN-010: «El 20 de febrero de 1991, van Rossum publicó el código por primera vez». AGN-014: «BOE núm. 311, de 29 de diciembre de 1978». → Respuesta: Python es posterior (1991 > 1978). |
| CON-CAL-A003 | answerable (multi-doc) | AGN-004, AGN-002 | AGN-004: «Se han descubierto o sintetizado todos los elementos de número atómico del 1 (hidrógeno) al 118 (oganesón)». AGN-002: «comprende: ocho planetas (cuatro planetas interiores y cuatro planetas exteriores)». → Respuesta: sí, 118 > 8. |
| CON-CAL-A004 | answerable (multi-doc) | AGN-013, AGN-005 | AGN-013: «…35 % de la producción mundial y es, con amplia diferencia, el mayor productor global» + tabla «1. Brasil. 2 681 000» toneladas. AGN-005: «Brasil, la selección más exitosa, cinco victorias; le siguen Alemania e Italia con cuatro». → Respuesta: sí, Brasil. |
| CON-CAL-A005 | answerable (multi-doc) | AGN-002, AGN-008 | AGN-002: «El sistema solar se formó hace unos 4600 millones de años a partir del colapso de una nube molecular». AGN-008: «la existencia de fotosíntesis oxigénica y la oxigenación de la atmósfera y océanos se habría producido desde hace más de 3.460 millones de años». → Respuesta: la formación del sistema solar fue anterior. |
| CON-CAL-G001 | answerable (graficable, AGN-007) | AGN-007 | Pasaje de las fases: «1. **Monarquía Constitucional** (1789-1792)», «Nacional Constituyente (1789-1791) y la de la Asamblea Nacional Legislativa (1791-1792)», «2. **República radical** (1792-1794). Tras la caída de la monarquía en agosto de 1792», «Constitución de 1791», «Declaración de los Derechos del Hombre y del Ciudadano de 1793», «Termidor del Año II (27 de julio de 1794)». → Respuesta: 1789-1792 y 1792-1794; el pasaje esperado contiene cinco años distintos (1789, 1791, 1792, 1793, 1794). |
| CON-CAL-G002 | answerable (graficable, AGN-003) | AGN-003 | «Síntomas clásicos de la enfermedad (poliuria, polidipsia, polifagia y pérdida de peso) más una toma sanguínea casual o al azar con cifras mayores o iguales de 200 mg/dL (11,1 mmol/L)». → Respuesta: ≥ 200 mg/dL (magnitud y unidad). |
| CON-CAL-U001 | unanswerable (fuera de corpus) | — | Ninguna de las 17 fuentes (AGN-005 incluida) contiene métricas de redes sociales; el corpus no puede responder. |
| CON-CAL-U002 | unanswerable (premisa falsa) | — | AGN-009 sitúa la inscripción Unesco en 2010/2013 y AGN-007 la Bastilla en 1789: la pregunta invierte el orden temporal y el «por qué» resultante no tiene respuesta en el corpus. |
| CON-CAL-M001 | ambiguous (referente ausente) | — | «los dos acontecimientos» no queda definido en ninguna parte; sin antecedente la pregunta no designa nada. |
| CON-CAL-C001-T1 | conversation, turno 1 (multi-doc) | AGN-005, AGN-010 | AGN-005: «La primera Copa Mundial de Fútbol se inauguró el 13 de julio de 1930 en el Estadio Centenario de Uruguay». AGN-010: «El 20 de febrero de 1991, van Rossum publicó el código por primera vez». → Respuesta: la Copa (1930) es más antigua. |
| CON-CAL-C001-T2 | conversation, turno 2 (multi-doc) | AGN-005, AGN-010, AGN-014 | Mismas citas del turno 1 + AGN-014: «BOE núm. 311, de 29 de diciembre de 1978». → Respuesta: 1930 < 1978 < 1991, la Constitución queda entre ambos. «Esos dos hitos» solo se entiende con el turno 1. |

## `concept-validation-v1.jsonl`

| id | tipo | docs esperados | evidencia leída (texto convertido) |
|---|---|---|---|
| CON-VAL-A001 | answerable (multi-doc) | AGN-005, AGN-007 | AGN-005: «La primera Copa Mundial de Fútbol se inauguró el 13 de julio de 1930 en el Estadio Centenario de Uruguay». AGN-007: «la toma de la Bastilla (14 de julio de 1789)». → Respuesta: la Bastilla (1789 < 1930). |
| CON-VAL-A002 | answerable (multi-doc) | AGN-015, AGN-014 | AGN-015: «Ley 49/1960, de 21 de julio, sobre propiedad horizontal» y «BOE núm. 176, de 23 de julio de 1960». AGN-014: «BOE núm. 311, de 29 de diciembre de 1978». → Respuesta: la LPH es anterior (1960 < 1978). |
| CON-VAL-A003 | answerable (multi-doc) | AGN-016, AGN-010 | AGN-016 (pie del propio artículo): «31st Conference on Neural Information Processing Systems (NIPS 2017), Long Beach, CA, USA.» y «arXiv:1706.03762v7». AGN-010: «El 20 de febrero de 1991, van Rossum publicó el código por primera vez». → Respuesta: el artículo es posterior (2017 > 1991). |
| CON-VAL-A004 | answerable (multi-doc) | AGN-017, AGN-016 | AGN-017: «BERTBASE (L=12, H=768, A=12, Total Parameters=110M) and BERTLARGE (L=24, H=1024, A=16, Total Parameters=340M)». AGN-016 (tabla 3, columna «params ×10⁶»): «base … 65» y «big … 213». → Respuesta: sí, 340M > 213M. |
| CON-VAL-A005 | answerable (multi-doc) | AGN-015, AGN-006 | AGN-015: «Ley 49/1960, de 21 de julio, sobre propiedad horizontal». AGN-006: «El actual impuesto fue instaurado en 1978, en el ámbito de la reforma fiscal de 1977». → Respuesta: sí, existía (1960 < 1978). |
| CON-VAL-G001 | answerable (graficable, AGN-007) | AGN-007 | «el juicio comienza el 3 de diciembre de 1792. El resultado es que el 21 de enero de 1793 Luis XVI es guillotinado» y «el 30 de marzo de 1794 (10 Germinal Año II), el Comité decreta la detención de los jacobinos «indulgentes» de Danton». → Respuesta: 3-12-1792, 21-1-1793 y 30-3-1794; el pasaje de la Convención contiene tres años distintos (1792, 1793, 1794). |
| CON-VAL-G002 | answerable (graficable, AGN-013) | AGN-013 | «pasó de un promedio de 168 millones de sacos en la campaña 2022/23 a 178 millones de sacos en 2023/2024, un aumento del 5,8 %, y a unos 174,9 millones de sacos previstos para la campaña 2024/2025». → Respuesta: 168 millones (2022/23) y 174,9 millones (2024/2025) de sacos de 60 kg (magnitudes y unidad). |
| CON-VAL-U001 | unanswerable (fuera de corpus) | — | AGN-014 es el texto consolidado de la Constitución (BOE-A-1978-31229); no contiene horarios de archivo ni información museística. |
| CON-VAL-U002 | unanswerable (premisa falsa) | — | AGN-017 se construye sobre el Transformer: «BERT's model architecture is a multi-layer bidirectional Transformer encoder based on the original implementation described in Vaswani et al. (2017)», y AGN-016 es el artículo de NIPS 2017. La premisa «BERT se publicó antes» contradice el corpus. |
| CON-VAL-M001 | ambiguous (referente ausente) | — | «ambos hitos» no tiene antecedente; la pregunta no designa nada. |
| CON-VAL-C001-T1 | conversation, turno 1 (multi-doc) | AGN-017, AGN-016 | AGN-017: «BERTBASE (L=12, H=768, A=12, Total Parameters=110M)». AGN-016 (tabla 3): «base … 65». → Respuesta: BERT-base (110M > 65M). |
| CON-VAL-C001-T2 | conversation, turno 2 (multi-doc) | AGN-017, AGN-016 | AGN-017: «BERTLARGE (L=24, H=1024, A=16, Total Parameters=340M)». AGN-016 (tabla 3): «big … 213». → Respuesta: BERT-large (340M > 213M). «Sus versiones grandes» solo se entiende tras el turno 1 (las bases de ambos modelos). |

## Mínimos por fichero y test

Cada fichero tiene 12 casos: 7 filas multi-documento (5 `answerable` + los 2
turnos de conversación, ≥ 6 exigidos), 2 `answerable` graficables de un solo
documento (uno sobre AGN-007 con ≥ 3 años distintos en el pasaje, otro con
magnitudes y unidad sobre AGN-003 en calibración y AGN-013 en validación),
2 `unanswerable` (uno fuera de corpus y uno con premisa falsa), 1 `ambiguous`
con referente ausente y un grupo conversacional completo de dos turnos cuyo
seguimiento exige la misma evidencia multi-documento del turno 1.

`tests/test_concept_banks.py` comprueba el contrato (JSONL válido, 12 casos,
ids `CON-CAL-`/`CON-VAL-` únicos dentro y entre bancos, `expected_documents`
dentro del catálogo y según el `kind`, grupo conversacional completo con
`subject` en el turno ≥ 2) y los mínimos de la spec (≥ 6 multi-documento,
≥ 2 graficables con etiqueta `graficable` —uno `AGN-007` y otro `AGN-003` o
`AGN-013`—, ≥ 2 turnos de conversación). La correspondencia pregunta-evidencia
no es comprobable sin corpus: queda documentada en la tabla anterior.
