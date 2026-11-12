# Librería de lecciones

Conocimiento de ejecución del kit, capturado de los runs y reutilizado por los workers.
Formato derivado de [google-research/harness2](https://github.com/google-research/harness2)
(Apache 2.0), adaptado al ciclo Orca + OpenCode. Ver `docs/08-prd-harnessing.md`.

## Estructura

```
ops/orca/library/
├── INDEX.md                    # regenerado desde disco; nunca se edita a mano
├── README.md                   # este archivo
├── NO_ENTRY.log                # tareas sin evidencia suficiente para una lección
└── <dominio>/
    └── lessons/
        └── <taskId>/
            └── EXPERIENCE.md   # una lección
```

## Formato de una lección (EXPERIENCE.md)

| Campo | Qué es |
|---|---|
| **Cue** | La forma de la situación a la que aplica. Es lo que el worker debe reconocer antes de actuar. |
| **Lesson** | La operación a realizar; debe nombrar el componente del kit al que afecta. |
| **Evidence** | Citas exactas de `audit-<run>.jsonl` o del report archivado del worker, con formato `- [accion] fecha motivo: ...`. Sin evidencia no hay lección. |
| **Confidence** | `high`, `medium` o `low`. Los borradores automáticos nacen `low`. |

## Reglas

1. **Evidencia o nada**: si `lesson.ps1` no encuentra eventos reales en la auditoría, escribe
   `NO_ENTRY` y no crea el archivo. Que una tarea se haya integrado no demuestra que su
   método funcione.
2. `INDEX.md` se regenera con `lesson.ps1 -Index`. No editar a mano.
3. `lesson.ps1 -Validate` falla si hay cue/lesson sin completar, evidencia vacía o
   `confidence` inválida. Ejecútalo antes de commitear.
4. Los cambios se commitean como el resto del kit: revisión humana antes de push.

## Flujo

1. El bucle emite `LESSON_PENDING task=<id>` tras integrar o escalar una tarea, y lo registra
   como `lesson-candidate` en `audit-<run>.jsonl`.
2. El líder ejecuta `lesson.ps1 -RunId <run>` (scaffolding de todas las pendientes) o
   `lesson.ps1 -RunId <run> -TaskId <task>`: crea el borrador con la evidencia autocompletada.
3. El líder rellena `Cue` y `Lesson` (directamente en el archivo, o relanzando con
   `-Cue`/`-Lesson`).
4. `lesson.ps1 -Validate` antes de commitear.
