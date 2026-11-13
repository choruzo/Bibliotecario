/* Contrato de figuras declarativas (docs/h6/figures-contract.md), lado web.

   La API ya valida cada figura antes de guardarla; este guarda es la barrera
   de la web: rechaza (devuelve null, nunca lanza) cualquier objeto que no
   encaje con el contrato cerrado, y los componentes fijos solo reciben lo que
   `parseFigure` acepta. Espeja `apps/api/bibliotecario/figures.py`. */

export type FigureSource = {
  citation_id: string;
  title: string;
  version: number;
  quote: string;
  locator: { page?: number; section_path?: string[]; line_start?: number; line_end?: number };
};

export type TableData = { columns: string[]; rows: string[][] };
export type TimelineEvent = { when: string; label: string; citations: string[] };
export type TimelineData = { events: TimelineEvent[] };
export type BarSeries = { label: string; value: number; citations: string[] };
export type BarsData = { unit: string; series: BarSeries[] };
export type StepItem = { label: string; citations: string[]; detail?: string };
export type StepsData = { items: StepItem[] };

export type Figure =
  | { kind: 'table'; title: string; caption?: string; source_citations: string[]; table: TableData }
  | { kind: 'timeline'; title: string; caption?: string; source_citations: string[]; timeline: TimelineData }
  | { kind: 'bars'; title: string; caption?: string; source_citations: string[]; bars: BarsData }
  | { kind: 'steps'; title: string; caption?: string; source_citations: string[]; steps: StepsData };

type Raw = Record<string, unknown>;

/* Caracteres de control, de ancho cero y de formato: el contrato es texto
   plano, igual que el `_FORBIDDEN` de la API. */
const FORBIDDEN = /[\x00-\x1F\x7F\u200B-\u200F\u2060-\u2064\uFEFF]/;

function isObject(value: unknown): value is Raw {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/* Texto plano saneado: sin caracteres prohibidos, no vacío tras strip() y
   dentro del límite. La longitud se mide sobre el texto saneado. */
function cleanText(value: unknown, max: number, min = 1): string | null {
  if (typeof value !== 'string' || FORBIDDEN.test(value)) return null;
  const text = value.trim();
  if (text.length < min || text.length > max) return null;
  return text;
}

/* Citas: lista de marcadores distintos, no vacía, sin texto prohibido. */
function citations(value: unknown, max: number): string[] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > max) return null;
  const markers: string[] = [];
  for (const marker of value) {
    if (typeof marker !== 'string' || FORBIDDEN.test(marker)) return null;
    const marker_text = marker.trim();
    if (!marker_text) return null;
    markers.push(marker_text);
  }
  return new Set(markers).size === markers.length ? markers : null;
}

/* Solo claves declaradas en cualquier nivel (contrato cerrado). */
function onlyKeys(data: Raw, allowed: readonly string[]): boolean {
  return Object.keys(data).every(key => allowed.includes(key));
}

function parseTable(data: unknown): TableData | null {
  if (!isObject(data) || !onlyKeys(data, ['columns', 'rows'])) return null;
  const rawColumns = data['columns'];
  if (!Array.isArray(rawColumns) || rawColumns.length < 2 || rawColumns.length > 6) return null;
  const columns: string[] = [];
  for (const column of rawColumns) {
    const text = cleanText(column, 80);
    if (!text) return null;
    columns.push(text);
  }
  const rawRows = data['rows'];
  if (!Array.isArray(rawRows) || rawRows.length < 1 || rawRows.length > 12) return null;
  const rows: string[][] = [];
  for (const row of rawRows) {
    if (!Array.isArray(row) || row.length !== columns.length) return null;
    const cells: string[] = [];
    for (const cell of row) {
      const text = cleanText(cell, 240);
      if (!text) return null;
      cells.push(text);
    }
    rows.push(cells);
  }
  return { columns, rows };
}

function parseTimeline(data: unknown): TimelineData | null {
  if (!isObject(data) || !onlyKeys(data, ['events'])) return null;
  const rawEvents = data['events'];
  if (!Array.isArray(rawEvents) || rawEvents.length < 1 || rawEvents.length > 12) return null;
  const events: TimelineEvent[] = [];
  for (const event of rawEvents) {
    if (!isObject(event) || !onlyKeys(event, ['when', 'label', 'citations'])) return null;
    const when = cleanText(event['when'], 40);
    const label = cleanText(event['label'], 160);
    const marks = citations(event['citations'], 3);
    if (!when || !label || !marks) return null;
    events.push({ when, label, citations: marks });
  }
  return { events };
}

function parseBars(data: unknown): BarsData | null {
  if (!isObject(data) || !onlyKeys(data, ['unit', 'series'])) return null;
  const unit = cleanText(data['unit'], 16);
  if (!unit) return null;
  const rawSeries = data['series'];
  if (!Array.isArray(rawSeries) || rawSeries.length < 1 || rawSeries.length > 12) return null;
  const series: BarSeries[] = [];
  for (const entry of rawSeries) {
    if (!isObject(entry) || !onlyKeys(entry, ['label', 'value', 'citations'])) return null;
    const label = cleanText(entry['label'], 80);
    const marks = citations(entry['citations'], 3);
    if (!label || !marks) return null;
    const value = entry['value'];
    if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return null;
    series.push({ label, value, citations: marks });
  }
  return { unit, series };
}

function parseSteps(data: unknown): StepsData | null {
  if (!isObject(data) || !onlyKeys(data, ['items'])) return null;
  const rawItems = data['items'];
  if (!Array.isArray(rawItems) || rawItems.length < 1 || rawItems.length > 8) return null;
  const items: StepItem[] = [];
  for (const entry of rawItems) {
    if (!isObject(entry) || !onlyKeys(entry, ['label', 'detail', 'citations'])) return null;
    const label = cleanText(entry['label'], 120);
    const marks = citations(entry['citations'], 3);
    if (!label || !marks) return null;
    const item: StepItem = { label, citations: marks };
    if (entry['detail'] !== undefined && entry['detail'] !== null) {
      const detail = cleanText(entry['detail'], 240);
      if (!detail) return null;
      item.detail = detail;
    }
    items.push(item);
  }
  return { items };
}

/* Devuelve la figura tipada si y solo si encaja con el contrato congelado:
   `kind` conocido, claves exactas en la raíz y en el payload, tipos correctos,
   límites de tamaño y citas presentes y distintas. Cualquier otra cosa es
   null; nunca lanza. El número y la figura no se cruzan contra el corpus aquí:
   eso lo garantiza la API con `validate_figure`. */
export function parseFigure(value: unknown): Figure | null {
  if (!isObject(value)) return null;
  const kind = value['kind'];
  if (kind !== 'table' && kind !== 'timeline' && kind !== 'bars' && kind !== 'steps') return null;
  if (!onlyKeys(value, ['kind', 'title', 'caption', 'source_citations', kind])) return null;
  const title = cleanText(value['title'], 120);
  if (!title) return null;
  let caption: string | undefined;
  if (value['caption'] !== undefined && value['caption'] !== null) {
    caption = cleanText(value['caption'], 240) ?? undefined;
    if (!caption) return null;
  }
  const sourceCitations = citations(value['source_citations'], 4);
  if (!sourceCitations) return null;
  const body = value[kind];
  if (!isObject(body)) return null;
  switch (kind) {
    case 'table': {
      const table = parseTable(body);
      if (!table) return null;
      return caption !== undefined
        ? { kind, title, caption, source_citations: sourceCitations, table }
        : { kind, title, source_citations: sourceCitations, table };
    }
    case 'timeline': {
      const timeline = parseTimeline(body);
      if (!timeline) return null;
      return caption !== undefined
        ? { kind, title, caption, source_citations: sourceCitations, timeline }
        : { kind, title, source_citations: sourceCitations, timeline };
    }
    case 'bars': {
      const bars = parseBars(body);
      if (!bars) return null;
      return caption !== undefined
        ? { kind, title, caption, source_citations: sourceCitations, bars }
        : { kind, title, source_citations: sourceCitations, bars };
    }
    default: {
      const steps = parseSteps(body);
      if (!steps) return null;
      return caption !== undefined
        ? { kind, title, caption, source_citations: sourceCitations, steps }
        : { kind, title, source_citations: sourceCitations, steps };
    }
  }
}
