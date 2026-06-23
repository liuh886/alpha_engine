import { test, expect } from '@playwright/test';

/**
 * Smoke tests against the real FastAPI backend in demo mode.
 *
 * These tests validate that `uv run python api_server.py --demo` serves
 * a working dashboard. They are intentionally lightweight — the full
 * contract suite runs against the fixture server.
 *
 * Run with: npm run e2e:demo-real
 */

const DEMO_USER = 'release-user';
const DEMO_PASS = 'release-pass';

async function login(page: import('@playwright/test').Page) {
  await page.goto('/');
  const usernameInput = page.getByPlaceholder(/username/i);
  const passwordInput = page.getByPlaceholder(/password/i);
  if (await usernameInput.isVisible({ timeout: 3000 }).catch(() => false)) {
    await usernameInput.fill(DEMO_USER);
    await passwordInput.fill(DEMO_PASS);
    await page.getByRole('button', { name: /sign in/i }).click();
    await page.waitForURL(/#\/(dashboard|$)/, { timeout: 10_000 });
  }
}

test.describe('Demo Real Backend Smoke', () => {
  test('dashboard loads', async ({ page }) => {
    await login(page);
    await page.goto('/#/dashboard');
    await expect(page.getByRole('heading', { name: /dashboard/i })).toBeVisible({ timeout: 15_000 });
  });

  test('Demo Mode badge visible', async ({ page }) => {
    await login(page);
    await page.goto('/#/dashboard');
    await expect(page.getByText(/demo mode/i)).toBeVisible({ timeout: 10_000 });
  });

  test('dashboard tabs visible', async ({ page }) => {
    await login(page);
    await page.goto('/#/dashboard');
    for (const tab of ['Performance', 'Holdings', 'Attribution', 'Trades', 'Alpha']) {
      await expect(page.getByRole('tab', { name: tab })).toBeVisible({ timeout: 10_000 });
    }
  });

  test('at least one model in selector', async ({ page }) => {
    await login(page);
    await page.goto('/#/dashboard');
    // The model selector button should show a model name
    const selectorButton = page.getByRole('button').filter({ hasText: /release|baseline|candidate/i });
    await expect(selectorButton.first()).toBeVisible({ timeout: 10_000 });
  });
});
