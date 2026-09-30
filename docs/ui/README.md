# Revisión de interfaz y accesibilidad

Fecha: 30 de septiembre de 2026.

Se revisaron el acceso, el chat de usuarios y las vistas administrativas de servicios, documentos, trabajos, recuperación y operaciones. La revisión combina inspección visual en Chrome, auditorías Lighthouse y pruebas de navegador con datos sintéticos; no modifica el corpus ni ejecuta ingestas o reindexaciones reales.

## Correcciones

- Tema oscuro fijo según `sistema-diseno-estilos.md`: paleta de doce variables semánticas en `:root` (verde éxito/acción principal, rojo error, ámbar revisión o espera, azul información o proceso en curso). Se retiró el alternador claro/oscuro porque el sistema de diseño no contempla tema claro.
- Insignias de estado en documentos, trabajos, lotes y trazas; tarjetas de resumen en servicios y operación; barra de progreso con degradado y animación solo mientras el trabajo está en curso; animaciones de estado desactivadas con `prefers-reduced-motion`.
- Paleta común para fondos, texto, campos, avisos, errores, selección, enlaces y foco.
- Distribución adaptable a 320 píxeles, títulos y citas largos, controles que se pueden repartir en varias líneas y metadatos en una columna en móvil.
- Casillas de selección con dimensiones propias, independientes de los campos de texto.
- Tablas anchas contenidas en regiones desplazables con acceso por teclado, encabezados de columna identificados y tablas Markdown con desplazamiento local.
- Enlace para saltar al contenido, foco visible, áreas de interacción ampliadas y respeto por movimiento reducido y colores forzados.
- Diálogos con navegación circular por teclado, cierre con Escape y devolución del foco al botón de apertura, incluyendo operaciones asíncronas.
- Fragmentos citados con foco al abrir y retorno al control de cita al cerrar.
- Respuestas del chat con Markdown y citas interactivas; el contenido HTML y las imágenes externas no se ejecutan ni cargan.
- Enlaces de operaciones a páginas de documentos y trazas en la aplicación, en lugar de respuestas JSON. El documento enlazado se puede consultar aunque no aparezca en la página actual de la lista.
- Listas vacías con recuentos correctos.

## Validación

`npm run typecheck` y `npm run build` terminan correctamente.

La suite Playwright termina con **20 pruebas superadas y 8 omitidas**, en proyectos de escritorio y móvil. Incluye el tema del sistema, alternancia y persistencia de la elección, navegación con teclado, pantallas de 320 píxeles en ambos modos, documentos con vista previa, trabajos, configuración, trazas, Markdown y citas del chat, y foco de diálogos. Las ocho pruebas omitidas necesitan Compose y una cuenta mediante `BIB_E2E_CREDENTIALS`; no se ejecutaron contra datos reales.

Capturas de las pruebas: `.artifacts/ui-audit/final-tests/`. Informes Lighthouse de las vistas en ambos temas: `.artifacts/ui-audit/lighthouse/`.

Las **14 auditorías Lighthouse** en modo snapshot y perfil móvil obtienen **100/100 en accesibilidad**: acceso, servicios, operaciones, documento seleccionado, trabajos, traza de recuperación y chat con una conversación abierta, cada uno en modo claro y oscuro. Los informes completos y la correspondencia de vista/tema están en `summary.json` dentro de la carpeta indicada.

Los criterios de revisión se basan en [WCAG 2.2 del W3C](https://www.w3.org/TR/WCAG22/) y sus guías sobre [redistribución del contenido](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html), [contraste](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), [foco visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html) y [tamaño mínimo de objetivos](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html). Las auditorías automáticas no certifican conformidad completa ni sustituyen una prueba manual con lectores de pantalla.
