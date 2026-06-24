import { test, expect } from '@playwright/test';

/**
 * Smoke tests against the real FastAPI backend in demo mode.
 *
 * These tests validate that `uv run python api_server.py --demo` serves
 * a working dashboard using the contract fixtures from fixtures/contract/.
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
  test('dashboard loads with contract fixture data', async ({ page }) => {
    await login(page);
    await page.goto('/#/dashboard');

    // Dashboard heading visible
    await expect(page.getByRole('heading', { name: /dashboard/i })).toBeVisible({ timeout: 15_000 });

    // Demo Mode badge visible
    await expect(page.getByText(/demo mode/i).first()).toBeVisible({ timeout: 10_000 });

    // All five tabs visible
    for (const tab of ['Performance', 'Holdings', 'Attribution', 'Trades', 'Alpha']) {
      await expect(page.getByRole('tab', { name: tab })).toBeVisible({ timeout: 10_000 });
    }

    // SH600000 visible (from contract fixture positions_normal)
    await page.getByRole('tab', { name: 'Holdings' }).click();
    await expect(page.getByText('SH600000').first()).toBeVisible({ timeout: 10_000 });

    // 5.00% visible (from contract fixture weight)
    await expect(page.getByText('5.00%').first()).toBeVisible({ timeout: 10_000 });

    // Attribution tab contains SH600000
    await page.getByRole('tab', { name: 'Attribution' }).click();
    await expect(page.getByText('SH600000').first()).toBeVisible({ timeout: 10_000 });

    // Equity curve container has data-strategy-point-count >= 2
    await page.getByRole('tab', { name: 'Performance' }).click();
    const equityChart = page.getByTestId('equity-curve-container');
    await expect(equityChart).toBeVisible({ timeout: 10_000 });
    await expect(equityChart).toHaveAttribute('data-strategy-point-count', /^[2-9]|[1-9]\d+$/, { timeout: 10_000 });
  });
});
