import { chromium } from 'playwright';

const baseURL = process.env.PUBLIC_BASE_URL || 'https://concordia.srikarjy.site';
const apiOrigin = 'https://srikarjy025-concordia-thermompnn.hf.space';
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  extraHTTPHeaders: process.env.VERCEL_OIDC_TOKEN
    ? { 'x-vercel-trusted-oidc-idp-token': process.env.VERCEL_OIDC_TOKEN }
    : {},
});
const page = await context.newPage();
const unexpected = [];
page.on('request', (request) => {
  const origin = new URL(request.url()).origin;
  if (origin !== new URL(baseURL).origin && origin !== apiOrigin) unexpected.push(request.url());
});
await page.goto(baseURL, { waitUntil: 'networkidle' });
await page.getByRole('heading', { name: 'Connector status', exact: true }).waitFor();
await page.getByLabel('Mutations').fill('A13Q,K6Q,L52Y');
await page.getByRole('button', { name: 'Score mutations' }).click();
await page.getByText('Live result from the ThermoMPNN Space.', { exact: false }).waitFor({ timeout: 120000 });
const ranked = await page.getByRole('heading', { name: 'Ranked candidates', exact: true }).locator('..').locator('tbody tr').count();
await page.getByRole('heading', { name: 'Ranked candidates', exact: true }).locator('..').locator('tbody tr').first().click();
await page.locator('tr.selected').waitFor();
await page.getByLabel('Mutations').fill('Q21E');
await page.getByRole('button', { name: 'Score mutations' }).click();
await page.getByText('HARD_PROTECTED_UNIPROT', { exact: true }).first().waitFor({ timeout: 120000 });
await page.getByText('P02633', { exact: false }).waitFor();
await page.getByLabel('Mutations').fill('A13Q:K6Q');
await page.getByRole('button', { name: 'Score mutations' }).click();
await page.getByText('T3_MULTI_MUTANT_SINGLE_MODEL', { exact: true }).first().waitFor({ timeout: 120000 });
await page.getByText('mutation_count', { exact: false }).waitFor();
await page.getByLabel('Mutations').fill('A75Q');
await page.getByRole('button', { name: 'Score mutations' }).click();
await page.getByRole('alert').filter({ hasText: 'OUT_OF_RANGE' }).waitFor({ timeout: 120000 });
await page.screenshot({ path: '/tmp/concordia-live-e2e.png', fullPage: true });
console.log(JSON.stringify({ baseURL, ranked, selected_candidate: true, protected_refusal: true, multi_mutant_refusal: true, out_of_range_refusal: true, screenshot: '/tmp/concordia-live-e2e.png', unexpected_requests: unexpected }));
await browser.close();
