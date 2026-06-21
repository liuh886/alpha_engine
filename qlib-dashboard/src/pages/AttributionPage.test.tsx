import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttributionPage } from "./AttributionPage";

const mockApiFetch = vi.fn();

vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
}));

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <>{children}</>,
  LineChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CartesianGrid: () => null,
  Legend: () => null,
  Line: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
}

describe("AttributionPage percentage contracts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApiFetch.mockImplementation((url: string) => {
      if (url.startsWith("/api/models")) return jsonResponse({ ok: true, versions: [] });
      return jsonResponse({
        ok: true,
        summary: {
          total_return: 4.2,
          excess_return: 1.1,
          factor_coverage: 0.72,
          unexplained_return: 0.4,
        },
        factors: [{
          factor_id: 1,
          factor_name: "momentum",
          factor_expression: "$close / Ref($close, 20) - 1",
          ic: 0.08,
          return_contribution: 12.5,
          risk_contribution: 25,
          exposure: 0.4,
          status: "Active",
        }],
      });
    });
  });

  it("renders R-squared as a ratio and risk contribution as an existing percent", async () => {
    render(<AttributionPage />);

    await waitFor(() => expect(screen.getAllByText("momentum")).toHaveLength(2));
    expect(screen.getByText("72.0%")).toBeVisible();
    expect(screen.getByText("25.00%")).toBeVisible();
    expect(screen.queryByText("2500.00%")).not.toBeInTheDocument();
  });
});
