import { expect, test } from '@playwright/test';

test('public stability page stays same-origin', async ({ page }) => {
  const offenders: string[] = [];
  const origin = new URL('http://127.0.0.1:4173').origin;
  page.on('request', (request) => {
    if (new URL(request.url()).origin !== origin) offenders.push(request.url());
  });

  await page.goto('/stability.html', { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: 'Upload and inspect your protein', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Ranked candidates', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Refusals', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Structure', exact: true })).toBeVisible();
  await page.getByRole('heading', { name: 'Ranked candidates', exact: true }).locator('..').locator('table tbody tr').first().click();
  await expect(page.locator('tr.selected')).toHaveCount(1);
  await expect(page.getByText('pLDDT coloring is off', { exact: false })).toBeVisible();
  expect(offenders).toEqual([]);
});


test('saved evidence is distinguished from edited and failed requests', async ({ page }) => {
  await page.route('**/api/stability/score', async (route) => {
    await route.fulfill({ status: 503, json: { detail: 'Scoring unavailable' } });
  });
  await page.goto('/stability.html', { waitUntil: 'networkidle' });
  await expect(page.getByRole('status').filter({ hasText: 'Showing a saved example' })).toContainText('Q21E');
  await page.getByLabel('Mutations', { exact: true }).fill('K6Q');
  await page.getByRole('button', { name: 'Score mutations', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('Scoring unavailable');
  await expect(page.getByRole('status').filter({ hasText: 'Showing a saved example' })).toContainText('Q21E');
});

test('missing saved evidence shows an error instead of loading forever', async ({ page }) => {
  await page.route('**/data/*.json', async (route) => {
    await route.fulfill({ status: 404, json: {} });
  });
  await page.goto('/stability.html');
  await expect(page.getByRole('alert')).toContainText('The saved evidence could not be loaded');
  await expect(page.getByText('Loading precomputed result…')).toHaveCount(0);
});
