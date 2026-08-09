import { useMemo, useState } from 'react';
import { Area, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, Line, ComposedChart, ReferenceLine, Brush } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { format, parseISO } from 'date-fns';
import { cn } from '@/lib/utils';
import type { ReportRow } from '@/lib/types';

type BenchmarkKey = 'benchmark_byd' | 'benchmark_byd_v1_1' | 'benchmark_qqq' | 'benchmark_csi300' | 'benchmark';
type NormalizedSeries = Array<number | null>;

interface BenchmarkContract {
  key: BenchmarkKey;
  label: string;
}

interface BenchmarkOption extends BenchmarkContract {
  series: NormalizedSeries;
}

function declaredBenchmarkContract(benchmarkId?: string): BenchmarkContract | null {
  const value = String(benchmarkId ?? '').trim();
  if (!value) return null;
  const normalized = value.toUpperCase();
  if (normalized === 'BYD') return { key: 'benchmark_byd', label: 'BYD' };
  if (['BYD V1.1', 'BYD V1_1', 'BYD V1.1 BASELINE'].includes(normalized)) {
    return { key: 'benchmark_byd_v1_1', label: 'BYD v1.1' };
  }
  if (normalized === 'QQQ') return { key: 'benchmark_qqq', label: 'QQQ' };
  if (['CSI300', 'CSI 300', '000300', '000300.SH'].includes(normalized)) {
    return { key: 'benchmark_csi300', label: 'CSI 300' };
  }
  return { key: 'benchmark', label: value };
}

function effectiveDate(row: ReportRow): string {
  const holdingEnd = typeof row.holding_end_date === 'string' ? row.holding_end_date : '';
  return /^\d{4}-\d{2}-\d{2}$/.test(holdingEnd) ? holdingEnd : row.date;
}

function normalizeBenchmarkSeries(values: Array<number | undefined>): NormalizedSeries | null {
  const numeric = values.map(value => Number.isFinite(Number(value)) ? Number(value) : null);
  const firstIndex = numeric.findIndex((value) => value !== null);
  if (firstIndex < 0) return null;
  const first = numeric[firstIndex] as number;

  if (Math.abs(first) > 0.5) {
    let previous = first;
    return numeric.map((value, index) => {
      if (index < firstIndex) return null;
      if (value !== null) previous = value;
      return previous / first - 1;
    });
  }

  let cumulative = 1;
  return numeric.map((value, index) => {
    if (index < firstIndex) return null;
    cumulative *= 1 + (value ?? 0);
    return cumulative - 1;
  });
}

function benchmarkLooksCorrupt(report: ReportRow[], values: Array<number | undefined>): boolean {
  const normalized = values.map(value => Number.isFinite(Number(value)) ? Number(value) : null);
  const first = normalized.find((value): value is number => value !== null);
  if (first === undefined || Math.abs(first) <= 0.5) return false;

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

function benchmarkStroke(key: BenchmarkKey): string {
  if (key === 'benchmark_byd') return '#ef4444';
  if (key === 'benchmark_csi300') return '#0ea5e9';
  if (key === 'benchmark_byd_v1_1') return '#8b5cf6';
  return '#f59e0b';
}

export function PerformanceCharts({ report, benchmarkId }: { report: ReportRow[]; benchmarkId?: string }) {
  const [hiddenSeries, setHiddenSeries] = useState<Record<string, boolean>>({});
  const [selectedBenchmarkKey, setSelectedBenchmarkKey] = useState<BenchmarkKey | null>(null);

  const toggleVisibility = (entry: any) => {
    const key = String(entry?.dataKey ?? '');
    if (key) {
      setHiddenSeries(prev => ({ ...prev, [key]: !prev[key] }));
    }
  };

  const declaredBenchmark = useMemo(
    () => declaredBenchmarkContract(benchmarkId ?? String(report[0]?.benchmark_id ?? '')),
    [benchmarkId, report],
  );

  const benchmarkOptions = useMemo((): BenchmarkOption[] => {
    if (!report.length) return [];
    const candidates: Array<{ key: BenchmarkKey; label: string; values: Array<number | undefined> }> = [
      { key: 'benchmark_byd', label: 'BYD', values: report.map(row => row.bench_byd as number | undefined) },
      { key: 'benchmark_byd_v1_1', label: 'BYD v1.1', values: report.map(row => row.bench_byd_v1_1 as number | undefined) },
      { key: 'benchmark_qqq', label: 'QQQ', values: report.map(row => row.bench_qqq) },
      { key: 'benchmark_csi300', label: 'CSI 300', values: report.map(row => row.bench_hs300) },
      {
        key: 'benchmark',
        label: declaredBenchmark?.key === 'benchmark' ? declaredBenchmark.label : 'Benchmark',
        values: report.map(row => row.bench),
      },
    ];

    return candidates.flatMap(({ key, label, values }) => {
      if (benchmarkLooksCorrupt(report, values)) return [];
      const series = normalizeBenchmarkSeries(values);
      if (!series || !series.some(value => Number.isFinite(value))) return [];
      return [{ key, label, series }];
    });
  }, [declaredBenchmark, report]);

  const defaultBenchmarkKey = useMemo((): BenchmarkKey | null => {
    if (declaredBenchmark) {
      return benchmarkOptions.some(option => option.key === declaredBenchmark.key)
        ? declaredBenchmark.key
        : null;
    }
    return benchmarkOptions[0]?.key ?? null;
  }, [benchmarkOptions, declaredBenchmark]);

  const activeBenchmarkKey = selectedBenchmarkKey && benchmarkOptions.some(option => option.key === selectedBenchmarkKey)
    ? selectedBenchmarkKey
    : defaultBenchmarkKey;
  const activeBenchmark = benchmarkOptions.find(option => option.key === activeBenchmarkKey) ?? null;
  const excessBaseline = activeBenchmark?.label ?? null;

  const chartData = useMemo(() => {
    if (!report.length) return [];
    const initialAccount = Number(report[0].account);
    if (!Number.isFinite(initialAccount) || initialAccount <= 0) return [];

    const byKey = Object.fromEntries(benchmarkOptions.map(option => [option.key, option.series])) as Partial<Record<BenchmarkKey, NormalizedSeries>>;
    return report.map((row, index) => {
      const account = Number(row.account);
      const strategy = Number.isFinite(account)
        ? (account / initialAccount) - 1
        : null as unknown as number;
      const benchmarkByd = byKey.benchmark_byd?.[index] ?? null;
      const benchmarkBydV11 = byKey.benchmark_byd_v1_1?.[index] ?? null;
      const benchmarkQqq = byKey.benchmark_qqq?.[index] ?? null;
      const benchmarkCsi300 = byKey.benchmark_csi300?.[index] ?? null;
      const benchmark = byKey.benchmark?.[index] ?? null;
      const activeValue = activeBenchmarkKey ? byKey[activeBenchmarkKey]?.[index] ?? null : null;
      const value = Number(row.value);
      const posRatio = Number.isFinite(account) && account > 0 && Number.isFinite(value)
        ? value / account
        : null as unknown as number;

      return {
        date: effectiveDate(row),
        strategy,
        benchmark_byd: benchmarkByd,
        benchmark_byd_v1_1: benchmarkBydV11,
        benchmark_qqq: benchmarkQqq,
        benchmark_csi300: benchmarkCsi300,
        benchmark,
        primary_benchmark_key: activeBenchmarkKey,
        excess: Number.isFinite(strategy) && Number.isFinite(activeValue)
          ? strategy - Number(activeValue)
          : null as unknown as number,
        pos_ratio: posRatio,
      };
    });
  }, [activeBenchmarkKey, benchmarkOptions, report]);

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
      const date = effectiveDate(row);
      if (!date || !Number.isFinite(account)) continue;
      const yearMonth = date.slice(0, 7);
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
  const realizedThrough = chartData.length ? chartData[chartData.length - 1].date : null;

  return (
    <div className="space-y-5">
      <Card
        data-testid="equity-curve-container"
        data-strategy-point-count={String(strategyPointCount)}
        data-default-benchmark={excessBaseline ?? 'unavailable'}
        data-realized-through={realizedThrough ?? 'unavailable'}
      >
        <CardHeader className="pb-3 border-b">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-sm font-semibold">Equity Curve</CardTitle>
              {realizedThrough && <p className="mt-1 text-[10px] text-muted-foreground">Settled returns through {realizedThrough}</p>}
            </div>
            <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
              <span>Chart baseline</span>
              {benchmarkOptions.length > 1 ? (
                <select
                  aria-label="Chart baseline"
                  className="h-7 rounded-md border bg-background px-2 text-xs text-foreground"
                  value={activeBenchmarkKey ?? ''}
                  onChange={(event) => setSelectedBenchmarkKey(event.target.value ? event.target.value as BenchmarkKey : null)}
                >
                  {!activeBenchmarkKey && <option value="">Unavailable</option>}
                  {benchmarkOptions.map(option => <option key={option.key} value={option.key}>{option.label}</option>)}
                </select>
              ) : (
                <span className="font-medium text-foreground">
                  {excessBaseline ?? (declaredBenchmark ? `${declaredBenchmark.label} unavailable` : 'Unavailable')}
                </span>
              )}
            </div>
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
              {activeBenchmarkKey && activeBenchmark && (
                <Line
                  hide={hiddenSeries[activeBenchmarkKey]}
                  type="monotone"
                  dataKey={activeBenchmarkKey}
                  stroke={benchmarkStroke(activeBenchmarkKey)}
                  dot={false}
                  strokeWidth={1.5}
                  strokeDasharray="5 5"
                  name={activeBenchmark.label}
                />
              )}
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
