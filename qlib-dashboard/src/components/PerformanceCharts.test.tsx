import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PerformanceCharts } from "./PerformanceCharts";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <>{children}</>,
  ComposedChart: ({ data, children }: { data: unknown[]; children: ReactNode }) => (
    <div data-testid="chart-data" data-chart={JSON.stringify(data)}>{children}</div>
  ),
  Area: () => null,
  Brush: () => null,
  CartesianGrid: () => null,
  Legend: () => null,
  Line: ({ dataKey, name }: { dataKey: string; name: string }) => (
    <span data-testid="benchmark-line" data-key={dataKey}>{name}</span>
  ),
  ReferenceLine: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

function equityChartData() {
  const raw = screen.getAllByTestId("chart-data")[0].getAttribute("data-chart");
  return JSON.parse(raw || "[]") as Array<Record<string, number | null>>;
}

describe("PerformanceCharts benchmark infrastructure", () => {
  it("shows QQQ as the named default baseline for US evidence", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, bench_qqq: 10_000 },
        { date: "2026-01-02", account: 10_100, bench_qqq: 10_050 },
        { date: "2026-01-03", account: 10_200, bench_qqq: 10_100 },
      ]} />,
    );

    const data = equityChartData();
    expect(data.map((row) => row.benchmark_qqq)).toEqual([0, 0.005, 0.01]);
    expect(data[2].excess).toBeCloseTo(0.01, 10);
    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-default-benchmark", "QQQ");
    expect(screen.getAllByTestId("benchmark-line").some((line) => line.textContent === "QQQ")).toBe(true);
  });

  it("shows CSI 300 as the named default baseline for CN evidence", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 1, bench_hs300: 1 },
        { date: "2026-01-02", account: 1.04, bench_hs300: 1.01 },
        { date: "2026-01-03", account: 1.02, bench_hs300: 0.99 },
      ]} />,
    );

    const data = equityChartData();
    expect(data[1].benchmark_csi300).toBeCloseTo(0.01, 10);
    expect(data[1].excess).toBeCloseTo(0.03, 10);
    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-default-benchmark", "CSI 300");
    expect(screen.getAllByTestId("benchmark-line").some((line) => line.textContent === "CSI 300")).toBe(true);
  });

  it("prefers named benchmark evidence over the generic source column", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, bench: 0, bench_qqq: 10_000 },
        { date: "2026-01-02", account: 10_100, bench: 0.02, bench_qqq: 10_050 },
        { date: "2026-01-03", account: 10_200, bench: 0.02, bench_qqq: 10_100 },
      ]} />,
    );

    const data = equityChartData();
    expect(data[2].benchmark_qqq).toBeCloseTo(0.01, 10);
    expect(data[2].benchmark).toBeNull();
    expect(data[2].excess).toBeCloseTo(0.01, 10);
  });

  it("uses the generic source benchmark only when no named identity is retained", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, bench: 0 },
        { date: "2026-01-02", account: 10_100, bench: 0.01 },
        { date: "2026-01-03", account: 10_201, bench: 0.01 },
      ]} />,
    );

    const data = equityChartData();
    expect(data[0].benchmark).toBe(0);
    expect(data[1].benchmark).toBeCloseTo(0.01, 10);
    expect(data[2].benchmark).toBeCloseTo(0.0201, 10);
    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-default-benchmark", "Benchmark");
  });

  it("fails visibly instead of fabricating a baseline when named benchmark evidence is corrupt", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, bench_qqq: 10_000 },
        { date: "2026-01-02", account: 10_100, bench_qqq: 10_100 },
        { date: "2026-01-03", account: 10_200, bench_qqq: 10_200 },
      ]} />,
    );

    const data = equityChartData();
    expect(data[0].strategy).toBe(0);
    expect(data.every((row) => row.benchmark_qqq === null)).toBe(true);
    expect(data.every((row) => row.excess === null)).toBe(true);
    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-default-benchmark", "unavailable");
    expect(screen.getByText("Baseline evidence unavailable")).toBeInTheDocument();
  });

  it("handles empty report gracefully", () => {
    render(<PerformanceCharts report={[]} />);
    expect(equityChartData()).toEqual([]);
  });

  it("handles invalid initial account", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 0 },
        { date: "2026-01-02", account: 0 },
      ]} />,
    );
    expect(equityChartData()).toEqual([]);
  });

  it("handles missing date rows in monthly returns", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000 },
        { date: "", account: 10_100 },
        { date: "2026-01-03", account: 10_200 },
      ]} />,
    );
    expect(equityChartData().length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("chart-data").length).toBeGreaterThanOrEqual(1);
  });
});
