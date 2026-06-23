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
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible({ timeout: 10_000 });

    // Assert tabs exist
    await expect(page.getByRole("tab", { name: "Performance" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Holdings" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Attribution" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Trades" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Alpha" })).toBeVisible();

    // 1. Verify Return Indicators
    // The fixture 'Release Candidate 42' has annual_return = 0.18
    await expect(page.getByTestId("metric-return")).toContainText("18.00%");

    // 2. Verify Drawdown Indicators
    // max_drawdown = -0.08
    await expect(page.getByTestId("metric-drawdown")).toContainText("-8.00%");

    // Verify other key risk metrics
    await expect(page.getByTestId("metric-sharpe")).toContainText("1.42");

    // 3. Verify Equity/Performance Chart existence
    await expect(page.getByTestId("backtest-performance-section")).toBeVisible();
    await expect(page.getByTestId("equity-curve-container")).toBeVisible();
    await expect(page.getByTestId("drawdown-container")).toBeVisible();

    // Assert equity chart has non-empty point count
    const equityChart = page.getByTestId("equity-curve-container");
    await expect(equityChart).toBeVisible({ timeout: 10_000 });
    await expect(equityChart).toHaveAttribute("data-strategy-point-count", /^[2-9]|[1-9]\d+$/, { timeout: 10_000 });

    // 4. Verify Positions Data
    // Ensure the specific holding from the fixture is rendered
    // fixture: instrument: "SH600000", weight: 0.05
    await expect(page.getByTestId("current-holdings-section")).toBeVisible();
    
    await page.getByRole("tab", { name: "Holdings" }).click();
    await expect(page.getByTestId("position-history-section")).toBeVisible();
    
    const currentRows = page.getByTestId("current-holdings-section").getByTestId("positions-table-row");
    await expect(currentRows.first()).toBeVisible();
    await expect(currentRows.filter({ hasText: "SH600000" }).first()).toBeVisible();
    await expect(currentRows.filter({ hasText: "SH600000" }).first()).toContainText("5.00%");

    // 5. Verify Attribution / Return Decomposition or explicit missing data diagnostic
    await page.getByRole("tab", { name: "Attribution" }).click();
    const attributionSection = page.getByTestId("attribution-section");
    await expect(attributionSection).toBeVisible();
    await expect(attributionSection.getByText(/Attribution unavailable: missing payload.attribution_normal|Asset Execution/)).toBeVisible();
  });
});
