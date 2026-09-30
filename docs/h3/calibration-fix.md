# Corrección de suficiencia y calibración de la biblioteca

Fecha: 2026-09-30. Los informes iniciales de H3 y de su revalidación con H4 se conservan como antecedentes.

## Problema confirmado

El reranker asignaba 3,797647 a `EVAL-M002`, una pregunta que necesita identificar la rama antes de decidir cuál borrar. El umbral 2,052673 la admitía y no admitía ningún positivo de validación. Además, la biblioteca real tenía nueve documentos sin versión activa y ninguna fuente H0 publicada: el corpus temporal de evaluación no podía habilitar su chat.

## Corrección aplicada

- Se publican las 13 fuentes H0 mediante la API normal de revisión/indexación, con autorización del usuario. Se verifican SHA-256 del original, igualdad exacta de la conversión Markdown, ausencia de diagnósticos y límites de localizadores. No se modifican ni eliminan los nueve documentos ajenos al catálogo. La base real contiene 13 documentos y 1.448 fragmentos activos.
- Se clasifica la claridad de la pregunta sin mostrar fuentes al modelo. Las preguntas ambiguas reciben una petición fija de contexto sin respuesta factual ni citas; el mensaje se conserva como `abstained`, con motivo `clarification_required`.
- Las preguntas claras pasan una evaluación de cobertura completa y contradicciones. El modelo selecciona identificadores y el servidor conserva sus pasajes originales. La salida JSON se restringe por esquema y referencias válidas, y se valida otra vez en la API. Las decisiones usan temperatura cero.
- Solo una evaluación positiva puede superar el umbral empírico de una política aprobada para su corpus, configuración y ámbito. La firma de suficiencia cambia sin invalidar vectores. No se reutilizan políticas anteriores, administrativas para usuarios, ni consultas filtradas.
- Fallos del proveedor, respuestas truncadas, JSON inválido, resultados incoherentes o referencias inexistentes producen abstención. La calibración informa sus motivos de rechazo y no se aprueba si hay errores.

## Separación de evaluación

Las 24 preguntas originales de H0 forman el banco de calibración. El primer banco nuevo (`validation-v1.jsonl`, 24 preguntas) produjo 10 positivos de validación, cero respuestas indebidas y aclaración de los seis casos ambiguos entre ambos bancos. Se rechazó por seis errores de evaluación. Se conserva en `evaluation/h3/attempt-v1-admin.json`.

Los diagnósticos con los casos originales mostraron incumplimientos del esquema JSON, aun con finalización normal de la generación. La corrección impone salida estructurada al proveedor; los cinco errores originales diagnosticados se resolvieron. Después de ese cambio se reserva un segundo banco nuevo (`validation-v2.jsonl`, 24 preguntas); el primero no se reutiliza para aprobar la versión posterior. Las conversaciones completas permanecen en un único banco. Cada banco independiente debe cubrir las cuatro clases y sus mínimos de H0.

El primer ensayo con salida estructurada volvió a rechazarse por siete agotamientos del límite de 15 segundos, con nueve positivos y cero respuestas indebidas de validación. Se conserva en `attempt-v2-admin.json`. Se amplía el timeout del cliente y proxy a 60 segundos y el presupuesto de razonamiento a 2.000 tokens para claridad y 4.000 para suficiencia, manteniendo el límite global de 100 segundos del chat. No cambian prompts, etiquetas, partición ni selección del umbral al repetir ese banco por motivos operativos. El evaluador comprueba disponibilidad de proveedores antes de empezar; una repetición arrancada durante el reinicio del proxy se interrumpió sin publicar política. La firma incorpora esquemas, presupuestos y timeout para invalidar políticas de configuraciones anteriores.

El ensayo posterior alcanzó 12 positivos y cero respuestas indebidas de validación, pero siguió rechazado por una generación truncada de un seguimiento original (`attempt-v3-admin.json`). La comprobación de ese caso original con razonamiento bajo terminó sin errores. La configuración final utiliza `BIB_SUFFICIENCY_REASONING_EFFORT=low` solo en las decisiones estructuradas de claridad/suficiencia, y lo liga a la firma de política. Para proveedores que no admitan ese parámetro puede configurarse `disabled`, con nueva calibración. No se flexibilizan los rechazos por truncación ni se ajusta el umbral al banco de validación.

Los seguimientos se reformulan con la misma función de H4 y las preguntas previas del usuario. Esto mide recuperación contextual y suficiencia, sin inventar respuestas previas del asistente como evidencia. La generación final y sus citas se comprueban separadamente con `scripts/h4/calibration_acceptance.py`.

## Verificación

Las políticas vigentes de administrador y usuario están aprobadas y verificadas mediante la API después del despliegue. Se evaluaron 48 consultas por ámbito (96 en total): 24 originales para calibrar y 24 nuevas para validar. El umbral elegido exclusivamente en calibración es 1,3823637962341309; es una puntuación del reranker, no una probabilidad.

| Resultado por ámbito | Administrador | Usuario |
| --- | ---: | ---: |
| Positivos aceptados en validación | 12 de 16 | 12 de 16 |
| Respuestas indebidas en validación | 0 | 0 |
| Errores del evaluador | 0 | 0 |
| Casos ambiguos con aclaración, ambos bancos | 6 de 6 | 6 de 6 |
| Estado de la política | Aprobada | Aprobada |

La calibración original conserva 5 positivos aceptados de 16 y cero respuestas indebidas. La cobertura es conservadora y difiere entre bancos; la aprobación no significa responder todas las preguntas que tienen respuesta.

El chat real ha pasado tres escenarios por rol: aclaración sin respuesta factual, abstención sin cobertura y respuesta fundamentada con citas y descarga del original. También pasó un seguimiento contextual administrativo, con nueva recuperación, respuesta validada y cinco citas. Los originales descargados se comprobaron por SHA-256. El resumen público está en `evaluation/h3/chat-validation.json`; la cuenta temporal de lector quedó desactivada y sus sesiones revocadas.

La generación final utiliza un esquema JSON que empareja cada identificador de cita con su pasaje literal, sin publicar texto antes de validarlo. El verificador semántico también usa salida estructurada y recibe los encabezados documentales originales para identificar apartados; estos no permiten completar hechos ausentes. Se mantienen los rechazos por afirmaciones no sustentadas y los controles finales de permisos y publicación.

- API: 83 pruebas pasadas; una advertencia heredada de Starlette/httpx. El sandbox de Windows impidió crear temporales; la suite aprobada se ejecutó con acceso permitido al directorio de pruebas.
- Después de los ajustes finales: 38 pruebas enfocadas de H3/H4/suficiencia, 27 de generación estructurada y 13 de H4 tras incorporar el contexto documental al verificador, todas pasadas.
- Web: TypeScript y builds API/web correctos; ocho pruebas Playwright de chat y sesión pasadas en escritorio y móvil contra Compose, con respuestas simuladas.
- Publicación real: 13 originales íntegros, conversiones exactas y 1.448 fragmentos activos. Los informes privados están en `.artifacts/h3/catalog-publication.json`.

Los informes de cada ámbito se guardan sin preguntas ni fragmentos en `evaluation/h3/library-calibration-admin.json` y `evaluation/h3/library-calibration-usuario.json`. Las trazas completas permanecen en PostgreSQL y los informes privados en `.artifacts/h3/`. Cambios de fuentes, visibilidad o configuración invalidan las políticas.

## Límites

El banco es pequeño, español y Markdown; no proporciona garantía estadística ni evalúa calidad pedagógica en todo el corpus. El juicio semántico depende del modelo: un esquema correcto y referencias válidas no prueban por sí solos suficiencia. Los requisitos de cero respuestas indebidas, localizadores completos y aclaraciones se verifican empíricamente; se conserva abstención fuera de los casos aceptados. El nuevo proceso añade dos inferencias locales a las preguntas claras. Se mantiene el timeout global de chat y los rechazos de citas y generación incompleta de H4.
