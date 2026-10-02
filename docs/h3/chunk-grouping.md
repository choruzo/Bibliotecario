# Agrupación de bloques pequeños al trocear (prioridad 3)

Fecha: 2026-10-02.

## Problema

`split_blocks` generaba un fragmento por cada bloque estructural de Markdown (párrafo, fila de tabla, encabezado, línea convertida de un PDF). En los PDF convertidos los bloques son muy cortos, así que los fragmentos quedaban muy por debajo del presupuesto de 900 bytes: la biblioteca publicada (30 documentos) tenía 7658 fragmentos con una media de 347 bytes (mediana 230) y 3490 por debajo de 200 bytes. La Constitución, por ejemplo, ocupaba 725 fragmentos de 229 bytes de media. Un encabezado suelto o un artículo de una línea apenas da contexto al embedding ni al reranker.

## Cambio

`chunking.group_blocks` une bloques consecutivos con el mismo `section_path` mientras el tramo completo (incluidas las líneas en blanco entre ellos) quepa en el presupuesto, descontado el prefijo de encabezados. Después, cada grupo se trocea con el mismo bucle de antes.

- Los cortes caen en los límites entre bloques. Un bloque que no cabe solo sigue su propio grupo y lo parte `break_point` como antes (nunca dentro de una palabra o un enlace).
- Una sección nueva siempre empieza fragmento: no se mezclan apartados distintos, de modo que el prefijo de encabezados de `search_content` sigue siendo exacto.
- El fragmento conserva todos los localizadores de origen que solapan sus líneas, de cualquier página. Si un bloque unido no tiene localizador de origen (HTML que el mapa estructural omite), aporta su propio localizador `normalized` sin página.
- `build_index` mantiene la comprobación de cobertura (`chunk_coverage_loss`) y la de tokens del embedding.
- Los bloques de navegación (líneas que solo son enlaces internos `[…](#…)`, como un índice de Word) no se agrupan. Ver «Primera iteración» más abajo.
- `CHUNK_BYTES` sigue en 900. A 1200 bytes la media subiría a 822, pero el contexto ampliado (60 fragmentos / 36.000 bytes) y el reranker están ajustados a 900, y el criterio de la prioridad ya se cumple sin subirlo.

## Medición del troceado (30 documentos publicados)

Medido offline sobre el Markdown normalizado y la `provenance` de cada versión activa, con el tokenizador real de nomic (`/tokenize` de `:8081`, con el prefijo `search_document: `).

| | Antes | Después |
| --- | ---: | ---: |
| Fragmentos | 7658 | 3852 |
| Bytes medios (`search_content`) | 347 | 624 |
| Bytes medios de contenido | — | 555 |
| Mediana | 230 | 738 |
| Fragmentos < 200 bytes | 3490 | 415 |
| Cortes a mitad de palabra | 0 | 0 |
| Cortes dentro de un enlace | 0 | 0 |
| Tokens máximos del embedding (límite 1000) | 584 | 584 |

Los fragmentos cortos que quedan son secciones con solo un encabezado o una línea, entradas de índice o colas de un bloque grande partido. Los tokens se midieron con la primera iteración (3810 fragmentos); la segunda solo separa líneas de índice, que no aumentan el máximo. El índice real tras reindexar coincide con la medición offline (3852 fragmentos, 624 bytes de media).

El indicador automático de enlaces partidos marcó unos 60 fragmentos, antes y después. Al reconstruir las posiciones de corte sobre el Markdown no hay ningún corte dentro de un enlace: eran falsos positivos por corchetes dentro del texto del enlace.

## Pruebas

- Nuevas: `test_small_blocks_of_one_section_are_grouped_with_all_locators` (agrupa, conserva los localizadores de todas las páginas y no mezcla secciones) y `test_table_of_contents_links_are_not_grouped_into_one_fragment`.
- Ajustadas, porque un documento mínimo («# Titulo / Texto original.») ahora es un único fragmento con encabezado y cuerpo:
  - `test_unmapped_html_is_preserved_as_inert_normalized_text` busca el localizador del rango HTML en lugar de suponer que va solo.
  - `test_context_expansion_keeps_exact_passages_in_the_same_revision` indexa un documento con dos secciones.
  - `test_rejected_paraphrase_can_publish_only_independently_verified_exact_passages` compara la cita en bloque línea a línea, porque el pasaje tiene varias líneas.

## Primera iteración: el índice como fragmento único

Tras reindexar con la agrupación sin excepciones, la calibración de administrador se aprobó (umbral −1,2895, 0 indebidas), pero el banco técnico empeoró en nDCG@10 (0,744 → 0,710), aunque mejoró en recall@10 (0,838 → 0,848).

La pérdida venía de `EVAL-A006` («¿Qué apartados incluye el flujo de análisis con SonarQube?»). Las métricas se calculan sobre los pasajes que la evaluación de cobertura selecciona como apoyo, y el modelo elegía siempre (3 de 3 repeticiones) el índice del documento: «Contenido» seguido de los títulos de los apartados con su número de página, todos ya en un solo fragmento. Ese fragmento encaja con cualquier pregunta sobre «apartados», pero no contiene los pasos del flujo. Cuatro documentos técnicos tienen índices de este tipo (Doors, Git, Header y SonarQube); ninguno del corpus agnóstico.

Corrección: las líneas que solo son un enlace interno quedan como fragmentos sueltos, como antes. Se reindexaron solo esos cuatro documentos (el troceado del resto no cambia) y se recalibró.

Tras la corrección, `EVAL-A006` pasa a abstenerse: el apartado correcto está entre los candidatos (recall@10 = 1), pero la evaluación de cobertura no lo da por completo. Es un falso negativo seguro y queda como caso pendiente.

## Resultados con el índice final

Repeticiones operativas: reindexado completo de 30 documentos (1298 s, 0 fallos), reindexado parcial de 4 (51 s) y tres calibraciones de unos 20 minutos (administrador dos veces, usuario una). Ninguna tuvo errores de proveedor.

### Calibración (bancos técnico y agnóstico combinados)

| | Antes | Administrador | Usuario |
| --- | ---: | ---: | ---: |
| Aprobada | sí | sí | sí |
| Umbral | −1,2932 | −1,2895 | −1,2895 |
| Respuestas indebidas | 0 | 0 | 0 |
| Positivos aceptados en validación | 45/46 | 46/46 | 46/46 |
| Negativos correctos en validación | 17/17 | 17/17 | 17/17 |
| Positivos aceptados en calibración | 44/47 | 44/47 | 44/47 |
| Cobertura media de apartados aceptados | 0,972 | 0,978 | 0,978 |

Positivos rechazados en calibración: antes `EVAL-A008`, `EVAL-A009` y `EVAL-C002-T3`; ahora `EVAL-A006` (ver arriba), `EVAL-A009` y `EVAL-C002-T3`. `EVAL-A008` pasa a aceptarse.

### Ranking por banco (respondibles y seguimientos con apartados esperados; ambos ámbitos dan lo mismo)

| Banco | recall@5 | recall@10 | MRR@10 | nDCG@10 |
| --- | --- | --- | --- | --- |
| Técnico, antes | 0,792 | 0,838 | 0,883 | 0,744 |
| Técnico, después | 0,825 | **0,879** | 0,898 | **0,750** |
| Agnóstico, antes | 0,967 | 0,967 | 1,000 | 0,911 |
| Agnóstico, después | 0,978 | 0,978 | 1,000 | 0,931 |

Mejoras destacadas: `EVAL-C002-T3` (recall@10 0 → 0,67), `AGN-CAL-C001-T1` y `AGN-CAL-C002-T1` (0,5 → 1). Retroceso: `AGN-CAL-C002-T3` (1 → 0,5), aunque se sigue respondiendo correctamente.

### Aceptación de chat

- `colloquial_acceptance.py`: 13 de 13 (6 `grounded`, 2 `grounded_extract`).
- `agnostic_acceptance.py`, ambos bancos, administrador: **62 de 64** (antes 61), 0 indebidas, 0 cifras sin respaldo, 0 citas no literales. 34 `grounded` y 12 `grounded_extract` (antes 35 y 10). La pregunta translingüe «How long does a queen bee live?» (`AGN-VAL-A016`), que antes se abstenía, ahora se responde: el fragmento agrupado reúne la esperanza de vida de reinas y obreras. Los dos fallos que quedan son los conocidos `AGN-VAL-U002` y `AGN-VAL-U003` (aclaración en lugar de abstención).

### Efectos secundarios observados

- Al unirse con su párrafo, el encabezado de la sección forma parte del fragmento. En las respuestas extractivas la cita empieza a veces por «## Título», repetido bajo el encabezado en negrita que ya añade `extractive_answer`. Es correcto (la cita es literal), pero redundante.
- La latencia de recuperación por fase apenas cambia: búsqueda p50 109 ms (antes 232), reranking p50 483 ms (antes 344, porque los pasajes son más largos) y suficiencia p50 4,6 s (antes 4,0).
