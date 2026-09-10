import { expect, test } from '@playwright/test';

test('claim selection illuminates a saved evidence path', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Genomic attribution audit' })).toBeVisible();
  await expect(page.getByText('Software demonstration.')).toBeVisible();

  const claims = page.locator('.claim');
  await expect(claims).toHaveCount(4);
  await claims.nth(1).click();
  await expect(claims.nth(1)).toHaveClass(/selected/);
  await expect(page.getByText('SELECTED PATH')).toBeVisible();
  await expect(page.locator('.node.active').first()).toBeVisible();
});

test('event playback controls do not mutate the backend', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Saved orchestration history' })).toBeVisible();
  const events = page.locator('.event');
  const fullCount = await events.count();
  expect(fullCount).toBeGreaterThan(10);
  await page.getByRole('button', { name: 'pause playback' }).click();
  await expect(events).toHaveCount(10);
  await page.getByRole('button', { name: 'show all' }).click();
  await expect(events).toHaveCount(fullCount);
});
