# Validacion H2

Ensayo local de 2026-09-29 en Windows, Docker Compose y Chrome, con fuentes privadas verificadas por SHA-256. Los informes sin extractos y las capturas se conservan en `.artifacts/h2/`.

## Pipeline y regresiones

| Comprobacion | Resultado |
| --- | --- |
| API H1 + H2 | 45 tests, correctos |
| Contratos H0 | 4 tests, correctos |
| Interfaz Playwright | 10 tests, escritorio y movil |
| Build Next/TypeScript | Correcto en Docker |
| Migracion PostgreSQL | `0003_h2_events`; `alembic check` sin diferencias |
| Compose | API, worker, web, PostgreSQL y LiteLLM saludables |
| Servicios H1 | Base de datos, generacion, embedding y reranker disponibles |

La aceptacion contra Compose comprueba MD, TXT, PDF textual y DOCX, original intacto, dos revisiones con instantaneas de metadatos, procedencia manual y aprobacion sin publicacion. Comprueba archivos vacios, PDF sin texto, rechazo de PDF corrupto, cancelacion, nuevo trabajo de reintento, lease vencido recuperado al reiniciar el worker (generacion 2), resultado tardio rechazado y sustitucion con dos versiones. Se eliminaron los siete documentos sinteticos mediante la API confirmada.

Playwright usa la cuenta local sin grabar trazas con credenciales: carga multipart real, edicion de etiquetas, historial y metadatos originales, vista previa sin scripts ni imagenes remotas, mapa de procedencia, aprobacion, Escape en confirmaciones, eliminacion y pagina de trabajos. Se verifico ausencia de desbordamiento de pagina en escritorio y movil; capturas revisadas visualmente.

Los tests de API cubren ademas permisos, idempotencia, conflictos de revision, limites, rutas peligrosas, ZIP con traversal, expansion excesiva, entidades XML y XML corrupto, cancelacion en ejecucion, parada del worker, retirada y retencion. La retirada de versiones publicadas se prueba con un estado sembrado: H2 no publica documentos para probarla.

## Matriz del corpus

Se ejecutaron los extractores reales sobre los 13 Markdown originales y las seis variantes seleccionadas en H0. Los 19 casos superan las puertas **de referencia de H0** y las comprobaciones de localizadores. Esas puertas validaban los fixtures, no constituyen por si solas una aprobacion final de fidelidad del extractor H2. No se ha inventado un umbral nuevo para `structure_recall`.

| Caso | Tokens | Encabezados | Estructura | Orden | Diferencia |
| --- | --- | --- | --- | --- | --- |
| 13 fuentes MD | 1.0000 | 1.0000 | 1.0000 | 1.0000 | Sin diferencia de cobertura |
| DOC-003 PDF, tablas | 1.0000 | 1.0000 | 0.8810 | 0.9160 | 587 tokens frente a 496; diferencias de tablas/bloques |
| DOC-003 DOCX | 1.0000 | 1.0000 | 1.0000 | 1.0000 | Sin diferencia medida |
| DOC-007 PDF, codigo | 1.0000 | 1.0000 | 0.9534 | 1.0000 | Diferencias de estructura de bloques |
| DOC-007 DOCX | 1.0000 | 1.0000 | 1.0000 | 1.0000 | Sin diferencia medida |
| DOC-008 PDF, procedimiento | 1.0000 | 1.0000 | 1.0000 | 0.9996 | 2544 tokens frente a 2542 |
| DOC-008 DOCX | 1.0000 | 1.0000 | 1.0000 | 1.0000 | Sin diferencia medida |

`Tokens`, `Encabezados` y `Estructura` son recalls; `Orden` es similitud de secuencia. Cobertura completa no implica ausencia de duplicacion. El informe señala explicitamente `structure_difference` y `additional_tokens`.

**Pendiente de cierre funcional de H2:** revisar visualmente las tablas/bloques de los PDF DOC-003 y DOC-007 y aceptar o corregir esas diferencias; si se exige una puerta estructural numerica adicional, acordarla con evidencia. El pipeline es operativo, pero estos PDF no se declaran fieles por un PASS agregado. Ninguna conversion se publico automaticamente.

Se usa PyMuPDF4LLM 0.3.4 en modo legacy sin `pymupdf_layout` ni OCR. La libreria avisa de que `use_ocr=False` se ignora en legacy, que ya carece de OCR. Paginas sin texto se notifican para revision. La posible necesidad de OCR es un diagnostico, no una deteccion fiable de escaneado.

## Limites del ensayo

No se ha hecho una prueba de carga con multiples workers, ni crash real del host, ni validacion de todos los PDF de terceros. La recuperacion real se prueba mediante un worker detenido, una adquisicion simulada de un worker perdido y un lease expirado; la parada cooperativa y el bloqueo de generaciones se prueban tambien en tests de API. No se han ejecutado indexacion, embeddings de corpus ni publicacion, que corresponden a H3.
