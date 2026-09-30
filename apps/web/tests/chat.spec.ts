import { expect, test } from '@playwright/test';

test('conversation, streaming, citations, general explanation and persistence', async ({ page }, info) => {
  const cid = '11111111-1111-4111-8111-111111111111';
  const source = { citation_id: 'C1', title: 'Manual', version: 2, quote: 'El archivo se conserva.', locator: { page: 3 } };
  const answer = { id: '22222222-2222-4222-8222-222222222222', role: 'assistant', content: 'Se conserva el archivo. [C1]\n\nExplicación general\n\nComo una estantería.', status: 'completed', sources: [source] };
  let created = false; let messages: unknown[] = []; let title = 'Nueva conversación'; let preferences = '';
  await page.route('**/api/auth/me', route => route.fulfill({ json: { username: 'lector', role: 'usuario', csrf_token: 'csrf' } }));
  await page.route('**/api/chat/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/messages') && route.request().method() === 'POST') {
      expect(route.request().headers()['x-csrf-token']).toBe('csrf');
      messages = [{ id: 'u1', role: 'user', content: '¿Se conserva?', status: 'completed', sources: [] }, answer];
      await route.fulfill({ contentType: 'application/x-ndjson', body: [
        { type: 'status', message: 'Validando' }, { type: 'delta', content: answer.content }, { type: 'done', message: answer }
      ].map(row => JSON.stringify(row) + '\n').join('') });
    } else if (path.endsWith('/conversations')) {
      if (route.request().method() === 'POST') { created = true; await route.fulfill({ status: 201, json: { id: cid, title } }); }
      else await route.fulfill({ json: { items: created ? [{ id: cid, title }] : [] } });
    } else {
      if (route.request().method() === 'PATCH') { const body = route.request().postDataJSON(); title = body.title; preferences = body.preferences; }
      await route.fulfill({ json: { id: cid, title, preferences, busy: false, messages } });
    }
  });
  await page.goto('/chat');
  await page.getByRole('button', { name: 'Nueva conversación', exact: true }).click();
  await page.getByLabel('Título de la conversación').fill('Mi clase');
  await page.getByLabel('Preferencias pedagógicas').fill('Con ejemplos');
  await page.getByRole('button', { name: 'Guardar cambios' }).click();
  await page.getByLabel('Pregunta a la biblioteca').fill('¿Se conserva?');
  await page.getByRole('button', { name: 'Enviar', exact: true }).click();
  await expect(page.getByText('Explicación general', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '[C1]', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Fragmento citado' })).toContainText('El archivo se conserva.');
  await expect(page.getByRole('region', { name: 'Fragmento citado' })).toContainText('Página 3');
  await expect(page.getByRole('link', { name: 'Descargar original' })).toHaveAttribute('href', `/api/chat/messages/${answer.id}/sources/C1/original`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('chat.png'), fullPage: true });
  await page.reload();
  await page.getByRole('button', { name: 'Mi clase', exact: true }).click();
  await expect(page.getByLabel('Preferencias pedagógicas')).toHaveValue('Con ejemplos');
  await expect(page.getByText('Como una estantería.', { exact: true })).toBeVisible();
});
