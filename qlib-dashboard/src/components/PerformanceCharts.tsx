import { useMemo, useState } from 'react';
import { Area, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, Line, ComposedChart, ReferenceLine, Brush } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { format, parseISO } from 'date-fns';
import { cn } from '@/lib/utils';
import type { ReportRow } from '@/lib/types';

function normalizeBenchmarkSeries(values: Array<number | undefined>): number[] {
  const numeric = values.map(value => Number.isFinite(Number(value)) ? Number(value) : null);
  const first = numeric.find((value): value is number => value !== null && value > 0);
  if (first === undefined) return values.map(() => 0);

  // Backtest artifacts use both benchmark equity levels (often starting at
  // 1, 100, or initial capital) and daily returns. Normalize both contracts
  // to cumulative return before charting.
  // Values near zero represent daily returns; values above 0.5 represent
  // equity levels (e.g. initial capital 10000 or normalised 1.0).
  if (first > 0.5) {
    let previous = first;
    return numeric.map(value => {
      if (value !== null) previous = value;
      return previous / first - 1;
    });
  }

  let cumulative = 1;
  return numeric.map(value => {
    cumulative *= 1 + (value ?? 0);
    return cumulative - 1;
  });
}

export function PerformanceCharts({ report }: { report: ReportRow[] }) {
  const [hiddenSeries, setHiddenSeries] = useState<Record<string, boolean>>({});

   
  const toggleVisibility = (entry: any) => {
    const key = String(entry?.dataKey ?? '');
    if (key) {
      setHiddenSeries(prev => ({ ...prev, [key]: !prev[key] }));
    }
  };

  const chartData = useMemo(() => {
    if (!report.length) return [];
    const initialAccount = Number(report[0].account);
    // Bail out if the first account value is missing or invalid — all curves
    // are normalised against it and would render NaN/Infinity silently.
    if (!Number.isFinite(initialAccount) || initialAccount <= 0) return [];

    // ── Benchmark data source ──────────────────────────────────────────
    // Qlib artefacts carry a "bench" column with daily benchmark returns.
    // Newer training paths append "bench_qqq" / "bench_hs300" (equity-level
    // or daily-return columns).  Prefer the Qlib "bench" column when present
    // and valid; fall back to the merged columns otherwise.
    const benchDaily: Array<number | undefined> = report.map(row => row.bench);
    const benchQqq: Array<number | undefined> = report.map(row => row.bench_qqq);
    const benchHs300: Array<number | undefined> = report.map(row => row.bench_hs300);

    const hasBench = benchDaily.some(v => Number.isFinite(Number(v)));
    const hasQqq = benchQqq.some(v => Number.isFinite(Number(v)));
    const hasHs300 = benchHs300.some(v => Number.isFinite(Number(v)));

    // Detect corrupt benchmark data — if every benchmark value equals the
    // corresponding account value, the merge was broken and the series
    // would paint a fake identical curve.
    const isCorrupt = (benchVals: Array<number | undefined>) => {
      if (benchVals.length === 0) return true;
      let differs = false;
      for (let i = 0; i < Math.min(benchVals.length, report.length); i++) {
        const bv = Number(benchVals[i]);
        const av = Number(report[i].account);
        if (!Number.isFinite(bv) || !Number.isFinite(av)) continue;
        // Allow floating-point rounding (1e-6 relative tolerance)
        if (Math.abs(bv - av) > Math.max(Math.abs(av), 1) * 1e-6) { differs = true; break; }
      }
      return !differs;
    };

    // Primary benchmark: Qlib "bench" (daily returns) → compound.
    // Secondary: bench_qqq / bench_hs300 equity series → normalise.
    let benchSeries: number[];
    let benchLabel: string;
    if (hasBench && !isCorrupt(benchDaily)) {
      benchSeries = normalizeBenchmarkSeries(benchDaily);
      benchLabel = 'benchmark';
    } else if (hasQqq && !isCorrupt(benchQqq)) {
      benchSeries = normalizeBenchmarkSeries(benchQqq);
      benchLabel = 'benchmark_qqq';
    } else if (hasHs300 && !isCorrupt(benchHs300)) {
      benchSeries = normalizeBenchmarkSeries(benchHs300);
      benchLabel = 'benchmark_hs300';
    } else {
      // No valid benchmark — still render the strategy curve
      benchSeries = report.map(() => 0);
      benchLabel = '';
    }

    return report.map((d, index) => {
      const account = Number(d.account);
      const strategyRet = Number.isFinite(account)
        ? (account / initialAccount) - 1
        : null as unknown as number;  // Recharts skips null data points
      const benchVal = benchLabel ? benchSeries[index] : null as unknown as number;
      const value = Number(d.value);
      const posRatio = Number.isFinite(account) && account > 0 && Number.isFinite(value)
        ? value / account
        : null as unknown as number;
      return {
        date: d.date,
        strategy: strategyRet,
        benchmark: benchVal,
        excess: Number.isFinite(strategyRet) && Number.isFinite(benchVal)
          ? strategyRet - benchVal
          : null as unknown as number,
        pos_ratio: posRatio,
      };
    });
  }, [report]);

  // T5: Drawdown data
  const drawdownData = useMemo(() => {
    if (!chartData.length) return [];
    // Find first valid strategy value as initial peak
    let peak = 0;
    let initialized = false;
    return chartData.map(d => {
      if (!Number.isFinite(d.strategy)) return { date: d.date, drawdown: null as unknown as number };
      if (!initialized) { peak = d.strategy; initialized = true; }
      if (d.strategy > peak) peak = d.strategy;
      const dd = (d.strategy - peak) / (1 + peak);
      return { date: d.date, drawdown: dd };
    });
  }, [chartData]);

  const maxDrawdown = useMemo(() => {
    if (!drawdownData.length) return null;
    let worst = 0;
    let worstIdx = 0;
    drawdownData.forEach((d, i) => {
      if (Number.isFinite(d.drawdown) && (d.drawdown as number) < worst) {
        worst = d.drawdown as number;
        worstIdx = i;
      }
    });
    return worst < 0 ? { value: worst, date: drawdownData[worstIdx].date, index: worstIdx } : null;
  }, [drawdownData]);

  // T6: Monthly returns
  const monthlyReturns = useMemo(() => {
    if (!report.length) return [];
    const firstAccount = Number(report[0].account);
    if (!Number.isFinite(firstAccount) || firstAccount <= 0) return [];
    const byMonth: Record<string, number[]> = {};
    let prevAccount = firstAccount;
    for (let i = 1; i < report.length; i++) {
      const d = report[i];
      const account = Number(d.account);
      // Skip rows with missing date or invalid account
      if (!d.date || !Number.isFinite(account)) continue;
      const ym = d.date.slice(0, 7); // "YYYY-MM"
      if (!byMonth[ym]) byMonth[ym] = [];
      const dayRet = (account - prevAccount) / prevAccount;
      byMonth[ym].push(dayRet);
      prevAccount = account;
    }
    return Object.entries(byMonth).map(([ym, rets]) => {
      const cumRet = rets.reduce((acc, r) => acc * (1 + r), 1) - 1;
      return { ym, year: ym.slice(0, 4), month: parseInt(ym.slice(5, 7)), return: cumRet };
    });
  }, [report]);

  const monthlyByYear = useMemo(() => {
    const years: Record<string, (number | null)[]> = {};
    for (const m of monthlyReturns) {
      if (!years[m.year]) years[m.year] = Array(12).fill(null);
      years[m.year][m.month - 1] = m.return;
    }
    return years;
  }, [monthlyReturns]);

  const hasBenchmark = useMemo(() => chartData.some(d => Number.isFinite(d.benchmark)), [chartData]);

  const CustomTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number | string; color: string }>; label?: string }) => {
    if (!active || !payload?.length) return null;
    return (
      <div className="bg-background/95 border shadow-lg rounded p-2.5 text-[10px] min-w-[140px]">
        <p className="font-semibold mb-1.5 pb-1 border-b">{label}</p>
        {payload.map((p) => (
          <div key={p.name} className="flex justify-between gap-4 py-0.5">
            <span className="flex items-center gap-1 text-muted-foreground">
              <div className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: p.color }} />
              {p.name}
            </span>
            <span className="font-mono" style={{ color: p.color }}>
              {typeof p.value === 'number' ? `${(p.value * 100).toFixed(2)}%` : p.value}
            </span>
          </div>
        ))}
      </div>
    );
  };

  const colorReturn = (v: number | null) => {
    if (v === null) return "text-muted-foreground/30";
    return v >= 0 ? "text-green-500" : "text-red-500";
  };

  const bgReturn = (v: number | null) => {
    if (v === null) return "";
    const intensity = Math.min(Math.abs(v) * 5, 0.3);
    return v >= 0 ? `rgba(34,197,94,${intensity})` : `rgba(239,68,68,${intensity})`;
  };

  const strategyPointCount = chartData.filter(d => Number.isFinite(d.strategy)).length;

  return (
    <div className="space-y-5">
      {/* 1. Equity Curve */}
      <Card data-testid="equity-curve-container" data-strategy-point-count={String(strategyPointCount)}>
        <CardHeader className="pb-3 border-b">
          <CardTitle className="text-sm font-semibold">Equity Curve</CardTitle>
        </CardHeader>
        <CardContent className="h-[400px] pt-4">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData}>
              <defs>
                <linearGradient id="gradStrategy" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.1} />
              <XAxis dataKey="date" tickFormatter={d => format(parseISO(d), 'MMM yy')} minTickGap={40} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={v => `${(v * 100).toFixed(0)}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={45} />
              <Tooltip content={<CustomTooltip />} cursor={{ stroke: 'hsl(var(--primary))', strokeWidth: 1, strokeDasharray: '4 4' }} />
              <Legend verticalAlign="top" align="right" height={30} iconType="circle" onClick={toggleVisibility} wrapperStyle={{ fontSize: '11px', cursor: 'pointer' }} />
              <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" strokeOpacity={0.3} />
              <Area hide={hiddenSeries['strategy']} type="monotone" dataKey="strategy" stroke="hsl(var(--primary))" strokeWidth={2} fillOpacity={1} fill="url(#gradStrategy)" name="Alpha Engine" />
              {hasBenchmark && <Line hide={hiddenSeries['benchmark']} type="monotone" dataKey="benchmark" stroke="#f59e0b" dot={false} strokeWidth={1.5} strokeDasharray="5 5" name="Benchmark" />}
              <Brush dataKey="date" height={28} stroke="hsl(var(--primary))" fill="hsl(var(--background))" tickFormatter={d => format(parseISO(d), 'MMM yy')} />
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* 2. T5: Drawdown Chart */}
      {drawdownData.length > 0 && (
        <Card data-testid="drawdown-container">
          <CardHeader className="pb-3 border-b">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-semibold">Drawdown</CardTitle>
              {maxDrawdown && (
                <span className="text-xs text-red-500 font-mono">
                  Max: {(maxDrawdown.value * 100).toFixed(2)}% ({maxDrawdown.date})
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent className="h-[200px] pt-4">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={drawdownData}>
                <defs>
                  <linearGradient id="gradDD" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0.2} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.1} />
                <XAxis dataKey="date" tickFormatter={d => format(parseISO(d), 'MMM yy')} minTickGap={40} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={v => `${(v * 100).toFixed(0)}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={45} domain={['dataMin', 0]} />
                <Tooltip content={<CustomTooltip />} cursor={{ stroke: '#ef4444', strokeWidth: 1, strokeDasharray: '4 4' }} />
                <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" strokeOpacity={0.3} />
                <Area type="monotone" dataKey="drawdown" stroke="#ef4444" strokeWidth={1.5} fill="url(#gradDD)" name="Drawdown" />
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* 3. T6: Monthly Returns Heatmap */}
      {monthlyReturns.length > 0 && (
        <Card>
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm font-semibold">Monthly Returns</CardTitle>
          </CardHeader>
          <CardContent className="pt-4 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr>
                  <th className="text-left py-1 pr-3 text-muted-foreground font-medium">Year</th>
                  {["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].map(m => (
                    <th key={m} className="text-center py-1 px-1 text-muted-foreground font-medium">{m}</th>
                  ))}
                  <th className="text-center py-1 pl-3 text-muted-foreground font-medium">Total</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(monthlyByYear).sort(([a],[b]) => a.localeCompare(b)).map(([year, months]) => {
                  const yearTotal = months.reduce((acc, r) => acc !== null && r !== null ? acc * (1 + r) : acc, 1 as number | null);
                  const yearRet = yearTotal !== null ? yearTotal - 1 : null;
                  return (
                    <tr key={year}>
                      <td className="py-1 pr-3 font-mono font-medium">{year}</td>
                      {months.map((r, i) => (
                        <td key={i} className="text-center py-1 px-1">
                          <span className={cn("font-mono", colorReturn(r))} style={{ backgroundColor: bgReturn(r) }}>
                            {r !== null ? `${(r * 100).toFixed(1)}%` : "—"}
                          </span>
                        </td>
                      ))}
                      <td className={cn("text-center py-1 pl-3 font-mono font-medium", colorReturn(yearRet))}>
                        {yearRet !== null ? `${(yearRet * 100).toFixed(1)}%` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* 4. Excess Alpha & Exposure */}
      <Card>
        <CardHeader className="pb-3 border-b">
          <CardTitle className="text-sm font-semibold">Excess Alpha & Exposure</CardTitle>
        </CardHeader>
        <CardContent className="h-[250px] pt-4">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.1} />
              <XAxis dataKey="date" tickFormatter={d => format(parseISO(d), 'MM/yy')} minTickGap={30} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis yAxisId="left" tickFormatter={v => `${(v * 100).toFixed(1)}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={45} />
              <YAxis yAxisId="right" orientation="right" tickFormatter={v => `${(v * 100).toFixed(0)}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={40} />
              <Tooltip content={<CustomTooltip />} />
              <Legend verticalAlign="top" align="right" height={24} iconType="circle" onClick={toggleVisibility} wrapperStyle={{ fontSize: '11px', cursor: 'pointer' }} />
              <Area yAxisId="left" hide={hiddenSeries['excess']} type="monotone" dataKey="excess" stroke="hsl(var(--primary))" fill="hsl(var(--primary))" fillOpacity={0.08} name="Excess Return" />
              <Area yAxisId="right" hide={hiddenSeries['pos_ratio']} type="monotone" dataKey="pos_ratio" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.05} name="Position Ratio" />
              <ReferenceLine yAxisId="left" y={0} stroke="red" strokeDasharray="3 3" strokeOpacity={0.3} />
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}
