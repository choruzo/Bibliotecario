# Banco de evaluación agnóstico y arnés reproducible

Fecha: 2026-10-01. Prioridad 2 del plan de mejora para documentos de cualquier dominio. Sucede a `model-pinning-gemma.md`. No cambia el código del API, los *prompts* ni la firma de política: solo publica corpus, añade bancos y scripts, y recalibra.

## Corpus publicado

`scripts/h4/publish_agnostic.py` sube por la API los 17 PDF de licencia abierta de `.artifacts/agnostic-corpus/` (`POST /admin/documents`, revisión y publicación, como `bee_chat_check.py republish`). Es idempotente: omite los que ya tienen una versión publicada con el mismo SHA-256. Genera `evaluation/h3/agnostic_corpus_catalog.json` con identificador (`AGN-001` … `AGN-017`), dominio, licencia y SHA-256 del original, sin texto de los documentos.

| ID | Documento | Dominio |
| --- | --- | --- |
| AGN-001 | Abeja europea (ya publicada) | biología |
| AGN-002 | Sistema solar | astronomía |
| AGN-003 | Diabetes mellitus | medicina |
| AGN-004 | Tabla periódica de los elementos | química |
| AGN-005 | Copa Mundial de Fútbol | deporte |
| AGN-006 | IRPF (España) | fiscalidad |
| AGN-007 | Revolución francesa | historia |
| AGN-008 | Fotosíntesis | biología vegetal |
| AGN-009 | Dieta mediterránea | nutrición |
| AGN-010 | Python | informática |
| AGN-011 | Inflación | economía |
| AGN-012 | Volcán | geología |
| AGN-013 | Café | agroalimentación |
| AGN-014 | Constitución Española (BOE) | derecho |
| AGN-015 | Ley de Propiedad Horizontal (BOE) | derecho |
| AGN-016 | Attention Is All You Need (arXiv, inglés) | inteligencia artificial |
| AGN-017 | BERT (arXiv, inglés) | inteligencia artificial |

La publicación de los 16 nuevos tardó entre 57 y 176 s por documento (conversión más indexación), unos 35 minutos en total. La biblioteca activa tiene 30 documentos.

## Bancos

`evaluation/h3/agnostic-calibration-v1.jsonl` y `agnostic-validation-v1.jsonl`, 32 casos cada uno:

| Clase | Calibración | Validación |
| --- | ---: | ---: |
| answerable | 16 | 16 |
| unanswerable | 6 | 6 |
| ambiguous | 3 | 3 |
| conversation | 7 (3 grupos) | 7 (3 grupos) |

- Respondibles: datos de tablas (satélites de Júpiter, pupa de la obrera, finales del Mundial, producción de café, recaudación del IRPF, temperatura óptima C4, mutabilidad de `bytes`), cifras y fechas en prosa, dos preguntas sí/no coloquiales y otras coloquiales sin tildes ni signos.
- Inglés en primer turno: dos sobre los artículos de arXiv (fuente en inglés) y dos translingües sobre documentos en español (`cross_lingual`).
- Irrespondibles: tres fuera del corpus (temporales, futuras o personales) y tres con premisa falsa por banco (p. ej., «¿Por qué Brasil ganó el Mundial de 1950 en su propio país?»).
- Ambiguos: preguntas sin referente («¿Cuánto mide?», «¿Quién lo creó?»).
- Seguimientos: «¿Y Argentina?», «¿En qué años?», «En ese artículo, …», «¿Y de plantas CAM?». Cada turno posterior al primero lleva `subject`, el término que la consulta reformulada debe conservar.

Ningún grupo conversacional se reparte entre bancos y cada banco cumple los mínimos de H0. Las secciones esperadas se comprobaron contra los encabezados del Markdown normalizado publicado. En los textos del BOE y de arXiv la estructura de encabezados es plana, así que esos casos solo esperan documento. `tests/test_agnostic_banks.py` fija este contrato y comprueba el SHA-256 del catálogo si el corpus está descargado.

## Scripts

- `scripts/h3/calibrate_library.py` admite varios bancos y catálogos: `--calibration-bank`, `--validation-bank` y `--catalog` aceptan varias rutas. Rechaza identificadores repetidos de caso o de fuente. Con una sola ruta por opción, el comportamiento y los SHA-256 del informe son los de antes; el informe añade `banks` con el SHA-256 de cada banco.
- `scripts/h4/agnostic_acceptance.py` (sucesor de `bee_chat_check.py chat`) pasa uno o más bancos por el chat real. Los grupos comparten conversación. En cada turno comprueba:
  - el estado esperado (respuesta, abstención o aclaración) y que alguna fuente sea un documento esperado;
  - que cada cita sea literalmente su pasaje recuperado y aparezca citada en la respuesta;
  - que las cifras de la respuesta (`bibliotecario.chat.numbers`) figuren en los pasajes, títulos o apartados citados;
  - que la consulta reformulada conserve `subject`;
  - que el original descargado coincida con el SHA-256 citado y con el del catálogo.

  Guarda el detalle con pasajes en `.artifacts/agnostic-acceptance/` y un resumen sin pasajes, por clase y por dominio, en `evaluation/h3/agnostic-acceptance-<ámbito>[-etiqueta].json`.

## Política heredada antes de recalibrar (prioridad 8)

Tras publicar el corpus, el chat siguió usando la política aprobada del corpus técnico (`policy_inherited: true`). Con ella se pasaron los dos bancos agnósticos completos (64 turnos) antes de recalibrar (`agnostic-acceptance-admin-inherited.json`):

- 61 de 64 correctos, **0 respuestas indebidas** y 0 cifras sin respaldo. Las 12 preguntas irrespondibles y las 6 ambiguas acabaron en abstención o aclaración.
- 45 respuestas: 33 `grounded` y 12 `grounded_extract`.

En esta muestra, heredar el umbral al publicar documentos de otros dominios no introdujo respuestas indebidas. Es una muestra pequeña: no garantiza nada para otros corpus.

Repetición operativa: la primera pasada marcó dos `unsupported_number` en respuestas extractivas del BOE. Era un falso positivo del arnés: la respuesta extractiva muestra cada pasaje bajo su encabezado documental («TEXTO CONSOLIDADO Última modificación: 20 de mayo de 2026») y el arnés solo admitía cifras de las citas. Se corrigió para admitir también títulos y apartados citados, igual que la validación del API, y el informe se recalculó sobre las respuestas guardadas sin repetir el chat.

## Calibración combinada

Bancos técnicos coloquiales y agnósticos juntos: 64 casos de calibración y 63 de validación por ámbito. Se ejecutaron en secuencia, unos 20 minutos por ámbito, sin errores de proveedor.

```bash
.venv/Scripts/python.exe scripts/h3/calibrate_library.py --scope admin \
  --calibration-bank evaluation/h3/colloquial-calibration-v1.jsonl evaluation/h3/agnostic-calibration-v1.jsonl \
  --validation-bank evaluation/h3/colloquial-validation-v1.jsonl evaluation/h3/agnostic-validation-v1.jsonl \
  --catalog evaluation/h0/corpus_catalog.json evaluation/h3/agnostic_corpus_catalog.json
# después, igual con --scope usuario
```

| Resultado | Administrador | Usuario |
| --- | ---: | ---: |
| Aprobada | sí | sí |
| Umbral | −1,2932 | −1,2932 |
| Positivos aceptados en validación | 45 de 46 | 45 de 46 |
| Respuestas indebidas (calibración y validación) | 0 | 0 |
| Negativos correctos en validación | 17 de 17 | 17 de 17 |
| Aclaraciones correctas, ambos bancos | 100 % | 100 % |
| Cobertura media de apartados aceptados | 0,972 | 0,972 |

El umbral no cambia respecto a la política anterior. Por dominio, en validación todos los positivos agnósticos se aceptan salvo uno (biología, 1 de 2). El banco técnico acepta 23 de 23. En calibración, los únicos positivos rechazados son técnicos (`EVAL-A008` y `EVAL-C002-T3` por abstención de la evaluación de cobertura, y `EVAL-A009` por aclaración); los 25 positivos agnósticos de calibración se aceptan.

El positivo rechazado en validación es «How long does a queen bee live?» (`AGN-VAL-A016`, puntuación −2,65): una pregunta en inglés sobre un documento en español queda por debajo del umbral (prioridad 7). Su pareja de calibración, «What is the capital of Spain according to the Constitution?», sí se respondió. El comportamiento translingüe depende, pues, de la pregunta.

## Aceptación con la política nueva

- `colloquial_acceptance.py`: 13 de 13.
- `agnostic_acceptance.py` (ambos bancos, administrador): **61 de 64**, 0 indebidas, 0 cifras sin respaldo, 0 citas no literales, 0 sujetos perdidos y 0 SHA-256 discrepantes. 35 respuestas `grounded` y 10 `grounded_extract`; mediana de 13,6 s por respuesta y máximo de 28,9 s.

| Dominio | Correctas |
| --- | ---: |
| agroalimentación | 2/2 |
| astronomía | 3/3 |
| biología | 2/3 |
| biología vegetal | 3/3 |
| deporte | 5/5 |
| derecho | 5/5 |
| economía | 1/1 |
| fiscalidad | 4/4 |
| geología | 2/2 |
| historia | 2/2 |
| informática | 2/2 |
| inteligencia artificial | 7/7 |
| medicina | 4/4 |
| nutrición | 1/1 |
| química | 2/2 |
| sin documento (irrespondibles y ambiguas) | 16/18 |

Los tres fallos son conocidos y no son respuestas indebidas:

1. `AGN-VAL-A016`, la pregunta translingüe sobre la reina, se abstiene (prioridad 7).
2. `AGN-VAL-U002` («¿Cuántas abejas hay ahora mismo en mi colmena?») y `AGN-VAL-U003` («¿Qué glucemia me salió en mi último análisis de sangre?») piden aclaración en lugar de abstenerse. La salvaguarda de referentes trata el posesivo «mi» como un referente sin sujeto. El usuario no recibe una respuesta inventada, pero la aclaración («¿qué documento… quieres consultar?») no le sirve: el dato no existe en la biblioteca. El banco mantiene la expectativa estricta de abstención para seguir midiendo este caso.

Las preguntas con premisa falsa se abstuvieron en todos los casos, sin corregir la premisa. Es seguro, aunque una respuesta que señalase la contradicción («ganó Uruguay») sería más útil.

## Pendiente

- Prioridad 7: preguntas en inglés en primer turno sobre documentos en español.
- Distinguir los datos personales o del momento presente («mi colmena», «este mes») de los referentes sin sujeto, para abstenerse en vez de pedir aclaración.
- Las prioridades 3 a 6 pueden medirse ya con estos bancos y el arnés.
