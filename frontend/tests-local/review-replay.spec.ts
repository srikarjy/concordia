import { expect, test } from '@playwright/test';

test('replays the completed example review read-only without calling the API', async ({ page }) => {
  const apiCalls: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiCalls.push(request.url());
  });
  await page.goto('/?replay', { waitUntil: 'networkidle' });

  await expect(page.getByRole('note')).toContainText('Illustrative decisions written by the Concordia author');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('1IGV');
  await expect(page.getByRole('region', { name: 'Fresh prediction execution status' })).toContainText('Unavailable');
  const feasibility = await page.getByRole('link', { name: 'Open checksum-verified feasibility record' }).getAttribute('href');
  expect((await page.request.get(feasibility!)).status()).toBe(200);
  await expect(page.locator('.summary-strip')).toContainText('1selected by you');
  await expect(page.getByRole('button', { name: 'Import evidence' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Save decision' })).toBeDisabled();
  await expect(page.locator('.assay-batch tr', { hasText: 'K6Q' })).toContainText('selected');

  await page.getByLabel('Recorded revision').selectOption('1');
  await expect(page.locator('.summary-strip')).toContainText('5awaiting review');
  await expect(page.locator('.assay-batch')).toHaveCount(0);

  const firstSelected = await page.getByRole('link', { name: 'Selected CSV' }).getAttribute('href');
  expect(firstSelected).toContain('/r1-selected.csv');
  expect(await (await page.request.get(firstSelected!)).text()).not.toContain('K6Q');

  for (const name of ['Selected CSV', 'HTML report', 'Complete bundle']) {
    const href = await page.getByRole('link', { name }).getAttribute('href');
    expect((await page.request.get(href!)).status()).toBe(200);
  }
  expect(apiCalls).toEqual([]);
});
