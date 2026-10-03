# Llamadas al LLM y latencia del chat (prioridad 5)

Fecha: 2026-10-03.

## Instrumentación

Antes de cambiar nada se midió dónde se va el tiempo. `providers.py` registra cada llamada al LLM con su fase (`rewrite`, `intent`, `assessment`, `generation`, `verification`), su latencia y los tokens que informa vLLM; en `stream_generate` se piden con `stream_options.include_usage`. El chat guarda en cada `RetrievalRun`:

- `llm`: número de llamadas y, por fase, llamadas, milisegundos y tokens, más la traza completa;
- `chat_latency`: `rewrite_ms`, `generation_ms`, `verification_ms` y `total_ms`, que completan `latency` (embedding, búsqueda, fusión, reranker y suficiencia).

`/admin/retrieval/search`, que usa la calibración, guarda también `llm`. `agnostic_acceptance.py` resume la latencia p50/p95 (rango más próximo, sin interpolar) de todos los turnos, de las respuestas y de las abstenciones, y las llamadas por fase; `colloquial_acceptance.py` imprime el mismo resumen.

## Medición inicial

Aceptación coloquial (13/13): media de 4,77 llamadas por turno. En la agnóstica (62/64; `evaluation/h3/agnostic-acceptance-admin-p5-before.json`), 3,95.

| Fase | Llamadas (agnóstica) | Media | Tokens típicos |
| --- | ---: | ---: | --- |
| Intención | 72 | 0,23 s | 520 de entrada, 6 de salida |
| Evaluación de cobertura | 56 | 4,9 s | 12.000-13.700 de entrada, 20-360 de salida |
| Generación | 46 | 11,1 s | hasta 2.306 de salida (`cisco-install`, 61 s) |
| Verificación por afirmación | 71 | 0,29 s | en paralelo |
| Reformulación | 8 | 0,57 s | |

La latencia no depende del número de llamadas, sino de los **tokens decodificados** (unos 37 tokens/s con salida estructurada):

- La generación copiaba cada pasaje completo en `quote` (un `const` del esquema que el modelo decodifica token a token) antes de escribir su explicación.
- En la evaluación, casi toda la salida son los `chunk_id` de `support` (UUID de unos 25 tokens cada uno).
- La intención cuesta 0,23 s. Fusionarla con la evaluación, como proponía el plan, ahorraría como mucho 0,25-0,5 s por turno.

## Decisiones

- **No se fusionan intención y suficiencia.** La intención se separó a propósito (`colloquial-retrieval-fix.md`): decide si la pregunta es clara viendo solo la pregunta y, si acaso, títulos y apartados, nunca el texto de los pasajes, para que un documento no pueda hacer pasar por clara una pregunta ambigua. Una llamada fusionada tendría que ver los pasajes. En su lugar, **la evaluación se lanza en paralelo con la intención** (`asyncio.create_task`): la intención sigue sin ver los pasajes y, si la pregunta es ambigua, la evaluación se cancela, de modo que la aclaración sigue siendo inmediata. El número de llamadas no cambia, pero la latencia de la intención queda oculta.
- **La generación ya no copia los pasajes.** El esquema solo pide `citation_id` (`const`) y `explanation` por pasaje. `attach_quotes` añade en el servidor el pasaje exacto de cada marcador antes de `validate_answer`, que mantiene todos sus controles (marcador conocido, cita idéntica, cifras, todos los pasajes en orden y verificación por afirmación). Una cita escrita por el modelo, si el proveedor ignorase el esquema, se sigue comparando.
- **Los seguimientos autónomos no se reformulan.** `standalone` (`query.py`) trata como primer turno, con `normalize_query` y sin LLM, un seguimiento que no muestra ninguna señal de dependencia: elipsis o referencias (`needs_context`), conectores iniciales y pronombres (también en inglés), elipsis nominal («el de Wikipedia»), palabras que una reformulación sustituye («ese documento», «después») o cualquier palabra de contenido compartida con el historial. Es conservador a propósito: todos los seguimientos de los bancos se siguen reformulando y lo que se ahorra es la reformulación de las preguntas que cambian de tema. `needs_context` por sí solo no basta: «¿Cuántas palabras tiene el de Wikipedia?» no lo activa.

## Intento descartado: identificadores cortos en la evaluación

Para recortar la salida de la evaluación se probaron identificadores más cortos que el UUID. Cada variante obligó a recalibrar los dos ámbitos:

| Variante | Positivos de validación aceptados | Indebidas |
| --- | ---: | ---: |
| UUID (antes) | 46/46 | 0 |
| `S1`…`S60` con el *prompt* ajustado | 43/46 | 0 |
| Prefijo hexadecimal de 8 caracteres, *prompt* original | 44/46 | 0 |
| UUID con los cambios finales | **45/46** | 0 |

Al repetir la evaluación fuera del chat con los mismos candidatos (5 casos, 3 repeticiones), las decisiones son deterministas y cambian solo por el formato: con `S<n>`, 4 de 5 pasan de `answer` a `abstain`; con el prefijo hexadecimal, 2 de 5 cambian. Un modelo de 12B decide los casos límite de cobertura de forma sensible a detalles de formato. El ahorro (de 4,9 a 3,8 s de media) no compensaba perder positivos, así que la evaluación conserva el UUID.

## Resultados

Medición final con el reranker en GPU y las políticas recalibradas.

### Aceptación agnóstica (ambos bancos, administrador)

| | Antes | Después |
| --- | ---: | ---: |
| Correctas | 62/64 | 62/64 |
| Respuestas indebidas / cifras sin respaldo | 0 / 0 | 0 / 0 |
| `grounded` / `grounded_extract` | 43 / 3 | **45 / 1** |
| Todos los turnos, p50 / p95 | 13,2 / 29,3 s | **7,3 / 12,3 s** |
| Respuestas, p50 / p95 | 14,5 / 30,8 s | **8,0 / 13,1 s** |
| Abstenciones y aclaraciones, p50 / p95 | 4,3 / 5,3 s | 4,5 / 5,1 s |
| Generación, p50 / p95 | 8,1 / 21,3 s | **1,7 / 4,7 s** |
| Suficiencia (intención y evaluación), p50 / p95 | 4,7 / 7,5 s | 4,5 / 6,6 s |
| Llamadas al LLM por turno | 3,95 | 3,91 |

Los dos fallos siguen siendo `AGN-VAL-U002` y `AGN-VAL-U003` (piden aclaración en lugar de abstenerse). El único recurso al extracto es `AGN-CAL-A002`: la explicación añade la cifra 4, el mismo caso de antes. Entre las respuestas que pasan a `grounded`, las de `AGN-CAL-A009`, `AGN-CAL-C002-T1` y `AGN-VAL-C003-T1` se revisaron a mano: todas sus cifras («16 de noviembre de 2013», «tres años después», «cuatro ocasiones», «80 %/10 %/10 %») están en su pasaje.

La intención tarda ahora 2,5 s de media frente a 0,23 s, porque comparte la GPU con el *prefill* de la evaluación (unos 12.000 tokens). Al ir en paralelo no alarga el turno: la suficiencia baja de 4,7 a 4,5 s de p50.

En una ejecución intermedia, con los prefijos hexadecimales, la generación sin copia dio 39 `grounded` / 6 `grounded_extract`: 3 explicaciones añadían cifras de otros pasajes. Los controles las detectaron y se publicaron como extractos. Esos recursos al extracto dependen de qué pasajes se seleccionen, así que conviene vigilarlos en las próximas mediciones.

### Aceptación coloquial (administrador)

| | Antes | Después |
| --- | ---: | ---: |
| Correctas | 13/13 | 13/13 |
| `grounded` / `grounded_extract` | 6 / 2 | 7 / 1 |
| Respuestas, p50 / p95 | 23,0 / 75,5 s | **12,3 / 35,1 s** |

`cisco-install` (10 pasajes) sigue siendo el peor caso: 35 s, frente a 75 s antes, y recurso al extracto porque el verificador rechaza 1 de 10 afirmaciones.

### Calibración (bancos técnico y agnóstico)

| | Administrador | Usuario |
| --- | ---: | ---: |
| Aprobada / umbral | sí / −1,2895 | sí / −1,2895 |
| Positivos de validación aceptados | 45/46 (antes 46) | 45/46 (antes 46) |
| Respuestas indebidas / negativos correctos | 0 / 17 de 17 | 0 / 17 de 17 |
| Aclaraciones correctas | 100 % | 100 % |

Cambios de decisión: `EVAL-A006`, el falso negativo pendiente de la prioridad 3, pasa a responderse; `VAL2-A008` pasa a abstenerse (falso negativo seguro). En usuario, `VAL2-U002` pide aclaración en lugar de abstenerse, sin efecto en la decisión.

## Validación y repeticiones operativas

- API: 125 pruebas (antes 123). Nuevas: `test_generation_does_not_copy_passages_but_answers_carry_the_exact_quote` y `test_complete_follow_ups_on_a_new_topic_skip_the_rewrite`. `test_intent_sees_titles_but_not_document_instructions…` comprueba ahora, con la evaluación en curso, que las llamadas de intención no contienen el texto de los pasajes y que la evaluación se cancela.
- Raíz: 8 pruebas. Web: `tsc` sin errores. Playwright: 18 aprobadas y 6 omitidas (modo Compose).
- Cuatro rondas de calibración de los dos ámbitos. El sistema se quedó sin memoria dos veces y Claude Code detuvo las tareas: una calibración se reanudó con `--resume` y una aceptación se repitió.
- **Reranker en CPU.** Al reiniciar los modelos, el reranker de `:8082` se relanzó sin `-Gpu` (`start_rerank.ps1`) y pasó de 0,5 a 20,5 s por consulta. Además, sus puntuaciones difieren unas centésimas de las de la GPU, lo bastante para reordenar candidatos vecinos y cambiar decisiones límite de la evaluación (comprobado con `AGN-VAL-A013`). Se relanzó con `-Gpu` y se recalibró. Lanza siempre el reranker con `-Gpu`, o con `start_all.ps1`, y calibra con la misma configuración que usa el chat.
