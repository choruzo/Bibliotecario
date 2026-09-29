import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';

test.use({ trace: 'off' });
test('published document can be inspected and withdrawal removes its evidence', async ({ page }, info) => {
  test.skip(!process.env.BIB_E2E_CREDENTIALS, 'Requires local Compose credentials');
  test.setTimeout(90000);
  const origin = process.env.BIB_E2E_ORIGIN || 'http://localhost:3000';
  const credentials = JSON.parse(readFileSync(process.env.BIB_E2E_CREDENTIALS!, 'utf8'));
  const marker = `h3browser${info.project.name}${Date.now()}`;
  const name = `${marker}.md`;
  await page.goto(`${origin}/login`);
  await page.getByLabel('Usuario', { exact: true }).fill(credentials.username);
  await page.getByLabel('Contrasena').fill(credentials.password);
  await page.getByRole('button', { name: 'Entrar' }).click();
  await expect(page).toHaveURL(`${origin}/admin`);
  await page.getByRole('link', { name: 'Documentos', exact: true }).click();
  await page.locator('input[type=file]').first().setInputFiles({ name, mimeType: 'text/markdown',
    buffer: Buffer.from(`# Tema ${marker}\n\nEste procedimiento ${marker} permite comprobar fuentes y versiones.\n`) });
  await expect(page.getByLabel('Markdown')).toHaveValue(new RegExp(marker), { timeout: 30000 });
  await page.getByRole('button', { name: 'Marcar revisado', exact: true }).click();
  await expect(page.getByText('Revisado', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Publicar', exact: true }).click();
  await expect(page.locator('.document-review .review-status')).toContainText('Publicado', { timeout: 30000 });
  try {
    await page.getByRole('link', { name: 'Recuperacion', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Inspeccion de recuperacion' })).toBeVisible();
    await page.getByLabel('Consulta de recuperacion').fill(marker);
    await page.getByRole('button', { name: 'Inspeccionar', exact: true }).click();
    const ownSource = page.locator('.retrieval-card').filter({ hasText: marker }).first();
    await expect(ownSource).toBeVisible({ timeout: 30000 });
    await expect(page.getByText(/Decision: Abstencion/)).toBeVisible();
    await expect(ownSource.getByRole('link', { name: 'Descargar original' })).toBeVisible();
    await ownSource.getByText('Identificadores de la cita').click();
    await expect(ownSource).toContainText('Fragmento:');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
    await page.screenshot({ path: info.outputPath('retrieval.png'), fullPage: true });
  } finally {
    await page.getByRole('link', { name: 'Documentos', exact: true }).click();
    await page.getByRole('button', { name, exact: true }).click();
    await page.getByRole('button', { name: 'Retirar version publicada', exact: true }).click();
    await expect(page.getByText('Retirado', { exact: true }).first()).toBeVisible();
  }
  await page.getByRole('link', { name: 'Recuperacion', exact: true }).click();
  await page.getByLabel('Consulta de recuperacion').fill(marker);
  await page.getByRole('button', { name: 'Inspeccionar', exact: true }).click();
  await expect(page.getByText(/Decision:/)).toBeVisible({ timeout: 30000 });
  await expect(page.locator('.retrieval-card').filter({ hasText: marker })).toHaveCount(0);
});
