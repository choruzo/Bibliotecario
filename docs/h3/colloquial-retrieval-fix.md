# Consultas coloquiales y recuperación de procedimientos

Fecha: 2026-09-30. Esta revisión sucede a `calibration-fix.md`; sus resultados describen la versión anterior.

## Problema reproducido

La traza `4307af43-a37d-46ba-b1e7-b20fa6987d10`, correspondiente a la pregunta sobre los pasos de instalación del Cisco, recuperó 30 candidatos. Sus primeros diez pertenecían a la guía de instalación del Catalyst y el primero contenía las instrucciones de conexión por consola. La clasificación de intención, sin contexto documental, devolvió `ambiguous_question`. La búsqueda textual no produjo candidatos y el umbral tampoco habría admitido el primer resultado.

## Cambios

- La pregunta inicial se limpia de fórmulas de cortesía y faltas frecuentes mediante reglas deterministas. Conserva sus restricciones y no incorpora requisitos nuevos. El modelo se reserva para resolver seguimientos con historial; una reformulación truncada o una negativa del modelo conserva la pregunta original.
- PostgreSQL busca términos unidos mediante OR, descartando palabras conversacionales. La entrada no puede introducir operadores booleanos propios. El reranker sigue decidiendo la relevancia.
- Antes del reranking se amplía el contexto con fragmentos exactos de las mismas versiones/revisiones recuperadas. El presupuesto global es de 60 fragmentos y 36.000 bytes. Las guías pequeñas pueden aportar su recorrido completo; las grandes aportan vecinos de los fragmentos recuperados.
- La intención evalúa primero la pregunta sola, separando claridad de disponibilidad documental. Si no reconoce el tema, recibe títulos y apartados como datos no confiables, sin el cuerpo de los documentos. Puede reconocer el tema explícito en una guía sin exigir su título exacto. Las preguntas de configuración general o estimación de recursos sin alcance suficiente conservan la aclaración.
- La cobertura evalúa los fragmentos ampliados y selecciona hasta diez identificadores. La generación recibe únicamente esos pasajes, conservando sus citas exactas, la verificación semántica y las comprobaciones finales de vigencia y permisos.
- Si el verificador rechaza una paráfrasis o la generación omite pasajes seleccionados como necesarios, se ofrece una alternativa con todos los pasajes literales completos, ordenados por documento/localizador, encabezados originales y sin explicación general añadida. Se comprueba mecánicamente que cada pasaje y cada cita coincidan con la fuente; los controles finales de vigencia y permisos permanecen activos. Se presenta explícitamente como extractos, sin conservar la prosa rechazada. Su traza indica `grounded_extract` para distinguirla de una explicación generada. La identidad de un texto con su fuente no se delega a un juicio probabilístico del modelo.
- Las políticas incluyen el nuevo contrato y se recalibran por ámbito; los embeddings y los originales permanecen intactos. Las métricas de localizadores se calculan sobre los pasajes seleccionados para responder.

## Evaluación reproducible

Los bancos `evaluation/h3/colloquial-calibration-v1.jsonl` y `evaluation/h3/colloquial-validation-v1.jsonl` conservan los casos originales H0/VAL2 y añaden preguntas coloquiales independientes: 32 casos de calibración y 31 de validación. No se divide un grupo conversacional entre ambos bancos.

```powershell
.venv/Scripts/python.exe scripts/h3/calibrate_library.py --scope admin --calibration-bank evaluation/h3/colloquial-calibration-v1.jsonl --validation-bank evaluation/h3/colloquial-validation-v1.jsonl
.venv/Scripts/python.exe scripts/h3/calibrate_library.py --scope usuario --calibration-bank evaluation/h3/colloquial-calibration-v1.jsonl --validation-bank evaluation/h3/colloquial-validation-v1.jsonl
.venv/Scripts/python.exe scripts/h4/colloquial_acceptance.py
```

El script de chat prueba trece casos, incluido un seguimiento de Cisco. Comprueba estado, guía esperada, correspondencia literal de cada cita, marcadores y SHA-256 del original descargado. Para el ámbito usuario requiere credenciales de lector mediante `--credentials` y `--scope usuario`; las credenciales y los informes completos permanecen en `.artifacts/retrieval-fix/`, excluidos de Git.

La evaluación mantiene las abstenciones ante falta de documentación y las aclaraciones de objeto/alcance. Un banco pequeño y el juicio semántico del modelo no garantizan exactitud fuera de los casos evaluados.

## Resultados

Ambos ámbitos aprobaron la calibración con umbral `-1.2909311056137085`. En validación independiente, cada ámbito obtuvo 23 respuestas aceptadas y ocho casos negativos correctamente tratados, sin falsos positivos. En calibración permanecieron dos falsos negativos para administrador y tres para lector; entre ellos, una reformulación de seguimiento puede perder la restricción «otra guía» y provocar una abstención conservadora. Estos resultados no garantizan cobertura de todos los seguimientos.

La suite completa del API pasó 91 pruebas antes del último control de cobertura de la generación. La regresión final pasó 36 pruebas tras incorporarlo, con una advertencia de deprecación heredada de Starlette/httpx.

El chat final pasó los trece casos en cada rol: 26 comprobaciones satisfactorias. Respondió sobre instalación, consola y SSH de Cisco (incluido seguimiento), VMware, Git, Cantata y SonarQube; se abstuvo en dos consultas sin documentación y pidió aclaración en tres consultas ambiguas por rol. Las citas se contrastaron con los pasajes y con el SHA-256 de cada original descargado. La mayoría de las respuestas utilizaron la alternativa de extractos completos, por lo que su presentación es más literal que conversacional. El resumen reproducible está en `evaluation/h3/colloquial-chat-validation.json` y las preguntas/respuestas completas en `.artifacts/retrieval-fix/respuestas.md`. La cuenta temporal de lector se desactivó y sus sesiones se revocaron al terminar.
