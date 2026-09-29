import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';

test.use({ trace: 'off' });
test('real Compose login, four checks and logout', async ({ page }, info) => {
  test.skip(!process.env.BIB_E2E_CREDENTIALS, 'Requires a running Compose deployment and a local account file');
  const credentials = JSON.parse(readFileSync(process.env.BIB_E2E_CREDENTIALS!, 'utf8'));
  const origin = process.env.BIB_E2E_ORIGIN || 'http://localhost:3000';
  await page.goto(`${origin}/login`);
  await page.getByLabel('Usuario', { exact: true }).fill(credentials.username);
  await page.getByLabel('Contrasena').fill(credentials.password);
  await page.getByRole('button', { name: 'Entrar' }).click();
  await expect(page).toHaveURL(`${origin}/admin`);
  await page.getByRole('button', { name: 'Comprobar' }).click();
  await expect(page.getByText('Disponible', { exact: true })).toHaveCount(4, { timeout: 30000 });
  await page.screenshot({ path: info.outputPath('compose-admin.png'), fullPage: true });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Estado de los servicios' })).toBeVisible();
  await page.getByRole('button', { name: 'Cerrar sesion' }).click();
  await expect(page).toHaveURL(`${origin}/login`);
});
