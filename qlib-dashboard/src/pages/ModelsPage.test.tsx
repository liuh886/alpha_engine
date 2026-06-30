/**
 * Component tests for ModelsPage.
 *
 * Verifies that model identity fields (artifact_id, snapshot_id, run_id),
 * stage badges, provenance chain, gate failures, and distinct outcome states
 * are rendered correctly against mocked API responses.
 */

import { render, screen, within, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ModelsPage } from "./ModelsPage";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockListModels = vi.fn();
const mockDeleteModel = vi.fn();
const mockPromoteModel = vi.fn();
const mockGetModelEvidence = vi.fn();

vi.mock("@/lib/release-api", () => ({
  releaseApi: {
    listModels: (...args: unknown[]) => mockListModels(...args),
    deleteModel: (...args: unknown[]) => mockDeleteModel(...args),
    promoteModel: (...args: unknown[]) => mockPromoteModel(...args),
    getModelEvidence: (...args: unknown[]) => mockGetModelEvidence(...args),
  },
}));

// Stub confirm-dialog to auto-approve
vi.mock("@/components/ui/confirm-dialog", () => ({
  useConfirm: () => ({
    confirm: () => Promise.resolve(true),
    ConfirmDialog: () => null,
  }),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const FIXTURE_MODELS = {
  ok: true,
  versions: [
    {
      id: "artifact-release-42",
      tag: "release-candidate-42",
      name: "Release Candidate 42",
      market: "cn",
      model_type: "lgbm",
      run_id: "run-release-42",
      snapshot_id: "snapshot-cn-20260620",
      evidence_id: "artifact-release-42",
      created_at: "2026-06-20T07:55:00Z",
      stage: "STAGING",
      description: "Stage: STAGING",
      params: { data_snapshot_id: "snapshot-cn-20260620" },
      metrics: {
        "Total Return": 0.3365,
        "Benchmark Return": 0.2899,
        "Excess Return": 0.0466,
        "Sharpe Ratio": 1.42,
        "Annualized Return": 0.18,
        "Max Drawdown": -0.08,
        "IC": 0.0176,
        "ICIR": 0.5761,
        "Positive IC Ratio": 0.7692,
        "Consistency": 0.7692,
        "WF Successful Splits": 13,
        "WF Total Splits": 16,
      },
    },
    {
      id: "artifact-recommended-99",
      tag: "recommended-model",
      name: "Recommended Model",
      market: "us",
      model_type: "xgb",
      run_id: "run-recommended-99",
      snapshot_id: "snapshot-us-20260619",
      evidence_id: "artifact-recommended-99",
      created_at: "2026-06-19T10:00:00Z",
      stage: "RECOMMENDED",
      description: "Stage: RECOMMENDED",
      params: {},
      metrics: { "Sharpe Ratio": 2.1, "Annualized Return": 0.25, "Max Drawdown": -0.05 },
    },
    {
      id: "artifact-old-01",
      tag: "old-model",
      name: "Old Model",
      market: "cn",
      model_type: "lgbm",
      run_id: "run-old-01",
      created_at: "2026-05-01T00:00:00Z",
      stage: "CANDIDATE",
      description: "",
      params: {},
      metrics: { "Sharpe Ratio": 0.5, "Annualized Return": 0.05, "Max Drawdown": -0.15 },
    },
  ],
};

const EMPTY_MODELS = { ok: true, versions: [] };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderModelsPage(search = "") {
  return render(
    <MemoryRouter initialEntries={[`/models${search}`]}>
      <ModelsPage />
    </MemoryRouter>,
  );
}

/** Find the table row that contains the given text. */
function getRowContaining(text: string) {
  const el = screen.getByText(text);
  return el.closest("tr");
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ModelsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListModels.mockResolvedValue(FIXTURE_MODELS);
  });

  // ---- Loading state ----

  it("shows loading state initially", () => {
    mockListModels.mockReturnValue(new Promise(() => {})); // never resolves
    renderModelsPage();

    expect(screen.getByText(/Loading models/i)).toBeVisible();
  });

  // ---- Empty state ----

  it("shows empty state when no models exist", async () => {
    mockListModels.mockResolvedValue(EMPTY_MODELS);
    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByText(/No models found/i)).toBeVisible();
    });
  });

  // ---- Identity fields in table ----

  it("displays model artifact IDs (tag names)", async () => {
    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByText("release-candidate-42")).toBeVisible();
      expect(screen.getByText("recommended-model")).toBeVisible();
      expect(screen.getByText("old-model")).toBeVisible();
    });
  });

  it("displays snapshot ID column with truncated values", async () => {
    renderModelsPage();

    await waitFor(() => {
      // snapshot_id "snapshot-cn-20260620" is shown truncated in the snapshot column
      // The title attribute holds the full ID
      const snapshotCell = screen.getByTitle("snapshot-cn-20260620");
      expect(snapshotCell).toBeVisible();
      // The text content is a truncated form with "..."
      expect(snapshotCell.textContent).toMatch(/snapshot-cn/);
      expect(snapshotCell.textContent).toContain("...");
    });
  });

  it("displays run ID column with truncated values", async () => {
    renderModelsPage();

    await waitFor(() => {
      // shortId("run-release-42") = "run-rele" (8 chars)
      expect(screen.getByText("run-rele")).toBeVisible();
    });
  });

  // ---- Stage badges ----

  it("displays STAGING stage badge for staging models", async () => {
    renderModelsPage();

    await waitFor(() => {
      const stagingBadges = screen.getAllByText("STAGING");
      expect(stagingBadges.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("displays RECOMMENDED stage badge for recommended models", async () => {
    renderModelsPage();

    await waitFor(() => {
      const recommendedBadges = screen.getAllByText("RECOMMENDED");
      expect(recommendedBadges.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("displays CANDIDATE stage badge for models without explicit stage", async () => {
    renderModelsPage();

    await waitFor(() => {
      const candidateBadges = screen.getAllByText("CANDIDATE");
      expect(candidateBadges.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("shows star icon for recommended models", async () => {
    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByLabelText("Recommended model")).toBeVisible();
    });
  });

  // ---- Provenance chain expansion ----

  it("expands provenance chain on click", async () => {
    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByText("release-candidate-42")).toBeVisible();
    });

    // Click the expand button for the first model
    const expandButton = screen.getByLabelText(/Show provenance for.*release-candidate-42/i);
    fireEvent.click(expandButton);

    // Verify provenance chain section
    expect(screen.getByText("Provenance Chain")).toBeVisible();
    expect(screen.getByText("Artifact ID:")).toBeVisible();
    expect(screen.getByText("Snapshot ID:")).toBeVisible();
    expect(screen.getByText("Run ID:")).toBeVisible();
    expect(screen.getByText("Evidence ID:")).toBeVisible();

    // Verify stage progress indicators (CANDIDATE, STAGING, RECOMMENDED are in the progress bar)
    const provenanceSection = screen.getByText("Provenance Chain").closest("td");
    expect(provenanceSection).toBeTruthy();
  });

  it("shows complete effectiveness metrics in the expanded model row", async () => {
    renderModelsPage();
    await screen.findByText("release-candidate-42");
    fireEvent.click(screen.getByLabelText(/Show provenance for.*release-candidate-42/i));

    const metrics = screen.getByLabelText("Model effectiveness metrics");
    for (const label of [
      "Total Return",
      "Benchmark Return",
      "Excess Return",
      "Max Drawdown",
      "Sharpe Ratio",
      "Mean IC",
      "ICIR",
      "Positive IC Ratio",
      "Consistency",
      "WF Splits",
    ]) {
      expect(within(metrics).getByText(label)).toBeVisible();
    }
    expect(within(metrics).getByText("13/16")).toBeVisible();
  });

  it("collapses provenance chain on second click", async () => {
    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByText("release-candidate-42")).toBeVisible();
    });

    const expandButton = screen.getByLabelText(/Show provenance for.*release-candidate-42/i);
    fireEvent.click(expandButton);
    expect(screen.getByText("Provenance Chain")).toBeVisible();

    fireEvent.click(expandButton);
    expect(screen.queryByText("Provenance Chain")).toBeNull();
  });

  it("shows full identity table in expanded provenance", async () => {
    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByText("release-candidate-42")).toBeVisible();
    });

    const expandButton = screen.getByLabelText(/Show provenance for.*release-candidate-42/i);
    fireEvent.click(expandButton);

    // Verify the full identity details are shown
    expect(screen.getByText("Artifact ID:")).toBeVisible();
    expect(screen.getByText("Stage:")).toBeVisible();
    expect(screen.getByText("Market:")).toBeVisible();
    expect(screen.getByText("Type:")).toBeVisible();
    expect(screen.getByText("Created:")).toBeVisible();
  });

  // ---- Failed state ----

  it("shows failed state on API error", async () => {
    mockListModels.mockRejectedValue(new Error("Network down"));
    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByText("Network down")).toBeVisible();
    });
  });

  // ---- Stale warning ----

  it("shows stale warning for old models", async () => {
    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByLabelText(/Stale: model is.*days old/i)).toBeVisible();
    });
  });

  // ---- Gate failures ----

  it("displays gate failure reasons after failed promotion", async () => {
    mockPromoteModel.mockResolvedValue({
      ok: false,
      gate_failures: ["Sharpe ratio 0.3 below minimum 0.5", "Max drawdown exceeds limit"],
    });

    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByText("release-candidate-42")).toBeVisible();
    });

    // Find the promote button for the staging model (not the recommended one)
    const row = getRowContaining("release-candidate-42");
    expect(row).toBeTruthy();
    const promoteButton = within(row!).getByLabelText(/Promote to recommended/i);
    fireEvent.click(promoteButton);

    await waitFor(() => {
      expect(screen.getByText(/Promotion blocked/)).toBeVisible();
      // Gate failures appear in both the inline row and the ReleaseOutcome details
      const failureTexts = screen.getAllByText("Sharpe ratio 0.3 below minimum 0.5");
      expect(failureTexts.length).toBeGreaterThanOrEqual(1);
      const drawdownTexts = screen.getAllByText("Max drawdown exceeds limit");
      expect(drawdownTexts.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ---- Sort by metrics ----

  it("sorts models by Sharpe Ratio when clicking column header", async () => {
    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByText("release-candidate-42")).toBeVisible();
    });

    // Click the Sharpe column header (find the th, not the filter button)
    const sharpeHeader = screen.getAllByText("Sharpe").find(
      (el) => el.closest("th") && el.closest("th")!.querySelector("svg"),
    );
    expect(sharpeHeader).toBeTruthy();
    fireEvent.click(sharpeHeader!.closest("th")!);

    // After sorting descending, recommended model (Sharpe 2.1) should appear first
    const rows = screen.getAllByRole("row");
    // First data row (after header) should contain the highest Sharpe
    const firstDataRow = rows[1]; // rows[0] is header
    expect(within(firstDataRow).getByText("recommended-model")).toBeTruthy();
  });

  // ---- Market filter ----

  it("triggers a new fetch with market=us when US filter is clicked", async () => {
    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByText("release-candidate-42")).toBeVisible();
    });

    // Find the US market filter button (not the market badge in the table)
    const usButtons = screen.getAllByText(/us/i);
    const usMarketButton = usButtons.find((el) => {
      const btn = el.closest("button");
      return btn && btn.className.includes("uppercase");
    });
    expect(usMarketButton).toBeTruthy();
    fireEvent.click(usMarketButton!);

    // Should trigger a new fetch with market=us
    await waitFor(() => {
      expect(mockListModels).toHaveBeenCalledWith("us", expect.anything());
    });
  });

  // ---- Min Sharpe filter ----

  it("filters models by minimum Sharpe threshold", async () => {
    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByText("release-candidate-42")).toBeVisible();
    });

    const input = screen.getByPlaceholderText("e.g. 0.5");
    fireEvent.change(input, { target: { value: "2.0" } });

    // Only the recommended model (Sharpe 2.1) should remain
    await waitFor(() => {
      expect(screen.queryByText("release-candidate-42")).toBeNull();
      expect(screen.getByText("recommended-model")).toBeVisible();
    });
  });

  // ---- URL identity matching ----

  it("highlights model matching route identity", async () => {
    renderModelsPage("?model_id=artifact-release-42");

    await waitFor(() => {
      const row = screen.getByText("release-candidate-42").closest("tr");
      expect(row).toBeTruthy();
      expect(row!.className).toContain("bg-primary/5");
    });
  });

  it("shows blocked outcome when route identity run_id mismatches", async () => {
    renderModelsPage("?model_id=artifact-release-42&run_id=run-different");

    await waitFor(() => {
      expect(screen.getByText(/is bound to run/)).toBeVisible();
    });
  });

  it("shows blocked outcome when route identity snapshot_id mismatches", async () => {
    renderModelsPage("?model_id=artifact-release-42&snapshot_id=snapshot-different");

    await waitFor(() => {
      expect(screen.getByText(/is bound to snapshot/)).toBeVisible();
    });
  });

  // ---- Refresh ----

  it("refetches models on refresh button click", async () => {
    renderModelsPage();

    await waitFor(() => {
      expect(screen.getByText("release-candidate-42")).toBeVisible();
    });

    expect(mockListModels).toHaveBeenCalledTimes(1);

    const refreshButton = screen.getByText("Refresh").closest("button")!;
    fireEvent.click(refreshButton);

    await waitFor(() => {
      expect(mockListModels).toHaveBeenCalledTimes(2);
    });
  });
});
