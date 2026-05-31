import { useMemo, useState } from 'react';
import { Area, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, Line, ComposedChart, ReferenceLine } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { format, parseISO } from 'date-fns';
import { cn } from '@/lib/utils';

export function PerformanceCharts({ report }: { report: any[] }) {
  const [hiddenSeries, setHiddenSeries] = useState<Record<string, boolean>>({});

  const toggleVisibility = (entry: any) => {
    setHiddenSeries(prev => ({ ...prev, [entry.dataKey]: !prev[entry.dataKey] }));
  };

  const chartData = useMemo(() => {
    if (!report.length) return [];
    let cumulativeQqq = 1.0;
    let cumulativeHs300 = 1.0;
    const initialAccount = report[0].account;

    return report.map(d => {
      const qqqRet = Number.isFinite(Number(d.bench_qqq)) ? Number(d.bench_qqq) : 0;
      const hs300Ret = Number.isFinite(Number(d.bench_hs300)) ? Number(d.bench_hs300) : 0;
      cumulativeQqq *= (1 + qqqRet);
      cumulativeHs300 *= (1 + hs300Ret);
      const strategyRet = (d.account / initialAccount) - 1;
      return {
        date: d.date,
        strategy: strategyRet,
        benchmark_qqq: cumulativeQqq - 1,
        benchmark_hs300: cumulativeHs300 - 1,
        excess: strategyRet - (Number.isFinite(Number(d.bench_qqq)) ? cumulativeQqq - 1 : cumulativeHs300 - 1),
        pos_ratio: (Number(d.value) || 0) / (Number(d.account) || 1),
      };
    });
  }, [report]);

  // T5: Drawdown data
  const drawdownData = useMemo(() => {
    if (!chartData.length) return [];
    let peak = chartData[0].strategy;
    return chartData.map(d => {
      if (d.strategy > peak) peak = d.strategy;
      const dd = peak > 0 ? (d.strategy - peak) / (1 + peak) : 0;
      return { date: d.date, drawdown: dd };
    });
  }, [chartData]);

  const maxDrawdown = useMemo(() => {
    if (!drawdownData.length) return null;
    let worst = 0;
    let worstIdx = 0;
    drawdownData.forEach((d, i) => {
      if (d.drawdown < worst) { worst = d.drawdown; worstIdx = i; }
    });
    return worst < 0 ? { value: worst, date: drawdownData[worstIdx].date, index: worstIdx } : null;
  }, [drawdownData]);

  // T6: Monthly returns
  const monthlyReturns = useMemo(() => {
    if (!report.length) return [];
    const byMonth: Record<string, number[]> = {};
    let prevAccount = report[0].account;
    for (let i = 1; i < report.length; i++) {
      const d = report[i];
      const ym = d.date.slice(0, 7); // "YYYY-MM"
      if (!byMonth[ym]) byMonth[ym] = [];
      const dayRet = (d.account - prevAccount) / prevAccount;
      byMonth[ym].push(dayRet);
      prevAccount = d.account;
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

  const hasQqq = useMemo(() => report.some(d => Number.isFinite(Number(d.bench_qqq))), [report]);
  const hasHs300 = useMemo(() => report.some(d => Number.isFinite(Number(d.bench_hs300))), [report]);

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    return (
      <div className="bg-background/95 border shadow-lg rounded p-2.5 text-[10px] min-w-[140px]">
        <p className="font-semibold mb-1.5 pb-1 border-b">{label}</p>
        {payload.map((p: any) => (
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

  return (
    <div className="space-y-5">
      {/* 1. Equity Curve */}
      <Card>
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
              {hasQqq && <Line hide={hiddenSeries['benchmark_qqq']} type="monotone" dataKey="benchmark_qqq" stroke="#f59e0b" dot={false} strokeWidth={1.5} strokeDasharray="5 5" name="Nasdaq 100" />}
              {hasHs300 && <Line hide={hiddenSeries['benchmark_hs300']} type="monotone" dataKey="benchmark_hs300" stroke="#0ea5e9" dot={false} strokeWidth={1.5} name="CSI 300" />}
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* 2. T5: Drawdown Chart */}
      {drawdownData.length > 0 && (
        <Card>
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
