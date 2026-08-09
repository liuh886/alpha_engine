import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
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
  return JSON.parse(raw || "[]") as Array<Record<string, number | string | null>>;
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
    expect(data[0].benchmark_qqq).toBe(0);
    expect(data[1].benchmark_qqq).toBeCloseTo(0.005, 10);
    expect(data[2].benchmark_qqq).toBeCloseTo(0.01, 10);
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

  it("uses the formal benchmark identity instead of choosing the first named series", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, benchmark_id: "CSI300", bench_qqq: 10_000, bench_hs300: 10_000 },
        { date: "2026-01-02", account: 10_400, benchmark_id: "CSI300", bench_qqq: 10_300, bench_hs300: 10_100 },
        { date: "2026-01-03", account: 10_600, benchmark_id: "CSI300", bench_qqq: 10_500, bench_hs300: 10_200 },
      ]} />,
    );

    const data = equityChartData();
    expect(data[1].excess).toBeCloseTo(0.03, 10);
    expect(data[1].primary_benchmark_key).toBe("benchmark_csi300");
    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-default-benchmark", "CSI 300");
  });

  it("lets the user switch between retained baselines while defaulting BYD to the stock itself", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 1, benchmark_id: "BYD", bench_byd: 100, bench_byd_v1_1: 1 },
        { date: "2026-01-02", account: 1.05, benchmark_id: "BYD", bench_byd: 102, bench_byd_v1_1: 1.01 },
        { date: "2026-01-03", account: 1.08, benchmark_id: "BYD", bench_byd: 104, bench_byd_v1_1: 1.02 },
      ]} />,
    );

    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-default-benchmark", "BYD");
    expect(screen.getByTestId("benchmark-line")).toHaveTextContent("BYD");

    fireEvent.change(screen.getByLabelText("Chart baseline"), { target: { value: "benchmark_byd_v1_1" } });

    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-default-benchmark", "BYD v1.1");
    expect(screen.getByTestId("benchmark-line")).toHaveTextContent("BYD v1.1");
    expect(equityChartData()[1].excess).toBeCloseTo(0.04, 10);
  });

  it("plots 10-session returns on their realized holding-end date", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-07-01", holding_end_date: "2026-07-16", account: 1, bench_qqq: 1 },
        { date: "2026-07-16", holding_end_date: "2026-07-30", account: 1.1, bench_qqq: 1.05 },
      ]} />,
    );

    const data = equityChartData();
    expect(data[0].date).toBe("2026-07-16");
    expect(data[1].date).toBe("2026-07-30");
    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-realized-through", "2026-07-30");
    expect(screen.getByText("Settled returns through 2026-07-30")).toBeInTheDocument();
  });

  it("keeps generic source evidence secondary when a named benchmark is retained", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, bench: 0, bench_qqq: 10_000 },
        { date: "2026-01-02", account: 10_100, bench: 0.02, bench_qqq: 10_050 },
        { date: "2026-01-03", account: 10_200, bench: 0.02, bench_qqq: 10_100 },
      ]} />,
    );

    const data = equityChartData();
    expect(data[2].benchmark_qqq).toBeCloseTo(0.01, 10);
    expect(data[2].excess).toBeCloseTo(0.01, 10);
    expect(screen.getAllByTestId("benchmark-line").some((line) => line.textContent === "Benchmark")).toBe(false);
  });

  it("uses a generic retained series as the declared baseline without inventing identity", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, benchmark_id: "SPY", bench: 0 },
        { date: "2026-01-02", account: 10_100, benchmark_id: "SPY", bench: 0.01 },
        { date: "2026-01-03", account: 10_201, benchmark_id: "SPY", bench: 0.01 },
      ]} />,
    );

    const data = equityChartData();
    expect(data[0].benchmark).toBe(0);
    expect(data[1].benchmark).toBeCloseTo(0.01, 10);
    expect(data[2].benchmark).toBeCloseTo(0.0201, 10);
    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-default-benchmark", "SPY");
    expect(screen.getAllByTestId("benchmark-line").some((line) => line.textContent === "SPY")).toBe(true);
  });

  it("does not substitute another named benchmark when the declared baseline is corrupt", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 10_000, benchmark_id: "QQQ", bench_qqq: 10_000, bench_hs300: 10_000 },
        { date: "2026-01-02", account: 10_100, benchmark_id: "QQQ", bench_qqq: 10_100, bench_hs300: 10_050 },
        { date: "2026-01-03", account: 10_200, benchmark_id: "QQQ", bench_qqq: 10_200, bench_hs300: 10_100 },
      ]} />,
    );

    const data = equityChartData();
    expect(data.every((row) => row.benchmark_qqq === null)).toBe(true);
    expect(data.every((row) => row.excess === null)).toBe(true);
    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-default-benchmark", "unavailable");
    expect(screen.getByText("QQQ unavailable")).toBeInTheDocument();
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
