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
    await expect(page.getByText("Return", { exact: true })).toBeVisible();
    await expect(page.getByText("18.0%", { exact: true })).toBeVisible();

    // 2. Verify Drawdown Indicators
    // max_drawdown = -0.08
    await expect(page.getByText("Max Drawdown", { exact: true })).toBeVisible();
    await expect(page.getByText("-8.0%", { exact: true })).toBeVisible();

    // Verify other key risk metrics
    await expect(page.getByText("Sharpe", { exact: true })).toBeVisible();
    await expect(page.getByText("1.42", { exact: true })).toBeVisible();

    // 3. Verify Equity/Performance Chart existence
    // The chart container should be present if data was loaded
    await expect(page.locator('.recharts-wrapper').first()).toBeVisible();

    // 4. Verify Positions Data
    // Ensure the specific holding from the fixture is rendered
    // fixture: instrument: "SH600000", weight: 0.05
    await expect(page.getByText("SH600000").first()).toBeVisible();
    await expect(page.getByText("5.00%").first()).toBeVisible();
  });
});
