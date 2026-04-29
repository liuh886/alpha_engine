import { useMemo, useState } from 'react';
import { Area, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, Line, ComposedChart, ReferenceLine } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { format, parseISO } from 'date-fns';

export function PerformanceCharts({
  report,
}: {
  report: any[];
}) {
  const [hiddenSeries, setHiddenSeries] = useState<Record<string, boolean>>({});

  const toggleVisibility = (entry: any) => {
    const { dataKey } = entry;
    setHiddenSeries(prev => ({
      ...prev,
      [dataKey]: !prev[dataKey]
    }));
  };

  const chartData = useMemo(() => {
    if (!report.length) return [];
    
    let cumulativeQqq = 1.0;
    let cumulativeHs300 = 1.0;
    const initialAccount = report[0].account;
    
    return report.map(d => {
      const qqqRaw = d.bench_qqq ?? 0;
      const hs300Raw = d.bench_hs300 ?? 0;
      const qqqRet = Number.isFinite(Number(qqqRaw)) ? Number(qqqRaw) : 0;
      const hs300Ret = Number.isFinite(Number(hs300Raw)) ? Number(hs300Raw) : 0;
      cumulativeQqq = cumulativeQqq * (1 + qqqRet);
      cumulativeHs300 = cumulativeHs300 * (1 + hs300Ret);
      
      const strategyRet = (d.account / initialAccount) - 1;
      const qqqCum = cumulativeQqq - 1;
      const hs300Cum = cumulativeHs300 - 1;
      
      const accountVal = Number(d.account) || 1;
      const positionsVal = Number(d.value) || 0;
      const posRatio = positionsVal / accountVal;
      
      return {
        date: d.date,
        strategy: strategyRet,
        benchmark_qqq: qqqCum,
        benchmark_hs300: hs300Cum,
        excess: strategyRet - (Number.isFinite(Number(d.bench_qqq)) ? qqqCum : (Number.isFinite(Number(d.bench_hs300)) ? hs300Cum : 0)),
        pos_ratio: posRatio
      };
    });
  }, [report]);

  const hasBenchmarkQqq = useMemo(() => report.some((d) => Number.isFinite(Number(d.bench_qqq))), [report]);
  const hasBenchmarkHs300 = useMemo(() => report.some((d) => Number.isFinite(Number(d.bench_hs300))), [report]);

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-background/95 backdrop-blur-md border shadow-xl rounded-lg p-3 text-[10px] min-w-[140px] border-primary/10 text-left">
          <p className="font-black text-primary mb-2 border-b pb-1 uppercase tracking-tighter">{label}</p>
          <div className="space-y-1.5">
            {payload.map((p: any) => (
              <div key={p.name} className="flex justify-between items-center gap-4">
                <span className="flex items-center gap-1.5 font-bold text-muted-foreground uppercase text-[9px]">
                  <div className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: p.color }} />
                  {p.name}
                </span>
                <span className="font-mono font-black" style={{ color: p.color }}>
                  {p.dataKey === 'pos_ratio' || p.dataKey === 'strategy' || p.dataKey?.includes('benchmark') || p.dataKey === 'excess' 
                    ? `${(p.value * 100).toFixed(2)}%` 
                    : p.value.toFixed(4)}
                </span>
              </div>
            ))}
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="flex flex-col space-y-6">
      {/* 1. Equity Curve */}
      <Card className="border-none shadow-xl bg-card overflow-hidden">
        <CardHeader className="bg-muted/20 border-b pb-4 text-left">
          <div className="space-y-0.5">
            <CardTitle className="text-lg font-black tracking-tight uppercase">Equity Curve</CardTitle>
            <CardDescription className="text-[10px] uppercase font-bold text-muted-foreground">Cumulative performance vs indices. Click legend to toggle.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="h-[450px] p-6 pt-10">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData}>
              <defs>
                <linearGradient id="colorStrategy" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.2}/>
                  <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.1} />
              <XAxis dataKey="date" tickFormatter={(d) => format(parseISO(d), 'MMM yy')} minTickGap={40} tick={{fontSize: 9, fontWeight: 700}} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} tick={{fontSize: 9, fontWeight: 700}} axisLine={false} tickLine={false} width={40} />
              <Tooltip content={<CustomTooltip />} cursor={{ stroke: 'hsl(var(--primary))', strokeWidth: 1, strokeDasharray: '4 4' }} />
              <Legend verticalAlign="top" align="right" height={36} iconType="circle" onClick={toggleVisibility} wrapperStyle={{ fontSize: '10px', fontWeight: 800, textTransform: 'uppercase', cursor: 'pointer' }} />
              <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" strokeOpacity={0.5} />
              
              <Area hide={hiddenSeries['strategy']} type="monotone" dataKey="strategy" stroke="hsl(var(--primary))" strokeWidth={3} fillOpacity={1} fill="url(#colorStrategy)" name="Alpha Engine" animationDuration={1500} />
              {hasBenchmarkQqq && (
                  <Line hide={hiddenSeries['benchmark_qqq']} type="monotone" dataKey="benchmark_qqq" stroke="#f59e0b" dot={false} strokeWidth={2} strokeDasharray="5 5" name="Nasdaq 100" />
              )}
              {hasBenchmarkHs300 && (
                  <Line hide={hiddenSeries['benchmark_hs300']} type="monotone" dataKey="benchmark_hs300" stroke="#0ea5e9" dot={false} strokeWidth={2} name="CSI 300" />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* 2. Excess Alpha & Position Ratio */}
      <Card className="border-none shadow-lg bg-card overflow-hidden text-left">
        <CardHeader className="bg-muted/10 pb-2 border-b">
          <CardTitle className="text-xs font-black uppercase tracking-widest">Excess Alpha & Exposure</CardTitle>
          <CardDescription className="text-[9px] uppercase font-bold text-muted-foreground">Relative return vs benchmark and total exposure</CardDescription>
        </CardHeader>
        <CardContent className="h-[300px] p-4 pt-6">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.1} />
              <XAxis dataKey="date" tickFormatter={(d) => format(parseISO(d), 'MM/yy')} minTickGap={30} tick={{fontSize: 8}} axisLine={false} tickLine={false} />
              <YAxis yAxisId="left" tickFormatter={(v) => `${(v * 100).toFixed(1)}%`} tick={{fontSize: 8}} axisLine={false} tickLine={false} width={30} />
              <YAxis yAxisId="right" orientation="right" tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} tick={{fontSize: 8}} axisLine={false} tickLine={false} width={35} />
              <Tooltip content={<CustomTooltip />} />
              <Legend verticalAlign="top" align="right" height={24} iconType="circle" onClick={toggleVisibility} wrapperStyle={{ fontSize: '9px', fontWeight: 700, cursor: 'pointer' }} />
              
              <Area yAxisId="left" hide={hiddenSeries['excess']} type="monotone" dataKey="excess" stroke="hsl(var(--primary))" fill="hsl(var(--primary))" fillOpacity={0.1} name="Excess Return" />
              <Area yAxisId="right" hide={hiddenSeries['pos_ratio']} type="monotone" dataKey="pos_ratio" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.05} name="Position Ratio" />
              <ReferenceLine yAxisId="left" y={0} stroke="red" strokeDasharray="3 3" strokeOpacity={0.3} />
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}
