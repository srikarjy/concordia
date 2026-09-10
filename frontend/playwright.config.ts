import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  retries: 0,
  use: { baseURL: 'http://127.0.0.1:7861', trace: 'retain-on-failure' },
  webServer: {
    command: '../.venv/bin/concordia serve-workspace --state-root ../.concordia/playwright --frontend dist --port 7861',
    url: 'http://127.0.0.1:7861/health',
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
