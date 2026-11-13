import { expect, test } from '@playwright/test';

const cid = '11111111-1111-4111-8111-111111111111';
type PostBody = { content?: string; mode?: string };

test('por defecto la casilla está desmarcada y el turno lleva mode "answer"', async ({ page }, info) => {
  const bodies: PostBody[] = [];
  let created = false; let messages: unknown[] = []; const title = 'Nueva conversación';
  await page.route('**/api/auth/me', route => route.fulfill({ json: { username: 'lector', role: 'usuario', csrf_token: 'csrf' } }));
  await page.route('**/api/chat/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/messages') && route.request().method() === 'POST') {
      bodies.push(route.request().postDataJSON() as PostBody);
      const answer = { id: '22222222-2222-4222-8222-222222222222', role: 'assistant', content: 'Se conserva el archivo.', status: 'completed', sources: [] };
      messages = [{ id: 'u1', role: 'user', content: '¿Se conserva?', status: 'completed', sources: [] }, answer];
      await route.fulfill({ contentType: 'application/x-ndjson', body: [
        { type: 'status', message: 'Validando' }, { type: 'delta', content: answer.content }, { type: 'done', message: answer }
      ].map(row => JSON.stringify(row) + '\n').join('') });
    } else if (path.endsWith('/conversations')) {
      if (route.request().method() === 'POST') { created = true; await route.fulfill({ status: 201, json: { id: cid, title } }); }
      else await route.fulfill({ json: { items: created ? [{ id: cid, title }] : [] } });
    } else {
      await route.fulfill({ json: { id: cid, title, preferences: '', busy: false, messages } });
    }
  });
  await page.goto('/chat');
  await page.getByRole('button', { name: 'Nueva conversación', exact: true }).click();
  const explain = page.getByLabel('Explicar concepto');
  await expect(explain).not.toBeChecked();
  await expect(explain).toBeEnabled();
  await page.getByLabel('Pregunta a la biblioteca').fill('¿Se conserva?');
  await page.getByRole('button', { name: 'Enviar', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Detener' })).toHaveCount(0);
  await expect(page.getByText('¿Se conserva?', { exact: true })).toBeVisible();
  expect(bodies).toHaveLength(1);
  expect(bodies[0]).toEqual({ content: '¿Se conserva?', mode: 'answer' });
  await expect(explain).not.toBeChecked();
  await page.screenshot({ path: info.outputPath('chat-mode-default.png'), fullPage: true });
});

test('marcada envía mode "explain" y pinta secciones con citas que abren el fragmento', async ({ page }, info) => {
  const bodies: PostBody[] = [];
  const sources = [
    { citation_id: 'C1', title: 'Manual', version: 2, quote: 'El archivo se conserva.', locator: { page: 3 } },
    { citation_id: 'C2', title: 'Guía de series', version: 1, quote: 'Las series ordenan las carpetas.', locator: { section_path: ['Archivo', 'Series'] } }
  ];
  const answer = { id: '22222222-2222-4222-8222-222222222222', role: 'assistant', status: 'completed',
    content: '## Qué es el archivo\n\nEs el conjunto documental conservado. [C1]\n\n## Cómo se organiza\n\nSe ordena por series. [C2]',
    sources };
  let created = false; let messages: unknown[] = []; const title = 'Nueva conversación';
  await page.route('**/api/auth/me', route => route.fulfill({ json: { username: 'lector', role: 'usuario', csrf_token: 'csrf' } }));
  await page.route('**/api/chat/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/messages') && route.request().method() === 'POST') {
      bodies.push(route.request().postDataJSON() as PostBody);
      messages = [{ id: 'u1', role: 'user', content: '¿Qué es el archivo?', status: 'completed', sources: [] }, answer];
      await route.fulfill({ contentType: 'application/x-ndjson', body: [
        { type: 'status', message: 'Validando' }, { type: 'delta', content: answer.content }, { type: 'done', message: answer }
      ].map(row => JSON.stringify(row) + '\n').join('') });
    } else if (path.endsWith('/conversations')) {
      if (route.request().method() === 'POST') { created = true; await route.fulfill({ status: 201, json: { id: cid, title } }); }
      else await route.fulfill({ json: { items: created ? [{ id: cid, title }] : [] } });
    } else {
      await route.fulfill({ json: { id: cid, title, preferences: '', busy: false, messages } });
    }
  });
  await page.goto('/chat');
  await page.getByRole('button', { name: 'Nueva conversación', exact: true }).click();
  const explain = page.getByLabel('Explicar concepto');
  await explain.check();
  await page.getByLabel('Pregunta a la biblioteca').fill('¿Qué es el archivo?');
  await page.getByRole('button', { name: 'Enviar', exact: true }).click();
  expect(bodies).toHaveLength(1);
  expect(bodies[0]).toEqual({ content: '¿Qué es el archivo?', mode: 'explain' });
  await expect(page.getByRole('heading', { name: 'Qué es el archivo' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Cómo se organiza' })).toBeVisible();
  await page.getByRole('button', { name: '[C1]', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Fragmento citado' })).toContainText('El archivo se conserva.');
  await expect(page.getByRole('region', { name: 'Fragmento citado' })).toContainText('Página 3');
  await page.getByRole('button', { name: 'Cerrar fragmento' }).click();
  await page.getByRole('button', { name: '[C2]', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Fragmento citado' })).toContainText('Las series ordenan las carpetas.');
  await expect(explain).toBeChecked();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('chat-mode-explain.png'), fullPage: true });
});

test('con la respuesta en curso la casilla está deshabilitada y luego alterna con teclado', async ({ page }, info) => {
  let release = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  let created = false; let messages: unknown[] = []; const title = 'Nueva conversación';
  await page.route('**/api/auth/me', route => route.fulfill({ json: { username: 'lector', role: 'usuario', csrf_token: 'csrf' } }));
  await page.route('**/api/chat/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/messages') && route.request().method() === 'POST') {
      const answer = { id: '22222222-2222-4222-8222-222222222222', role: 'assistant', content: 'Se conserva el archivo.', status: 'completed', sources: [] };
      messages = [{ id: 'u1', role: 'user', content: '¿Se conserva?', status: 'completed', sources: [] }, answer];
      await gate;
      await route.fulfill({ contentType: 'application/x-ndjson', body: [
        { type: 'status', message: 'Validando' }, { type: 'delta', content: answer.content }, { type: 'done', message: answer }
      ].map(row => JSON.stringify(row) + '\n').join('') });
    } else if (path.endsWith('/conversations')) {
      if (route.request().method() === 'POST') { created = true; await route.fulfill({ status: 201, json: { id: cid, title } }); }
      else await route.fulfill({ json: { items: created ? [{ id: cid, title }] : [] } });
    } else {
      await route.fulfill({ json: { id: cid, title, preferences: '', busy: false, messages } });
    }
  });
  await page.goto('/chat');
  await page.getByRole('button', { name: 'Nueva conversación', exact: true }).click();
  const explain = page.getByLabel('Explicar concepto');
  await expect(explain).toBeEnabled();
  await page.getByLabel('Pregunta a la biblioteca').fill('¿Se conserva?');
  await page.getByRole('button', { name: 'Enviar', exact: true }).click();
  await expect(explain).toBeDisabled();
  release();
  await expect(explain).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Detener' })).toHaveCount(0);
  await expect(page.getByText('¿Se conserva?', { exact: true })).toBeVisible();
  await explain.focus();
  await page.keyboard.press('Space');
  await expect(explain).toBeChecked();
  await page.keyboard.press('Space');
  await expect(explain).not.toBeChecked();
  await page.screenshot({ path: info.outputPath('chat-mode-busy.png'), fullPage: true });
});
