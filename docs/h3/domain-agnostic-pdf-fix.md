# Corrección tras ingerir un PDF ajeno al dominio

Fecha: 2026-10-01. Esta revisión sucede a `colloquial-retrieval-fix.md`; sus resultados describen la versión anterior.

## Problemas reproducidos

Se publicó un PDF enciclopédico sin relación con el corpus técnico (*Abeja europea (Apis mellifera)*, 11 páginas). Las trazas guardadas en PostgreSQL permitieron reproducir seis fallos:

1. **Pérdida silenciosa de tablas.** El modo *legacy* de `pymupdf4llm` eliminaba por completo las tablas de desarrollo por casta (páginas 3 y 4), el cuadro taxonómico (página 1) y un pie de figura (página 11), sin ningún diagnóstico. La pregunta sobre la pupa del zángano recibió una respuesta con cita sobre el desarrollo general de la obrera y la explicación «aproximadamente una semana (casi 7 días)». La tabla original indica 14½ días.
2. **Explicaciones con datos añadidos.** El verificador semántico aceptó «de dos a cuatro años» para la vida de la reina (el pasaje dice «tres años»). También aceptó «casi 7 días» y cifras de reina y zángano ausentes del pasaje citado.
3. **Fragmentos cortados.** El troceado cortaba exactamente en el límite de 900 bytes, a mitad de palabra o de enlace Markdown.
4. **Calibración inestable y chat bloqueado.** En la política nueva, el caso `EVAL-A002` respondió con el documento correcto, pero cubrió dos de sus tres apartados esperados (`recall10` = 0,67). La regla exigía `recall10 = 1` en toda fila aceptada, así que ese caso invalidó todos los umbrales inferiores: −1,29 pasó a 0,10. Además, cualquier publicación cambiaba la firma del corpus y dejaba el chat en abstención hasta recalibrar.
5. **Falso negativo coloquial.** En «los zánganos pican?», el candidato n.º 2 era «Los zánganos no poseen aguijón», pero la suficiencia se abstuvo.
6. **Seguimiento mal reformulado.** Tras «¿Cuántos días tarda en desarrollarse una abeja obrera?», «¿Y la reina?» se reformuló como la *primera* pregunta de la conversación («¿Quién clasificó a la abeja europea…?»), perdiendo «reina».

## Cambios

- **Conversión PDF** (`converters.py`). Tras `pymupdf4llm`, cada página se contrasta con su texto original:
  - Las tablas detectadas cuyo texto falta se reconstruyen asignando cada palabra a la columna de su cabecera por coordenadas. Las celdas combinadas de PyMuPDF repetían el texto completo en cada celda.
  - Las líneas de texto ausentes se recuperan como párrafos inertes. Las líneas cortas exigen coincidencia exacta de su secuencia de palabras; las largas toleran diferencias menores, como una «o» convertida en viñeta.
  - El contenido situado por encima del primer bloque convertido se inserta al principio de la página, para heredar el apartado de la página anterior.
  - Diagnósticos visibles en la revisión: `pdf_tables_recovered_page_N`, `pdf_text_recovered_page_N` y, si la cobertura de palabras sigue por debajo del 97 %, `pdf_text_loss_page_N`.
- **Verificación de respuestas** (`chat.py`):
  - Control determinista: toda cifra de una explicación debe figurar en su pasaje (o en el título y los apartados), y las de la explicación general, en alguno de los pasajes citados. Se reconocen dígitos, números en palabras («veintiún», «treinta y dos») y fracciones («14½»).
  - El incumplimiento (`unsupported_number`) activa la alternativa de extractos literales, igual que `grounding_rejected`.
  - Los *prompts* de generación y verificación enumeran como hechos añadidos las cifras, rangos, conversiones de unidades, causas, comparaciones y datos atribuidos a otro sujeto.
- **Troceado** (`chunking.py`). Dentro del presupuesto, el corte prefiere salto de línea, final de frase y espacio, buscando primero en la segunda mitad. Nunca corta dentro de un enlace Markdown o una URL, salvo que un único token supere el presupuesto. La cobertura textual se sigue comprobando al indexar. La biblioteca se reindexó con este troceado.
- **Calibración** (`evaluation.py`, `retrieval.py`):
  - Un umbral solo es inseguro por respuestas indebidas o por evidencia sin los documentos esperados (`document_recall10 < 1`). La cobertura de apartados se publica como métrica (`accepted_locator_recall10`), pero no desplaza el umbral.
  - Cada política guarda la versión y la visibilidad de cada documento calibrado (`corpus_members`). Si el corpus cambia solo porque se añaden o retiran otros documentos, se hereda la última política aprobada del mismo ámbito y la misma firma. La decisión lo indica (`policy_inherited`) y la administración muestra «Calibración heredada».
  - Cambiar la versión o la visibilidad de un documento calibrado sigue exigiendo recalibrar. La evaluación de cobertura por pregunta sigue decidiendo cada respuesta.
- **Suficiencia** (`sufficiency.py`, versión `h4-sufficiency-v4-direct-implication-subject`):
  - Una pregunta de sí/no queda cubierta si un pasaje afirma un hecho que la resuelve de forma inmediata («no poseen aguijón» → no pican), sin encadenar inferencias ni usar conocimiento externo.
  - Un dato general o de otro sujeto no cubre una pregunta sobre un sujeto concreto.
  - Las tablas se usan respetando su correspondencia entre fila y columna.
- **Aclaración determinista** (`query.py`). Un posesivo o demostrativo sin sustantivo previo («Necesito cambiar sus parámetros») exige aclaración antes de mostrar títulos de la biblioteca al clasificador, porque esos títulos podían aportar un referente inexistente.
- **Seguimientos** (`chat.py`, `query.py`):
  - La reformulación recibe explícitamente `last_user_question`, con un ejemplo de pregunta elíptica, y las respuestas previas se truncan a 300 caracteres.
  - Si la consulta reformulada omite palabras con contenido de la pregunta nueva, se reintenta indicando cuáles. No se exigen las palabras que una reformulación fiel sustituye: referencias resueltas («ese documento», «esa guía») y palabras de secuencia («inmediatamente después»).
  - Una pregunta dependiente del contexto (empieza por «Y», contiene una referencia o tiene una sola palabra con contenido) debe incorporar al menos un término del historial. Así se rechazan el eco sin cambios y el relleno con texto de las instrucciones, que el modelo produjo de forma intermitente tras actualizar litellm.
  - Se hacen como máximo tres intentos; si ninguno cumple, se conserva la pregunta original y las fases de aclaración y evidencia la tratan.

Los cambios de *prompt*, de versión de suficiencia y de contrato de seguimiento forman parte de la firma de política; las políticas previas dejan de aplicarse.

## Verificación

- **Pruebas automáticas.** El API pasa 116 pruebas, incluidas las nuevas de `tests/test_domain_agnostic.py`: tablas con y sin pérdida, texto recuperado, cortes, cifras, umbral, herencia de política, referentes y seguimientos. La web pasa TypeScript y 18 pruebas Playwright de escritorio y móvil; las 6 omitidas son las del modo Compose.
- **Conversión real del PDF.** La tabla del zángano queda como `| Zángano | 3 días | 6½ días | 10 días | 14½ días | 24 días | aprox. 38 días |`, con diagnósticos de tablas reconstruidas (páginas 3 y 4) y texto recuperado (páginas 1, 5 y 11). Tras reindexar, ningún fragmento de los 169 corta a mitad de palabra ni de enlace. Se reindexó toda la biblioteca: 14 documentos, sin fallos.
- **Calibración** con los bancos coloquiales de `colloquial-retrieval-fix.md`:

| Resultado | Administrador | Usuario |
| --- | ---: | ---: |
| Umbral | −1,8354 | −2,2028 |
| Positivos aceptados en validación | 23 de 23 | 23 de 23 |
| Respuestas indebidas en validación | 0 | 0 |
| Negativos correctos en validación | 8 de 8 | 8 de 8 |
| Aclaraciones correctas, ambos bancos | 100 % | 100 % |
| Cobertura media de apartados aceptados | 0,989 | 0,982 |

  En administrador, un caso de calibración (`COL-calibration-A001`) agotó el tiempo del proveedor. Se reevaluó solo ese caso desde el *checkpoint*, sin cambiar *prompts*, corpus ni criterio. Una calibración intermedia se rechazó porque el caso ambiguo `VAL2-M002` («Necesito cambiar sus parámetros») recibía referente desde los títulos de la biblioteca; de ahí la salvaguarda determinista de referentes. Otra intermedia perdía dos seguimientos válidos («En ese documento, ¿cómo se exporta?»), lo que motivó los ajustes de reformulación descritos arriba.
- **Chat real.** Pasan los 13 casos de `scripts/h4/colloquial_acceptance.py` como administrador. Casos de la abeja:
  - «¿Cuántos días dura la fase de pupa de un zángano?» → «14½ días» con cita de la tabla.
  - «los zánganos pican?» → extractos literales que incluyen «Los zánganos no poseen aguijón».
  - «¿Y la reina?», tras la pregunta sobre la obrera → «¿Cuántos días tarda en desarrollarse una abeja reina?», 16 días.
  - «¿Por qué las abejas reinas viven solo tres meses?» (premisa falsa) → abstención.
  - En las respuestas publicadas no aparecen cifras ausentes de los pasajes citados.
- **Operación.** Durante la validación, la unidad del disco de Docker Desktop se llenó y el motor quedó en solo lectura. Se reinició el disco de Docker; los datos de PostgreSQL y de los documentos residen en `BIB_DATA_DIR` y se conservaron. Al descargarse de nuevo la imagen `litellm:main-stable` cambió su versión (1.103.2), y con ella apareció el eco intermitente de las reformulaciones.

## Límites

La reconstrucción de tablas depende de que PyMuPDF detecte la tabla y su fila de cabecera. Las tablas sin cabecera reconocible se recuperan como texto, sin estructura de columnas. Las líneas de una o dos palabras repetidas en otro lugar de la página pueden darse por presentes. El control de cifras no detecta hechos no numéricos añadidos; esos siguen dependiendo del verificador semántico. Heredar una política conserva un umbral calibrado sin los documentos nuevos; conviene recalibrar para incluirlos en la evaluación. Las primeras preguntas no se traducen: «How long does a queen bee live?» como primer turno se abstiene por puntuación, mientras que como seguimiento se reformula en español. La reformulación sigue dependiendo del modelo; los controles deterministas rechazan sus fallos detectables y, si persisten, conservan la pregunta original. La imagen de litellm usa la etiqueta móvil `main-stable`, así que una nueva descarga puede cambiar su comportamiento.
