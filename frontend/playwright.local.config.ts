import { defineConfig } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const stateRoot = mkdtempSync(join(tmpdir(), 'concordia-local-test-'));
export default defineConfig({
  testDir: './tests-local',
  timeout: 90_000,
  use: { baseURL: 'http://127.0.0.1:7864', trace: 'retain-on-failure' },
  webServer: {
    command: `cd .. && PYTHONPATH=src .venv/bin/python -m concordia.cli serve-workspace --state-root "${stateRoot}" --frontend frontend/dist --port 7864`,
    url: 'http://127.0.0.1:7864/health',
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
