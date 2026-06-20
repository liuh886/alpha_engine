import { useEffect, useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid, Line, ComposedChart, ReferenceDot, Area, Legend } from 'recharts';
import { format, parseISO } from 'date-fns';
import { Loader2, TrendingUp, TrendingDown } from 'lucide-react';
import { useNameMap } from '@/lib/useNameMap';
import { apiFetch } from '@/lib/api';
import type { Position, ReportRow } from '@/lib/types';

export function Attribution({ positions, report }: { positions: Position[]; report?: ReportRow[] }) {
  const [selectedInstrument, setSelectedInstrument] = useState<string | null>(null);
  const [fullPriceHistory, setFullPriceHistory] = useState<Record<string, number>>({});
  const [loadingPrice, setLoadingPrice] = useState(false);
  const { getName } = useNameMap();

  const labelByInstrument = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of positions) {
      if (!row?.instrument) continue;
      const code = String(row.instrument);
      const label = row.instrument_label ? String(row.instrument_label) : getName(code);
      if (!map.has(code)) map.set(code, label);
    }
    return map;
  }, [positions, getName]);

  const accountByDate = useMemo(() => {
    const map = new Map<string, number>();
    if (!report) return map;
    for (const row of report) {
      if (row?.date && typeof row.account === "number") {
        map.set(row.date, row.account);
      }
    }
    return map;
  }, [report]);

  // Fetch full price action when instrument changes
  useEffect(() => {
    if (!selectedInstrument) return;
    
    const fetchHistory = async () => {
      setLoadingPrice(true);
      try {
        const resp = await apiFetch(`/api/data/stock/${selectedInstrument}`);
        const json = await resp.json();
        if (json.ok && json.ohlcv) {
          const history: Record<string, number> = {};
          json.ohlcv.forEach((d: { time: string; close: number | null }) => {
            // Robust normalization
            const dStr = String(d.time).split('T')[0].split(' ')[0].trim();
            if (d.close !== null && d.close !== undefined) {
                history[dStr] = Number(d.close);
            }
          });
          setFullPriceHistory(history);
        }
      } catch (e) {
        console.error("Failed to fetch history", e);
      } finally {
        setLoadingPrice(false);
      }
    };
    fetchHistory();
  }, [selectedInstrument]);

  // Shared calculation logic for consistency
  const calculateInstrumentPnL = (instrument: string) => {
    if (!report || report.length === 0) return 0;
    
    const instrumentPositions = positions.filter(p => p.instrument === instrument);
    const posMap = new Map();
    instrumentPositions.forEach(p => posMap.set(p.date, p));

    let totalPnL = 0;
    let lastPrice = 0;
    let prevWeight = 0;

    const sortedPos = [...instrumentPositions].sort((a, b) => a.date.localeCompare(b.date));
    if (sortedPos.length > 0) {
        lastPrice = Number(sortedPos[0].price);
    }

    for (const day of report) {
        const date = day.date;
        const p = posMap.get(date);
        const weight = p ? (typeof p.weight === "number" ? p.weight : Number(p.weight)) : 0;
        
        // Attempt to find price from multiple sources
        let price = fullPriceHistory[date] || (p ? (typeof p.price === "number" ? p.price : Number(p.price)) : 0);
        if (price === 0) price = lastPrice;

        if (prevWeight > 0 && lastPrice > 0 && price > 0) {
            const ret = (price / lastPrice) - 1;
            totalPnL += ret * prevWeight * (accountByDate.get(date) || 0);
        }

        if (price > 0) lastPrice = price;
        prevWeight = weight;
    }
    return totalPnL;
  };

  const contributionRows = useMemo(() => {
    if (!positions.length) return [];
    const instruments = Array.from(new Set(positions.map(p => p.instrument)));
    return instruments.map(inst => {
        const val = calculateInstrumentPnL(inst);
        return {
            instrument: inst,
            name: labelByInstrument.get(inst) || inst,
            value: val
        };
    });
  }, [positions, accountByDate, labelByInstrument, report, fullPriceHistory]);

  const topContributors = useMemo(() => contributionRows.filter(d => d.value > 0).sort((a, b) => b.value - a.value).slice(0, 10), [contributionRows]);
  const topLosers = useMemo(() => contributionRows.filter(d => d.value < 0).sort((a, b) => a.value - b.value).slice(0, 10), [contributionRows]);

  const selectionOptions = useMemo(() => {
    return [...topContributors, ...topLosers].map(d => ({ instrument: d.instrument, name: d.name }));
  }, [topContributors, topLosers]);

  const tradeData = useMemo(() => {
      if (!selectedInstrument || !report || report.length === 0) return [];
      
      const instrumentPositions = positions.filter(p => p.instrument === selectedInstrument);
      const posMap = new Map();
      instrumentPositions.forEach(p => posMap.set(p.date, p));

      let runningPnL = 0;
      let lastKnownPrice = 0;
      let prevWeight = 0;

      // Robust price initialization for the chart: Scan all report dates
      for (const day of report) {
          const p = fullPriceHistory[day.date] || posMap.get(day.date)?.price;
          if (p !== undefined && p !== null && Number(p) > 0) {
              lastKnownPrice = Number(p);
              break;
          }
      }

      return report.map((day) => {
          const date = day.date;
          const pRecord = posMap.get(date);
          const weight = pRecord ? (typeof pRecord.weight === "number" ? pRecord.weight : Number(pRecord.weight)) : 0;
          
          let currentPrice = fullPriceHistory[date] || (pRecord ? (typeof pRecord.price === "number" ? pRecord.price : Number(pRecord.price)) : 0);
          
          // Carry forward price if missing on this day (e.g. non-trading day)
          if (!currentPrice || Number(currentPrice) === 0) {
              currentPrice = lastKnownPrice;
          } else {
              lastKnownPrice = Number(currentPrice);
          }
          
          const delta = weight - prevWeight;
          let action = null;
          if (delta > 0.01) action = 'buy';
          if (delta < -0.01) action = 'sell';

          if (prevWeight > 0 && lastKnownPrice > 0 && currentPrice > 0) {
              const ret = (currentPrice / lastKnownPrice) - 1;
              runningPnL += ret * prevWeight * (accountByDate.get(date) || 0);
          }

          prevWeight = weight;
          
          return {
              date,
              price: currentPrice > 0 ? currentPrice : null,
              weight,
              action,
              delta,
              cumPnL: runningPnL
          };
      });
  }, [positions, selectedInstrument, report, accountByDate, fullPriceHistory]);

  useEffect(() => {
    if (!positions.length) {
      if (selectedInstrument !== null) setSelectedInstrument(null);
      return;
    }
    const exists = selectedInstrument && positions.some((p) => p?.instrument && String(p.instrument) === String(selectedInstrument));
    if (exists) return;
    const fallback = topContributors[0]?.instrument ?? topLosers[0]?.instrument ?? null;
    setSelectedInstrument(fallback);
  }, [positions, selectedInstrument, topContributors, topLosers]);

  const selectedLabel = useMemo(() => {
    if (!selectedInstrument) return "";
    return labelByInstrument.get(selectedInstrument) || selectedInstrument;
  }, [labelByInstrument, selectedInstrument]);

  interface TradeTooltipPayload {
    price: number | null;
    weight: number;
    cumPnL: number;
    action: string | null;
    delta: number;
  }

  const CustomTradeTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ payload: TradeTooltipPayload }>; label?: string }) => {
      if (active && payload && payload.length) {
          const d = payload[0].payload;
          return (
              <div className="bg-background border rounded-lg p-3 shadow-xl text-xs text-left">
                  <p className="font-black border-b pb-1 mb-2 uppercase tracking-tighter text-muted-foreground">{label}</p>
                  <div className="space-y-1.5">
                    <div className="flex justify-between gap-10">
                        <span className="text-muted-foreground font-bold uppercase text-[10px]">Quote</span>
                        <span className="font-mono font-bold">{d.price?.toFixed(2) || 'N/A'}</span>
                    </div>
                    <div className="flex justify-between gap-10">
                        <span className="text-muted-foreground font-bold uppercase text-[10px]">Exposure</span>
                        <span className="font-mono">{(d.weight * 100).toFixed(1)}%</span>
                    </div>
                    <div className="flex justify-between gap-10 pt-1.5 border-t mt-1">
                        <span className="text-muted-foreground font-bold uppercase text-[10px]">Net PnL</span>
                        <span className={`font-mono font-black ${d.cumPnL >= 0 ? "text-green-600" : "text-red-600"}`}>
                            {d.cumPnL >= 0 ? '+' : ''}{(d.cumPnL ?? 0).toFixed(2)} USD
                        </span>
                    </div>
                    {d.action && (
                        <div className={`mt-2 py-1 px-2 rounded text-[10px] font-black uppercase text-center border ${d.action === 'buy' ? 'bg-green-50 text-green-600 border-green-200' : 'bg-red-50 text-red-600 border-red-200'}`}>
                            {d.action} • {Math.abs(d.delta * 100).toFixed(1)}%
                        </div>
                    )}
                  </div>
              </div>
          );
      }
      return null;
  };

  return (
    <div className="space-y-8 flex flex-col text-left max-w-[1400px] mx-auto pb-20">
      <Card className="border shadow-lg overflow-hidden">
          <CardHeader className="flex flex-row items-center justify-between border-b bg-muted/30 py-4 px-8">
              <div className="flex items-center gap-5">
                <div className="bg-primary px-3 py-1 rounded-sm text-[10px] font-black uppercase tracking-widest text-primary-foreground shadow-md shadow-primary/10">
                    {selectedInstrument || "N/A"}
                </div>
                <div className="space-y-0.5 text-left">
                    <CardTitle className="text-base font-black uppercase tracking-tight">Asset Execution & Yield Dynamics</CardTitle>
                    <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.2em]">{selectedLabel}</p>
                </div>
              </div>
              <div className="flex items-center gap-4">
                {loadingPrice && <Loader2 className="h-3 w-3 animate-spin text-primary" />}
                <select 
                    className="h-9 w-[240px] rounded border border-input bg-background px-4 text-[10px] font-black uppercase tracking-widest focus:ring-1 focus:ring-primary outline-none cursor-pointer transition-all text-center"
                    value={selectedInstrument || ''}
                    onChange={(e) => setSelectedInstrument(e.target.value)}
                >
                {selectionOptions.map(d => (
                        <option key={d.instrument} value={d.instrument}>{d.name} ({d.instrument})</option>
                    ))}
                </select>
              </div>
          </CardHeader>
          <CardContent className="h-[450px] p-8 pt-12">
              {tradeData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                      <ComposedChart data={tradeData} margin={{ top: 0, right: 10, left: 0, bottom: 0 }}>
                          <defs>
                            <linearGradient id="colorPnL" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.2}/>
                                <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0}/>
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.1} />
                          <XAxis 
                            dataKey="date" 
                            tickFormatter={(d) => format(parseISO(d), 'MM/dd')} 
                            minTickGap={60} 
                            tick={{fill: 'hsl(var(--muted-foreground))', fontSize: 9, fontWeight: 800}} 
                            axisLine={false}
                            tickLine={false}
                          />
                          <YAxis 
                            yAxisId="left" 
                            domain={['auto', 'auto']} 
                            tick={{fill: 'hsl(var(--muted-foreground))', fontSize: 9, fontWeight: 700}} 
                            width={50} 
                            axisLine={false} 
                            tickLine={false}
                            label={{ value: 'MARKET PRICE', angle: -90, position: 'insideLeft', fill: 'hsl(var(--muted-foreground))', opacity: 0.5, fontSize: 8, fontWeight: 900, offset: 10 }}
                          />
                          <YAxis 
                            yAxisId="right" 
                            orientation="right" 
                            domain={['auto', 'auto']} 
                            tick={{fill: 'hsl(var(--primary))', fontSize: 9, fontWeight: 700}} 
                            width={50} 
                            axisLine={false} 
                            tickLine={false}
                            label={{ value: 'YIELD (USD)', angle: 90, position: 'insideRight', fill: 'hsl(var(--primary))', opacity: 0.5, fontSize: 8, fontWeight: 900, offset: 10 }}
                          />
                          <YAxis yAxisId="pos" hide domain={[0, 8]} />
                          
                          <Tooltip content={<CustomTradeTooltip />} cursor={{stroke: 'hsl(var(--primary))', strokeWidth: 1, strokeOpacity: 0.1}} />
                          <Legend 
                            verticalAlign="top" 
                            align="right" 
                            height={40} 
                            iconType="circle" 
                            wrapperStyle={{fontSize: '9px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.15em', paddingTop: '0px', paddingRight: '10px'}} 
                          />
                          
                          <Bar yAxisId="pos" dataKey="weight" fill="hsl(var(--muted-foreground))" opacity={0.1} name="Exposure" animationDuration={500} />
                          <Area 
                            yAxisId="right" 
                            type="stepAfter" 
                            dataKey="cumPnL" 
                            stroke="hsl(var(--primary))" 
                            strokeWidth={3} 
                            fill="url(#colorPnL)" 
                            fillOpacity={1} 
                            name="Net Yield" 
                            animationDuration={1200}
                          />
                          <Line 
                            yAxisId="left" 
                            type="monotone" 
                            dataKey="price" 
                            stroke="hsl(var(--muted-foreground))" 
                            dot={false} 
                            strokeWidth={1.5} 
                            opacity={0.3}
                            strokeDasharray="4 4"
                            name="Quote Basis" 
                            animationDuration={1000}
                            connectNulls={true}
                          />
                          
                          {tradeData.filter(d => d.action === 'buy').map((d, i) => (
                              <ReferenceDot yAxisId="left" key={`buy-${i}`} x={d.date} y={d.price} r={4} fill="#10b981" stroke="#fff" strokeWidth={1.5} />
                          ))}
                          {tradeData.filter(d => d.action === 'sell').map((d, i) => (
                              <ReferenceDot yAxisId="left" key={`sell-${i}`} x={d.date} y={d.price} r={4} fill="#f43f5e" stroke="#fff" strokeWidth={1.5} />
                          ))}
                      </ComposedChart>
                  </ResponsiveContainer>
              ) : (
                  <div className="flex h-full items-center justify-center text-muted-foreground uppercase tracking-[0.3em] text-[10px] font-black italic">Initialize diagnostic engine to view execution data</div>
              )}
          </CardContent>
      </Card>

      <div className="flex flex-col gap-8">
          <Card className="border shadow-lg bg-card overflow-hidden text-left border-l-4 border-emerald-500">
            <CardHeader className="bg-muted/30 border-b flex flex-row items-center justify-between py-3 px-8">
              <div className="flex items-center gap-4">
                <div className="p-2 bg-emerald-500/10 rounded-xl text-emerald-600">
                    <TrendingUp className="h-5 w-5" />
                </div>
                <div className="space-y-0.5 text-left">
                    <CardTitle className="text-xs font-black uppercase tracking-[0.1em]">Alpha Generators</CardTitle>
                    <p className="text-[10px] font-bold text-muted-foreground/60 uppercase tracking-tight text-left">Top performing assets by realized net gain</p>
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-2">
              <div style={{ height: Math.max(120, topContributors.length * 20) }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart layout="vertical" data={topContributors} margin={{ left: 20, right: 60, top: 5, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} strokeOpacity={0.05} />
                    <XAxis type="number" tick={{fontSize: 9, fontWeight: 800}} axisLine={false} tickLine={false} />
                    <YAxis dataKey="name" type="category" width={180} tick={{ fontSize: 10, fontWeight: 800, fill: 'hsl(var(--foreground))' }} interval={0} axisLine={false} tickLine={false} />
                    <Tooltip cursor={{fill: 'rgba(0,0,0,0.03)'}} contentStyle={{borderRadius: '8px', border: 'none', boxShadow: '0 25px 50px -12px rgb(0 0 0 / 0.25)', fontSize: '10px', fontWeight: 'bold'}} formatter={(v: number) => [`$${(v ?? 0).toFixed(2)}`, 'Gain']} />
                    <Bar dataKey="value" onClick={(data) => setSelectedInstrument(data.instrument)} cursor="pointer" radius={[0, 4, 4, 0]} barSize={14}>
                      {topContributors.map((_, index) => (
                        <Cell key={`cell-${index}`} fill="#10b981" fillOpacity={0.7} className="hover:fill-opacity-100 transition-all duration-300" />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          <Card className="border shadow-lg bg-card overflow-hidden text-left border-l-4 border-rose-500">
            <CardHeader className="bg-muted/30 border-b flex flex-row items-center justify-between py-3 px-8">
              <div className="flex items-center gap-4">
                <div className="p-2 bg-rose-500/10 rounded-xl text-rose-600">
                    <TrendingDown className="h-5 w-5" />
                </div>
                <div className="space-y-0.5 text-left">
                    <CardTitle className="text-xs font-black uppercase tracking-[0.1em]">Alpha Drags</CardTitle>
                    <p className="text-[10px] font-bold text-muted-foreground/60 uppercase tracking-tight text-left">Assets resulting in maximum portfolio drawdown</p>
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-2">
              <div style={{ height: Math.max(120, topLosers.length * 20) }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart layout="vertical" data={topLosers} margin={{ left: 20, right: 60, top: 5, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} strokeOpacity={0.05} />
                    <XAxis type="number" tick={{fontSize: 9, fontWeight: 800}} axisLine={false} tickLine={false} />
                    <YAxis dataKey="name" type="category" width={180} tick={{ fontSize: 10, fontWeight: 800, fill: 'hsl(var(--foreground))' }} interval={0} axisLine={false} tickLine={false} />
                    <Tooltip cursor={{fill: 'rgba(0,0,0,0.03)'}} contentStyle={{borderRadius: '8px', border: 'none', boxShadow: '0 25px 50px -12px rgb(0 0 0 / 0.25)', fontSize: '10px', fontWeight: 'bold'}} formatter={(v: number) => [`$${(v ?? 0).toFixed(2)}`, 'Loss']} />
                    <Bar dataKey="value" onClick={(data) => setSelectedInstrument(data.instrument)} cursor="pointer" radius={[0, 4, 4, 0]} barSize={14}>
                      {topLosers.map((_, index) => (
                        <Cell key={`cell-${index}`} fill="#f43f5e" fillOpacity={0.7} className="hover:fill-opacity-100 transition-all duration-300" />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>
      </div>
    </div>
  );
}
