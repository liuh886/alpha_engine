import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PerformanceCharts } from "./PerformanceCharts";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <>{children}</>,
  ComposedChart: ({ data }: { data: unknown[]; children: ReactNode }) => (
    <div data-testid="chart-data" data-chart={JSON.stringify(data)} />
  ),
  Area: () => null,
  CartesianGrid: () => null,
  Legend: () => null,
  Line: () => null,
  ReferenceLine: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

function equityChartData() {
  const raw = screen.getAllByTestId("chart-data")[0].getAttribute("data-chart");
  return JSON.parse(raw || "[]") as Array<Record<string, number>>;
}

describe("PerformanceCharts benchmark normalization", () => {
  it("normalizes a benchmark equity curve instead of compounding it as daily returns", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, bench_qqq: 10_000 },
        { date: "2026-01-02", account: 10_100, bench_qqq: 10_100 },
        { date: "2026-01-03", account: 10_200, bench_qqq: 10_200 },
      ]} />,
    );

    const data = equityChartData();
    const values = data.map((row) => row.benchmark_qqq);
    expect(values[0]).toBe(0);
    expect(values[1]).toBeCloseTo(0.01, 10);
    expect(values[2]).toBeCloseTo(0.02, 10);
    expect(data[2].excess).toBeCloseTo(0, 10);
  });

  it("continues compounding a benchmark daily-return series", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, bench_qqq: 0 },
        { date: "2026-01-02", account: 10_100, bench_qqq: 0.01 },
        { date: "2026-01-03", account: 10_201, bench_qqq: 0.01 },
      ]} />,
    );

    const values = equityChartData().map((row) => row.benchmark_qqq);
    expect(values[0]).toBe(0);
    expect(values[1]).toBeCloseTo(0.01, 10);
    expect(values[2]).toBeCloseTo(0.0201, 10);
  });
});
