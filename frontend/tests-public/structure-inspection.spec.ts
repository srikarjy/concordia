import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';

const gateway = 'https://zoosebdmsaflxcqtyyho.supabase.co/functions/v1/structure-gateway';

test('inspection is explicit, authenticated, and shows the returned structure', async ({ page }) => {
  const pdb = await readFile('public/data/structure/1IGV.pdb', 'utf8');
  let calls = 0;
  await page.route(gateway, async (route) => {
    calls += 1;
    const request = route.request();
    expect(request.headers().authorization).toBe('Bearer browser-test-token');
    const body = request.postDataJSON();
    expect(body.mutations).toContain(body.selected_mutation);
    await route.fulfill({ json: {
      status: 'completed', selected_mutation: body.selected_mutation,
      artifact_digest: 'a'.repeat(64), ledger_intact: true,
      scope_statement: 'Browser test fixture; no hosted inference was used.',
      structure: {
        structure_text: pdb, structure_format: 'pdb',
      },
      operation: 'boltz2', model: 'mit/boltz2', provider_latency_ms: 1000,
      provider_response_digest: 'b'.repeat(64), input_sequence_hash: 'c'.repeat(64), limitations: ['Test fixture only'],
    } });
  });
  await page.goto('/stability.html', { waitUntil: 'networkidle' });
  const button = page.getByRole('button', { name: 'Predict with Boltz-2', exact: true });
  await expect(button).toBeDisabled();
  expect(calls).toBe(0);
  await page.getByLabel('Optional Supabase access token override').fill('browser-test-token');
  await button.click();
  await expect(page.getByText('Ledger chain: verified', { exact: false })).toBeVisible();
  await expect(page.getByRole('img', { name: /mit\/boltz2 prediction/ })).toBeVisible();
  await expect(page.locator('.inspection-result .viewer-status')).toContainText('Loaded');
  expect(calls).toBe(1);
  expect(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]))).not.toContain('browser-test-token');
  await page.getByRole('button', { name: 'Clear token', exact: true }).click();
  await expect(button).toBeDisabled();
});

test('a selected refused candidate cannot request structure inspection', async ({ page }) => {
  await page.goto('/stability.html', { waitUntil: 'networkidle' });
  await page.getByLabel('Optional Supabase access token override').fill('browser-test-token');
  await page.locator('button.refusal').filter({ hasText: 'Q21E' }).click();
  await expect(page.getByRole('button', { name: 'Predict with Boltz-2', exact: true })).toBeDisabled();
});

test('refused multi-mutant sharing an accepted position cannot be inspected', async ({ page }) => {
  await page.goto('/stability.html', { waitUntil: 'networkidle' });
  await page.getByLabel('Optional Supabase access token override').fill('browser-test-token');
  await page.locator('button.refusal').filter({ hasText: 'A13Q:K6Q' }).click();
  await expect(page.getByRole('button', { name: 'Predict with Boltz-2', exact: true })).toBeDisabled();
  await expect(page.locator('tr.selected')).toHaveCount(0);
  await page.getByRole('row').filter({ hasText: '1IGV.pdb_A13Q' }).click();
  await expect(page.getByRole('button', { name: 'Predict with Boltz-2', exact: true })).toBeEnabled();
  await expect(page.locator('.structure-inspection')).toContainText('Selected: A13Q');
});
