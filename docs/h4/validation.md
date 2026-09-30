# Validación de H4 — 2026-09-30

## Resultado

H4 implementado en API, migración PostgreSQL y web. API/worker/web actualizados en Docker Compose sin borrar ni reemplazar datos de la biblioteca. Migración aditiva `0005_h4` aplicada.

- Suite API H1–H4: **69 pruebas aprobadas**, con una advertencia de deprecación heredada de Starlette/TestClient.
- Revalidación específica: **13 pruebas de H4 aprobadas** tras ajustar el presupuesto del modelo; **3 casos aprobados** tras añadir el resultado final a la traza administrativa.
- TypeScript: `npm run typecheck` aprobado.
- Compilación de producción Next.js y construcción Docker API/web: aprobadas.
- Playwright contra la web compilada en Compose: **8 pruebas aprobadas**, escritorio y móvil. Cubren conversaciones, preferencias, streaming, citas navegables, fragmentos, enlace al original, explicación general diferenciada, recarga y permisos de navegación. Los casos de respuesta positiva usan respuestas API controladas.
- Ensayo HTTP real con PostgreSQL, embeddings, reranker y LiteLLM: creación/renombrado/preferencias, dos recuperaciones, reformulación del seguimiento y abstención ante preguntas sin cobertura aprobados.
- Persistencia tras recrear API y web: cuatro mensajes y preferencias conservados.
- Adaptador real de generación: **64 partes de streaming** recibidas desde LiteLLM; JSON, cita y verificador semántico aprobados con una fuente sintética.

Los resultados privados y capturas están en `.artifacts/h4/`. Las pruebas no habilitan umbrales artificiales ni alteran publicaciones o políticas de la biblioteca. El ensayo deja una conversación sintética identificada en `.artifacts/h4/acceptance.json`.

## Casos de seguridad comprobados en API

Conversaciones ajenas y originales de sus citas no son accesibles; las mutaciones exigen CSRF/Origin. Sin evidencia no se genera una respuesta documental. El seguimiento vuelve a recuperar con consulta autónoma y permisos del usuario. Citas falsas y rechazo del verificador producen abstención sin emitir el contenido rechazado. Retirar una fuente durante generación invalida la respuesta. Fallos de proveedor conservan preguntas y liberan el lease. Un lease activo bloquea el turno simultáneo; un lease caducado permite continuar y marca el anterior interrumpido. Resúmenes no incorporan respuestas anteriores como hechos. Una política administrativa no habilita respuestas para el ámbito de usuario. Streams incompletos o terminados por límite de tokens se rechazan.

## Límites y ajustes del ensayo

En la validación inicial de H4 la calibración de H3 seguía rechazada y el chat conservaba la abstención. La generación positiva se comprobó con fuentes sintéticas y pruebas controladas; ese ensayo no demostraba suficiencia del corpus real ni calidad pedagógica en todo el banco H0. Se añadió calibración independiente por ámbito y firma sensible a metadatos/visibilidad. La corrección posterior y la evaluación de la biblioteca publicada se documentan en `docs/h3/calibration-fix.md`.

La validación semántica usa el mismo proveedor generativo en una llamada separada y es probabilística. No sustituye la evaluación adversarial de H7. Los IDs y pasajes completos se verifican determinísticamente; el contenido generado no se envía hasta superar ambos controles. Las citas históricas conservan su fragmento incluso tras retirada; el original deja de descargarse cuando se elimina.

En la revalidación con documentos reales se detectó un fallo de instalación limpia: `0004_h3` importaba el modelo ORM vigente de `EvidencePolicy`, que ya incluía `scope`, y `0005_h4` intentaba añadirlo otra vez. Se fijó explícitamente el esquema histórico de esa tabla en H3. El ensayo aislado comprueba ahora la cadena completa de migraciones desde una base PostgreSQL vacía; la base existente no requiere cambios adicionales.

Pytest dentro del sandbox produjo errores de permisos en temporales de Windows; la suite aprobada se ejecutó fuera del sandbox. Playwright con `next dev` agotó el timeout de arranque; las ocho pruebas se ejecutaron correctamente contra el build de Compose. La primera prueba real del verificador agotó 150 tokens sin contenido final por el razonamiento de gpt-oss: se amplió a 1.200 tokens (reformulación: 900), manteniendo el timeout total y rechazo de respuestas incompletas.
