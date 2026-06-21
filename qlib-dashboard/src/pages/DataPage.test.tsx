/**
 * Component tests for DataPage.
 *
 * Verifies that snapshot identity, quality verdict, symbol accounting,
 * and distinct outcome states (loading/empty/partial/stale/failed/blocked/success)
 * are rendered correctly against mocked API responses.
 */

import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { DataPage } from "./DataPage";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockGetDataStatus = vi.fn();
const mockGetWatchlist = vi.fn();
const mockAddSymbols = vi.fn();
const mockRemoveSymbols = vi.fn();
const mockSubmitDataUpdate = vi.fn();
const mockGetJob = vi.fn();
const mockGetCompleteness = vi.fn();

vi.mock("@/lib/release-api", () => ({
  releaseApi: {
    getDataStatus: (...args: unknown[]) => mockGetDataStatus(...args),
    getWatchlist: (...args: unknown[]) => mockGetWatchlist(...args),
    addSymbols: (...args: unknown[]) => mockAddSymbols(...args),
    removeSymbols: (...args: unknown[]) => mockRemoveSymbols(...args),
    submitDataUpdate: (...args: unknown[]) => mockSubmitDataUpdate(...args),
    getJob: (...args: unknown[]) => mockGetJob(...args),
    getCompleteness: (...args: unknown[]) => mockGetCompleteness(...args),
  },
}));

vi.mock("@/lib/useNameMap", () => ({
  useNameMap: () => ({ getName: (s: string) => s }),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const FIXTURE_STATUS_OK = {
  ok: true,
  data: {
    latest_calendar_date: "2026-06-20",
    latest_calendar_day: "2026-06-20",
    dashboard_generated_at: "2026-06-20T08:00:00Z",
    latest_snapshot_id: "snapshot-cn-20260620",
    quality_status: "ok",
    quality_warnings: [],
    symbols_configured: 50,
    symbols_updated: 48,
    symbols_failed: 1,
    symbols_stale: 1,
  },
};

const FIXTURE_STATUS_FAILED_QUALITY = {
  ok: true,
  data: {
    latest_snapshot_id: "snapshot-cn-20260620",
    quality_status: "failed",
    quality_warnings: ["Schema validation error on column 'volume'"],
  },
};

const FIXTURE_STATUS_STALE = {
  ok: true,
  data: {
    latest_snapshot_id: "snapshot-old",
    quality_status: "stale",
    quality_warnings: [],
  },
};

const FIXTURE_STATUS_EMPTY = {
  ok: true,
  data: {
    quality_status: "unknown",
    quality_warnings: [],
  },
};

const FIXTURE_STATUS_PARTIAL = {
  ok: true,
  data: {
    latest_snapshot_id: "snapshot-partial",
    quality_status: "warning",
    quality_warnings: ["Missing data for 3 symbols"],
  },
};

const FIXTURE_WATCHLIST = {
  ok: true,
  watchlist: {
    cn: [
      { symbol: "600519", name: "Kweichow Moutai" },
      { symbol: "000001", name: "Ping An Bank" },
    ],
    us: [{ symbol: "AAPL", name: "Apple Inc." }],
    hk: [],
  },
};

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

function renderDataPage(search = "") {
  return render(
    <MemoryRouter initialEntries={[`/data${search}`]}>
      <DataPage />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DataPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetDataStatus.mockResolvedValue(FIXTURE_STATUS_OK);
    mockGetWatchlist.mockResolvedValue(FIXTURE_WATCHLIST);
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  // ---- Loading state ----

  it("shows loading spinner while fetching watchlist", () => {
    mockGetWatchlist.mockReturnValue(new Promise(() => {})); // never resolves
    renderDataPage();

    expect(screen.getByText("Loading watchlist...")).toBeVisible();
  });

  // ---- Snapshot identity ----

  it("displays the latest snapshot ID", async () => {
    renderDataPage();

    await waitFor(() => {
      // The snapshot ID is displayed truncated with "..."
      // Find by title attribute which holds the full ID
      const snapshotEl = screen.getByTitle("snapshot-cn-20260620");
      expect(snapshotEl).toBeVisible();
      expect(snapshotEl.textContent).toMatch(/snapshot-cn/);
    });
  });

  // ---- Quality verdict ----

  it("displays Pass quality verdict for ok status", async () => {
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("Quality Verdict")).toBeVisible();
      expect(screen.getByText("Pass")).toBeVisible();
    });
  });

  it("displays Warning quality verdict for warning status", async () => {
    mockGetDataStatus.mockResolvedValue(FIXTURE_STATUS_PARTIAL);
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("Warning")).toBeVisible();
    });
  });

  it("displays Fail quality verdict for failed status", async () => {
    mockGetDataStatus.mockResolvedValue(FIXTURE_STATUS_FAILED_QUALITY);
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("Fail")).toBeVisible();
    });
  });

  it("displays quality warnings when present", async () => {
    mockGetDataStatus.mockResolvedValue(FIXTURE_STATUS_FAILED_QUALITY);
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("Schema validation error on column 'volume'")).toBeVisible();
    });
  });

  // ---- Symbol accounting ----

  it("displays symbol accounting when available", async () => {
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("Symbol Accounting")).toBeVisible();
      expect(screen.getByText("configured")).toBeVisible();
      expect(screen.getByText("updated")).toBeVisible();
    });
  });

  it("shows failed symbol count when > 0", async () => {
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("failed")).toBeVisible();
    });
  });

  it("shows stale symbol count when > 0", async () => {
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("stale")).toBeVisible();
    });
  });

  it("hides symbol accounting when not available in response", async () => {
    mockGetDataStatus.mockResolvedValue(FIXTURE_STATUS_PARTIAL);
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("Quality Verdict")).toBeVisible();
    });

    // Symbol accounting should not be shown
    expect(screen.queryByText("Symbol Accounting")).toBeNull();
  });

  // ---- Outcome states ----

  it("shows empty outcome when no snapshot exists", async () => {
    mockGetDataStatus.mockResolvedValue(FIXTURE_STATUS_EMPTY);
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText(/No published snapshot/)).toBeVisible();
    });
  });

  it("shows blocked outcome when quality is failed", async () => {
    mockGetDataStatus.mockResolvedValue(FIXTURE_STATUS_FAILED_QUALITY);
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText(/quality checks block/)).toBeVisible();
    });
  });

  it("shows stale outcome when snapshot is stale", async () => {
    mockGetDataStatus.mockResolvedValue(FIXTURE_STATUS_STALE);
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText(/stale/)).toBeVisible();
    });
  });

  it("shows partial outcome when quality has warnings", async () => {
    mockGetDataStatus.mockResolvedValue(FIXTURE_STATUS_PARTIAL);
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText(/incomplete or warning/)).toBeVisible();
    });
  });

  it("shows failed state on API error", async () => {
    mockGetDataStatus.mockRejectedValue(new Error("Connection refused"));
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("Connection refused")).toBeVisible();
    });
  });

  it("shows success outcome with 'Train on this snapshot' button", async () => {
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText(/Snapshot is approved for training/)).toBeVisible();
    });
    await waitFor(() => {
      expect(screen.getByText("Train on this snapshot")).toBeVisible();
    });
  });

  // ---- Watchlist display ----

  it("displays watchlist symbols", async () => {
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("600519")).toBeVisible();
      expect(screen.getByText("Kweichow Moutai")).toBeVisible();
    });
  });

  it("shows empty state for market with no symbols", async () => {
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("600519")).toBeVisible();
    });

    // Click HK market card
    const hkCard = screen.getByLabelText("Select HK market");
    fireEvent.click(hkCard);

    await waitFor(() => {
      expect(screen.getByText("No symbols in HK watchlist")).toBeVisible();
    });
  });

  it("submits an update for the selected market", async () => {
    mockSubmitDataUpdate.mockResolvedValue({ ok: true, job_id: "job-us" });
    mockGetJob.mockResolvedValue({ ok: true, job: { id: "job-us", status: "RUNNING" } });
    renderDataPage();

    fireEvent.click(await screen.findByLabelText("Select US market"));
    fireEvent.click(screen.getByRole("button", { name: "Incremental" }));

    await waitFor(() => expect(mockSubmitDataUpdate).toHaveBeenCalledWith(false, "us"));
  });

  // ---- Job reconnection ----

  it("reconnects to active job from URL params", async () => {
    mockGetJob.mockResolvedValue({
      ok: true,
      job: { id: "job-123", status: "RUNNING" },
    });
    renderDataPage("?job_id=job-123");

    await waitFor(() => {
      expect(screen.getByText("Data Update Job")).toBeVisible();
      expect(screen.getByText("running")).toBeVisible();
    });
  });

  it("shows succeeded state when job completes", async () => {
    mockGetJob.mockResolvedValue({
      ok: true,
      job: { id: "job-123", status: "SUCCEEDED" },
    });
    renderDataPage("?job_id=job-123");

    await waitFor(() => {
      // "Data update published" is rendered as the reason inside a ReleaseOutcome component
      // which splits label and reason into separate spans, so use textContent matching
      const statusEl = screen.getAllByRole("status").find(
        (el) => el.textContent?.includes("Data update published"),
      );
      expect(statusEl).toBeTruthy();
    });
  });

  it("shows failed state when job fails", async () => {
    mockGetJob.mockResolvedValue({
      ok: true,
      job: { id: "job-123", status: "FAILED", error: "Download quota exceeded" },
    });
    renderDataPage("?job_id=job-123");

    await waitFor(() => {
      // "Download quota exceeded" appears in both the ReleaseOutcome and the error detail div
      const matches = screen.getAllByText("Download quota exceeded");
      expect(matches.length).toBeGreaterThanOrEqual(1);
    });
  });

  // ---- Data freshness card ----

  it("displays calendar date", async () => {
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("2026-06-20")).toBeVisible();
    });
  });

  it("displays Data Freshness header", async () => {
    renderDataPage();

    await waitFor(() => {
      expect(screen.getByText("Data Freshness")).toBeVisible();
    });
  });
});
