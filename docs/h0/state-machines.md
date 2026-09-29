# Estados de documentos y trabajos

## Documento y versión

Los estados visibles del documento representan la versión de trabajo o la versión activa. El historial conserva todas las transiciones. Una transición inválida debe rechazarse con conflicto y no modificar datos.

| Estado | Significado | Transiciones permitidas |
|---|---|---|
| `subido` | Original validado y guardado de forma inmutable. | `procesando`, `error` |
| `procesando` | Un trabajo posee el arrendamiento de conversión. | `requiere_revision`, `error` |
| `requiere_revision` | Existe Markdown normalizado y diagnóstico revisable. | `procesando`, `indexando`, `error` |
| `indexando` | Se construyen fragmentos y vectores de una versión candidata. | `publicado`, `requiere_revision`, `error` |
| `publicado` | La versión está activa y puede recuperarse según visibilidad. | `indexando` para sustitución, `retirado` |
| `retirado` | La versión se conserva, pero no participa en recuperación. | `indexando` para republicación, `eliminando` |
| `eliminando` | Una eliminación confirmada está en curso. | `eliminado`, `error` |
| `eliminado` | Datos borrados según política; queda el mínimo registro de auditoría. | ninguna |
| `error` | Fallo terminal del intento actual con diagnóstico. | estado seguro anterior mediante reintento explícito |

`retirado`, `eliminando` y `eliminado` completan los estados enumerados inicialmente en el plan porque retirada y eliminación necesitan estados comprobables. La API puede exponer un estado de documento agregado, pero debe conservar el estado de cada versión.

## Trabajo persistente

| Estado | Significado | Transiciones permitidas |
|---|---|---|
| `pendiente` | En cola y disponible para adquisición. | `en_ejecucion`, `cancelado` |
| `en_ejecucion` | Worker con arrendamiento vigente. | `completado`, `reintentable`, `fallido`, `cancelando` |
| `reintentable` | Fallo transitorio con próximo intento programado. | `pendiente`, `cancelado` |
| `cancelando` | Se solicitó cancelación; el worker debe llegar a un punto seguro. | `cancelado`, `fallido` |
| `cancelado` | No realizará más efectos. | ninguna |
| `completado` | Efectos íntegros confirmados. | ninguna |
| `fallido` | Agotó reintentos o encontró un fallo permanente. | `pendiente` solo por reintento manual nuevo |

## Invariantes

1. Existe como máximo una versión activa por documento.
2. Publicar cambia la versión activa en una única transacción junto con sus fragmentos recuperables.
3. Solo `publicado` es recuperable; `retirado` deja de serlo en la misma transacción de retirada.
4. Un trabajo solo puede escribir si conserva el arrendamiento y la generación con la que fue adquirido.
5. Repetir una operación con la misma clave de idempotencia no duplica originales, versiones, fragmentos ni auditorías de éxito.
6. Cancelar no borra el original ni deja una versión parcialmente publicada.
7. El reintento crea un nuevo intento auditable; no oculta el diagnóstico anterior.
8. La eliminación física requiere confirmación, permiso, cumplimiento de retención y ausencia de referencias protegidas.

## Fallos y recuperación

- Un PDF sin texto útil termina en `requiere_revision` con diagnóstico de posible OCR, no en `publicado` ni como error genérico.
- Una dependencia de modelos no disponible convierte el intento en `reintentable` cuando no se ha agotado la política.
- Si el worker pierde el arrendamiento, debe abandonar cualquier resultado tardío.
- Si la activación atómica falla, la versión previamente publicada permanece activa.
