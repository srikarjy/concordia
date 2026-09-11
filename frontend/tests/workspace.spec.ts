import { expect, test } from '@playwright/test';

test('guides a claim from sequence context to its verification decision', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Genomic attribution audit' })).toBeVisible();
  await expect(page.getByText('Every result is fixture-backed')).toBeVisible();

  const claims = page.locator('.claim-item');
  await expect(claims).toHaveCount(4);
  await claims.nth(1).click();

  await expect(claims.nth(1)).toHaveClass(/active/);
  await expect(page.getByRole('button', { name: 'Position 12, base G' })).toHaveClass(/selected/);
  await expect(page.getByRole('heading', { name: 'Verification result' })).toBeVisible();
  await expect(page.getByText('Why this claim cannot pass')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Trace this claim' })).toBeVisible();
});

test('replays a bounded fixture mutation entirely in the browser', async ({ page }) => {
  const mutationRequests: string[] = [];
  page.on('request', request => {
    if (request.method() !== 'GET') mutationRequests.push(`${request.method()} ${request.url()}`);
  });
  await page.goto('/');
  await page.getByRole('button', { name: /Sequence sandbox/ }).click();

  await expect(page.getByRole('heading', { name: /Explore a recorded mutation/ })).toBeVisible();
  await page.getByRole('group', { name: 'Alternate' }).getByRole('button', { name: 'C' }).click();
  await page.getByRole('button', { name: 'Replay bounded check' }).click();

  await expect(page.getByRole('heading', { name: 'Replay complete' })).toBeVisible();
  await expect(page.getByText('4 checks passed')).toBeVisible();
  await expect(page.getByText('Recorded change')).toBeVisible();
  await expect(page.getByText('Software behavior only.')).toBeVisible();
  expect(mutationRequests).toEqual([]);
});

test('scrubs colony generations and keeps the selected member visible', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Colony evolution/ }).click();
  const generation = page.getByRole('slider', { name: 'Generation' });

  await generation.fill('0');
  await expect(page.locator('.member-card')).toHaveCount(1);
  await expect(page.locator('.member-facts').getByText('0', { exact: true })).toBeVisible();

  await generation.fill('2');
  expect(await page.locator('.member-card').count()).toBeGreaterThan(1);
  const extinct = page.locator('.member-card').filter({ hasText: 'Extinct' }).first();
  if (await extinct.count()) {
    await extinct.click();
    await expect(page.getByText('Extinction reason')).toBeVisible();
  }
});

test('opens provenance records and controls local event playback', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Provenance graph/ }).click();
  await page.getByLabel('Accessible graph nodes').getByRole('button').first().click();

  await expect(page.getByText(/direct connections/)).toBeVisible();
  await expect(page.locator('.full-digest')).toBeVisible();

  const events = page.locator('.event');
  await expect(events).toHaveCount(6);
  await page.getByRole('button', { name: /Show all/ }).click();
  expect(await events.count()).toBeGreaterThan(10);
  await page.getByRole('button', { name: 'Show recent' }).click();
  await expect(events).toHaveCount(6);
});
