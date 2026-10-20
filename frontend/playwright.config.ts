import { defineConfig } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const stateRoot = mkdtempSync(join(tmpdir(), 'concordia-workspace-test-'));
const python = process.env.CONCORDIA_TEST_PYTHON ?? '../.venv/bin/python';

export default defineConfig({
  testDir: './tests',
  retries: 0,
  use: { baseURL: 'http://127.0.0.1:7861', trace: 'retain-on-failure' },
  webServer: {
    command: `PYTHONPATH=../src "${python}" -m concordia.cli serve-workspace --state-root "${stateRoot}" --frontend dist --port 7861`,
    url: 'http://127.0.0.1:7861/health',
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
