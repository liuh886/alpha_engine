import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: 'static-artifact.spec.ts',
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: 'list',
  timeout: 30_000,
  outputDir: 'test-results/static-artifact',
  use: {
    baseURL: 'http://127.0.0.1:43173',
    browserName: 'chromium',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'node e2e/fixture-server.mjs',
    url: 'http://127.0.0.1:43173',
    reuseExistingServer: false,
    timeout: 15_000,
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], browserName: 'chromium' } },
    {
      name: 'tablet',
      use: {
        browserName: 'chromium',
        viewport: { width: 1024, height: 1366 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
        userAgent: devices['iPad (gen 7)'].userAgent,
      },
    },
    { name: 'mobile', use: { ...devices['Pixel 7'], browserName: 'chromium' } },
  ],
});
