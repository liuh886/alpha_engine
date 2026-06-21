import { expect, test } from "@playwright/test";

// ----------------------------------------------------------------------------------
// Live Backend Audit
// 
// This test suite contains strict assertions for a live environment.
// Since a live environment's data state is non-deterministic (e.g., might be empty, 
// might have models), these tests are skipped by default. They serve as an executable 
// audit checklist that a developer can un-skip when verifying against a seeded live DB.
// NOTE: This file is intentionally skipped by default and is NOT a CI gate.
// ----------------------------------------------------------------------------------

test.describe("Live Backend Audit Checklist", () => {
  
  test.beforeEach(async ({ page }) => {
    // Strict assertion: We expect the live environment to not require auth by default,
    // or if it does, we explicitly login. We remove the permissive "if visible" pattern.
    await page.goto("/");
  });

  test.skip("1. Data Update Pipeline Audit (Assumes Data is Empty)", async ({ page }) => {
    // Strict assertion: The page must be in the bootstrap state.
    await page.goto("/#/data");
    const updateBtn = page.getByRole("button", { name: /Update|Bootstrap|Pull/i });
    await expect(updateBtn).toBeVisible({ timeout: 5000 });
    
    // Strict assertion: Trigger update and verify the success boundary.
    await updateBtn.click();
    await expect(page.locator('[data-outcome="success"]')).toBeVisible({ timeout: 60000 });
  });

  test.skip("2. Data Update Pipeline Audit (Assumes Data is Seeded)", async ({ page }) => {
    // Strict assertion: The page must already show a successful snapshot.
    await page.goto("/#/data");
    await expect(page.locator('[data-outcome="success"]')).toBeVisible({ timeout: 10000 });
  });

  test.skip("3. Model Registry Audit (Assumes Models Exist)", async ({ page }) => {
    await page.goto("/#/models");
    
    // Strict assertion: The models table must be populated.
    await expect(page.getByRole("heading", { name: "Model Registry" })).toBeVisible();
    
    const modelRows = page.locator('tr[data-model-id]');
    await expect(modelRows.first()).toBeVisible();

    // Expand the first model
    const expandButton = page.locator('button[aria-label*="provenance"]').first();
    await expect(expandButton).toBeVisible();
    await expandButton.click();
    
    // Expect provenance data to show up
    await expect(page.getByText(/Metrics|Evaluation/i).first()).toBeVisible();
  });

});
