import { useMemo, useState } from 'react';
import { Area, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, Line, ComposedChart, ReferenceLine, Brush } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { format, parseISO } from 'date-fns';
import { cn } from '@/lib/utils';
import type { ReportRow } from '@/lib/types';

type BenchmarkKey = 'benchmark_qqq' | 'benchmark_csi300' | 'benchmark';

function normalizeBenchmarkSeries(values: Array<number | undefined>): number[] | null {
  const numeric = values.map(value => Number.isFinite(Number(value)) ? Number(value) : null);
  const first = numeric.find((value): value is number => value !== null);
  if (first === undefined) return null;

  // Formal evidence can retain either an equity level or a periodic return.
  // A normalized equity trace begins around 1 (or a larger capital base),
  // while a return trace begins near zero. Normalize both to cumulative return.
  if (Math.abs(first) > 0.5) {
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

function benchmarkLooksCorrupt(report: ReportRow[], values: Array<number | undefined>): boolean {
  const normalized = values.map(value => Number.isFinite(Number(value)) ? Number(value) : null);
  const first = normalized.find((value): value is number => value !== null);
  if (first === undefined || Math.abs(first) <= 0.5) return false;

  // Reject the historical merge failure where benchmark equity was copied
  // from strategy equity verbatim. Periodic-return series are not compared
  // against account levels.
  let compared = 0;
  let differs = false;
  for (let index = 0; index < Math.min(values.length, report.length); index += 1) {
    const benchmark = Number(values[index]);
    const account = Number(report[index].account);
    if (!Number.isFinite(benchmark) || !Number.isFinite(account)) continue;
    compared += 1;
    if (Math.abs(benchmark - account) > Math.max(Math.abs(account), 1) * 1e-6) {
      differs = true;
      break;
    }
  }
  return compared > 0 && !differs;
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
    if (!Number.isFinite(initialAccount) || initialAccount <= 0) return [];

    const rawQqq = report.map(row => row.bench_qqq);
    const rawCsi300 = report.map(row => row.bench_hs300);
    const rawGeneric = report.map(row => row.bench);

    const qqq = !benchmarkLooksCorrupt(report, rawQqq) ? normalizeBenchmarkSeries(rawQqq) : null;
    const csi300 = !benchmarkLooksCorrupt(report, rawCsi300) ? normalizeBenchmarkSeries(rawCsi300) : null;

    // `bench` is retained only as an identity-unknown legacy/source fallback.
    // Named benchmark evidence always wins and the browser never invents a
    // zero-return baseline when no benchmark evidence exists.
    const generic = !qqq && !csi300 && !benchmarkLooksCorrupt(report, rawGeneric)
      ? normalizeBenchmarkSeries(rawGeneric)
      : null;
    const primaryBenchmark: BenchmarkKey | null = qqq
      ? 'benchmark_qqq'
      : csi300
        ? 'benchmark_csi300'
        : generic
          ? 'benchmark'
          : null;

    return report.map((row, index) => {
      const account = Number(row.account);
      const strategy = Number.isFinite(account)
        ? (account / initialAccount) - 1
        : null as unknown as number;
      const benchmarkQqq = qqq?.[index] ?? null as unknown as number;
      const benchmarkCsi300 = csi300?.[index] ?? null as unknown as number;
      const benchmark = generic?.[index] ?? null as unknown as number;
      const primaryValue = primaryBenchmark === 'benchmark_qqq'
        ? benchmarkQqq
        : primaryBenchmark === 'benchmark_csi300'
          ? benchmarkCsi300
          : primaryBenchmark === 'benchmark'
            ? benchmark
            : null as unknown as number;
      const value = Number(row.value);
      const posRatio = Number.isFinite(account) && account > 0 && Number.isFinite(value)
        ? value / account
        : null as unknown as number;

      return {
        date: row.date,
        strategy,
        benchmark_qqq: benchmarkQqq,
        benchmark_csi300: benchmarkCsi300,
        benchmark,
        excess: Number.isFinite(strategy) && Number.isFinite(primaryValue)
          ? strategy - primaryValue
          : null as unknown as number,
        pos_ratio: posRatio,
      };
    });
  }, [report]);

  const drawdownData = useMemo(() => {
    if (!chartData.length) return [];
    let peak = 0;
    let initialized = false;
    return chartData.map(row => {
      if (!Number.isFinite(row.strategy)) return { date: row.date, drawdown: null as unknown as number };
      if (!initialized) { peak = row.strategy; initialized = true; }
      if (row.strategy > peak) peak = row.strategy;
      const drawdown = (row.strategy - peak) / (1 + peak);
      return { date: row.date, drawdown };
    });
  }, [chartData]);

  const maxDrawdown = useMemo(() => {
    if (!drawdownData.length) return null;
    let worst = 0;
    let worstIdx = 0;
    drawdownData.forEach((row, index) => {
      if (Number.isFinite(row.drawdown) && (row.drawdown as number) < worst) {
        worst = row.drawdown as number;
        worstIdx = index;
      }
    });
    return worst < 0 ? { value: worst, date: drawdownData[worstIdx].date, index: worstIdx } : null;
  }, [drawdownData]);

  const monthlyReturns = useMemo(() => {
    if (!report.length) return [];
    const firstAccount = Number(report[0].account);
    if (!Number.isFinite(firstAccount) || firstAccount <= 0) return [];
    const byMonth: Record<string, number[]> = {};
    let prevAccount = firstAccount;
    for (let index = 1; index < report.length; index += 1) {
      const row = report[index];
      const account = Number(row.account);
      if (!row.date || !Number.isFinite(account)) continue;
      const yearMonth = row.date.slice(0, 7);
      if (!byMonth[yearMonth]) byMonth[yearMonth] = [];
      const dayReturn = (account - prevAccount) / prevAccount;
      byMonth[yearMonth].push(dayReturn);
      prevAccount = account;
    }
    return Object.entries(byMonth).map(([yearMonth, returns]) => {
      const cumulative = returns.reduce((accumulator, value) => accumulator * (1 + value), 1) - 1;
      return { ym: yearMonth, year: yearMonth.slice(0, 4), month: parseInt(yearMonth.slice(5, 7)), return: cumulative };
    });
  }, [report]);

  const monthlyByYear = useMemo(() => {
    const years: Record<string, (number | null)[]> = {};
    for (const month of monthlyReturns) {
      if (!years[month.year]) years[month.year] = Array(12).fill(null);
      years[month.year][month.month - 1] = month.return;
    }
    return years;
  }, [monthlyReturns]);

  const hasQqq = useMemo(() => chartData.some(row => Number.isFinite(row.benchmark_qqq)), [chartData]);
  const hasCsi300 = useMemo(() => chartData.some(row => Number.isFinite(row.benchmark_csi300)), [chartData]);
  const hasGenericBenchmark = useMemo(() => chartData.some(row => Number.isFinite(row.benchmark)), [chartData]);
  const excessBaseline = hasQqq ? 'QQQ' : hasCsi300 ? 'CSI 300' : hasGenericBenchmark ? 'Benchmark' : null;

  const CustomTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number | string; color: string }>; label?: string }) => {
    if (!active || !payload?.length) return null;
    return (
      <div className="bg-background/95 border shadow-lg rounded p-2.5 text-[10px] min-w-[140px]">
        <p className="font-semibold mb-1.5 pb-1 border-b">{label}</p>
        {payload.map((item) => (
          <div key={item.name} className="flex justify-between gap-4 py-0.5">
            <span className="flex items-center gap-1 text-muted-foreground">
              <div className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: item.color }} />
              {item.name}
            </span>
            <span className="font-mono" style={{ color: item.color }}>
              {typeof item.value === 'number' ? `${(item.value * 100).toFixed(2)}%` : item.value}
            </span>
          </div>
        ))}
      </div>
    );
  };

  const colorReturn = (value: number | null) => {
    if (value === null) return "text-muted-foreground/30";
    return value >= 0 ? "text-green-500" : "text-red-500";
  };

  const bgReturn = (value: number | null) => {
    if (value === null) return "";
    const intensity = Math.min(Math.abs(value) * 5, 0.3);
    return value >= 0 ? `rgba(34,197,94,${intensity})` : `rgba(239,68,68,${intensity})`;
  };

  const strategyPointCount = chartData.filter(row => Number.isFinite(row.strategy)).length;

  return (
    <div className="space-y-5">
      <Card
        data-testid="equity-curve-container"
        data-strategy-point-count={String(strategyPointCount)}
        data-default-benchmark={excessBaseline ?? 'unavailable'}
      >
        <CardHeader className="pb-3 border-b">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-sm font-semibold">Equity Curve</CardTitle>
            <span className="text-[10px] text-muted-foreground">
              {excessBaseline ? `Default baseline · ${excessBaseline}` : 'Baseline evidence unavailable'}
            </span>
          </div>
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
              <XAxis dataKey="date" tickFormatter={date => format(parseISO(date), 'MMM yy')} minTickGap={40} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={value => `${(value * 100).toFixed(0)}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={45} />
              <Tooltip content={<CustomTooltip />} cursor={{ stroke: 'hsl(var(--primary))', strokeWidth: 1, strokeDasharray: '4 4' }} />
              <Legend verticalAlign="top" align="right" height={30} iconType="circle" onClick={toggleVisibility} wrapperStyle={{ fontSize: '11px', cursor: 'pointer' }} />
              <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" strokeOpacity={0.3} />
              <Area hide={hiddenSeries.strategy} type="monotone" dataKey="strategy" stroke="hsl(var(--primary))" strokeWidth={2} fillOpacity={1} fill="url(#gradStrategy)" name="Alpha Engine" />
              {hasQqq && <Line hide={hiddenSeries.benchmark_qqq} type="monotone" dataKey="benchmark_qqq" stroke="#f59e0b" dot={false} strokeWidth={1.5} strokeDasharray="5 5" name="QQQ" />}
              {hasCsi300 && <Line hide={hiddenSeries.benchmark_csi300} type="monotone" dataKey="benchmark_csi300" stroke="#0ea5e9" dot={false} strokeWidth={1.5} strokeDasharray="5 5" name="CSI 300" />}
              {hasGenericBenchmark && <Line hide={hiddenSeries.benchmark} type="monotone" dataKey="benchmark" stroke="#f59e0b" dot={false} strokeWidth={1.5} strokeDasharray="5 5" name="Benchmark" />}
              <Brush dataKey="date" height={28} stroke="hsl(var(--primary))" fill="hsl(var(--background))" tickFormatter={date => format(parseISO(date), 'MMM yy')} />
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

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
                <XAxis dataKey="date" tickFormatter={date => format(parseISO(date), 'MMM yy')} minTickGap={40} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={value => `${(value * 100).toFixed(0)}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={45} domain={['dataMin', 0]} />
                <Tooltip content={<CustomTooltip />} cursor={{ stroke: '#ef4444', strokeWidth: 1, strokeDasharray: '4 4' }} />
                <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" strokeOpacity={0.3} />
                <Area type="monotone" dataKey="drawdown" stroke="#ef4444" strokeWidth={1.5} fill="url(#gradDD)" name="Drawdown" />
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

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
                  {["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].map(month => (
                    <th key={month} className="text-center py-1 px-1 text-muted-foreground font-medium">{month}</th>
                  ))}
                  <th className="text-center py-1 pl-3 text-muted-foreground font-medium">Total</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(monthlyByYear).sort(([left], [right]) => left.localeCompare(right)).map(([year, months]) => {
                  const yearTotal = months.reduce((accumulator, value) => accumulator !== null && value !== null ? accumulator * (1 + value) : accumulator, 1 as number | null);
                  const yearReturn = yearTotal !== null ? yearTotal - 1 : null;
                  return (
                    <tr key={year}>
                      <td className="py-1 pr-3 font-mono font-medium">{year}</td>
                      {months.map((value, index) => (
                        <td key={index} className="text-center py-1 px-1">
                          <span className={cn("font-mono", colorReturn(value))} style={{ backgroundColor: bgReturn(value) }}>
                            {value !== null ? `${(value * 100).toFixed(1)}%` : "—"}
                          </span>
                        </td>
                      ))}
                      <td className={cn("text-center py-1 pl-3 font-mono font-medium", colorReturn(yearReturn))}>
                        {yearReturn !== null ? `${(yearReturn * 100).toFixed(1)}%` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-3 border-b">
          <CardTitle className="text-sm font-semibold">
            {excessBaseline ? `Excess vs ${excessBaseline} & Exposure` : 'Exposure'}
          </CardTitle>
        </CardHeader>
        <CardContent className="h-[250px] pt-4">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.1} />
              <XAxis dataKey="date" tickFormatter={date => format(parseISO(date), 'MM/yy')} minTickGap={30} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis yAxisId="left" tickFormatter={value => `${(value * 100).toFixed(1)}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={45} />
              <YAxis yAxisId="right" orientation="right" tickFormatter={value => `${(value * 100).toFixed(0)}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={40} />
              <Tooltip content={<CustomTooltip />} />
              <Legend verticalAlign="top" align="right" height={24} iconType="circle" onClick={toggleVisibility} wrapperStyle={{ fontSize: '11px', cursor: 'pointer' }} />
              {excessBaseline && <Area yAxisId="left" hide={hiddenSeries.excess} type="monotone" dataKey="excess" stroke="hsl(var(--primary))" fill="hsl(var(--primary))" fillOpacity={0.08} name={`Excess vs ${excessBaseline}`} />}
              <Area yAxisId="right" hide={hiddenSeries.pos_ratio} type="monotone" dataKey="pos_ratio" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.05} name="Position Ratio" />
              <ReferenceLine yAxisId="left" y={0} stroke="red" strokeDasharray="3 3" strokeOpacity={0.3} />
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}
