import { defineConfig, devices } from '@playwright/test';

const pageUrl = process.env.PAGE_URL;
if (!pageUrl) throw new Error('PAGE_URL is required for live Pages acceptance.');

export default defineConfig({
  testDir: './e2e',
  testMatch: 'live-pages.spec.ts',
  fullyParallel: false,
  forbidOnly: true,
  retries: 1,
  workers: 1,
  reporter: 'list',
  timeout: 60_000,
  expect: { timeout: 20_000 },
  outputDir: 'test-results/live-pages',
  use: {
    baseURL: pageUrl.endsWith('/') ? pageUrl : `${pageUrl}/`,
    browserName: 'chromium',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    serviceWorkers: 'block',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], browserName: 'chromium' } },
    { name: 'mobile', use: { ...devices['Pixel 7'], browserName: 'chromium' } },
  ],
});
