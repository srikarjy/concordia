import { expect, test } from '@playwright/test';

test('real measured-data execution is reachable with model results and a bundle', async ({ page }) => {
  await page.goto('/review');
  await page.getByRole('link', { name: /freshly executed 1PGA/ }).click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('1PGA');
  const response = await page.request.get('/public-data-review/execution.json');
  expect(response.ok()).toBe(true);
  const record = await response.json();
  expect(record.status).toBe('executed');
  expect(record.dataset_rows).toBe(930);
  expect(record.test_rows).toBe(185);
  expect(record.interactive_review_count).toBe(3);
  expect(record.interactive_review_candidate_ids).toHaveLength(3);
  expect(record.train_rows + record.test_rows).toBe(930);
  expect(record.decisions_preserved).toBe(true);
  expect(record.scientific_use_allowed).toBe(false);
  expect(record.test_positions.every((p: number) => !record.train_positions.includes(p))).toBe(true);
  const reviewHtml = await (await page.request.get('/public-data-review/review.html')).text();
  expect(reviewHtml).not.toContain('Source ordering differs');
  expect(reviewHtml).toContain('Fresh CPU Ridge');
  await page.getByRole('link', { name: 'Review decisions and assays' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('1PGA');
  expect((await page.request.get('/public-data-review/bundle.zip')).status()).toBe(200);
});
