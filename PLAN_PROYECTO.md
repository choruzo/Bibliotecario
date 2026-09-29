# Bibliotecario — arquitectura e hitos del proyecto

Estado: propuesta inicial para revisión  
Fecha: 2026-09-29

## 1. Objetivo

Construir una aplicación local y portable que convierta una colección de documentos en una biblioteca consultable mediante conversación.

La aplicación tendrá dos áreas:

1. **Administración**: carga, conversión, revisión, publicación, reindexación, versionado y eliminación de documentos.
2. **Chat**: consultas conversacionales con memoria, recuperación híbrida, reranking, citas verificables y abstención cuando la biblioteca no contenga evidencia suficiente.

El sistema se distribuirá mediante Docker y deberá poder trasladarse a otra máquina sin conexión a Internet. Los datos persistentes vivirán fuera de los contenedores y se montarán como volúmenes o bind mounts.

## 2. Principios funcionales

### 2.1 Recuperar antes de responder

Cada turno que solicite información deberá ejecutar recuperación documental. El historial de conversación podrá reformular o desambiguar la consulta, pero nunca sustituirá esta recuperación.

Si no se obtiene evidencia suficientemente relevante, el asistente no improvisará una respuesta. Indicará que no encuentra base documental bastante y podrá sugerir cómo reformular la pregunta.

### 2.2 Comportamiento de profesor

Cuando exista evidencia documental suficiente, el asistente podrá:

- explicar conceptos con lenguaje adaptado al usuario;
- relacionar varias partes de la documentación;
- proponer ejemplos o analogías;
- aclarar procesos internos paso a paso;
- conservar el contexto pedagógico entre turnos.

Se distinguirán dos clases de contenido en la respuesta:

- **Afirmaciones sobre la organización, sus documentos o sus procesos**: deben estar respaldadas por citas.
- **Explicación general añadida por el modelo**: se permite para facilitar la comprensión, pero no podrá contradecir las fuentes ni presentarse como una política o hecho interno documentado. Cuando pueda confundirse con contenido de la biblioteca, se marcará como explicación general.

### 2.3 Evidencia y abstención

La decisión de responder no dependerá de un único umbral inventado. Se calibrará con un conjunto de evaluación que contenga:

- preguntas respondibles;
- preguntas no respondibles;
- preguntas ambiguas;
- preguntas de seguimiento;
- consultas cuyo vocabulario no coincida literalmente con el documento.

El sistema conservará, para diagnóstico, los candidatos recuperados, sus puntuaciones, el resultado del reranker y la decisión final. Estos detalles solo serán visibles para administración.

### 2.4 Trazabilidad

Toda respuesta documental mostrará citas navegables. Una cita identificará, como mínimo:

- documento y versión;
- página para PDF, cuando esté disponible;
- sección o encabezado para DOCX/Markdown/TXT;
- fragmento usado como evidencia.

El Markdown normalizado no reemplazará al original: ambos se conservarán.

## 3. Alcance acordado del MVP

### Incluido

- Biblioteca única compartida.
- Roles `admin` y `usuario` con autenticación local.
- Ingesta de PDF con texto, DOCX, Markdown y TXT.
- Estados `subido`, `procesando`, `requiere_revision`, `indexando`, `publicado` y `error`.
- Revisión y edición del Markdown antes de publicarlo.
- Metadatos: título, autor, fecha, categoría, etiquetas, idioma, versión y visibilidad.
- Conservación del archivo original y de cada versión normalizada.
- Sustitución, reindexación, retirada y eliminación controlada de documentos.
- Recuperación vectorial y textual, seguida de reranking.
- Chat con conversaciones persistentes, streaming y citas.
- Resumen de conversaciones largas sin perder los últimos turnos relevantes.
- Interfaz administrativa para consultar fallos y trazas del pipeline.
- Docker Compose y paquete exportable para instalación offline.
- Base de datos y documentos montados desde el host.

### Pospuesto

- OCR de documentos escaneados.
- GraphRAG y grafo de conocimiento.
- SSO/OAuth y multitenencia.
- Formatos HTML y PowerPoint.
- Acceso a fuentes de Internet.

La arquitectura dejará puntos de extensión para OCR y GraphRAG, pero el MVP no incluirá implementaciones vacías que compliquen su operación.

### Corpus inicial de prueba

El repositorio contiene actualmente **13 documentos Markdown** en `docs/`. Este conjunto se utilizará como primer corpus funcional y como fuente de casos para el banco de evaluación de H0.

Además de indexar directamente los Markdown, se generarán variantes controladas en PDF y DOCX para probar el pipeline completo. El Markdown original actuará como referencia esperada frente a la que comparar:

- conservación de títulos, encabezados, párrafos, listas, tablas y bloques de código;
- orden y cobertura del texto extraído;
- calidad del Markdown reconstruido;
- segmentación y procedencia de las citas;
- consistencia de la recuperación entre formatos equivalentes;
- detección de pérdidas o alteraciones introducidas por la conversión.

Las conversiones serán fixtures reproducibles generados mediante scripts, no copias editadas manualmente. Cada variante conservará una relación explícita con su Markdown de origen y su SHA-256. PDF, DOCX y Markdown equivalentes no se publicarán simultáneamente en la biblioteca de producción para evitar resultados duplicados; sí podrán convivir en un entorno de prueba aislado.

## 4. Servicios locales comprobados

Comprobación realizada contra `127.0.0.1` el 2026-09-29:

| Puerto | Función | Modelo detectado | Contrato comprobado |
|---|---|---|---|
| `8080` | generación | `gpt-oss-20b-Q5_K_M.gguf` | `/health`, `/v1/models`, API de `llama.cpp`; contexto activo 32 768 |
| `8081` | embeddings | `nomic-embed-text-v1.5.f16.gguf` | `/v1/embeddings`; vector de 768 dimensiones; contexto activo 1 024 |
| `8082` | reranking | `bge-reranker-v2-m3-Q8_0.gguf` | `/v1/rerank` y `/rerank`; contexto activo 2 048 |

Los tres puertos pertenecen directamente a `llama.cpp`; no hay un daemon de Docker accesible durante esta comprobación.

La aplicación consumirá el modelo generativo a través de **LiteLLM**. LiteLLM será un contenedor propio y tendrá como upstream configurable el `llama.cpp` de generación. Los adaptadores de embeddings y reranking usarán inicialmente sus APIs `llama.cpp` directas, sin acoplar la lógica de dominio a URLs concretas.

En Windows y macOS, los contenedores podrán alcanzar los modelos del host mediante `host.docker.internal`. En Linux se documentará el `host-gateway` o una URL de red explícita. Todas las URLs y nombres de modelo serán configuración, no constantes en el código.

## 5. Arquitectura propuesta

### 5.1 Componentes

- **Web**: Next.js/React con rutas `/admin` y `/chat`.
- **API**: FastAPI, autenticación, documentos, conversaciones, recuperación y streaming.
- **Worker**: misma base Python que la API, ejecutada como proceso independiente para conversión e indexación.
- **PostgreSQL + pgvector**: usuarios, documentos, versiones, trabajos, fragmentos, vectores, conversaciones, mensajes y auditoría.
- **Almacenamiento de archivos**: directorio del host montado en API y worker.
- **LiteLLM**: pasarela configurable para generación.
- **llama.cpp externos**: generación, embeddings y reranker disponibles en el host o en otra máquina de la LAN.

No se añadirá Redis al principio. La cola persistente se implementará en PostgreSQL con bloqueos transaccionales y reintentos. Así se reduce el número de servicios que hay que exportar y operar offline.

### 5.2 Flujo de ingesta

1. Validar extensión, MIME, tamaño y nombre; calcular SHA-256.
2. Guardar el original de forma inmutable.
3. Extraer texto y estructura mediante un adaptador por formato.
4. Generar Markdown normalizado y un mapa de procedencia.
5. Detectar documento vacío, corrupto o probablemente escaneado.
6. Presentar el Markdown para revisión.
7. Al publicar, segmentar respetando encabezados, párrafos, listas y límites del modelo.
8. Generar embeddings con el prefijo apropiado de Nomic para documentos.
9. Escribir fragmentos y vectores en una transacción versionada.
10. Activar la nueva versión de forma atómica; las búsquedas en curso no verán una mezcla de versiones.

Los PDF se procesarán inicialmente con PyMuPDF/PyMuPDF4LLM y los DOCX con `python-docx`, detrás de interfaces sustituibles. Un PDF sin texto útil pasará a `requiere_revision` con diagnóstico de posible necesidad de OCR.

### 5.3 Flujo de consulta

1. Cargar los últimos turnos y, si existe, el resumen persistido de la conversación.
2. Crear una consulta de búsqueda autónoma a partir de la pregunta y el contexto.
3. Generar el embedding con el prefijo de consulta de Nomic.
4. Recuperar candidatos por similitud vectorial y búsqueda textual de PostgreSQL.
5. Fusionar resultados evitando duplicados y respetando filtros y permisos.
6. Rerankear los mejores candidatos con BGE.
7. Aplicar la política calibrada de suficiencia de evidencia.
8. Si la evidencia no basta, abstenerse sin llamar al LLM para redactar una respuesta factual.
9. Si basta, generar mediante LiteLLM una respuesta pedagógica con citas permitidas únicamente a los fragmentos recuperados.
10. Validar que las citas emitidas existen y guardar respuesta, fuentes y métricas.

### 5.4 Memoria conversacional

Se persistirán conversaciones y mensajes completos. Para no sobrepasar el contexto del modelo se mantendrán:

- un resumen acumulativo de los turnos antiguos;
- los últimos turnos sin resumir;
- entidades, conceptos o preferencias pedagógicas mencionadas;
- referencias a documentos usados anteriormente.

La memoria sirve para entender pronombres, preguntas de seguimiento y nivel de explicación. No convierte una afirmación anterior del asistente en evidencia. Cada nueva respuesta documental debe volver a recuperar fuentes vigentes.

### 5.5 Esquema lógico mínimo

- `users`, `roles`, `sessions`
- `documents`, `document_versions`, `document_files`
- `ingestion_jobs`, `job_events`
- `chunks`, `chunk_embeddings`
- `conversations`, `messages`, `conversation_summaries`
- `message_sources`, `retrieval_runs`, `retrieval_candidates`
- `audit_events`, `app_settings`

Los fragmentos pertenecerán siempre a una versión concreta. La retirada de una versión la excluirá inmediatamente de la recuperación sin borrar sus datos hasta que se ejecute una eliminación confirmada.

## 6. Seguridad y operación

- Contraseñas con Argon2id y cookies de sesión `HttpOnly`.
- Cuenta administradora inicial creada mediante un comando de bootstrap, sin credenciales predeterminadas.
- Validación del contenido real de cada archivo y límites configurables de tamaño.
- Los originales nunca se ejecutarán ni se servirán con MIME activo peligroso.
- Protección contra path traversal, archivos comprimidos abusivos y Markdown/HTML no confiable.
- Las claves, si llegan a ser necesarias, se leerán desde variables o archivos de secretos y no se guardarán en la base de datos.
- Auditoría de cargas, publicaciones, retiradas, eliminaciones y cambios de configuración.
- Health checks separados para aplicación, base de datos, generación, embeddings y reranking.
- Backups consistentes de PostgreSQL y del almacén de documentos, acompañados de un manifiesto de hashes.

## 7. Portabilidad offline

La entrega offline contendrá:

- archivo `compose.yaml` y configuración de ejemplo;
- imágenes Docker versionadas exportadas a archivos `.tar`;
- scripts PowerShell y shell para importar, configurar, iniciar, verificar y respaldar;
- migraciones incluidas dentro de la imagen de la API;
- dependencias frontend y Python ya incorporadas en las imágenes;
- manifiesto con versiones y SHA-256 de imágenes y artefactos;
- documentación de conexión a los tres servidores `llama.cpp`;
- prueba de restauración en un directorio nuevo sin acceso a Internet.

Directorios persistentes propuestos en el host:

```text
bibliotecario-data/
  postgres/
  documents/
    originals/
    normalized/
  backups/
  exports/
```

Las rutas se configurarán mediante variables y se montarán dentro de los contenedores. Ninguna actualización de imagen deberá borrar o sobrescribir estos datos.

## 8. Hitos

### H0 — Contrato del producto y banco de evaluación

**Resultado:** decisiones convertidas en especificaciones comprobables antes de implementar recuperación.

- Definir historias de usuario y permisos.
- Definir estados y transiciones de documentos y trabajos.
- Definir formato de las citas y política de explicación general.
- Catalogar los 13 Markdown existentes en `docs/` como corpus inicial.
- Crear scripts reproducibles que generen variantes PDF y DOCX de una selección representativa.
- Definir comparaciones entre el Markdown de referencia y el contenido recuperado de cada variante.
- Preparar preguntas respondibles, no respondibles, ambiguas y conversacionales.
- Registrar configuración real de los tres servicios de modelos.

**Criterio de aceptación:** existe una especificación aprobada y un conjunto de evaluación versionado sin información sensible; las variantes PDF/DOCX pueden regenerarse y mantienen trazabilidad hasta el Markdown de origen.

### H1 — Esqueleto ejecutable y persistencia

**Resultado:** aplicación vacía pero operable mediante Docker Compose.

- Crear monorepo, API, web, worker y migraciones.
- Incorporar PostgreSQL/pgvector y almacenamiento montado desde el host.
- Añadir configuración validada y perfiles de desarrollo/producción.
- Implementar autenticación local, roles y bootstrap del administrador.
- Añadir health checks y logging estructurado con identificadores de correlación.
- Conectar LiteLLM con el `llama.cpp` generativo y crear clientes de embeddings/reranking.

**Criterio de aceptación:** desde una instalación limpia se levantan los servicios, se crea el administrador y los cuatro checks —base de datos, LLM, embedding y reranker— informan correctamente de disponibilidad o error.

### H2 — Pipeline documental y página administrativa

**Resultado:** un administrador puede llevar un archivo desde la carga hasta una versión Markdown revisada.

- Implementar carga segura y almacenamiento inmutable.
- Convertir PDF textual, DOCX, MD y TXT.
- Preservar procedencia de página/sección.
- Implementar trabajos persistentes, progreso, cancelación segura y reintentos.
- Crear editor/vista previa de Markdown y metadatos.
- Mostrar diagnósticos de archivos vacíos, corruptos o posiblemente escaneados.
- Implementar versiones, sustitución, retirada y eliminación confirmada.
- Ejecutar la matriz MD/PDF/DOCX del corpus de `docs/` y registrar diferencias de extracción.

**Criterio de aceptación:** cada formato admitido produce Markdown revisable; un fallo no publica datos parciales; reiniciar el worker no pierde el trabajo; el original permanece intacto; las variantes seleccionadas de `docs/` superan las comprobaciones acordadas de cobertura, estructura y trazabilidad.

### H3 — Indexación, recuperación híbrida y evaluación

**Resultado:** buscador medible y trazable, todavía independiente del chat.

- Implementar segmentación estructural y mapa de procedencia.
- Generar y almacenar embeddings de 768 dimensiones.
- Añadir búsqueda textual PostgreSQL y fusión híbrida.
- Integrar BGE reranker mediante `/v1/rerank`.
- Crear endpoint y pantalla administrativa de inspección de recuperación.
- Ejecutar el banco de evaluación y calibrar suficiencia/abstención.
- Medir `Recall@k`, `MRR/nDCG`, exactitud de abstención y latencia.

**Criterio de aceptación:** la nueva versión de un documento se activa atómicamente; una versión retirada no aparece; las métricas y los errores del corpus de evaluación quedan registrados; no se elige un umbral sin evidencia empírica.

### H4 — Chat fundamentado con memoria pedagógica

**Resultado:** usuario conversa con la biblioteca y recibe respuestas útiles, trazables o una abstención honesta.

- Crear, listar, renombrar y continuar conversaciones.
- Implementar reformulación contextual de consultas.
- Aplicar recuperación y puerta de suficiencia en cada turno informativo.
- Generar respuestas por LiteLLM con streaming.
- Mostrar citas navegables y vista del fragmento/original.
- Validar citas antes de guardar la respuesta.
- Añadir resumen de conversaciones largas y preferencias pedagógicas.
- Separar visualmente evidencia documental y explicación general cuando sea necesario.

**Criterio de aceptación:** preguntas no cubiertas no reciben una respuesta inventada; preguntas de seguimiento recuperan evidencia de nuevo; las citas conducen al fragmento correcto; reiniciar la aplicación no pierde la conversación.

### H5 — Operación administrativa completa

**Resultado:** el sistema puede mantenerse sin intervenir manualmente en la base de datos.

- Panel de trabajos, fallos, reintentos y estado de modelos.
- Filtros, categorías, etiquetas y visibilidad documental.
- Reindexación selectiva y total con confirmaciones y progreso.
- Auditoría consultable.
- Configuración pública de proveedores y parámetros sin exponer secretos.
- Exportación de diagnósticos y resultados de evaluación.

**Criterio de aceptación:** un administrador puede diagnosticar y recuperar un trabajo fallido, retirar contenido y verificar qué versión sustenta cada respuesta.

### H6 — Empaquetado y restauración offline

**Resultado:** paquete transferible y reproducible.

- Fijar versiones e imágenes por digest.
- Exportar imágenes Docker y generar manifiesto SHA-256.
- Crear instaladores/verificadores PowerShell y shell.
- Documentar URLs de modelos para Windows, Linux y servicio remoto.
- Implementar backup y restauración coordinada de base de datos y documentos.
- Ensayar instalación y restauración sin red en otra ruta o máquina.

**Criterio de aceptación:** una máquina sin Internet puede importar las imágenes, montar una base existente, conectar los modelos, iniciar el sistema y recuperar una conversación y sus citas tras restaurar un backup.

### H7 — Endurecimiento y entrega del MVP

**Resultado:** versión preparada para uso continuado.

- Pruebas E2E de administración y chat.
- Pruebas de concurrencia, reinicios y carreras de versionado.
- Pruebas adversariales de archivos, prompt injection documental y citas falsas.
- Límites, timeouts, backpressure y cancelación.
- Revisión de accesibilidad y experiencia de usuario.
- Presupuesto de rendimiento y guía operativa.

**Criterio de aceptación:** pasan las pruebas funcionales y de seguridad acordadas; una indisponibilidad de cualquiera de los modelos produce un error recuperable, no pérdida de datos ni respuesta sin evidencia.

## 9. Extensiones posteriores

### OCR

Se añadirá como nuevo adaptador para versiones detectadas como escaneadas. Su salida deberá pasar por la misma revisión humana y conservar coordenadas/página, confianza y motor utilizado.

### GraphRAG

Se incorporará después de disponer de un RAG vectorial evaluado. La extracción de entidades y relaciones será versionada y mantendrá procedencia hacia fragmentos. El grafo aportará candidatos adicionales, pero no será una fuente sin trazabilidad ni sustituirá la puerta de evidencia.

## 10. Orden de ejecución

El orden recomendado es `H0 → H1 → H2 → H3 → H4 → H5 → H6 → H7`.

H0 evita construir recuperación sin una definición medible de “hay evidencia”. H2 permite inspeccionar la calidad documental antes de generar vectores. H3 valida la recuperación antes de pedir al LLM que redacte. H6 se diseña desde H1, aunque su prueba completa se realiza cuando el MVP ya funciona.

## 11. Decisiones pendientes antes de implementar H1

Solo quedan decisiones de detalle que pueden resolverse durante H0:

- nombre visible definitivo de la aplicación;
- tamaño máximo inicial de archivo y cuota total;
- tiempo de conservación de versiones retiradas y auditoría;
- idiomas iniciales de interfaz;
- objetivos mínimos del banco de evaluación y latencia aceptable;
- ubicación concreta del directorio persistente en las máquinas de destino.

Estas decisiones no bloquean la aprobación de la arquitectura general ni la creación del esqueleto.
