import { useEffect, useMemo, useState } from 'react';
import { Area, Bar, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, Line, ComposedChart, ReferenceLine, Brush } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartBenchmarkControl } from '@/components/ChartBenchmarkControl';
import { format, parseISO } from 'date-fns';
import { cn } from '@/lib/utils';
import {
  declaredBenchmarkDescriptor,
  discoverBenchmarkOptions,
  effectivePerformanceDate,
  type BenchmarkKey,
  type NormalizedSeries,
} from '@/lib/performanceBenchmarks';
import {
  alignMarketBarsToPerformanceDates,
  buildPerformanceComparisonOptions,
} from '@/lib/performanceComparisons';
import type { MarketEvidenceMarket } from '@/lib/market-evidence';
import { useMarketComparisons } from '@/hooks/useMarketComparisons';
import type { ReportRow } from '@/lib/types';

type RangeKey = '6m' | '1y' | '3y' | 'all';

const RANGE_OPTIONS: Array<{ key: RangeKey; label: string; months: number | null }> = [
  { key: '6m', label: '6M', months: 6 },
  { key: '1y', label: '1Y', months: 12 },
  { key: '3y', label: '3Y', months: 36 },
  { key: 'all', label: 'All', months: null },
];

const COMPARISON_STROKES = ['hsl(var(--chart-2))', 'hsl(var(--chart-4))', 'hsl(var(--chart-3))', 'hsl(var(--chart-5))', 'hsl(var(--chart-1))'];

function periodReturn(startValue: unknown, endValue: unknown) {
  const start = Number(startValue);
  const end = Number(endValue);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start <= -1) return null;
  return ((1 + end) / (1 + start)) - 1;
}

export function PerformanceCharts({
  report,
  benchmarkId,
  market,
}: {
  report: ReportRow[];
  benchmarkId?: string;
  market?: MarketEvidenceMarket;
}) {
  const [hiddenSeries, setHiddenSeries] = useState<Record<string, boolean>>({});
  const [selectedBenchmarkKey, setSelectedBenchmarkKey] = useState<BenchmarkKey | null>(null);
  const [selectedComparisonKeys, setSelectedComparisonKeys] = useState<string[] | null>(null);
  const [rangeKey, setRangeKey] = useState<RangeKey>('all');
  const {
    catalogs: marketCatalogs,
    marketBars,
    loadingKeys: loadingComparisonKeys,
    failedKeys: failedComparisonKeys,
    catalogsLoading,
    ensureCatalogs,
    requestComparison,
  } = useMarketComparisons(market);

  useEffect(() => {
    setSelectedComparisonKeys(null);
  }, [market]);

  const toggleVisibility = (entry: { dataKey?: unknown }) => {
    const rawKey = entry?.dataKey;
    const key = typeof rawKey === 'string' || typeof rawKey === 'number' ? String(rawKey) : '';
    if (key) {
      setHiddenSeries(prev => ({ ...prev, [key]: !prev[key] }));
    }
  };

  const declaredBenchmarkId = benchmarkId ?? String(report[0]?.benchmark_id ?? '');
  const declaredBenchmark = useMemo(
    () => declaredBenchmarkDescriptor(report, declaredBenchmarkId),
    [declaredBenchmarkId, report],
  );
  const benchmarkOptions = useMemo(
    () => discoverBenchmarkOptions(report, declaredBenchmarkId),
    [declaredBenchmarkId, report],
  );
  const comparisonOptions = useMemo(
    () => buildPerformanceComparisonOptions(benchmarkOptions, marketCatalogs),
    [benchmarkOptions, marketCatalogs],
  );

  const defaultBenchmarkKey = useMemo((): BenchmarkKey | null => {
    if (declaredBenchmark) {
      return benchmarkOptions.some(option => option.key === declaredBenchmark.key)
        ? declaredBenchmark.key
        : null;
    }
    return benchmarkOptions[0]?.key ?? null;
  }, [benchmarkOptions, declaredBenchmark]);

  const activeBenchmarkKey = selectedBenchmarkKey && comparisonOptions.some(option => option.key === selectedBenchmarkKey)
    ? selectedBenchmarkKey
    : defaultBenchmarkKey;
  const activeBenchmark = comparisonOptions.find(option => option.key === activeBenchmarkKey) ?? null;
  const activeComparisonKeys = selectedComparisonKeys ?? (activeBenchmarkKey ? [activeBenchmarkKey] : []);
  const performanceDates = useMemo(() => report.map(effectivePerformanceDate), [report]);
  const marketSeries = useMemo(() => Object.fromEntries(
    Object.entries(marketBars).flatMap(([key, bars]) => {
      const series = alignMarketBarsToPerformanceDates(bars, performanceDates);
      return series ? [[key, series]] : [];
    }),
  ) as Record<string, NormalizedSeries>, [marketBars, performanceDates]);
  const seriesByKey = useMemo(() => ({
    ...Object.fromEntries(benchmarkOptions.map(option => [option.key, option.series])),
    ...marketSeries,
  }) as Record<string, NormalizedSeries>, [benchmarkOptions, marketSeries]);
  const excessBaseline = activeBenchmark?.label ?? null;

  const requestMarketComparison = (key: string) => {
    const option = comparisonOptions.find(candidate => candidate.key === key);
    void requestComparison({
      key,
      market: option?.market,
      symbol: option?.marketSymbol?.symbol,
    });
  };

  const handlePrimaryBenchmarkChange = (key: string) => {
    setSelectedBenchmarkKey(key);
    setSelectedComparisonKeys(current => {
      const selected = current ?? (activeBenchmarkKey ? [activeBenchmarkKey] : []);
      return selected.includes(key) ? selected : [...selected, key];
    });
    requestMarketComparison(key);
  };

  const handleComparisonToggle = (key: string) => {
    setSelectedComparisonKeys(current => {
      const selected = current ?? (activeBenchmarkKey ? [activeBenchmarkKey] : []);
      return selected.includes(key)
        ? selected.filter(candidate => candidate !== key)
        : [...selected, key];
    });
    requestMarketComparison(key);
  };

  const chartData = useMemo(() => {
    if (!report.length) return [];
    const initialAccount = Number(report[0].account);
    if (!Number.isFinite(initialAccount) || initialAccount <= 0) return [];

    return report.map((row, index) => {
      const account = Number(row.account);
      const strategy = Number.isFinite(account)
        ? (account / initialAccount) - 1
        : null as unknown as number;
      const activeValue = activeBenchmarkKey ? seriesByKey[activeBenchmarkKey]?.[index] ?? null : null;
      const value = Number(row.value);
      const posRatio = Number.isFinite(account) && account > 0 && Number.isFinite(value)
        ? value / account
        : null as unknown as number;
      const turnover = Number(row.turnover);
      const benchmarkValues: Record<string, number | null> = Object.fromEntries(
        Object.entries(seriesByKey).map(([key, series]) => [key, series[index] ?? null]),
      );
      if (declaredBenchmark && !(declaredBenchmark.key in benchmarkValues)) {
        benchmarkValues[declaredBenchmark.key] = null;
      }

      return {
        date: effectivePerformanceDate(row),
        strategy,
        ...benchmarkValues,
        primary_benchmark_key: activeBenchmarkKey,
        excess: Number.isFinite(strategy) && Number.isFinite(activeValue)
          ? strategy - Number(activeValue)
          : null as unknown as number,
        pos_ratio: posRatio,
        turnover: Number.isFinite(turnover) ? turnover : null as unknown as number,
        provisional_mtm: row.provisional_mtm === true || row.settlement_status === 'provisional_mtm',
      };
    });
  }, [activeBenchmarkKey, declaredBenchmark, report, seriesByKey]);

  const visibleChartData = useMemo(() => {
    const selectedRange = RANGE_OPTIONS.find(option => option.key === rangeKey);
    if (!selectedRange?.months || chartData.length < 2) return chartData;

    const endTimestamp = Date.parse(`${chartData[chartData.length - 1].date}T00:00:00Z`);
    if (!Number.isFinite(endTimestamp)) return chartData;

    const threshold = new Date(endTimestamp);
    threshold.setUTCMonth(threshold.getUTCMonth() - selectedRange.months);
    const thresholdTimestamp = threshold.getTime();
    const filtered = chartData.filter(row => {
      const rowTimestamp = Date.parse(`${row.date}T00:00:00Z`);
      return Number.isFinite(rowTimestamp) && rowTimestamp >= thresholdTimestamp;
    });

    return filtered.length ? filtered : chartData;
  }, [chartData, rangeKey]);

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

  const visibleDrawdownData = useMemo(() => {
    if (visibleChartData.length === chartData.length) return drawdownData;
    const visibleDates = new Set(visibleChartData.map(row => row.date));
    return drawdownData.filter(row => visibleDates.has(row.date));
  }, [chartData.length, drawdownData, visibleChartData]);

  const visibleMaxDrawdown = useMemo(() => {
    if (!visibleDrawdownData.length) return null;
    let worst = 0;
    let worstIdx = 0;
    visibleDrawdownData.forEach((row, index) => {
      if (Number.isFinite(row.drawdown) && (row.drawdown as number) < worst) {
        worst = row.drawdown as number;
        worstIdx = index;
      }
    });
    return worst < 0 ? { value: worst, date: visibleDrawdownData[worstIdx].date } : null;
  }, [visibleDrawdownData]);

  const currentDrawdown = useMemo(() => {
    for (let index = visibleDrawdownData.length - 1; index >= 0; index -= 1) {
      const value = visibleDrawdownData[index].drawdown;
      if (Number.isFinite(value)) return value as number;
    }
    return null;
  }, [visibleDrawdownData]);

  const visibleSummary = useMemo(() => {
    if (!visibleChartData.length) {
      return { strategy: null, benchmark: null, excess: null };
    }
    const first = visibleChartData[0];
    const last = visibleChartData[visibleChartData.length - 1];
    const strategy = periodReturn(first.strategy, last.strategy);
    const firstRecord = first as unknown as Record<string, unknown>;
    const lastRecord = last as unknown as Record<string, unknown>;
    const benchmark = activeBenchmarkKey
      ? periodReturn(firstRecord[activeBenchmarkKey], lastRecord[activeBenchmarkKey])
      : null;
    return {
      strategy,
      benchmark,
      excess: strategy !== null && benchmark !== null ? strategy - benchmark : null,
    };
  }, [activeBenchmarkKey, visibleChartData]);

  const monthlyReturns = useMemo(() => {
    if (!report.length) return [];
    const firstAccount = Number(report[0].account);
    if (!Number.isFinite(firstAccount) || firstAccount <= 0) return [];
    const byMonth: Record<string, number[]> = {};
    let prevAccount = firstAccount;
    for (let index = 1; index < report.length; index += 1) {
      const row = report[index];
      const account = Number(row.account);
      const date = effectivePerformanceDate(row);
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
      <div className="min-w-[140px] rounded border bg-background/95 p-2.5 text-[10px] shadow-lg">
        <p className="mb-1.5 border-b pb-1 font-semibold">{label}</p>
        {payload.map((item) => (
          <div key={item.name} className="flex justify-between gap-4 py-0.5">
            <span className="flex items-center gap-1 text-muted-foreground">
              <div className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: item.color }} />
              {item.name}
            </span>
            <span className="font-mono tabular-nums" style={{ color: item.color }}>
              {typeof item.value === 'number' ? `${(item.value * 100).toFixed(2)}%` : item.value}
            </span>
          </div>
        ))}
      </div>
    );
  };

  const colorReturn = (value: number | null) => {
    if (value === null) return "text-muted-foreground/40";
    return value >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
  };

  const bgReturn = (value: number | null) => {
    if (value === null) return "";
    const intensity = Math.min(Math.abs(value) * 5, 0.28);
    return value >= 0 ? `rgba(34,197,94,${intensity})` : `rgba(239,68,68,${intensity})`;
  };

  const formatPercent = (value: number | null, digits = 2) => value === null ? '—' : `${(value * 100).toFixed(digits)}%`;
  const strategyPointCount = chartData.filter(row => Number.isFinite(row.strategy)).length;
  const performanceThrough = chartData.length ? chartData[chartData.length - 1].date : null;
  const latestRow = report[report.length - 1];
  const isProvisionalMtm = latestRow?.provisional_mtm === true || latestRow?.settlement_status === 'provisional_mtm';
  const hasExposure = chartData.some(row => Number.isFinite(row.pos_ratio));
  const hasTurnover = chartData.some(row => Number.isFinite(row.turnover));
  const hasCapitalUseChart = Boolean(excessBaseline || hasExposure || hasTurnover);
  const activeComparisonOptions = activeComparisonKeys
    .map(key => comparisonOptions.find(option => option.key === key) ?? null)
    .filter((option): option is NonNullable<typeof option> => Boolean(option && seriesByKey[option.key]));

  return (
    <div className="space-y-5">
      <Card
        data-testid="equity-curve-container"
        data-strategy-point-count={String(strategyPointCount)}
        data-default-benchmark={excessBaseline ?? 'unavailable'}
        data-comparison-count={String(activeComparisonOptions.length)}
        data-realized-through={performanceThrough ?? 'unavailable'}
        data-equity-status={isProvisionalMtm ? 'provisional_mtm' : 'settled'}
        data-range={rangeKey}
      >
        <CardHeader className="border-b pb-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-sm font-semibold">Equity Curve</CardTitle>
              {performanceThrough && (
                <p className="mt-1 text-[10px] text-muted-foreground">
                  {isProvisionalMtm ? `Provisional MTM through ${performanceThrough}` : `Settled returns through ${performanceThrough}`}
                </p>
              )}
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <ChartBenchmarkControl
                options={comparisonOptions}
                primaryKey={activeBenchmarkKey}
                selectedKeys={activeComparisonKeys}
                loadingKeys={loadingComparisonKeys}
                failedKeys={failedComparisonKeys}
                catalogsLoading={catalogsLoading}
                unavailableLabel={declaredBenchmark ? `${declaredBenchmark.label} unavailable` : undefined}
                onOpenChange={(open) => { if (open) void ensureCatalogs(); }}
                onPrimaryChange={handlePrimaryBenchmarkChange}
                onToggle={handleComparisonToggle}
                onRetry={requestMarketComparison}
              />
              <div aria-label="Performance range" className="inline-flex rounded-md border bg-muted/20 p-0.5">
                {RANGE_OPTIONS.map(option => (
                  <button
                    key={option.key}
                    type="button"
                    aria-pressed={rangeKey === option.key}
                    onClick={() => setRangeKey(option.key)}
                    className={cn(
                      "rounded px-2 py-1 text-[10px] font-medium transition-colors",
                      rangeKey === option.key
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 border-t pt-3 sm:grid-cols-4">
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Strategy</p>
              <p data-testid="visible-strategy-return" className={cn("mt-1 font-mono text-sm font-semibold tabular-nums", colorReturn(visibleSummary.strategy))}>{formatPercent(visibleSummary.strategy)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{excessBaseline ?? 'Benchmark'}</p>
              <p data-testid="visible-benchmark-return" className={cn("mt-1 font-mono text-sm font-semibold tabular-nums", colorReturn(visibleSummary.benchmark))}>{formatPercent(visibleSummary.benchmark)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Excess</p>
              <p data-testid="visible-excess-return" className={cn("mt-1 font-mono text-sm font-semibold tabular-nums", colorReturn(visibleSummary.excess))}>{formatPercent(visibleSummary.excess)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Max drawdown</p>
              <p className="mt-1 font-mono text-sm font-semibold tabular-nums text-rose-600 dark:text-rose-400">{visibleMaxDrawdown ? formatPercent(visibleMaxDrawdown.value) : '—'}</p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="h-[330px] pt-4 sm:h-[400px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={visibleChartData} syncId="performance-analysis">
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
              {activeComparisonOptions.map((option, index) => {
                const isPrimary = option.key === activeBenchmarkKey;
                return (
                  <Line
                    key={option.key}
                    hide={hiddenSeries[option.key]}
                    type="monotone"
                    dataKey={option.key}
                    stroke={isPrimary ? 'hsl(var(--chart-3))' : COMPARISON_STROKES[index % COMPARISON_STROKES.length]}
                    dot={false}
                    strokeWidth={isPrimary ? 1.7 : 1.25}
                    strokeDasharray={isPrimary ? '5 5' : undefined}
                    name={option.label}
                  />
                );
              })}
              <Brush dataKey="date" height={26} stroke="hsl(var(--primary))" fill="hsl(var(--background))" tickFormatter={date => format(parseISO(date), 'MMM yy')} />
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {visibleDrawdownData.length > 0 && (
        <Card data-testid="drawdown-container">
          <CardHeader className="border-b pb-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle className="text-sm font-semibold">Drawdown</CardTitle>
              <div className="flex items-center gap-3 font-mono text-[11px] tabular-nums">
                {currentDrawdown !== null && <span className="text-muted-foreground">Current {formatPercent(currentDrawdown)}</span>}
                {visibleMaxDrawdown && <span className="text-rose-600 dark:text-rose-400">Max {formatPercent(visibleMaxDrawdown.value)} · {visibleMaxDrawdown.date}</span>}
              </div>
            </div>
          </CardHeader>
          <CardContent className="h-[180px] pt-4 sm:h-[210px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={visibleDrawdownData} syncId="performance-analysis">
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
          <CardHeader className="border-b pb-3">
            <CardTitle className="text-sm font-semibold">Monthly Returns</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto pt-4">
            <table className="w-full min-w-[760px] text-xs">
              <thead>
                <tr>
                  <th className="py-1 pr-3 text-left font-medium text-muted-foreground">Year</th>
                  {["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"].map(month => (
                    <th key={month} className="px-1 py-1 text-center font-medium text-muted-foreground">{month}</th>
                  ))}
                  <th className="py-1 pl-3 text-center font-medium text-muted-foreground">Total</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(monthlyByYear).sort(([left], [right]) => left.localeCompare(right)).map(([year, months]) => {
                  const yearTotal = months.reduce((accumulator, value) => accumulator !== null && value !== null ? accumulator * (1 + value) : accumulator, 1 as number | null);
                  const yearReturn = yearTotal !== null ? yearTotal - 1 : null;
                  return (
                    <tr key={year}>
                      <td className="py-1 pr-3 font-mono font-medium tabular-nums">{year}</td>
                      {months.map((value, index) => (
                        <td key={index} className="px-1 py-1 text-center">
                          <span className={cn("block rounded px-1.5 py-1 font-mono tabular-nums", colorReturn(value))} style={{ backgroundColor: bgReturn(value) }}>
                            {value !== null ? `${(value * 100).toFixed(1)}%` : "—"}
                          </span>
                        </td>
                      ))}
                      <td className="py-1 pl-3 text-center">
                        <span className={cn("block rounded px-1.5 py-1 font-mono font-medium tabular-nums", colorReturn(yearReturn))} style={{ backgroundColor: bgReturn(yearReturn) }}>
                          {yearReturn !== null ? `${(yearReturn * 100).toFixed(1)}%` : "—"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {hasCapitalUseChart && (
        <Card>
          <CardHeader className="border-b pb-3">
            <CardTitle className="text-sm font-semibold">{excessBaseline ? 'Relative Performance & Capital Use' : 'Capital Use'}</CardTitle>
            <p className="mt-1 text-[10px] text-muted-foreground">
              {excessBaseline ? `Excess vs ${excessBaseline}` : 'Portfolio usage'}{hasExposure ? ' · invested ratio' : ''}{hasTurnover ? ' · turnover' : ''}
            </p>
          </CardHeader>
          <CardContent className="h-[220px] pt-4 sm:h-[250px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={visibleChartData} syncId="performance-analysis">
                <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.1} />
                <XAxis dataKey="date" tickFormatter={date => format(parseISO(date), 'MM/yy')} minTickGap={30} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                {excessBaseline && <YAxis yAxisId="left" tickFormatter={value => `${(value * 100).toFixed(1)}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={45} />}
                {(hasExposure || hasTurnover) && <YAxis yAxisId="right" orientation="right" tickFormatter={value => `${(value * 100).toFixed(0)}%`} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} width={40} />}
                <Tooltip content={<CustomTooltip />} />
                <Legend verticalAlign="top" align="right" height={24} iconType="circle" onClick={toggleVisibility} wrapperStyle={{ fontSize: '11px', cursor: 'pointer' }} />
                {excessBaseline && <Area yAxisId="left" hide={hiddenSeries.excess} type="monotone" dataKey="excess" stroke="hsl(var(--primary))" fill="hsl(var(--primary))" fillOpacity={0.08} name={`Excess vs ${excessBaseline}`} />}
                {hasExposure && <Area yAxisId="right" hide={hiddenSeries.pos_ratio} type="monotone" dataKey="pos_ratio" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.05} name="Invested Ratio" />}
                {hasTurnover && <Bar yAxisId="right" hide={hiddenSeries.turnover} dataKey="turnover" fill="hsl(var(--muted-foreground))" fillOpacity={0.2} maxBarSize={8} name="Turnover" />}
                {excessBaseline && <ReferenceLine yAxisId="left" y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" strokeOpacity={0.3} />}
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
    </div>
  );
}