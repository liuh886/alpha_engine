import { useEffect, useMemo, useState } from "react";
import { ModelData } from "@/lib/data-parser";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { HoldingsSummary } from "@/components/HoldingsSummary";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine } from "recharts";
import { Layers, TrendingUp, Target } from "lucide-react";
import { cn } from "@/lib/utils";

const MAX_COMPARE = 5;
const COLORS = ["hsl(var(--primary))", "#f59e0b", "#0ea5e9", "#8b5cf6", "#ec4899"];

type MetricDef = { label: string; key: string; format: (value?: number) => string; };

function formatPercent(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return "N/A";
  return `${(value * 100).toFixed(2)}%`;
}

function formatNumber(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return "N/A";
  return value.toFixed(3);
}

function shortId(value: string) {
  if (!value) return "";
  return value.length <= 8 ? value : value.slice(0, 8);
}

const metricDefs: MetricDef[] = [
  { label: "Ann. Return", key: "Annualized Return", format: formatPercent },
  { label: "Sharpe Ratio", key: "Sharpe Ratio", format: formatNumber },
  { label: "Information Ratio", key: "Information Ratio", format: formatNumber },
  { label: "Max Drawdown", key: "Max Drawdown", format: formatPercent },
  { label: "Ann. Volatility", key: "Annualized Volatility", format: formatPercent },
  { label: "Total Return", key: "Total Return", format: formatPercent },
];

function buildEquitySeries(models: ModelData[]) {
  const rows = new Map<string, Record<string, any>>();
  for (const model of models) {
    const report = model.backtest.report || [];
    if (!report.length) continue;
    const firstAccount = Number(report[0]?.account || 1);
    for (const row of report) {
      const date = row.date;
      if (!date) continue;
      const entry = rows.get(date) || { date };
      entry[model.id] = (Number(row.account || 0) / firstAccount) - 1;
      rows.set(date, entry);
    }
  }
  return Array.from(rows.values()).sort((a, b) => a.date.localeCompare(b.date));
}

export function ComparePage({ models, preselectedIds, compact = false }: { models: ModelData[], preselectedIds?: string[], compact?: boolean }) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  useEffect(() => {
    if (preselectedIds && preselectedIds.length > 0) {
      setSelectedIds(preselectedIds);
    } else if (models.length > 0 && selectedIds.length === 0) {
      setSelectedIds(models.slice(0, 2).map(m => m.id));
    }
  }, [models, preselectedIds]);

  const selectedModels = useMemo(() => models.filter(m => selectedIds.includes(m.id)), [models, selectedIds]);
  const equitySeries = useMemo(() => buildEquitySeries(selectedModels), [selectedModels]);

  const toggleModel = (id: string) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : prev.length < MAX_COMPARE ? [...prev, id] : prev);
  };

  return (
    <div className={cn("space-y-8 max-w-[1600px] mx-auto", compact ? "pb-2" : "pb-20")}>
      {!compact && (
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b pb-6 text-left">
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-widest mb-1">
              <Layers className="h-3.5 w-3.5" /> Relative Analysis
            </div>
            <h1 className="text-4xl font-black tracking-tight">Model Comparison</h1>
            <p className="text-muted-foreground text-sm max-w-md">Overlay up to {MAX_COMPARE} strategies to analyze relative performance and alpha decay.</p>
          </div>
        </div>
      )}

      <div className={cn("grid gap-8", compact ? "grid-cols-1" : "grid-cols-1 xl:grid-cols-4")}>
        {!compact && (
          <Card className="xl:col-span-1 border-none shadow-lg bg-muted/30">
            <CardHeader>
              <CardTitle className="text-sm font-bold uppercase tracking-tight text-left">Active Portfolio</CardTitle>
              <CardDescription className="text-[10px] text-left">Select models to sync with the main engine</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {models.map((m) => {
                const isActive = selectedIds.includes(m.id);
                const colorIdx = selectedIds.indexOf(m.id);
                return (
                  <button
                    key={m.id}
                    onClick={() => toggleModel(m.id)}
                    className={cn(
                      "w-full flex items-center gap-3 p-3 rounded-xl border-2 transition-all group",
                      isActive ? "bg-background border-primary shadow-md scale-[1.02]" : "bg-transparent border-transparent hover:border-border hover:bg-muted/50"
                    )}
                  >
                    <div className={cn("h-4 w-4 rounded-full border-2 flex items-center justify-center shrink-0 transition-colors", isActive ? "border-primary" : "border-muted-foreground/30 group-hover:border-muted-foreground")}>
                      {isActive && <div className="h-2 w-2 rounded-full bg-primary" />}
                    </div>
                    <div className="flex flex-col items-start min-w-0 flex-1 text-left">
                      <span className="text-xs font-bold truncate w-full">{m.name || shortId(m.id)}</span>
                      <span className="text-[10px] text-muted-foreground uppercase font-black">{m.market} • {m.date}</span>
                    </div>
                    {isActive && colorIdx >= 0 && (
                      <div className="h-1.5 w-6 rounded-full" style={{ backgroundColor: COLORS[colorIdx % COLORS.length] }} />
                    )}
                  </button>
                );
              })}
            </CardContent>
          </Card>
        )}

        <div className={cn("space-y-8", compact ? "col-span-full" : "xl:col-span-3")}>
          {selectedModels.length === 0 ? (
            <div className="h-96 flex flex-col items-center justify-center bg-muted/10 rounded-3xl border-2 border-dashed border-border/50">
              <Target className="h-12 w-12 text-muted-foreground/30 mb-4" />
              <p className="text-muted-foreground font-medium uppercase tracking-widest text-xs italic">Awaiting Model Selection</p>
            </div>
          ) : (
            <>
              {!compact && (
                <Card className="border-none shadow-xl overflow-hidden">
                  <CardContent className="p-0">
                    <Table>
                      <TableHeader className="bg-muted/50 border-b">
                        <TableRow className="hover:bg-transparent text-left">
                          <TableHead className="w-[180px] font-black text-[10px] uppercase pl-6 py-4">Efficiency Metrics</TableHead>
                          {selectedModels.map((m, idx) => (
                            <TableHead key={m.id} className="text-center font-black text-[10px] uppercase">
                              <div className="flex items-center justify-center gap-2">
                                <div className="h-2 w-2 rounded-full" style={{ backgroundColor: COLORS[idx % COLORS.length] }} />
                                {m.name || shortId(m.id)}
                              </div>
                            </TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {metricDefs.map((metric) => (
                          <TableRow key={metric.key} className="hover:bg-muted/10 transition-colors border-b last:border-0 text-left">
                            <TableCell className="font-bold text-[10px] uppercase text-muted-foreground pl-6">{metric.label}</TableCell>
                            {selectedModels.map((m) => (<TableCell key={`${m.id}-${metric.key}`} className="text-center font-mono font-black text-xs">{metric.format(m.backtest.metrics[metric.key])}</TableCell>))}
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              )}

              <Card className="border-none shadow-2xl bg-card overflow-hidden text-left">
                <CardHeader className="bg-muted/20 border-b">
                  <CardTitle className="text-xs font-black uppercase tracking-widest flex items-center gap-2"><TrendingUp className="h-3.5 w-3.5" /> Normalized Alpha Trajectory (%)</CardTitle>
                </CardHeader>
                <CardContent className="h-[450px] p-6 pt-10">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={equitySeries}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.1} />
                      <XAxis dataKey="date" tickFormatter={(d) => format(parseISO(d), 'MMM yy')} minTickGap={40} tick={{ fontSize: 9, fontWeight: 700 }} axisLine={false} tickLine={false} />
                      <YAxis tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} tick={{ fontSize: 9, fontWeight: 700 }} axisLine={false} tickLine={false} />
                      <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--background))', border: '1px solid hsl(var(--border))', borderRadius: '12px', fontSize: '10px' }} formatter={(v: any) => `${(v * 100).toFixed(2)}%`} />
                      <Legend verticalAlign="top" align="right" height={36} iconType="circle" wrapperStyle={{ fontSize: '10px', fontWeight: 800, textTransform: 'uppercase' }} />
                      <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" />
                      {selectedModels.map((m, idx) => (<Line key={m.id} type="monotone" dataKey={m.id} name={m.name || shortId(m.id)} stroke={COLORS[idx % COLORS.length]} dot={false} strokeWidth={3} animationDuration={1500} />))}
                    </LineChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              {!compact && (
                <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3 text-left">
                  {selectedModels.map((m) => (
                    <HoldingsSummary key={m.id} positions={m.backtest.positions} title={`${m.name || shortId(m.id)} - Top Holdings`} />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function parseISO(s: string) { return new Date(s); }
function format(d: Date, fmt: string) {
  const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const m = monthNames[d.getMonth()];
  const y = d.getFullYear().toString().slice(-2);
  if (fmt.includes('MMM yy')) return `${m} ${y}`;
  return `${d.getMonth() + 1}/${y}`;
}
