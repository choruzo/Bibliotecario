import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';

test('administrative selection, confirmation, configuration and provenance', async ({ page }, info) => {
  const did = '11111111-1111-4111-8111-111111111111';
  const vid = '22222222-2222-4222-8222-222222222222';
  const rid = '33333333-3333-4333-8333-333333333333';
  const values = { llm_base_url: 'http://litellm:4000/v1', llm_model: 'generation', embedding_base_url: 'http://host:8081', embedding_model: 'nomic', reranker_base_url: 'http://host:8082', reranker_model: 'bge', model_timeout_seconds: 60, sufficiency_reasoning_effort: 'low', index_timeout_seconds: 900, conversion_timeout_seconds: 180 };
  let confirmed = false;
  await page.route('**/api/auth/me', route => route.fulfill({ json: { username: 'administrador', role: 'admin', csrf_token: 'csrf-h5' } }));
  await page.route('**/api/admin/documents?**', route => route.fulfill({ json: { items: [{ id: did, title: 'Manual sintetico', active_version_id: vid }], has_more: false } }));
  await page.route('**/api/admin/operations/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/admin/operations/', '');
    if (path === 'settings') {
      if (route.request().method() === 'PUT') {
        expect(route.request().headers()['x-csrf-token']).toBe('csrf-h5');
        expect(route.request().postDataJSON().values.model_timeout_seconds).toBe(35);
        await route.fulfill({ json: { revision: 1, active: values, saved: { ...values, model_timeout_seconds: 35 }, restart_required: true } });
      } else await route.fulfill({ json: { revision: 0, active: values, saved: values, restart_required: false } });
    } else if (path === 'status') await route.fulfill({ json: { jobs: { fallido: 1 }, workers: [{ name: 'ingestion', available: true, heartbeat_at: 1 }] } });
    else if (path === 'batches') await route.fulfill({ json: { items: confirmed ? [{ id: 'lote-sintetico', total: 1, finished: 0, failed: 0, progress: 10, items: [{ id: 'trabajo-sintetico', status: 'pendiente', progress: 10 }] }] : [] } });
    else if (path === 'reindex/preview') {
      expect(route.request().postDataJSON().document_ids).toEqual([did]);
      await route.fulfill({ json: { count: 1, snapshot: 'a'.repeat(64), items: [{ document_id: did, title: 'Manual sintetico', version: 2, revision_id: rid }] } });
    } else if (path === 'reindex') {
      expect(route.request().postDataJSON().confirmation).toBe('REINDEXAR');
      expect(route.request().postDataJSON().snapshot).toBe('a'.repeat(64));
      confirmed = true; await route.fulfill({ status: 202, json: { id: 'lote-sintetico', total: 1 } });
    } else if (path === 'audit') await route.fulfill({ json: { items: [{ id: 'audit', action: 'document_published', actor_id: 'administrador', object_id: vid, correlation_id: rid, result: 'success', created_at: new Date().toISOString() }], has_more: false } });
    else if (path === 'evaluations') await route.fulfill({ json: { items: [{ id: rid, scope: 'usuario', created_at: 1, approved: false }], has_more: false } });
    else if (path === 'responses') await route.fulfill({ json: { items: [{ id: 'respuesta', status: 'completed', conversation_id: 'conversacion', retrieval_run_id: rid, sources: [{ document_id: did, document_version_id: vid, revision_id: rid, title: 'Manual sintetico', version: 2, source_sha256: 'b'.repeat(64) }] }], has_more: false } });
    else await route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/admin/operations');
  await expect(page.getByRole('heading', { name: 'Operacion administrativa' })).toBeVisible();
  await page.getByLabel('Seleccionar Manual sintetico').check();
  await page.getByRole('button', { name: 'Previsualizar seleccion (1)', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Confirmar reindexacion', exact: true })).toBeDisabled();
  await page.getByLabel('Escriba REINDEXAR').fill('REINDEXAR');
  await page.getByRole('button', { name: 'Confirmar reindexacion', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('Lote lote-sintetico en cola: 1 trabajos.');
  await page.getByRole('button', { name: 'Configuracion', exact: true }).click();
  await page.getByLabel('Timeout de modelos (segundos)', { exact: false }).fill('35');
  await page.getByRole('button', { name: 'Guardar configuracion' }).click();
  await expect(page.getByText('Hay cambios pendientes de reiniciar API y worker.')).toBeVisible();
  await expect(page.locator('input[type=password]')).toHaveCount(0);
  await page.getByRole('button', { name: 'Auditoria', exact: true }).click();
  await expect(page.getByText('document_published', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Fuentes de respuestas', exact: true }).click();
  await page.locator('summary').filter({ hasText: 'Respuesta respuesta' }).click();
  await expect(page.getByRole('link', { name: 'Descargar original citado' })).toHaveAttribute('href', `/api/admin/versions/${vid}/original`);
  await expect(page.getByText(/Manual sintetico · version 2/)).toBeVisible();
  await page.getByRole('button', { name: 'Exportaciones', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Descargar diagnosticos JSON' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('operations.png'), fullPage: true });
});

test('compiled Compose exposes administrative operations through the proxy', async ({ page }) => {
  test.skip(!process.env.BIB_E2E_CREDENTIALS, 'Requires Compose account');
  const credentials = JSON.parse(readFileSync(process.env.BIB_E2E_CREDENTIALS!, 'utf8'));
  await page.goto('/login');
  await page.getByLabel('Usuario', { exact: true }).fill(credentials.username);
  await page.getByLabel('Contrasena').fill(credentials.password);
  await page.getByRole('button', { name: 'Entrar', exact: true }).click();
  await page.getByRole('link', { name: 'Operacion', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Operacion administrativa' })).toBeVisible();
  await expect(page.getByText('ingestion: Disponible', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Configuracion', exact: true }).click();
  await expect(page.getByLabel('URL de generacion (LiteLLM)', { exact: false })).not.toHaveValue('');
  await page.getByRole('button', { name: 'Exportaciones', exact: true }).click();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Descargar diagnosticos JSON' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('bibliotecario-diagnosticos.json');
  const file = await download.path();
  const data = JSON.parse(readFileSync(file!, 'utf8'));
  expect(data.schema).toBe('bibliotecario-diagnostics-v1');
  expect(data.settings.active.llm_api_key).toBeUndefined();
});
