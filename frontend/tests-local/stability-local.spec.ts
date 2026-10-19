import { expect, test } from '@playwright/test';

test('local UI scores through the real local engine without hosted calls', async ({ page }) => {
  const external: string[] = [];
  page.on('request', request => {
    if (new URL(request.url()).origin !== 'http://127.0.0.1:7864') external.push(request.url());
  });
  await page.goto('/stability.html', { waitUntil: 'networkidle' });
  await page.getByLabel('Mutations', { exact: true }).fill('A13Q,K6Q,L52Y,Q21E,A13Q:K6Q');
  const response = page.waitForResponse('**/api/stability/score');
  await page.getByRole('button', { name: 'Score mutations', exact: true }).click();
  const report = await (await response).json();
  expect(report.ledger_intact).toBe(true);
  expect(report.candidates).toHaveLength(3);
  expect(report.refusals).toHaveLength(2);
  await expect(page.locator('tbody tr')).toHaveCount(3);
  await expect(page.locator('button.refusal')).toHaveCount(2);
  await expect(page.locator('.live-status')).toContainText('last completed scoring result');
  expect(external).toEqual([]);
});
