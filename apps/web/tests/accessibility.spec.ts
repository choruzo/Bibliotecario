import { expect, test, Page } from '@playwright/test';

const title = 'Manual de procedimientos con un título extenso '.repeat(4);
const metadata = { title, author: 'Autor', date: '', category: 'Manuales', tags: [], language: 'es', version: '1', visibility: 'usuarios' };
const sampleDocument = { id: 'doc-audit', title, active_version_id: 'version-audit', deletion_requested: false, versions: [{ id: 'version-audit', number: 1, status: 'requiere_revision', metadata, revision_id: 'revision-audit', reviewed_at: null, original_sha256: 'a'.repeat(64), original_name: 'manual.md', format: 'md', diagnostics: [] }] };
const result = { results: [{ chunk_id: 'chunk', version_id: 'version-audit', revision_id: 'revision-audit', title, version: 1, content: 'Contenido '.repeat(80), rerank_score: 1, rrf_score: .01, channels: {}, provenance: [] }], candidates: [], decision: { action: 'abstain', reason: 'Sin calibración' }, latency: {} };

async function fixtures(page: Page, role = 'admin') {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    const data = path.endsWith('/auth/me') ? { username: 'cuenta-con-nombre-largo', role, csrf_token: 'audit' }
      : path.endsWith('/documents') ? { items: [sampleDocument], has_more: false }
      : path.endsWith('/documents/doc-audit') ? sampleDocument
      : path.endsWith('/normalized') ? { markdown: '# Manual\n\n| Campo | Valor |\n| --- | --- |\n| Texto | Contenido |', metadata, revision_id: 'revision-audit', provenance: [] }
      : path.endsWith('/revisions') ? { items: [{ id: 'revision-audit', number: 1, edited: false, created_at: 1 }] }
      : path.endsWith('/jobs') ? { items: [{ id: 'job', document_title: title, kind: 'convert', status: 'fallido', progress: 20, attempts: 1, error_code: 'conversion_timeout' }], has_more: false }
      : path.endsWith('/events') ? { items: [{ event: 'Error de conversión', attempt: 1, generation: 1, created_at: 1 }] }
      : path.endsWith('/policy') ? { report: { approved: false } }
      : path.endsWith('/runs/run-audit') ? { status: 'completed', result }
      : path.endsWith('/runs') ? { items: [{ id: 'run-audit', query: title, status: 'completed' }] }
      : path.endsWith('/settings') ? { revision: 0, active: { llm_base_url: 'http://localhost:4000/v1', model_timeout_seconds: 60 }, saved: { llm_base_url: 'http://localhost:4000/v1', model_timeout_seconds: 60 } }
      : path.endsWith('/status') ? { jobs: {}, workers: [] }
      : path.endsWith('/conversations') ? { items: [{ id: 'conversation', title }] }
      : path.endsWith('/conversations/conversation') ? { id: 'conversation', title, preferences: '', busy: false, messages: [{ id: 'answer', role: 'assistant', status: 'completed', content: '**Respuesta**\n\n- Primer paso\n- Segundo paso [C1]', sources: [{ citation_id: 'C1', title, version: 1, quote: 'Fuente del procedimiento', locator: { page: 1 } }] }] }
      : { items: [], has_more: false };
    return route.fulfill({ json: data });
  });
}

test('theme follows system, persists between pages and skip link works with keyboard', async ({ page }) => {
  await fixtures(page);
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/login');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.emulateMedia({ colorScheme: 'light' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.getByRole('button', { name: 'Activar modo oscuro' }).click();
  await page.goto('/admin');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.getByRole('button', { name: 'Activar modo claro' })).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Saltar al contenido' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

for (const theme of ['light', 'dark']) {
  test(`all administrative views reflow at 320px in ${theme} mode`, async ({ page }, info) => {
    await fixtures(page);
    await page.setViewportSize({ width: 320, height: 800 });
    await page.goto('/login');
    await expect(page.getByRole('button', { name: /Activar modo/ })).toBeVisible();
    if (await page.locator('html').getAttribute('data-theme') !== theme) await page.getByRole('button', { name: /Activar modo/ }).click();
    for (const path of ['/admin', '/admin/documents/doc-audit', '/admin/jobs', '/admin/retrieval/runs/run-audit', '/admin/operations']) {
      await page.goto(path);
      await expect(page.locator('.content h1')).toBeVisible();
      if (path.includes('documents')) {
        await expect(page.getByLabel('Markdown')).toBeVisible();
        await page.getByRole('button', { name: 'Vista previa', exact: true }).click();
        await expect(page.locator('.markdown-preview table')).toBeVisible();
      }
      if (path.includes('retrieval')) await expect(page.locator('.retrieval-card')).toBeVisible();
      if (path.includes('operations')) {
        await expect(page.getByRole('checkbox')).toBeVisible();
        const box = await page.getByRole('checkbox').boundingBox();
        expect(box?.width).toBe(24);
        await page.getByRole('button', { name: 'Configuracion', exact: true }).click();
        await expect(page.getByLabel('Timeout de modelos (segundos)', { exact: false })).toBeVisible();
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), path).toBe(true);
      await page.screenshot({ path: info.outputPath(`${theme}-${path.replaceAll('/', '-')}.png`), fullPage: true });
    }
  });
}

test('user markdown, long citations and source focus work on narrow screens', async ({ page }) => {
  await fixtures(page, 'usuario');
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto('/chat');
  await page.getByRole('button', { name: title, exact: true }).click();
  await expect(page.locator('.chat-markdown strong')).toHaveText('Respuesta');
  await expect(page.locator('.chat-markdown li')).toHaveCount(2);
  const citation = page.getByRole('button', { name: '[C1]', exact: true });
  await citation.click();
  await expect(page.getByRole('region', { name: 'Fragmento citado' })).toBeFocused();
  await page.getByRole('button', { name: 'Cerrar fragmento' }).click();
  await expect(citation).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('link', { name: 'Documentos', exact: true })).toHaveCount(0);
});

test('job dialog traps focus, closes with Escape and restores its trigger', async ({ page }) => {
  await fixtures(page);
  await page.goto('/admin/jobs');
  const trigger = page.getByRole('button', { name: 'Ver eventos' });
  await trigger.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Cerrar eventos' })).toBeFocused();
  await page.keyboard.press('Tab');
  expect(await page.evaluate(() => !!document.activeElement?.closest('dialog'))).toBe(true);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(trigger).toBeFocused();
});
