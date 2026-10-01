# Versiones fijadas y cambio de modelo de generación a Gemma 4

Fecha: 2026-10-01. Punto de partida: `8516e9c fix: harden ingestion and grounding for domain-agnostic PDFs`.

## Objetivo

Prioridad 1 del traspaso: fijar las imágenes por versión o *digest* para que una nueva descarga no cambie el comportamiento del sistema. Durante la sesión, el modelo de generación pasó de gpt-oss-20b (llama.cpp) a Gemma 4 12B NVFP4 (vLLM), y esta iteración incluye también esa migración.

## Cambios

- **Imágenes fijadas por etiqueta y *digest*.**
  - litellm: `ghcr.io/berriai/litellm:v1.103.2@sha256:f63fb81b…`. Es el mismo *digest* que tenía `main-stable` en la validación del commit anterior; la etiqueta `v1.103.2` apunta a él.
  - `pgvector/pgvector:0.8.2-pg17@sha256:feb68f4f…`.
  - Imágenes base de los Dockerfile: `python:3.12-slim@sha256:f77ac9e4…` y `node:22-alpine@sha256:0a7108bf…`.
  - `docker compose config` ya no contiene ninguna etiqueta móvil.
- **La firma de política incluye el modelo real.** `policy_signature` incluía `llm_model`, que es el alias de litellm (`bibliotecario-generation`), y no el modelo que hay detrás. Al cambiar gpt-oss por Gemma, la firma no variaba y el chat aplicaba a Gemma los umbrales calibrados con gpt-oss. Ahora compose pasa `LLAMA_GENERATION_MODEL` al API como `BIB_LLM_UPSTREAM_MODEL`, que forma parte de la firma. Como litellm y el API leen la misma variable, no pueden divergir.
- **Razonamiento desactivado con Gemma.** La reformulación de seguimientos forzaba `reasoning_effort="low"`; ahora respeta `BIB_SUFFICIENCY_REASONING_EFFORT=disabled`, igual que la evaluación y el verificador.
- **vLLM con `--reasoning-parser gemma4`** (script externo `G:\models\launch-gemma4-12b-vllm.ps1`). Sin el *parser*, el pensamiento de Gemma aparecía dentro de `content`. El script también elimina el contenedor anterior antes de medir la VRAM libre; si no, nunca había VRAM suficiente para relanzarlo.

## Mediciones

Evaluación de suficiencia (`assess`) con Gemma, sobre las dos últimas preguntas reales y con un *timeout* elevado a 120 s para poder medir:

| `reasoning_effort` | «como me conecto por consola al cisco» | «los pasos para la instalación del cisco» |
| --- | ---: | ---: |
| `disabled` | 5,7 s, *answer*, 2 apoyos | 12,2 s, *answer*, 10 apoyos |
| `low` | 71,2 s, *answer* | 133,3 s, `provider_timeout` |
| `medium` | 71,2 s, *answer* | 133,3 s, `provider_timeout` |

Gemma no distingue entre niveles: con cualquier `reasoning_effort` piensa extensamente, a unos 36 tokens/s. Con el *timeout* de producción (60 s), la aceptación coloquial se abstenía desde el primer caso con `assessment_failed` (`provider_timeout`). Sin razonamiento llega a la misma decisión en 6-12 s.

## Recalibración con Gemma (razonamiento desactivado)

El cambio de firma invalidó las políticas de gpt-oss. Se recalibraron los dos ámbitos en secuencia con `colloquial-calibration-v1.jsonl` y `colloquial-validation-v1.jsonl`. Los *checkpoints* de gpt-oss se conservan como `calibration-progress-<scope>-gptoss.json`. Cada ámbito tardó unos 6 minutos (con gpt-oss, unos 40).

| Ámbito | Umbral (gpt-oss → Gemma) | Validación | Entrenamiento | Aclaraciones | recall10 de localizadores |
| --- | --- | --- | --- | ---: | ---: |
| admin | −1,8354 → −1,2932 | 23/23 positivos, 0 indebidas, 8/8 negativos | 21/24 positivos, 0 indebidas, 8/8 negativos | 1,00 | 0,977 |
| usuario | −2,2028 → −1,2932 | 23/23 positivos, 0 indebidas, 8/8 negativos | 21/24 positivos, 0 indebidas, 8/8 negativos | 1,00 | 0,977 |

Latencia de la fase de suficiencia en la calibración: p50 de unos 4,0 s, p95 de unos 12,1 s y máximo de 15,3 s.

## Aceptación

- `scripts/h4/colloquial_acceptance.py` (admin): **13 de 13** en 3 min 44 s. Ocho respuestas factuales: 3 `grounded` (consola, SSH y el seguimiento de Cisco) y 5 `grounded_extract`. Con gpt-oss eran 2 `grounded` de 8. Las abstenciones (desconocido, dato ausente) y las aclaraciones (3 ambiguas) se comportan como se esperaba.
- `bee_chat_check.py chat` (PDF de la abeja): **5 de 6**. Las 4 preguntas factuales salen como `grounded`, con las cifras de la tabla (14½, 21 y 16 días). El seguimiento «¿Y la reina?» se reformula como «¿Cuántos días tarda en desarrollarse una abeja reina?». La premisa falsa («¿Por qué las reinas viven solo tres meses?») se abstiene. Falla «How long does a queen bee live?» en primer turno (`calibrated_score`), la limitación ya conocida de la prioridad 7.
- API: 118 pruebas, entre ellas la invalidación de la política por cambio del modelo real y la reformulación sin razonamiento. Raíz: 4. `tsc` sin errores. Playwright: 18 pasan y 6 se omiten (modo Compose).

## Incidencias operativas

- La primera aceptación con Gemma (antes de desactivar el razonamiento) se abstuvo en el primer caso por `provider_timeout`. Después el script abortó con `AttributeError`, porque el evento final del *stream* era un error con texto en `message`. Ahora el script lo cuenta como caso fallido y muestra el error.
- Las imágenes base no estaban en local tras el reinicio del disco de Docker; el *build* las descargó por *digest*.

## Limitaciones

- Gemma 4 12B en vLLM no ofrece niveles de razonamiento: con cualquier `reasoning_effort` razona extensamente. Con el razonamiento desactivado, la calidad depende de la decodificación guiada por esquema y de los controles deterministas.
- Las explicaciones generales siguen apareciendo en las respuestas `grounded` (por ejemplo, «Los zánganos no poseen el aguijón que tienen otras abejas»). Es el punto que aborda la prioridad 4.
- El *digest* fija la imagen, pero el modelo de vLLM y su lanzamiento viven fuera del repositorio (`G:\models`). Un cambio allí sí invalida ahora la política si cambia `LLAMA_GENERATION_MODEL`, pero no si se sustituyen los pesos con el mismo nombre servido.
