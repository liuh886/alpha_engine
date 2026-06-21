import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReportsPage } from "./ReportsPage";

const mockApiFetch = vi.fn();

vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
}));

describe("ReportsPage", () => {
  const reportWindow = {
    close: vi.fn(),
    location: { href: "" },
    opener: window,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        reports: [{
          id: "report-1",
          type: "backtest",
          ref_id: "run-1",
          date: "2026-06-20",
          paths: { html: "artifacts/reports/report.html" },
          meta: { market: "us" },
        }],
      }),
      blob: () => Promise.resolve(new Blob(["<h1>Report</h1>"], { type: "text/html" })),
    });
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:report-1"),
    });
    reportWindow.location.href = "";
    reportWindow.opener = window;
    vi.spyOn(window, "open").mockImplementation(() => reportWindow as unknown as Window);
  });

  it("opens report files through the authenticated reports API", async () => {
    render(<ReportsPage />);
    await screen.findByText("report-1");
    expect(mockApiFetch).toHaveBeenCalledWith("/api/reports?limit=100");

    fireEvent.click(screen.getByText("Open"));

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith("/api/reports/report-1/file?format=html");
      expect(window.open).toHaveBeenCalledWith("about:blank", "_blank");
      expect(reportWindow.opener).toBeNull();
      expect(reportWindow.location.href).toBe("blob:report-1");
    });
  });
});
