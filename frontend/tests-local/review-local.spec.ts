import { expect, test } from '@playwright/test';

test('reviews the 1IGV example from decision to verified export without hosted calls', async ({ page }) => {
  const external: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).origin !== 'http://127.0.0.1:7864') external.push(request.url());
  });
  await page.goto('/', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: /Try a complete example/ }).click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('1IGV');
  await expect(page.locator('.flag', { hasText: 'Source ordering differs' })).toHaveCount(2);

  await page.getByRole('button', { name: 'Review Q21E' }).click();
  await expect(page.locator('.inspector')).toContainText('Touches protected position 21');
  await page.getByLabel('Reason', { exact: true }).fill('Only candidate probing the binding loop.');
  const override = page.getByLabel('Protected-position override reason');
  await expect(override).toHaveAttribute('required', '');
  await override.fill('Binding loss is acceptable for this stability-only screen.');
  await page.getByRole('button', { name: 'Save decision' }).click();
  await expect(page.getByRole('status')).toContainText('new revision');

  await page.getByRole('button', { name: 'Review A13Q' }).click();
  await page.getByLabel('Reason', { exact: true }).fill('Both recorded sources rank it last; excluded.');
  await page.getByLabel('Your decision').selectOption('excluded');
  await page.getByRole('button', { name: 'Save decision' }).click();
  await expect(page.getByRole('status')).toContainText('new revision');
  await expect(page.locator('.summary-strip')).toContainText('1selected by you');

  await page.getByRole('button', { name: /Add published 1IGV outcomes/ }).click();
  await expect(page.locator('.assay-batch')).toContainText('Decision before import');
  await expect(page.locator('.assay-batch tr', { hasText: 'A13Q' })).toContainText('excluded');
  await expect(page.locator('.assay-batch tr', { hasText: 'Q21E' })).toContainText('selected');

  const href = await page.getByRole('link', { name: 'Complete bundle' }).getAttribute('href');
  const bundle = await page.request.get(href!);
  expect(bundle.status()).toBe(200);
  expect(bundle.headers()['content-type']).toBe('application/zip');
  expect(external).toEqual([]);
});
