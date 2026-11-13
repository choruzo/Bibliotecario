# Render de figuras declarativas en el chat (web)

Fecha: 2026-11-13. Componente: `apps/web/app/chat/figures/`, vista del chat
`apps/web/app/chat/chat-view.tsx`.

## Qué consume la web

El mensaje del turno lleva `figures` (lista, `0` o `1` elemento; los mensajes
antiguos vienen sin el campo o con `[]`). La web no confía en esa lista: cada
valor pasa por `parseFigure(value): Figure | null` (`figures/types.ts`), un
guarda en tiempo de ejecución que espeja `validate_figure` de la API
(`apps/api/bibliotecario/figures.py`) y el contrato congelado
(`figures-contract.md`):

- `kind` debe ser uno de `table | timeline | bars | steps`.
- La raíz acepta exactamente `kind`, `title`, `caption` (opcional),
  `source_citations` y la clave de datos del `kind`. Cualquier otra clave
  (raíz o nivel anidado) descarta la figura: no hay campos `html`, `css`,
  `script`, `href`, `src`, `url` ni `style` posibles.
- Los tipos de cada campo, los límites de tamaño y la presencia/distinción de
  las citas se comprueban como en la API (título 1..120, `caption` ≤ 240,
  `source_citations` 1..4, columnas 2..6, filas ≤ 12, celdas ≤ 240, eventos
  ≤ 12, series ≤ 12, pasos ≤ 8, citas por dato 1..3, `value` número finito ≥ 0).
- El texto debe ser texto plano: sin caracteres de control, sin ancho cero, sin
  saltos de línea y no vacío tras `strip()`.
- Si algo no encaja, `parseFigure` devuelve `null`: nunca lanza.

La API ya validó y saneó la figura al guardarla; el guarda es la segunda
barrera (defensa en profundidad), no la única. Lo que la API sí comprueba y el
guarda no puede es el cruce de números con el corpus (`unsupported_number`):
eso solo la API lo puede saber.

## Política de descarte

- Figura de `kind` desconocido → `null` → no se pinta.
- Figura con un campo extra (raíz o anidado) → `null` → no se pinta.
- Figura que supera un límite, con texto prohibido o con citas ausentes o
  repetidas → `null` → no se pinta.
- En todos los casos el resto del mensaje sigue funcionando: el texto
  (renderizado por `react-markdown` con `skipHtml`) y las citas del turno no
  se ven afectadas. Una figura mala nunca rompe un mensaje.

## Cómo se pinta cada tipo

`FigureBlock` (`figures/figure-block.tsx`) reparte por `kind` a un componente
fijo; el `default` devuelve `null` (cubrirá tipos futuros sin pintar nada).

- `table` (`TableFigure`): `<table>` con `<caption>` (el título), `<thead>`
  con las columnas y `<tbody>` con las filas. El contenedor
  `.figure-table-wrap` tiene `overflow-x: auto`, `tabIndex={0}`, `role="region"`
  y `aria-label`, para desplazar la tabla con teclado en pantallas estrechas.
  Las citas van como chips bajo la tabla (la tabla cita a nivel de figura).
- `timeline` (`TimelineFigure`): `<ol>` con cada evento: `when` como texto
  literal (sin parsear fechas ni objetos `Date`), `label` y las citas del
  evento junto a su etiqueta.
- `bars` (`BarsFigure`): cada serie es una fila etiqueta + barra + valor con
  `unit`. El ancho de la barra es un porcentaje contra el máximo de la serie:
  `Math.round(value / max * 100)`, acotado a `0..100`, con un mínimo visible
  del 2 % para valores mayores que cero. El único `style` en línea es ese
  número calculado (`width: 40%`); nunca una cadena del modelo. No hay ejes ni
  escalas automáticas. El gráfico lleva `role="img"` con `aria-label` que
  incluye título y valores, y fuera de él una lista textual equivalente
  oculta (`.figure-sr-only`) para lectores de pantalla. Las citas van como
  chips bajo el gráfico (dentro de `role="img"` un botón no sería alcanzable).
- `steps` (`StepsFigure`): `<ol>` con `label`, `detail` opcional y las citas
  de cada paso.

### Chips de cita

Cada cita se pinta como chip `[C1]`. Si el `citation_id` existe en
`message.sources`, es un botón que abre el panel «Fragmento citado» ya
existente (`showSource`, con el mismo `data-citation` para devolver el foco al
cerrar). Si no existe, se pinta como texto plano `[C9]`: nunca un botón muerto.
Ubicación por tipo: `table` y `bars` las citan a nivel de figura (debajo);
`timeline` y `steps` las citan por dato (junto a cada evento o paso).

## Accesibilidad

- Tabla: `<caption>` como título accesible; contenedor desplazable con teclado
  (`tabIndex={0}` + `role="region"` + `aria-label`).
- Barras: `role="img"` con `aria-label` («Título. Etiqueta: 5 cuadros. …») y
  lista textual equivalente fuera del elemento con `role="img"`.
- Línea de tiempo y pasos: `<ol>` nativos con `[li]`, numerales del propio
  navegador; el orden del contrato es el orden del DOM.
- Los chips son `<button type="button">` con nombre accesible `[C1]`, igual
  que las citas del texto.

## Impresión

`@media print` evita cortar una figura entre páginas (`break-inside: avoid`)
y garantiza que los chips de cita salgan impresos con borde y tinta oscura.

## Por qué no HTML ni recursos externos

El modelo nunca produce HTML: produce datos tipados. La web renderiza con
componentes fijos de React, que escapan el texto de forma natural, así que no
hay `dangerouslySetInnerHTML`, ni `sanitize-html`, ni `iframe`, ni
`allow-scripts`; no hay `<img>`, ni fuentes externas, ni peticiones de red
desde la figura (todo el estilo es CSS local con los tokens de la casa en
`:root`, sin `position: fixed` ni alturas que rompan el scroll móvil). Si
algún día hace falta un campo nuevo, se añade al contrato cerrado con test en
la API y en la web: no se abre un campo libre.

## Cómo se comprueba

`apps/web/tests/chat-figures.spec.ts` (Playwright, proyectos `desktop` y
`mobile`, mock de `/api/chat/**`):

1. tabla + línea de tiempo en dos mensajes, chips que abren el fragmento y
   enlace «Descargar original» correcto;
2. barras y pasos: valores con unidad, orden de pasos, `aria-label`, lista
   textual y, en el proyecto móvil (390 px), `scrollWidth <= innerWidth` y la
   tabla desplazable dentro de su contenedor con teclado;
3. tolerancia: `kind` desconocido, campo extra y cita inexistente no rompen el
   mensaje; la figura inválida no se pinta y la cita desconocida sale como
   texto.
