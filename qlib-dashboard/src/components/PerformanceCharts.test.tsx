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
  it("normalizes a benchmark equity curve (via bench_qqq)", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, bench_qqq: 10_000 },
        { date: "2026-01-02", account: 10_100, bench_qqq: 10_050 },
        { date: "2026-01-03", account: 10_200, bench_qqq: 10_100 },
      ]} />,
    );

    const data = equityChartData();
    const values = data.map((row) => row.benchmark);
    expect(values[0]).toBe(0);
    expect(values[1]).toBeCloseTo(0.005, 10);
    expect(values[2]).toBeCloseTo(0.01, 10);
    expect(data[2].excess).toBeCloseTo(0.01, 10);
  });

  it("compounds a benchmark daily-return series (via bench column)", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, bench: 0 },
        { date: "2026-01-02", account: 10_100, bench: 0.01 },
        { date: "2026-01-03", account: 10_201, bench: 0.01 },
      ]} />,
    );

    const values = equityChartData().map((row) => row.benchmark);
    expect(values[0]).toBe(0);
    expect(values[1]).toBeCloseTo(0.01, 10);
    expect(values[2]).toBeCloseTo(0.0201, 10);
  });

  it("prefers bench column over bench_qqq when both are present", () => {
    // bench has daily returns; bench_qqq is corrupt (matches account)
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, bench: 0.0, bench_qqq: 10_000 },
        { date: "2026-01-02", account: 10_100, bench: 0.01, bench_qqq: 10_100 },
        { date: "2026-01-03", account: 10_200, bench: 0.01, bench_qqq: 10_200 },
      ]} />,
    );

    const values = equityChartData().map((row) => row.benchmark);
    // Uses bench (daily returns, compounded), not bench_qqq
    expect(values[0]).toBe(0);
    expect(values[1]).toBeCloseTo(0.01, 10);
    expect(values[2]).toBeCloseTo(0.0201, 10);
  });

  it("rejects corrupt benchmark that matches account exactly", () => {
    // bench_qqq is identical to account — corrupt data
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, bench_qqq: 10_000 },
        { date: "2026-01-02", account: 10_100, bench_qqq: 10_100 },
        { date: "2026-01-03", account: 10_200, bench_qqq: 10_200 },
      ]} />,
    );

    const data = equityChartData();
    // Strategy curve still renders (always present)
    expect(data[0].strategy).toBe(0);
    // But benchmark is zeroed out because it was corrupt
    const benchVals = data.map((row) => row.benchmark);
    expect(benchVals.every(v => v === 0)).toBe(true);
  });

  it("handles empty report gracefully", () => {
    render(<PerformanceCharts report={[]} />);
    const data = equityChartData();
    expect(data).toEqual([]);
  });

  it("handles invalid initial account", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 0 },
        { date: "2026-01-02", account: 0 },
      ]} />,
    );
    const data = equityChartData();
    expect(data).toEqual([]);
  });

  it("handles missing date rows in monthly returns", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000 },
        { date: "", account: 10_100 },             // empty date — must not crash
        { date: "2026-01-03", account: 10_200 },
      ]} />,
    );
    const data = equityChartData();
    // Should render the valid rows only
    expect(data.length).toBeGreaterThan(0);
    // Monthly returns section should not throw
    const allCharts = screen.getAllByTestId("chart-data");
    expect(allCharts.length).toBeGreaterThanOrEqual(1);
  });
});
