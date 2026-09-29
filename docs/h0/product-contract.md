# Contrato funcional del MVP

## Decisiones y límites

El producto es una biblioteca local compartida con dos roles. `admin` gobierna documentos, configuración pública, evaluación y diagnóstico. `usuario` consulta únicamente versiones publicadas que su visibilidad le permita leer. Ningún historial conversacional ni conocimiento del modelo sustituye la recuperación documental en un turno informativo.

Las decisiones todavía abiertas no bloquean H0, pero sí H1. Se registran con un valor inicial conservador y deben aprobarse antes de cerrar H0.

| Decisión | Valor inicial propuesto | Estado |
|---|---|---|
| Nombre visible | Bibliotecario | pendiente de aprobación |
| Tamaño máximo por archivo | 100 MiB | pendiente de aprobación |
| Cuota total | configurable, sin límite implícito | pendiente de aprobación |
| Retención de versiones retiradas | 90 días antes de eliminación elegible | pendiente de aprobación |
| Retención de auditoría | 365 días como mínimo | pendiente de aprobación |
| Idiomas de interfaz | español inicial; contenido multilingüe | pendiente de aprobación |
| Directorio persistente | variable obligatoria del despliegue | pendiente de aprobación |
| Objetivo de latencia | p95 de recuperación menor o igual a 3 s, sin generación | sujeto a calibración H3 |

## Historias de administración

| ID | Historia | Permiso y comprobación |
|---|---|---|
| ADM-01 | Como administrador cargo MD, TXT, DOCX o PDF textual para preparar una nueva versión. | Solo `admin`; valida nombre, tipo real, tamaño y hash antes de persistir. |
| ADM-02 | Como administrador reviso y edito el Markdown normalizado antes de publicarlo. | Solo `admin`; editar no cambia el original inmutable. |
| ADM-03 | Como administrador publico una versión completa de forma atómica. | Solo `admin`; una búsqueda nunca mezcla versiones. |
| ADM-04 | Como administrador retiro una versión sin borrar su trazabilidad. | Solo `admin`; deja de ser recuperable inmediatamente. |
| ADM-05 | Como administrador sustituyo o reindexo un documento y observo progreso, errores y reintentos. | Solo `admin`; trabajos persistentes e idempotentes. |
| ADM-06 | Como administrador elimino contenido tras una confirmación explícita. | Solo `admin`; respeta retención y registra auditoría. |
| ADM-07 | Como administrador inspecciono candidatos, puntuaciones y decisión de suficiencia. | Solo `admin`; no expone secretos ni contenido fuera de su permiso. |
| ADM-08 | Como administrador compruebo por separado base de datos, generación, embedding y reranker. | Solo `admin`; cada dependencia informa disponible, degradada o no disponible. |
| ADM-09 | Como administrador creo la primera cuenta mediante un comando de bootstrap. | No existen credenciales predeterminadas; el secreto no se registra. |

## Historias de consulta

| ID | Historia | Permiso y comprobación |
|---|---|---|
| USR-01 | Como usuario inicio, renombro, continúo y consulto mis conversaciones. | `usuario` o `admin`; las conversaciones son persistentes y tienen propietario. |
| USR-02 | Como usuario hago una pregunta y recibo una respuesta basada en versiones publicadas. | Recuperación obligatoria en cada turno informativo. |
| USR-03 | Como usuario sigo una conversación con pronombres o referencias anteriores. | El contexto reformula la consulta, pero se vuelve a recuperar evidencia vigente. |
| USR-04 | Como usuario abro una cita y veo documento, versión, localizador y fragmento. | La cita solo apunta a un fragmento realmente recuperado y autorizado. |
| USR-05 | Como usuario recibo una abstención cuando la biblioteca no basta. | No se llama al generador para producir afirmaciones documentales sin evidencia. |
| USR-06 | Como usuario distingo una explicación pedagógica general de una afirmación interna. | La explicación general se etiqueta cuando pueda confundirse con la fuente. |

## Matriz resumida de permisos

| Acción | admin | usuario |
|---|:---:|:---:|
| Consultar documentos publicados permitidos | sí | sí |
| Gestionar sus conversaciones | sí | sí |
| Ver fragmentos citados permitidos | sí | sí |
| Cargar, editar, publicar o retirar | sí | no |
| Reindexar o eliminar | sí | no |
| Ver trazas y candidatos de recuperación | sí | no |
| Cambiar configuración pública | sí | no |
| Ver o recuperar secretos | no | no |

## Criterios transversales

- Toda mutación administrativa genera un evento de auditoría con actor, acción, objeto, instante y resultado.
- Las respuestas y búsquedas aplican la visibilidad antes del reranking y de la generación.
- Los errores no publican versiones ni índices parciales.
- El original es inmutable; cada normalización e índice pertenece a una versión identificable.
- La indisponibilidad de un modelo produce un estado recuperable y visible, nunca una respuesta sin evidencia.
- Logs, trazas, evaluaciones y exportaciones omiten contraseñas, cookies, claves y contenido marcado como secreto.
