import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for Alpha Engine dashboard e2e tests.
 *
 * Only Chromium is exercised — the dashboard targets a single rendering
 * engine and the release-journey gates only need smoke-level coverage.
 *
 * A deterministic Node fixture backend serves the production build and
 * domain endpoints on one origin. Tests must not intercept domain requests.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: 'list',
  timeout: 30_000,

  use: {
    baseURL: 'http://127.0.0.1:43173',
    trace: 'on-first-retry',
  },

  webServer: {
    command: 'node e2e/fixture-server.mjs',
    url: 'http://127.0.0.1:43173',
    reuseExistingServer: false,
    timeout: 15_000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
