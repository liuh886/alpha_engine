import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for smoke-testing against the real FastAPI
 * backend in demo mode (`uv run python api_server.py --demo`).
 *
 * This config is NOT run in CI by default. Use `npm run e2e:demo-real`
 * to validate that the real demo path works end-to-end.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: 'list',
  timeout: 60_000,

  use: {
    baseURL: 'http://127.0.0.1:8000',
    trace: 'on-first-retry',
  },

  webServer: {
    command: 'uv run python api_server.py --demo',
    url: 'http://127.0.0.1:8000',
    reuseExistingServer: false,
    timeout: 30_000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
