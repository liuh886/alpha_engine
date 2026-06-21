import { expect, test } from "@playwright/test";

const identity = {
  snapshotId: "snapshot-cn-20260620",
  workflowId: "workflow.run.cn",
  runId: "run-release-42",
  modelId: "artifact-release-42",
  evidenceId: "artifact-release-42",
};

// Helper to log in
async function login(page: import("@playwright/test").Page) {
  await page.getByLabel("Username").fill("release-user");
  await page.getByLabel("Password").fill("release-pass");
  await page.getByRole("button", { name: "Sign In" }).click();
}

test("production release journey preserves snapshot, workflow, run, model, and evidence identity", async ({ page }) => {
  await page.goto("/#/data");
  await login(page);

  await expect(page.getByRole("heading", { name: "Data Management" })).toBeVisible();
  await expect(page.locator('[data-outcome="success"]')).toContainText("Snapshot is approved for training");
  await page.getByRole("button", { name: "Train on this snapshot" }).click();
  await expect(page).toHaveURL(new RegExp(`snapshot_id=${identity.snapshotId}`));

  await page.getByLabel("Tag").fill("release-candidate-42");
  await page.getByRole("button", { name: "Execute" }).click();

  await expect(page.getByText("Results: Release Candidate 42")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('[data-outcome="success"]')).toContainText("Evidence identity is bound");
  await expect(page).toHaveURL(new RegExp([
    `snapshot_id=${identity.snapshotId}`,
    `workflow_id=${identity.workflowId.replaceAll(".", "\\.")}`,
    `run_id=${identity.runId}`,
    `model_id=${identity.modelId}`,
    `evidence_id=${identity.evidenceId}`,
  ].join(".*")));

  await page.getByRole("button", { name: "Compare exact result" }).click();
  await expect(page.getByRole("heading", { name: "Model Comparison" })).toBeVisible();
  await expect(page.locator('[data-outcome="success"]')).toContainText(identity.runId);
  await page.getByRole("button", { name: /Baseline Comparator/ }).click();
  await expect(page.getByRole("columnheader", { name: "Release Candidate 42" })).toBeVisible();

  await page.getByRole("button", { name: "Open exact model in registry" }).click();
  await expect(page.getByRole("heading", { name: "Model Registry", level: 1 })).toBeVisible();
  await expect(page.locator('[data-model-id="artifact-release-42"]')).toContainText("release-candidate-42");
  await expect(page.locator('[data-outcome="success"]')).toContainText("Exact release model is available");
});

test("Models page shows identity fields (snapshot, run, stage) in the table", async ({ page }) => {
  await page.goto("/#/models");
  await login(page);

  await expect(page.getByRole("heading", { name: "Model Registry" })).toBeVisible();
  // Wait for models to load
  await expect(page.locator('[data-model-id="artifact-release-42"]')).toBeVisible({ timeout: 10_000 });

  // Verify stage column is present
  const row = page.locator('[data-model-id="artifact-release-42"]');
  await expect(row).toContainText("STAGING");

  // Verify snapshot ID is displayed (truncated)
  await expect(row).toContainText("snapshot-cn");

  // Verify run ID is displayed (truncated)
  await expect(row).toContainText("run-rele");
});

test("Models page shows provenance chain on expand", async ({ page }) => {
  await page.goto("/#/models");
  await login(page);

  await expect(page.getByRole("heading", { name: "Model Registry" })).toBeVisible();
  await expect(page.locator('[data-model-id="artifact-release-42"]')).toBeVisible({ timeout: 10_000 });

  // Click expand button
  const expandButton = page.locator('[data-model-id="artifact-release-42"] button[aria-label*="provenance"]');
  await expandButton.click();

  // Verify provenance chain section appears
  await expect(page.getByText("Provenance Chain")).toBeVisible();
  await expect(page.getByText("Artifact ID:")).toBeVisible();
  await expect(page.getByText("Snapshot ID:")).toBeVisible();
  await expect(page.getByText("Run ID:")).toBeVisible();
  await expect(page.getByText("Evidence ID:")).toBeVisible();

  // Verify stage progress is visible
  await expect(page.getByText("CANDIDATE", { exact: true })).toBeVisible();
  await expect(page.getByText("STAGING").first()).toBeVisible();
  await expect(page.getByText("RECOMMENDED").first()).toBeVisible();
});

test("Data page shows snapshot identity and quality verdict", async ({ page }) => {
  await page.goto("/#/data");
  await login(page);

  await expect(page.getByRole("heading", { name: "Data Management" })).toBeVisible();

  // Verify snapshot ID is displayed
  await expect(page.locator('[data-outcome="success"]')).toBeVisible();

  // Verify Quality Verdict label
  await expect(page.getByText("Quality Verdict")).toBeVisible();

  // Verify quality Pass badge
  await expect(page.getByText("Pass")).toBeVisible();

  // Verify symbol accounting
  await expect(page.getByText("Symbol Accounting")).toBeVisible();
  await expect(page.getByText("configured")).toBeVisible();
  await expect(page.getByText("updated")).toBeVisible();
});

test("fixture backend rejects invalid credentials", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Username").fill("wrong");
  await page.getByLabel("Password").fill("credentials");
  await page.getByRole("button", { name: "Sign In" }).click();

  await expect(page.getByText("Invalid credentials. Please try again.")).toBeVisible();
});
