# Método de evaluación de H0

## Propósito

El banco separa calidad de conversión, recuperación, suficiencia y conversación. H0 define el protocolo y datos iniciales; H2 medirá conversión y H3 calibrará recuperación y abstención con resultados observados.

## Corpus y privacidad

El catálogo versionado contiene nombres, hashes y métricas estructurales, nunca texto extraído. Las variantes y sus manifiestos viven en `.artifacts/h0/` porque reproducen contenido del corpus. El banco de preguntas no incluye respuestas esperadas, credenciales, direcciones, nombres de usuario, fragmentos ni configuraciones internas; identifica únicamente documento y encabezado esperados.

## Clases de casos

- `answerable`: la respuesta debe apoyarse en uno o más localizadores esperados.
- `unanswerable`: ninguna fuente del corpus debe bastar y el sistema debe abstenerse.
- `ambiguous`: falta una elección material; el sistema debe pedir aclaración o enumerar interpretaciones sin inventar.
- `conversation`: varios turnos prueban elipsis y referencias; cada turno informativo vuelve a recuperar.

Cada caso tiene ID estable, idioma, consulta, comportamiento esperado y etiquetas. Los casos conversacionales comparten `conversation_id` y un `turn` creciente.

## Comparación de variantes

La generación seleccionada cubre tres perfiles: documento con tablas, documento con bloques de código y documento procedimental con listas. Para cada salida se registra el SHA-256 del Markdown de origen, del archivo generado y del texto extraído.

Las comparaciones normalizan Unicode, espacios y saltos de línea antes de calcular:

- `token_recall`: proporción de tokens del origen presentes en la extracción, con multiplicidad;
- `heading_recall`: proporción de encabezados reconocibles conservados;
- `structure_recall`: cobertura de bloques de código, elementos de lista y filas de tabla;
- `order_ratio`: similitud del orden textual mediante `SequenceMatcher`;
- páginas para PDF y párrafos/tablas para DOCX.

Puertas iniciales de H0 para los fixtures generados:

| Métrica | PDF | DOCX |
|---|---:|---:|
| `token_recall` | >= 0.90 | >= 0.94 |
| `heading_recall` | >= 0.90 | >= 0.95 |
| `order_ratio` | >= 0.75 | >= 0.82 |

Estas puertas validan el generador de fixtures, no la calidad final del extractor de H2. La comparación registra advertencias estructurales sin ocultarlas tras una media.

## Métricas de H3

- Recuperación: Recall@5 y Recall@10 por documento/localizador; MRR@10; nDCG@10.
- Suficiencia: precisión, exhaustividad y F1 de `responder`; tasa de respuesta indebida en `unanswerable`.
- Ambigüedad: exactitud de la decisión `aclarar`.
- Conversación: Recall@10 por turno y proporción de turnos informativos con recuperación registrada.
- Rendimiento: p50, p95 y máximo separados para embedding, búsqueda, fusión y reranking.

No se aprueba un umbral si mejora la cobertura a costa de respuestas indebidas no revisadas. Los resultados se desglosan por clase, idioma, formato y documento.

## Criterio de salida de H0

- 13 fuentes catalogadas y verificables por hash.
- Al menos 24 casos: 10 respondibles, 5 no respondibles, 3 ambiguos y 6 turnos conversacionales.
- Tres fuentes representativas generan PDF y DOCX con manifiesto trazable.
- Todos los artefactos generados superan las puertas de comparación o quedan como fallo explícito.
- La configuración de modelos declara contrato, dimensión/contexto conocido y fecha de observación sin secretos.
