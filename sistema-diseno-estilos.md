# Sistema de Diseño — Guía de Estilos

> Documento de referencia para mantener consistencia visual en futuros diseños. Tema oscuro fijo, sin build step — todo vive en variables CSS de `:root` y clases reutilizables.

---

## 1. Principios generales

- **Un único acento "caliente":** el verde es el único color que se usa para llamar la atención positivamente (éxito, marca, acción principal). No se duplica con otro color para el mismo propósito.
- **Color siempre semántico, nunca decorativo:** rojo = error/fail, ámbar = advertencia/pendiente, azul = información neutra, verde = éxito/acción principal.
- **Contraste suave:** el texto nunca es blanco puro ni negro puro. Se usa `--text` (texto principal) o `--dim` (metadatos, texto secundario) sobre superficies `--panel` / `--panel2`.
- **Foco visible:** todo elemento interactivo lleva un estado `:focus-visible` marcado — el uso por teclado es un caso real, no un extra.
- **Movimiento con propósito:** una animación solo se añade si comunica estado (en curso, confirmación, atención pendiente). Si no comunica nada, no lleva animación. Todo respeta `prefers-reduced-motion`.
- **Extender sin romper:** un componente nuevo reutiliza las variables de `:root`; no se introducen valores hex sueltos ni librerías de componentes externas.

---

## 2. Color

Paleta oscura fija (no hay tema claro). Doce variables semánticas en `:root`.

| Variable | Hex | Uso |
|---|---|---|
| `--bg` | `#0a1214` | Fondo de página, con degradados radiales sutiles |
| `--panel` | `#0f1b1e` | Superficie de tarjetas, tablas, cabecera |
| `--panel2` | `#122226` | Superficie secundaria: hover, campos de formulario, insignia neutra |
| `--line` | `#1b3237` | Bordes y separadores |
| `--text` | `#cfe3de` | Texto principal |
| `--dim` | `#6f8b86` | Texto secundario, metadatos, etiquetas |
| `--verde` | `#34d399` | Acento primario, éxito (PASS), marca |
| `--verde2` | `#0d9488` | Verde de superficie: botón primario, bordes de énfasis |
| `--azul` | `#38bdf8` | Enlaces, información, spinners "en curso" |
| `--azul2` | `#155e75` | Fondo de insignia informativa, borde de citas |
| `--ambar` | `#e8b545` | Advertencia, INCONCLUSO, pendiente de revisión |
| `--rojo` | `#e77070` | Error, FAIL — exclusivo, nunca decorativo |

**Cuándo usar cada uno:**
- **Verde** — acento primario y éxito. Único color "caliente" del sistema.
- **Rojo** — exclusivo para fallo/error.
- **Ámbar** — advertencia o algo que necesita revisión humana; debe atraer al revisor.
- **Azul** — información neutra; no implica éxito ni fallo.

---

## 3. Tipografía

Una sola familia para toda la interfaz; monoespaciada reservada a datos (contadores, hex, spinners).

```css
--sans: "Segoe UI", system-ui, -apple-system, sans-serif;
--mono: ui-monospace, "Cascadia Code", SFMono-Regular, Consolas, monospace;
```

### Escala tipográfica

| Tamaño | Uso |
|---|---|
| 1.7rem | Número principal de tarjeta (contador) |
| 1.05rem | Título de detalle |
| 1rem | Título de cabecera |
| .98rem | Título de elemento de revisión |
| .92rem | Botón primario, pestañas de navegación |
| .9rem | Celdas de tabla |
| .88rem | Campos de formulario |
| .85rem | Puntos de criterio, texto de meta |
| .8rem | Metadatos, insignias de salud |
| .78rem | Etiquetas en mayúsculas |
| .75rem | Texto de insignia |
| .72rem | Leyenda de gráficos apilados |

Base del body: `font-size: 15px`, `line-height: 1.5`.

---

## 4. Espaciado y radios

No hay escala numérica declarada formalmente — son valores que se repiten por convención. Reutilizar antes de inventar uno nuevo.

**Radios de borde:**

| Radio | Uso |
|---|---|
| 3px | Barra de progreso |
| 4px | Segmento apilado |
| 6px | Botón mini, input, miniatura |
| 8px | Botón primario, aviso |
| 10px | Tarjeta, tabla, panel |
| 99px | Insignia (píldora) |

**Espaciados frecuentes:** `.2rem · .35rem · .45rem · .6rem · .8rem · 1rem · 1.2rem · 1.6rem`

---

## 5. Componentes

### Botones

- `button.primario` — única acción principal por vista. Fondo `--verde2`, texto oscuro (`#04211c`), negrita, radio 8px. Hover: brillo +15%. Active: escala 0.96. Disabled: fondo `--panel2`, texto `--dim`.
- `button.mini` — acciones secundarias y decisiones de revisión. Fondo `--panel2`, borde `--line`, radio 6px.
  - `.pass` → borde `--verde2`
  - `.fail` → borde rojo oscuro (`#7a2e2e`)
  - `.inc` → borde ámbar oscuro (`#8a6d1d`)

```css
button.primario{background:var(--verde2);border:0;color:#04211c;font-weight:600;
  padding:.55rem 1.1rem;border-radius:8px}
button.mini{background:var(--panel2);border:1px solid var(--line);color:var(--text);
  padding:.3rem .8rem;border-radius:6px;font-size:.82rem}
```

### Insignias (badges)

Codifican estado (run, paso, veredicto) con color; si el estado está en curso, incluyen spinner. Forma píldora (`border-radius:99px`).

- `.b-pass` — fondo `#0b3a2b`, texto verde
- `.b-fail` — fondo `#3d1616`, texto rojo
- `.b-inc` — fondo `#3a2f10`, texto ámbar
- `.b-info` — fondo `--azul2`, texto azul
- `.b-dim` — fondo `--panel2`, texto `--dim`

### Tarjetas

Bloque mínimo: número grande + etiqueta, o cabecera + cuerpo. Fondo `--panel`, borde `--line`, radio 10px. Elevan levemente (`translateY(-3px)`) y cambian borde a `--verde2` al hover, para indicar que llevan a un detalle.

### Tablas y progreso

- Fondo `--panel`, borde 1px, sin líneas verticales internas, radio 10px con overflow oculto.
- Cabeceras en mayúsculas, `--dim`, `.75rem`.
- Barra de progreso: altura 3px, degradado `--verde2` → `--azul`. En estado activo añade animación `shimmer`.

### Formularios

Campos con fondo `--panel2`, borde `--line`, radio 6px. Foco: borde cambia a `--verde2`, sin halo adicional.

### Animaciones

Seis keyframes cubren todo el panel; todas respetan `prefers-reduced-motion`.

| Nombre | Uso | Duración |
|---|---|---|
| `fadeUp` | Entrada de tarjetas, filas y bloques | .28–.4s ease |
| `fadeIn` | Aparición de overlays | .2–.4s ease |
| `popIn` | Imagen ampliada en lightbox | .22s ease |
| `latido` | Punto de salud "ok", spinner en vivo | 2.6s / 1.6s infinito |
| `shimmer` | Barra de progreso activa | 1.6s linear infinito |
| `halo` | Elemento de revisión pendiente | 2.4s ease-in-out infinito |

### Patrones compuestos

- **Revisión pendiente (halo):** tarjeta con animación `halo` continua + badge `.b-inc`, para señalar algo que espera revisión humana.
- **Indicador de salud:** punto pequeño con animación `latido` + texto `--dim` (p. ej. "API — conectada").

---

## 6. Notas de implementación

- Todo el CSS vive en un único `<style>`, sin preprocesador ni build step.
- Un componente nuevo se añade directamente reutilizando las variables de `:root` — nunca un hex suelto.
- `color-scheme: dark` está fijado; no se contempla modo claro en este sistema.
