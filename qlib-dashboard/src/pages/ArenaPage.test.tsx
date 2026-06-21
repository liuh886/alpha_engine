import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ArenaPage } from "./ArenaPage";
import { MemoryRouter } from "react-router-dom";

const mockApiFetch = vi.fn();

vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
}));

function response(body: unknown) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(body),
    blob: () => Promise.resolve(new Blob(["<h1>Arena</h1>"], { type: "text/html" })),
  });
}

describe("ArenaPage", () => {
  const reportWindow = {
    close: vi.fn(),
    location: { href: "" },
    opener: window,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockApiFetch.mockImplementation((url: string) => {
      if (url === "/api/arena/list") {
        return response({ arenas: [{ id: "arena-1", name: "US Arena", market: "us" }] });
      }
      if (url.startsWith("/api/arena/leaderboard")) {
        return response({ leaderboard: [], date: "" });
      }
      return response({ reports: [{
        id: "report-1",
        type: "arena_daily",
        ref_id: "arena-1",
        paths: { html: "artifacts/reports/arena.html" },
      }] });
    });
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:arena-report"),
    });
    reportWindow.location.href = "";
    reportWindow.opener = window;
    vi.spyOn(window, "open").mockImplementation(() => reportWindow as unknown as Window);
  });

  it("renders an empty state after an empty leaderboard response", async () => {
    render(
      <MemoryRouter>
        <ArenaPage />
      </MemoryRouter>
    );

    expect(await screen.findByText(/No leaderboard results\. Run a settlement to add contestants\./i)).toBeVisible();
    await waitFor(() => expect(screen.queryByText(/Loading leaderboard.../i)).not.toBeInTheDocument());
  });

  it("opens the full report through the authenticated reports API", async () => {
    render(
      <MemoryRouter>
        <ArenaPage />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByText("Full Report"));

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith("/api/reports/report-1/file?format=html");
      expect(window.open).toHaveBeenCalledWith("about:blank", "_blank");
      expect(reportWindow.opener).toBeNull();
      expect(reportWindow.location.href).toBe("blob:arena-report");
    });
  });
});
