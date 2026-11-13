# Modo «explicar concepto» en el chat (explain)

Fecha: 2026-11-13.

## Contrato

El turno acepta `mode: "answer" | "explain"` (pydantic `Literal`, anyotro valor es un 422 antes de
empezar el turno). `answer` sigue siendo el valor por defecto y su ruta de generación es byte-idéntica
a la anterior: mismas funciones, mismos motivos de `chat_outcome` y la misma forma del resultado.
El modo nuevo vive en `apps/api/bibliotecario/explain.py`; `chat.py` solo añade la rama de generación
por modo y guarda el modo en `chat_outcome`.

En `explain` el turno pide al modelo una **síntesis por secciones** con esquema cerrado
(`additionalProperties: false` en todos los niveles):

```json
{"sections": [
  {"heading": "texto 1..120",
   "sentences": [{"text": "texto 1..600", "citations": ["C1", "C3"]}]}
]}
```

Entre 1 y 4 secciones, entre 1 y 14 frases en total (comprobado en el validador, que es quien puede
ver el total cruzado), entre 1 y 3 citas por frase y sin citas repetidas dentro de una frase. No hay
`figure`: llega en otra tarea. La respuesta publicada es exactamente `render_synthesis`: el `heading`
como `**heading**` y cada frase terminada en `[C1][C3]`, en orden de aparición.

## Garantías: frase → citas → verificador

La «explicación general» libre se eliminó en H3 porque era la vía por la que se colaba contenido no
respaldado (`docs/h3/general-explanation.md`); el modo explain no la reabre, la formaliza:

1. **Citas explícitas por frase.** Una frase sin citas no se publica; toda frase nombra los pasajes
   (etiquetas `C1..Cn` del turno) que la respaldan.
2. **Cifras solo contra las citas de esa frase.** `validate_synthesis` (determinista, antes del
   verificador) exige `numbers(frase) ⊆ numbers(pasajes citados por esa frase + sus títulos + sus
   section_path)`. El contexto se calcula **solo** con las citas de esa frase: una cifra que exista
   en otro pasaje del turno pero no en los citados sigue siendo `unsupported_number` (3 + 4 = 7 no
   está ni en el pasaje de los 3 ni en el de los 4). El `heading` tiene su propio control
   (`numbers(heading) ⊆ números de la unión de todas las citas del turno`): un dato numérico en un
   título es una frase sin citas por la puerta de atrás.
3. **Un verificador por frase.** `verify_synthesis_claim` audita cada frase en paralelo contra la
   **unión de los pasajes que esa frase cita** (nunca contra el corpus ni contra el resto del turno),
   con el mismo contrato de auditoría que `verify_claim` adaptado a varias fuentes y el mismo esquema
   de respuesta `{"supported": bool}`. Ante duda, `false`. Una sola frase rechazada tumba la
   explicación entera a `grounded_extract`: no se publica prosa parcial.

Motivos de rechazo: `invalid_synthesis` (estructura, límites o citas repetidas), `citation_unknown`
(etiqueta fuera de `C1..Cn`), `invalid_claim` (texto vacío, marcadores `[Cn]` en el texto, saltos de
línea o exceso de longitud), `unsupported_number` (cifra nueva en frase o heading), `no_evidence`
(cero frases) y `grounding_rejected` (el verificador no respalda alguna frase). **Todos** caen al
extracto literal con `status="completed"`, `outcome_reason="grounded_extract"` y `fallback` con el
motivo y su detalle, igual que el recurso seguro del modo `answer`; el extracto reutiliza
`extractive_answer` (solo pasajes literales verificados).

## Por qué no toca la política calibrada

`policy_signature` incluye `VERSION`, los prompts, `REWRITE_PROMPT`, `INTENT_PROMPT`,
`Assessment.model_json_schema()` y constantes; `SYSTEM`, `EXPLAIN_SYSTEM` y el verificador no forman
parte de la firma (ya era así desde H4, ver `docs/h3/general-explanation.md`). La tarea no toca
`sufficiency.assess` ni su prompt, ni el umbral `-1.2894607782363892`, ni las firmas
(`2899120c…`, `54c394a7…`): la política calibrada sigue gobernando el turno y no hay que recalibrar.

## Qué NO hace este modo

- **No amplía la recuperación.** Recibe el mismo `support` que el evaluador de cobertura seleccionó
  para el turno. Si ese conjunto es de un solo documento, la explicación es de un solo documento; el
  modo no añade pasajes ni reintenta las abstenciones.
- No cambia el cuerpo de la respuesta de la API ni el esquema del modo `answer`; no toca
  `apps/web`. El cliente elige el modo: no hay activación por palabras clave ni valor por defecto
  distinto de `answer`.
- No introduce figuras (`figure`) ni resúmenes sin cita.

## Medición

El turno sigue registrando `chat_outcome` (con `mode` cuando es `explain`; su ausencia significa
`answer`, de modo que los resultados de los turnos `answer` quedan byte-idénticos a los
anteriores), `chat_latency` (`generation_ms`, `verification_ms`) y la traza de llamadas LLM por fase
(`generation`, `verification: una llamada por frase, en paralelo`). El coste de auditoría pasa de
«una llamada por afirmación» a «una llamada por frase», que es el mismo orden. La medición de
latencia y de recursos al extracto sobre el banco real de aceptación queda pendiente del ciclo de
evaluación; con los dobles de test se comprueba el contrato, no el rendimiento.

## Pendiente

- Cobertura multi-documento en la recuperación (otro conjunto `support`) y su recalibración:
  prerequisite de explicaciones que crucen documentos, no de este modo.
- Figuras (`figure`) referenciadas en las secciones.
- Integración en la web para solicitar `mode="explain"` y mostrar los `heading` por sección.
