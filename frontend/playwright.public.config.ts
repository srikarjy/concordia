import { defineConfig } from '@playwright/test';

const deployedUrl = process.env.CONCORDIA_PUBLIC_BASE_URL;

export default defineConfig({
  testDir: './tests-public',
  retries: 0,
  use: { baseURL: deployedUrl ?? 'http://127.0.0.1:4173', trace: 'retain-on-failure' },
  webServer: deployedUrl ? undefined : {
    command: 'cd .. && python3 scripts/prepare_static_stability_payload.py && cd frontend && npm run build:stability && cd .. && python3 scripts/sanitize_static_stability_bundle.py && python3 scripts/serve_static_preview.py --port 4173',
    url: 'http://127.0.0.1:4173/stability.html',
    reuseExistingServer: false,
    timeout: 180_000,
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
