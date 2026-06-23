import { expect, test } from "@playwright/test";

async function login(page: import("@playwright/test").Page) {
  await page.getByLabel("Username").fill("release-user");
  await page.getByLabel("Password").fill("release-pass");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByText(/System Home|Model Dashboard|Data Management/i).first()).toBeVisible({ timeout: 10_000 });
}

test.describe("Dashboard Product Contract", () => {
  test("verifies Equity, Drawdown, Positions, and Return core outputs", async ({ page }) => {
    // Navigate to dashboard and authenticate
    await page.goto("/#/dashboard");
    await login(page);

    // Wait for the Dashboard to load and verify the heading
    await expect(page.getByRole("heading", { name: "Model Dashboard" })).toBeVisible({ timeout: 10_000 });

    // 1. Verify Return Indicators
    // The fixture 'Release Candidate 42' has annual_return = 0.18
    await expect(page.getByTestId("metric-return")).toContainText("18.0%");

    // 2. Verify Drawdown Indicators
    // max_drawdown = -0.08
    await expect(page.getByTestId("metric-drawdown")).toContainText("-8.0%");

    // Verify other key risk metrics
    await expect(page.getByTestId("metric-sharpe")).toContainText("1.42");

    // 3. Verify Equity/Performance Chart existence
    await expect(page.getByTestId("backtest-performance-section")).toBeVisible();
    await expect(page.getByTestId("equity-curve-container")).toBeVisible();
    await expect(page.getByTestId("drawdown-container")).toBeVisible();

    // 4. Verify Positions Data
    // Ensure the specific holding from the fixture is rendered
    // fixture: instrument: "SH600000", weight: 0.05
    const rows = page.getByTestId("positions-table-row");
    await expect(rows.first()).toBeVisible();
    await expect(rows.filter({ hasText: "SH600000" }).first()).toBeVisible();
    await expect(rows.filter({ hasText: "SH600000" }).first()).toContainText("5.00%");
  });
});
