import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SignalDiscoveryReport } from "@/lib/api-types";
import { SignalDiscoveryPanel } from "./SignalDiscoveryPanel";

const report: SignalDiscoveryReport = {
  schema_version: "1.0",
  market: "us",
  generated_at: "2026-07-05T00:00:00Z",
  label_horizon: 10,
  rebalance_days: 10,
  promoted: [],
  research_only: ["lgbm_regressor/original"],
  warnings: ["No candidate met all promotion thresholds."],
  summary: {
    best_candidate: "lgbm_regressor/original",
    best_candidate_summary: {
      candidate: "lgbm_regressor/original",
      direction: "keep_score",
      strength: "Positive rank IC and spread.",
      weakness: "ICIR remains below promotion threshold.",
    },
  },
  candidates: [{
    candidate_kind: "lgbm_regressor",
    orientation: "original",
    ic: 0.03,
    rank_ic: 0.04,
    icir: 0.2,
    positive_ic_ratio: 0.55,
    total_return: 0.1,
    benchmark_return: 0.08,
    excess_return: 0.02,
    sharpe: 0.7,
    max_drawdown: -0.06,
    turnover: 1.2,
    costs: 0.002,
    score_direction: {
      top_bucket_return: 0.03,
      bottom_bucket_return: 0.01,
      top_minus_bottom_spread: 0.02,
      rank_ic: 0.04,
      recommendation: "keep_score",
    },
    status: "research_candidate",
    promotion_blockers: ["ICIR 0.2 < 0.3"],
    top_selected_stocks: ["AAPL", "MSFT"],
    strength_rationale: "Positive rank IC and spread.",
    weakness_rationale: "ICIR remains below promotion threshold.",
  }],
};

describe("SignalDiscoveryPanel", () => {
  it("shows the best candidate, direction, evidence, stocks, and truthful warning", () => {
    render(<SignalDiscoveryPanel report={report} />);

    expect(screen.getByText("10D Signal Discovery")).toBeInTheDocument();
    expect(screen.getByText("lgbm_regressor/original")).toBeInTheDocument();
    expect(screen.getAllByText("keep score").length).toBeGreaterThan(0);
    expect(screen.getByText("AAPL, MSFT")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("No candidate met all promotion thresholds");
  });
});
