import { expect, test } from '@playwright/test';

test('replays the completed example review read-only without calling the API', async ({ page }) => {
  const apiCalls: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiCalls.push(request.url());
  });
  await page.goto('/?replay', { waitUntil: 'networkidle' });

  await expect(page.getByRole('note')).toContainText('Illustrative decisions written by the Concordia author');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('1IGV');
  await expect(page.locator('.summary-strip')).toContainText('1selected by you');
  await expect(page.getByRole('button', { name: 'Import evidence' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Save decision' })).toBeDisabled();
  await expect(page.locator('.assay-batch tr', { hasText: 'K6Q' })).toContainText('selected');

  await page.getByLabel('Recorded revision').selectOption('1');
  await expect(page.locator('.summary-strip')).toContainText('5awaiting review');
  await expect(page.locator('.assay-batch')).toHaveCount(0);

  for (const name of ['Selected CSV', 'HTML report', 'Complete bundle']) {
    const href = await page.getByRole('link', { name }).getAttribute('href');
    expect((await page.request.get(href!)).status()).toBe(200);
  }
  expect(apiCalls).toEqual([]);
});
