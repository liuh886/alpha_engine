import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricsExpanded } from "./MetricsExpanded";

describe("MetricsExpanded", () => {
  it("shows the complete CN effectiveness evidence", () => {
    render(
      <MetricsExpanded
        metrics={{
          "Total Return": 0.3365,
          "Benchmark Return": 0.2899,
          "Excess Return": 0.0466,
          "Max Drawdown": -0.0454,
          "Sharpe Ratio": 1.3063,
          "IC": 0.0176,
          "ICIR": 0.5761,
          "Positive IC Ratio": 0.7692,
          "Consistency": 0.7692,
          "WF Successful Splits": 13,
          "WF Total Splits": 16,
        }}
      />,
    );

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
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("13/16 successful")).toBeInTheDocument();
  });
});
