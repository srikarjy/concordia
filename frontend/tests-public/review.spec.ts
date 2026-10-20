import { expect, test } from '@playwright/test';

test('production routes ship a read-only review with working benchmark navigation', async ({ page }) => {
  const apiCalls: string[] = [];
  const errors: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiCalls.push(request.url());
  });
  page.on('pageerror', error => errors.push(error.message));
  for (const path of ['/', '/review', '/index.html']) {
    const response = await page.goto(path, { waitUntil: 'networkidle' });
    expect(response?.status()).toBe(200);
    expect(response?.headers()['content-security-policy']).toContain("default-src 'none'");
    await expect(page.getByRole('note')).toContainText('Read-only replay');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('1IGV');
    await expect(page.getByRole('button', { name: 'Import evidence' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Save decision' })).toBeDisabled();
    for (const name of ['Selected CSV', 'HTML report', 'Complete bundle']) {
      const href = await page.getByRole('link', { name }).getAttribute('href');
      expect((await page.request.get(href!)).status()).toBe(200);
    }
  }
  expect(apiCalls).toEqual([]);
  expect((await page.request.post('/api/reviews', { data: {} })).ok()).toBe(false);
  await page.getByRole('link', { name: '1IGV benchmark' }).click();
  await expect(page.getByRole('heading', { name: 'Ranked candidates', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Variant review workspace' }).click();
  await expect(page.getByRole('note')).toContainText('Read-only replay');
  expect(errors).toEqual([]);
});
