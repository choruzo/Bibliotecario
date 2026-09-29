import { expect, test } from '@playwright/test';

test('login shows errors and fits the viewport', async ({ page }, info) => {
  await page.route('**/api/auth/login', route => route.fulfill({ status: 401, json: { detail: 'denied' } }));
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'Bibliotecario' })).toBeVisible();
  await page.getByLabel('Usuario', { exact: true }).fill('lector');
  await page.getByLabel('Contrasena').fill('incorrecta');
  await page.getByRole('button', { name: 'Entrar' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Usuario o contrasena incorrectos.' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('login.png'), fullPage: true });
});

test('admin sees independent failures and can close the session', async ({ page }, info) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: { username: 'administrador', role: 'admin', csrf_token: 'csrf-test' } }));
  await page.route('**/api/health/dependencies', route => route.fulfill({ status: 503, json: { checks: {
    database: { status: 'available' }, llm: { status: 'unavailable', error: 'connection_error', latency_ms: 4 },
    embedding: { status: 'available', latency_ms: 12 }, reranker: { status: 'unavailable', error: 'timeout', latency_ms: 15000 }
  } } }));
  await page.route('**/api/auth/logout', route => route.fulfill({ status: route.request().headers()['x-csrf-token'] === 'csrf-test' ? 204 : 403 }));
  await page.goto('/admin');
  await page.getByRole('button', { name: 'Comprobar' }).click();
  await expect(page.getByText('connection_error', { exact: true })).toBeVisible();
  await expect(page.getByText('timeout', { exact: true })).toBeVisible();
  await expect(page.getByText('Disponible', { exact: true })).toHaveCount(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('admin.png'), fullPage: true });
  await page.getByRole('button', { name: 'Cerrar sesion' }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test('regular users are redirected from administration', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: { username: 'lector', role: 'usuario', csrf_token: 'csrf-test' } }));
  await page.goto('/admin');
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByRole('link', { name: 'Administracion' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Biblioteca sin documentos publicados' })).toBeVisible();
});
