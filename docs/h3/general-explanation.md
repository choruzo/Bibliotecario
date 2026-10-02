# Eliminación de la «explicación general» y verificación por afirmación (prioridad 4)

Fecha: 2026-10-02.

## Problema

La respuesta generada tenía dos partes: una explicación por cada pasaje citado y una «explicación general» libre, sin cita. Esa segunda parte era la vía por la que se colaba contenido no respaldado (por ejemplo, «la larva recibe alimento especializado»). Además, muchas respuestas acababan en `grounded_extract`, el recurso seguro a los extractos literales, sin que se supiera por qué: el motivo del rechazo no se guardaba.

## Instrumentación

`chat_outcome` registra ahora `fallback` cuando una respuesta cae a `grounded_extract`: el motivo (`grounding_rejected`, `incomplete_answer` o `unsupported_number`) y su detalle (qué afirmaciones rechaza el verificador, cuántos pasajes se usaron frente a los seleccionados, o qué cifras se añadieron y dónde). `agnostic_acceptance.py` resume esos motivos en `fallbacks`.

## Medición inicial

Con la instrumentación desplegada y sin cambiar el comportamiento: `agnostic_acceptance.py`, ambos bancos, administrador (`evaluation/h3/agnostic-acceptance-admin-p4-before.json`). 62 de 64, 0 indebidas, 0 cifras sin respaldo. 31 `grounded` y 15 `grounded_extract`.

| Motivo del recurso al extracto | Casos |
| --- | ---: |
| Verificador: `supported=false` y `general_safe=false` | 6 |
| `incomplete_answer`: el modelo omite pasajes seleccionados | 4 |
| Verificador: solo `general_safe=false` | 2 |
| Cifra no respaldada en la explicación general | 2 |
| Cifra no respaldada en una explicación de cita | 1 |

En las 31 respuestas `grounded`, la explicación general se limitaba a repetir lo que ya decían las explicaciones por cita, y a veces añadía matices que no estaban en el pasaje («el nombre del lenguaje está vinculado a la preferencia del creador…»). Aportaba poco y causaba al menos 4 de los 15 recursos al extracto.

## Cambios

1. **Sin explicación general.** El *prompt* y el esquema de generación solo admiten `evidence`. `validate_answer` rechaza (`invalid_answer`) cualquier campo adicional, de modo que cada frase de la respuesta va ligada a un pasaje y pasa por sus controles: cifras presentes en el pasaje y verificación semántica. El verificador ya no evalúa `general_safe`. La web sigue mostrando aparte la sección «Explicación general» de los mensajes antiguos que la tengan.
2. **Todos los pasajes seleccionados, en orden.** Los pasajes que recibe la generación son el `support` que la evaluación de cobertura seleccionó como evidencia completa, y `validate_answer` ya exigía usarlos todos. El esquema lo impone ahora con `prefixItems` (`items: false` y `minItems = maxItems` igual al número de pasajes), en lugar de descubrir la omisión después. Se comprobó que vLLM respeta `prefixItems` incluso cuando el *prompt* pide omitir pasajes. El control `incomplete_answer` se mantiene como salvaguarda.
3. **Verificación por afirmación.** Primera medición tras los cambios 1 y 2 (`…-p4-after.json`): 39 `grounded` y 7 `grounded_extract` en el banco agnóstico, pero en la aceptación coloquial se pasó de 6 a 4 `grounded`. Al repetir esos casos fuera del chat, el verificador rechazaba el conjunto de afirmaciones de git y cantata aunque aceptaba cada una por separado. En git ocurría lo mismo con el esquema anterior, así que el fallo era del verificador (un modelo de 12B auditando varias afirmaciones en una sola llamada) y no de `prefixItems`. El contrato ya era «cada afirmación se deduce de su pasaje», así que ahora se audita cada afirmación en una llamada propia, todas en paralelo (`asyncio.gather`; vLLM las procesa en lote). Si se rechaza alguna, se registra cuáles (`rejected`) y se recurre al extracto.

`SYSTEM` y el verificador no forman parte de `policy_signature`, así que no hace falta recalibrar.

## Resultados

### Aceptación agnóstica (ambos bancos, administrador)

| | Antes | Cambios 1 y 2 | Final |
| --- | ---: | ---: | ---: |
| Correctas | 62/64 | 62/64 | 62/64 |
| Respuestas indebidas | 0 | 0 | 0 |
| Cifras sin respaldo | 0 | 0 | 0 |
| `grounded` | 31 | 39 | **43** |
| `grounded_extract` | 15 | 7 | **3** |
| Latencia p50 / p95 (respuestas) | 15,6 / 25,9 s | 17,0 / 29,5 s | 14,7 / 29,5 s |

Los dos fallos son los conocidos `AGN-VAL-U002` y `AGN-VAL-U003` (piden aclaración en lugar de abstenerse). Recursos al extracto finales:

- `AGN-CAL-A002`: la explicación añade la cifra 4, que no está en el pasaje.
- `AGN-CAL-A005`: la única afirmación es rechazada por el verificador.
- `AGN-CAL-C001-T1`: el verificador rechaza la afirmación 3 de 3.

Revisión manual de las respuestas que pasan a `grounded` con la verificación por afirmación (`AGN-CAL-A009`, `AGN-CAL-C001-T2`, `AGN-VAL-A010`, `AGN-VAL-A013` y `AGN-VAL-C003-T2`): todas las afirmaciones están en su pasaje, incluidas las cifras y los matices («no podrá ser inferior, en ningún momento del ejercicio presupuestario, al mínimo legal»). Ninguna respuesta contiene explicaciones de relleno («el pasaje no es relevante»).

### Aceptación coloquial (administrador)

| | Antes (`chunk-grouping.md`) | Cambios 1 y 2 | Final |
| --- | ---: | ---: | ---: |
| Correctas | 13/13 | 13/13 | 13/13 |
| `grounded` | 6 | 4 | 6 |
| `grounded_extract` | 2 | 4 | 2 |

Recursos al extracto finales: `cisco-install` (1 afirmación rechazada de 10) y `sonar` (la primera afirmación resume una secuencia de 8 pasos y añade elementos de otros pasajes; el rechazo es correcto).

### Efectos secundarios

- Cuando varios pasajes seleccionados dicen lo mismo, la respuesta lo repite en cada explicación (p. ej., «340M de parámetros» tres veces en `AGN-CAL-A015`). Es el precio de explicar todos los pasajes que la evaluación de cobertura seleccionó.
- Más llamadas al LLM: una de verificación por afirmación en lugar de una por respuesta. Al ir en paralelo, la latencia no empeora (p50 14,7 s frente a 15,6 s), pero la prioridad 5 debe tenerlo en cuenta.

## Validación

- API: 123 pruebas (antes 120). Nuevas: `test_answer_schema_requires_every_assessed_passage_once_in_order`, `test_answers_cannot_add_text_outside_the_cited_explanations` y `test_grounding_is_audited_claim_by_claim`. Ajustadas las que generaban `general` o simulaban `general_safe`.
- Raíz: 8 pruebas. Web: `tsc` sin errores. Playwright: 17 aprobadas y 6 omitidas en la primera ejecución, con un fallo intermitente en `workspace.spec.ts` (móvil, redirección de usuarios). Al repetir ese archivo 3 veces: 18 de 18. No se tocó la web.
- Repeticiones operativas: tres despliegues de `api` y `worker` y tres pasadas agnósticas de unos 17 minutos, sin errores de proveedor.
