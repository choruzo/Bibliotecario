import { expect, test, type Page } from '@playwright/test';

/* El chat consume `figures` del mensaje: fixtures con la forma del contrato
   congelado (docs/h6/figures-contract.md), sin servidor real (mock de /api/chat/**). */

const cid = '33333333-3333-4333-8333-333333333333';
const conversationTitle = 'Consultas de apicultura';

function message(id: string, role: string, content: string, sources: unknown[], figures?: unknown[]) {
  return figures
    ? { id, role, content, status: 'completed', sources, figures }
    : { id, role, content, status: 'completed', sources };
}

async function mockChat(page: Page, messages: unknown[]) {
  await page.route('**/api/auth/me', route => route.fulfill({ json: { username: 'lector', role: 'usuario', csrf_token: 'csrf' } }));
  await page.route('**/api/chat/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/conversations') && route.request().method() === 'POST') {
      await route.fulfill({ status: 201, json: { id: cid, title: conversationTitle } });
    } else if (path.endsWith('/conversations')) {
      await route.fulfill({ json: { items: [{ id: cid, title: conversationTitle }] } });
    } else {
      await route.fulfill({ json: { id: cid, title: conversationTitle, preferences: '', busy: false, messages } });
    }
  });
}

const sourceA = { citation_id: 'C1', title: 'Manual de apicultura', version: 3, quote: 'La reina tarda dieciséis días en desarrollarse.', locator: { page: 12 } };
const sourceB = { citation_id: 'C1', title: 'Cuaderno de traslados', version: 1, quote: 'La colmena viajó la madrugada del 12 de mayo.', locator: { section_path: ['Apéndice B', 'Traslado'] } };

const tableFigure = {
  kind: 'table', title: 'Ciclo de desarrollo de las castas', caption: 'Fuente: apéndice A',
  source_citations: ['C1'],
  table: { columns: ['Casta', 'Días de desarrollo'], rows: [['Reina', '16 días'], ['Obrera', '21 días'], ['Zángano', '24 días']] }
};

const timelineFigure = {
  kind: 'timeline', title: 'Cronología del traslado',
  source_citations: ['C1'],
  timeline: { events: [
    { when: '12 de mayo', label: 'Llegada de la colmena', citations: ['C1'] },
    { when: '20 de mayo', label: 'Primera revisión', citations: ['C1'] }
  ] }
};

test('tabla y línea de tiempo con chips de cita que abren el fragmento', async ({ page }) => {
  await mockChat(page, [
    message('u1', 'user', '¿Cuánto tarda cada casta?', []),
    message('m1', 'assistant', 'El ciclo completo depende de la casta [C1].\n\nExplicación general\n\nLos tres roles maduran a ritmos distintos.', [sourceA], [tableFigure]),
    message('m2', 'assistant', 'El traslado añade dos hitos [C1].', [sourceB], [timelineFigure])
  ]);
  await page.goto('/chat');
  await page.getByRole('button', { name: 'Nueva conversación', exact: true }).click();

  const table = page.getByRole('table', { name: 'Ciclo de desarrollo de las castas' });
  await expect(table).toBeVisible();
  await expect(table.locator('caption')).toHaveText('Ciclo de desarrollo de las castas');
  await expect(table.locator('thead th').nth(0)).toHaveText('Casta');
  await expect(table.locator('thead th').nth(1)).toHaveText('Días de desarrollo');
  await expect(table.locator('tbody tr')).toHaveCount(3);
  await expect(table.getByRole('cell', { name: 'Reina' })).toBeVisible();
  await expect(table.getByRole('cell', { name: '16 días' })).toBeVisible();
  await expect(table.getByRole('cell', { name: '24 días' })).toBeVisible();

  await expect(page.locator('.figure-timeline li')).toHaveCount(2);
  await expect(page.locator('.figure-timeline li').nth(0)).toContainText('12 de mayo');
  await expect(page.locator('.figure-timeline li').nth(0)).toContainText('Llegada de la colmena');
  await expect(page.locator('.figure-timeline li').nth(1)).toContainText('20 de mayo');
  await expect(page.locator('.figure-timeline li').nth(1)).toContainText('Primera revisión');

  const tableBlock = page.locator('.figure', { hasText: 'Ciclo de desarrollo de las castas' });
  await tableBlock.getByRole('button', { name: '[C1]', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Fragmento citado' });
  await expect(panel).toContainText('La reina tarda dieciséis días en desarrollarse.');
  await expect(panel).toContainText('Página 12');
  await expect(panel.getByRole('link', { name: 'Descargar original' })).toHaveAttribute('href', '/api/chat/messages/m1/sources/C1/original');
  await page.getByRole('button', { name: 'Cerrar fragmento' }).click();

  const timelineBlock = page.locator('.figure', { hasText: 'Cronología del traslado' });
  // La línea de tiempo cita por evento: cada evento pinta su propio chip.
  await timelineBlock.getByRole('button', { name: '[C1]', exact: true }).first().click();
  await expect(panel).toContainText('La colmena viajó la madrugada del 12 de mayo.');
  await expect(panel.getByRole('link', { name: 'Descargar original' })).toHaveAttribute('href', '/api/chat/messages/m2/sources/C1/original');
});

test('barras y pasos con unidad y orden, sin desbordar en móvil', async ({ page }, info) => {
  const barsFigure = {
    kind: 'bars', title: 'Cuadros por colmena', source_citations: ['C1'],
    bars: { unit: 'cuadros', series: [
      { label: 'Cámara de cría', value: 5, citations: ['C1'] },
      { label: 'Alza melaria', value: 2, citations: ['C1'] }
    ] }
  };
  const stepsFigure = {
    kind: 'steps', title: 'Alimentación de una colonia', source_citations: ['C1'],
    steps: { items: [
      { label: 'Colocar el alimentador', detail: 'Añadir 1 litro de jarabe', citations: ['C1'] },
      { label: 'Reponer cada semana', citations: ['C1'] }
    ] }
  };
  const wideTable = {
    kind: 'table', title: 'Parámetros del colmenar', source_citations: ['C1'],
    table: {
      columns: ['Identificación de la colonia', 'Temperatura media del nido (°C)', 'Cuadros de cría operculada'],
      rows: [
        ['Colmena 1 del colmenar norte', '35,5', '8'],
        ['Colmena 2 del colmenar norte', '34,8', '6'],
        ['Colmena 3 del colmenar sur', '35,1', '7'],
        ['Colmena 4 del colmenar sur', '34,9', '5']
      ]
    }
  };
  await mockChat(page, [
    message('u1', 'user', '¿Cómo está el colmenar?', []),
    message('m1', 'assistant', 'El estado detallado es este [C1].', [sourceA], [wideTable, barsFigure, stepsFigure])
  ]);
  await page.goto('/chat');
  await page.getByRole('button', { name: 'Nueva conversación', exact: true }).click();

  const barsBlock = page.locator('.figure', { hasText: 'Cuadros por colmena' });
  await expect(barsBlock.getByText('5 cuadros', { exact: true })).toBeVisible();
  await expect(barsBlock.getByText('2 cuadros', { exact: true })).toBeVisible();
  await expect(barsBlock.locator('.figure-bar-fill').nth(0)).toHaveAttribute('style', /width:\s*100%/);
  await expect(barsBlock.locator('.figure-bar-fill').nth(1)).toHaveAttribute('style', /width:\s*40%/);
  await expect(barsBlock.getByRole('img')).toHaveAttribute('aria-label', /Cuadros por colmena.*2 cuadros/);
  await expect(barsBlock.locator('.figure-sr-only li').nth(0)).toHaveText('Cámara de cría: 5 cuadros');
  await expect(barsBlock.locator('.figure-sr-only li').nth(1)).toHaveText('Alza melaria: 2 cuadros');

  const stepsBlock = page.locator('.figure', { hasText: 'Alimentación de una colonia' });
  await expect(stepsBlock.locator('.figure-steps li').nth(0)).toContainText('Colocar el alimentador');
  await expect(stepsBlock.locator('.figure-steps li').nth(0)).toContainText('Añadir 1 litro de jarabe');
  await expect(stepsBlock.locator('.figure-steps li').nth(1)).toContainText('Reponer cada semana');
  await expect(stepsBlock.locator('.figure-steps li').nth(1)).not.toContainText('Añadir 1 litro');

  if (info.project.name === 'mobile') {
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const wrap = page.locator('.figure-table-wrap').first();
    expect(await wrap.evaluate(el => (el as HTMLElement).scrollWidth > (el as HTMLElement).clientWidth)).toBe(true);
    await wrap.focus();
    const before = await wrap.evaluate(el => (el as HTMLElement).scrollLeft);
    await page.keyboard.press('ArrowRight');
    // El desplazamiento con teclado es animado en Chromium: se consulta hasta que se mueve.
    await expect.poll(() => wrap.evaluate(el => (el as HTMLElement).scrollLeft), { timeout: 3000 }).toBeGreaterThan(before);
  }
});

test('figuras desconocidas o inválidas no rompen el mensaje', async ({ page }) => {
  const unknownKind = { kind: 'nube', title: 'Nube de palabras', source_citations: ['C1'], nube: { words: ['abeja'] } };
  const extraField = { ...tableFigure, tone: 'cálido' };
  const missingCitation = {
    kind: 'steps', title: 'Manejo inicial',
    source_citations: ['C9'],
    steps: { items: [{ label: 'Ahumar la colmena', citations: ['C9'] }] }
  };
  await mockChat(page, [
    message('u1', 'user', 'Resumen', []),
    message('m1', 'assistant', 'Comparativa de cuadros [C1].', [], [unknownKind]),
    message('m2', 'assistant', 'Tabla con un campo extra [C1].', [sourceA], [extraField]),
    message('m3', 'assistant', 'Ahumado recomendado [C9].', [], [missingCitation])
  ]);
  await page.goto('/chat');
  await page.getByRole('button', { name: 'Nueva conversación', exact: true }).click();

  await expect(page.getByText('Comparativa de cuadros [C1].')).toBeVisible();
  await expect(page.getByText('Tabla con un campo extra [C1].')).toBeVisible();
  await expect(page.getByText('Ahumado recomendado [C9].')).toBeVisible();

  await expect(page.locator('.figure')).toHaveCount(1);
  await expect(page.getByText('Ahumar la colmena')).toBeVisible();
  await expect(page.locator('.figure-citation-missing')).toHaveText('[C9]');
  await expect(page.getByRole('button', { name: '[C9]', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '[C1] Manual de apicultura · v3' })).toBeVisible();
});
