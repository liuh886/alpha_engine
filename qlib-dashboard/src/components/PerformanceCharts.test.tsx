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
  Bar: () => null,
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
  it('labels an observed-range comparison separately from a source metric and counts provisional marks', () => {
    render(<PerformanceCharts benchmarkId="QQQ" report={[
      { date: '2024-01-02', holding_end_date: '2024-01-17', account: .9, bench_qqq: 1.01 },
      { date: '2024-01-17', holding_end_date: '2024-01-31', account: 1.1, bench_qqq: 1.1 },
      { date: '2024-02-01', holding_end_date: '2024-02-02', account: 1.2, bench_qqq: 1.2, provisional_mtm: true },
    ]} />);
    expect(screen.getByTestId('visible-period-dates')).toHaveTextContent('2024-01-17 – 2024-02-02 · 3 observations · Chart comparison');
    expect(screen.getByTestId('chart-return-basis')).toHaveTextContent('not the published source return');
    expect(screen.getByTestId('chart-return-basis')).toHaveTextContent('wealth at the first selected observation (2024-01-17)');
    expect(screen.getByTestId('chart-return-basis')).toHaveTextContent('excludes the interval ending at that observation');
    expect(screen.getByTestId('chart-return-basis')).toHaveTextContent('1 provisional observation(s)');
    expect(screen.getByTestId('visible-strategy-return')).toHaveTextContent('33.33%');
    expect(screen.getByTestId('visible-benchmark-return')).toHaveTextContent('18.81%');
  });

  it('restores the declared strategy benchmark by default rather than a different stock comparison', () => {
    render(<PerformanceCharts benchmarkId="BYD v1.2" report={[
      { date: '2026-01-01', account: 1, bench_byd_v1_2: 1, bench_byd: 100 },
      { date: '2026-01-02', account: 1.2, bench_byd_v1_2: 1.1, bench_byd: 200 },
    ]} />);
    expect(screen.getByTestId('equity-curve-container')).toHaveAttribute('data-default-benchmark', 'BYD v1.2');
    expect(screen.getByTestId('visible-benchmark-return')).toHaveTextContent('10.00%');
    expect(screen.getByTestId('visible-excess-return')).toHaveTextContent('9.09%');
  });
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
    expect(data[2].excess).toBeCloseTo(1.02 / 1.01 - 1, 10);
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
    expect(data[1].excess).toBeCloseTo(1.04 / 1.01 - 1, 10);
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
    expect(data[1].excess).toBeCloseTo(1.04 / 1.01 - 1, 10);
    expect(data[1].primary_benchmark_key).toBe("benchmark_csi300");
    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-default-benchmark", "CSI 300");
  });

  it("lets the user switch the primary benchmark while defaulting BYD to the stock itself", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 1, benchmark_id: "BYD", bench_byd: 100, bench_byd_v1_1: 1 },
        { date: "2026-01-02", account: 1.05, benchmark_id: "BYD", bench_byd: 102, bench_byd_v1_1: 1.01 },
        { date: "2026-01-03", account: 1.08, benchmark_id: "BYD", bench_byd: 104, bench_byd_v1_1: 1.02 },
      ]} />,
    );

    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-default-benchmark", "BYD");
    expect(screen.getByTestId("benchmark-line")).toHaveTextContent("BYD");

    fireEvent.click(screen.getByLabelText("Benchmark comparisons"));
    fireEvent.click(screen.getByLabelText("Use BYD v1.1 as primary benchmark"));

    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-default-benchmark", "BYD v1.1");
    expect(screen.getAllByTestId("benchmark-line").some(line => line.textContent === "BYD v1.1")).toBe(true);
    expect(equityChartData()[1].excess).toBeCloseTo(1.05 / 1.01 - 1, 10);
  });

  it("can overlay several comparisons without changing Excess until the primary changes", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 1, benchmark_id: "QQQ", bench_qqq: 1, bench_hs300: 1 },
        { date: "2026-01-02", account: 1.08, benchmark_id: "QQQ", bench_qqq: 1.02, bench_hs300: 1.04 },
        { date: "2026-01-03", account: 1.12, benchmark_id: "QQQ", bench_qqq: 1.04, bench_hs300: 1.05 },
      ]} />,
    );

    expect(equityChartData()[1].excess).toBeCloseTo(1.08 / 1.02 - 1, 10);
    fireEvent.click(screen.getByLabelText("Benchmark comparisons"));
    fireEvent.click(screen.getByLabelText("Compare CSI 300"));

    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-comparison-count", "2");
    expect(screen.getAllByTestId("benchmark-line").map(line => line.textContent)).toEqual(expect.arrayContaining(["QQQ", "CSI 300"]));
    expect(equityChartData()[1].excess).toBeCloseTo(1.08 / 1.02 - 1, 10);
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
    expect(data[2].excess).toBeCloseTo(1.02 / 1.01 - 1, 10);
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

  it("supports quick time windows and rebases the visible-period summary", () => {
    render(
      <PerformanceCharts report={[
        { date: "2024-01-01", account: 100 },
        { date: "2025-01-01", account: 110 },
        { date: "2026-01-01", account: 120 },
        { date: "2026-08-01", account: 150 },
      ]} />,
    );

    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-range", "all");
    fireEvent.click(screen.getByRole("button", { name: "1Y" }));

    const data = equityChartData();
    expect(data.map(row => row.date)).toEqual(["2026-01-01", "2026-08-01"]);
    expect(data[0].strategy).toBeCloseTo(0);
    expect(data[1].strategy).toBeCloseTo(0.25);
    expect(screen.getByTestId("equity-curve-container")).toHaveAttribute("data-range", "1y");
    expect(screen.getByTestId("visible-strategy-return")).toHaveTextContent("25.00%");
  });

  it("retains turnover in the visualization data for capital-use analysis", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 100, value: 75, turnover: 0.1 },
        { date: "2026-01-02", account: 101, value: 80, turnover: 0.25 },
      ]} />,
    );

    const data = equityChartData();
    expect(data[1].pos_ratio).toBeCloseTo(80 / 101, 10);
    expect(data[1].turnover).toBeCloseTo(0.25, 10);
    expect(screen.getByText("Capital Use")).toBeInTheDocument();
  });

  it("labels chart max drawdown as a range-scoped approximation of the sealed metric", () => {
    render(
      <PerformanceCharts report={[
        { date: "2026-01-01", account: 100 },
        { date: "2026-01-02", account: 80 },
        { date: "2026-01-03", account: 90 },
      ]} />,
    );

    expect(screen.getByText("Max drawdown (chart)")).toBeInTheDocument();
    expect(screen.getByTestId("max-drawdown-stat")).toHaveTextContent("-20.00%");

    const provenance = screen.getByTestId("drawdown-provenance");
    expect(provenance).toHaveTextContent(/equity\/peak/);
    expect(provenance).toHaveTextContent(/sealed Bundle v2/i);
  });

  it("uses one custom interval for curves, summary, drawdown and capital use", () => {
    render(<PerformanceCharts report={[
      { date: '2026-01-01', account: 100, bench_qqq: 100, value: 50 },
      { date: '2026-01-08', account: 120, bench_qqq: 110, value: 60 },
      { date: '2026-01-15', account: 90, bench_qqq: 99, value: 45 },
      { date: '2026-01-22', account: 108, bench_qqq: 121, value: 54 },
    ]} />);
    fireEvent.change(screen.getByLabelText('Performance start date'), { target: { value: '2026-01-07' } });
    fireEvent.change(screen.getByLabelText('Performance end date'), { target: { value: '2026-01-20' } });
    expect(screen.getByTestId('equity-curve-container')).toHaveAttribute('data-range', 'custom');
    expect(screen.getByTestId('visible-period-dates')).toHaveTextContent('2026-01-08 – 2026-01-15');
    const curves = equityChartData();
    expect(curves.map(row => row.date)).toEqual(['2026-01-08', '2026-01-15']);
    expect(curves[0].strategy).toBeCloseTo(0);
    expect(curves[1].strategy).toBeCloseTo(-0.25);
    expect(curves[1].benchmark_qqq).toBeCloseTo(-0.1);
    expect(screen.getByTestId('visible-strategy-return')).toHaveTextContent('-25.00%');
    expect(screen.getByTestId('max-drawdown-stat')).toHaveTextContent('-25.00%');
    const charts = screen.getAllByTestId('chart-data').map(node => JSON.parse(node.getAttribute('data-chart') ?? '[]'));
    expect(charts.every(rows => rows.length === 2)).toBe(true);
    expect(charts[1][1].drawdown).toBeCloseTo(-0.25);
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    expect(equityChartData()).toHaveLength(4);
    expect(screen.getByTestId('visible-strategy-return')).toHaveTextContent('8.00%');
  });

  it("does not substitute a later benchmark boundary when the selected start is missing", () => {
    render(<PerformanceCharts report={[
      { date: '2025-01-01', account: 100, bench_qqq: 100 },
      { date: '2026-01-01', account: 120 },
      { date: '2026-02-01', account: 132, bench_qqq: 110 },
      { date: '2026-03-01', account: 144, bench_qqq: 121 },
    ]} />);
    fireEvent.change(screen.getByLabelText('Performance start date'), { target: { value: '2026-01-01' } });
    expect(equityChartData().every(row => row.benchmark_qqq === null)).toBe(true);
    expect(screen.getByTestId('visible-benchmark-return')).toHaveTextContent('—');
    expect(screen.getByRole('note')).toHaveTextContent('no valid wealth series at both selected boundaries');
    expect(screen.getByTestId('visible-strategy-return')).toHaveTextContent('20.00%');
  });

  it("resets custom evidence indices when a refreshed report arrives", () => {
    const { rerender } = render(<PerformanceCharts report={[
      { date: '2026-01-01', account: 100 },
      { date: '2026-01-02', account: 90 },
    ]} />);
    fireEvent.change(screen.getByLabelText('Performance start date'), { target: { value: '2026-01-02' } });
    expect(equityChartData()).toHaveLength(1);
    expect(screen.getByTestId('max-drawdown-stat')).toHaveTextContent('0.00%');
    rerender(<PerformanceCharts report={[
      { date: '2026-02-01', account: 100 },
      { date: '2026-02-02', account: 120 },
      { date: '2026-02-03', account: 130 },
    ]} />);
    expect(equityChartData()).toHaveLength(3);
    expect(screen.getByTestId('visible-period-dates')).toHaveTextContent('2026-02-01 – 2026-02-03');
    expect(screen.getByTestId('visible-strategy-return')).toHaveTextContent('30.00%');
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
  it("includes initial losses, excludes before fields from benchmarks, and switches 1M/3M/1Y", () => {
    render(<PerformanceCharts benchmarkId="000300" report={[
      { date: "2025-01-01", account_before: 1, account: 0.95, bench_hs300_before: 1, bench_hs300: 0.96 },
      { date: "2026-01-01", account: 1.1, bench_hs300: 1.02 },
      { date: "2026-06-01", account: 1.2, bench_hs300: 1.05 },
      { date: "2026-08-01", account: 1.3, bench_hs300: 1.1 },
      { date: "2026-08-31", account: 1.43, bench_hs300: 1.2 },
    ]} />);
    expect(screen.getByTestId("visible-strategy-return")).toHaveTextContent("43.00%");
    expect(screen.getByTestId("visible-benchmark-return")).toHaveTextContent("20.00%");
    expect(screen.getByTestId("visible-excess-return")).toHaveTextContent("19.17%");
    expect(screen.getByTestId('chart-return-basis')).toHaveTextContent('declared opening wealth before the first observation; includes the first interval');
    expect(equityChartData()[0].strategy).toBeCloseTo(-0.05);
    expect(Object.keys(equityChartData()[0]).some(key => key.endsWith('_before'))).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '1M' }));
    expect(screen.getByTestId('chart-return-basis')).toHaveTextContent('wealth at the first selected observation (2026-08-01)');
    expect(equityChartData()[0].strategy).toBeCloseTo(0);
    expect(equityChartData()[0].benchmark_csi300).toBeCloseTo(0);
    expect(equityChartData()[equityChartData().length - 1].strategy).toBeCloseTo(0.1);
    expect(equityChartData()[equityChartData().length - 1].benchmark_csi300).toBeCloseTo(1.2 / 1.1 - 1);
    expect(equityChartData()[equityChartData().length - 1].excess).toBeCloseTo(1.1 / (1.2 / 1.1) - 1);
    expect(screen.getByTestId('visible-strategy-return')).toHaveTextContent('10.00%');
    fireEvent.click(screen.getByRole('button', { name: '3M' }));
    expect(screen.getByTestId('visible-strategy-return')).toHaveTextContent('19.17%');
    fireEvent.click(screen.getByRole('button', { name: '1Y' }));
    expect(screen.getByTestId('visible-strategy-return')).toHaveTextContent('30.00%');
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    expect(screen.getByTestId('visible-strategy-return')).toHaveTextContent('43.00%');
  });

});
