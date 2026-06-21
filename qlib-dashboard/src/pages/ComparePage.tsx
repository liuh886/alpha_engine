import { Fragment, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ModelData, parseQlibData } from "@/lib/data-parser";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { HoldingsSummary } from "@/components/HoldingsSummary";
import { Placeholder } from "@/components/Placeholder";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine } from "recharts";
import { Layers, TrendingUp, Target, Trophy, RefreshCw, ArrowUpDown, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { shortId, formatPct } from "@/lib/format";
import { format, parseISO } from "date-fns";
import { ReleaseOutcome } from "@/components/ReleaseOutcome";
import { Button } from "@/components/ui/button";
import { useQuery } from "@/hooks/useQuery";
import { releaseApi } from "@/lib/release-api";
import { parseReleaseIdentity, type OutcomeSummary } from "@/lib/release-workflow";
import type { ModelVersion } from "@/lib/api-types";
import {
  STANDARD_METRICS,
  formatMetricValue,
  checkModelCompatibility,
  METRIC_SCHEMA_VERSION,
  type CompatibilityWarning,
} from "@/types/metrics";

const MAX_COMPARE = 5;
const COLORS = ["hsl(var(--primary))", "#f59e0b", "#0ea5e9", "#8b5cf6", "#ec4899"];

function buildEquitySeries(models: ModelData[]) {

  const rows = new Map<string, Record<string, any>>();
  for (const model of models) {
    const report = model.backtest.report || [];
    if (!report.length) continue;
    const firstAccount = Number(report[0]?.account);
    // Skip models whose first account value is missing/invalid —
    // there is no reliable base to normalise against.
    if (!Number.isFinite(firstAccount) || firstAccount <= 0) continue;
    for (const row of report) {
      const date = row.date;
      if (!date) continue;
      const account = Number(row.account);
      const entry = rows.get(date) || { date };
      // Missing or invalid account → null (gap in the chart), NOT -100 %
      entry[model.id] = Number.isFinite(account)
        ? (account / firstAccount) - 1
        : null;
      rows.set(date, entry);
    }
  }
  return Array.from(rows.values()).sort((a, b) => a.date.localeCompare(b.date));
}

type SortKey = "rank" | "participant_name" | "nav" | "daily_return" | "drawdown";

// ---- Tab type ----
type TabId = "comparison" | "leaderboard";

export function ComparePage({ models, preselectedIds: propIds, compact = false }: { models: ModelData[], preselectedIds?: string[], compact?: boolean }) {
  const location = useLocation();
  const navigate = useNavigate();
  const state = location.state as { preselectedIds?: string[] } | null;
  const preselectedIds = propIds ?? state?.preselectedIds;
  const routeIdentity = parseReleaseIdentity(location.search);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<TabId>("comparison");
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [sortAsc, setSortAsc] = useState(true);

  const comparisonQuery = useQuery<{ models: ModelData[]; registry: ModelVersion[] }>({
    enabled: !compact,
    fetcher: async (signal) => {
      const [artifact, registry] = await Promise.all([
        releaseApi.getDashboardArtifact(signal),
        releaseApi.listModels(undefined, signal),
      ]);
      return { models: parseQlibData(artifact), registry: registry.versions };
    },
  });
  const availableModels = compact ? models : comparisonQuery.data?.models ?? [];
  const registry = compact ? [] : comparisonQuery.data?.registry ?? [];

  const arenasQuery = useQuery({
    enabled: !compact && activeTab === "leaderboard",
    fetcher: (signal) => releaseApi.listArenas(signal),
  });
  const arenaId = arenasQuery.data?.arenas[0]?.id ?? "";
  const leaderboardQuery = useQuery({
    enabled: !compact && activeTab === "leaderboard" && Boolean(arenaId),
    queryKey: arenaId,
    fetcher: (signal) => releaseApi.getLeaderboard(arenaId, signal),
  });
  const leaderboard = leaderboardQuery.data?.leaderboard ?? [];
  const leaderboardLoading = arenasQuery.loading || leaderboardQuery.loading;

  useEffect(() => {
    const requested = [
      ...(preselectedIds ?? []),
      routeIdentity.modelId,
      routeIdentity.runId,
    ].filter(Boolean) as string[];
    const resolved = requested.flatMap((id) => {
      const direct = availableModels.find((model) => model.id === id);
      if (direct) return [direct.id];
      const registered = registry.find((model) => model.id === id || model.run_id === id);
      if (!registered) return [];
      const artifact = availableModels.find((model) => model.id === registered.run_id || model.id === registered.id);
      return artifact ? [artifact.id] : [];
    });

    if (resolved.length > 0) {
      setSelectedIds(Array.from(new Set(resolved)).slice(0, MAX_COMPARE));
    } else if (availableModels.length > 0) {
      // Prefer models that have actual metric data
      const withData = availableModels.filter(m => Object.values(m.backtest.metrics).some(v => v != null));
      const initial = withData.length >= 2 ? withData.slice(0, 2) : availableModels.slice(0, 2);
      setSelectedIds(initial.map(m => m.id));
    }
  }, [availableModels, preselectedIds, registry, routeIdentity.modelId, routeIdentity.runId]);

  const selectedModels = useMemo(() => availableModels.filter(m => selectedIds.includes(m.id)), [availableModels, selectedIds]);
  const equitySeries = useMemo(() => buildEquitySeries(selectedModels), [selectedModels]);
  const compatWarnings = useMemo(() => checkModelCompatibility(selectedModels), [selectedModels]);

  const toggleModel = (id: string) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : prev.length < MAX_COMPARE ? [...prev, id] : prev);
  };

  const comparisonOutcome = useMemo<OutcomeSummary>(() => {
    if (comparisonQuery.loading && !comparisonQuery.data) return { state: "loading", reason: "Loading registry and backtest artifacts." };
    if (comparisonQuery.error) return { state: "failed", reason: comparisonQuery.error };
    if (availableModels.length === 0) return { state: "empty", reason: "No backtest artifacts are available for comparison." };
    if (!routeIdentity.modelId && !routeIdentity.runId) return { state: "success", reason: `${availableModels.length} backtest artifacts are available.` };

    const registered = registry.find((model) => model.id === routeIdentity.modelId);
    if (routeIdentity.modelId && !registered) {
      return { state: "partial", reason: `Model ${routeIdentity.modelId} is missing from the registry.` };
    }
    if (routeIdentity.runId && registered?.run_id !== routeIdentity.runId) {
      return { state: "blocked", reason: `Model ${registered?.id} is not bound to run ${routeIdentity.runId}.` };
    }
    const exactRun = routeIdentity.runId || registered?.run_id;
    if (!exactRun || !availableModels.some((model) => model.id === exactRun || model.id === registered?.id)) {
      return { state: "partial", reason: `Run ${exactRun || "unknown"} is missing from dashboard artifacts.` };
    }
    if (routeIdentity.evidenceId && routeIdentity.modelId && routeIdentity.evidenceId !== routeIdentity.modelId) {
      return { state: "blocked", reason: `Evidence ${routeIdentity.evidenceId} is not bound to model ${routeIdentity.modelId}.` };
    }
    return { state: "success", reason: `Exact release identity selected: ${exactRun} / ${registered?.id || routeIdentity.modelId}.` };
  }, [availableModels, comparisonQuery.data, comparisonQuery.error, comparisonQuery.loading, registry, routeIdentity.evidenceId, routeIdentity.modelId, routeIdentity.runId]);

  const sortedLeaderboard = useMemo(() => {
    const rows = [...leaderboard];
    rows.sort((a, b) => {
       
      let va: any = a[sortKey];
       
      let vb: any = b[sortKey];
      if (sortKey === "participant_name") {
        va = (va || "").toLowerCase();
        vb = (vb || "").toLowerCase();
        return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
      }
      va = Number.isFinite(va) ? va : 0;
      vb = Number.isFinite(vb) ? vb : 0;
      return sortAsc ? va - vb : vb - va;
    });
    return rows;
  }, [leaderboard, sortKey, sortAsc]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
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
          {routeIdentity.modelId && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate({ pathname: "/models", search: location.search })}
            >
              Open exact model in registry
            </Button>
          )}
        </div>
      )}

      {!compact && <ReleaseOutcome state={comparisonOutcome.state} reason={comparisonOutcome.reason} />}

      {/* Tab bar (only in full mode) */}
      {!compact && (
        <div className="flex gap-1 p-1 bg-muted/50 rounded-lg w-fit">
          {([
            { id: "comparison" as TabId, label: "Comparison" },
            { id: "leaderboard" as TabId, label: "Leaderboard" },
          ]).map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "px-4 py-1.5 rounded-md text-xs font-bold uppercase tracking-wider transition-all",
                activeTab === tab.id
                  ? "bg-background shadow-sm text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {/* === Leaderboard Tab === */}
      {activeTab === "leaderboard" && !compact && (
        <Card className="border-none shadow-xl">
          <CardHeader className="bg-muted/20 border-b flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-xs font-black uppercase tracking-widest flex items-center gap-2">
                <Trophy className="h-3.5 w-3.5 text-amber-500" /> Strategy Leaderboard
              </CardTitle>
              <CardDescription className="text-[10px] mt-1">Strategies ranked by key performance metrics from the Arena</CardDescription>
            </div>
            <button
              onClick={() => arenaId ? leaderboardQuery.refetch() : arenasQuery.refetch()}
              className="p-1.5 rounded hover:bg-muted transition-colors"
              aria-label="Refresh leaderboard"
              title="Refresh leaderboard"
            >
              <RefreshCw className={cn("h-3.5 w-3.5 text-muted-foreground", leaderboardLoading && "animate-spin")} />
            </button>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-[60px] text-center cursor-pointer" onClick={() => handleSort("rank")}>
                    <span className="flex items-center justify-center gap-1">Rank <ArrowUpDown className="h-3 w-3" /></span>
                  </TableHead>
                  <TableHead className="cursor-pointer" onClick={() => handleSort("participant_name")}>
                    <span className="flex items-center gap-1">Strategy <ArrowUpDown className="h-3 w-3" /></span>
                  </TableHead>
                  <TableHead className="text-right cursor-pointer" onClick={() => handleSort("nav")}>
                    <span className="flex items-center justify-end gap-1">NAV <ArrowUpDown className="h-3 w-3" /></span>
                  </TableHead>
                  <TableHead className="text-right cursor-pointer" onClick={() => handleSort("daily_return")}>
                    <span className="flex items-center justify-end gap-1">Return <ArrowUpDown className="h-3 w-3" /></span>
                  </TableHead>
                  <TableHead className="text-right cursor-pointer" onClick={() => handleSort("drawdown")}>
                    <span className="flex items-center justify-end gap-1">Max DD <ArrowUpDown className="h-3 w-3" /></span>
                  </TableHead>
                  <TableHead className="text-right">Alpha</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedLeaderboard.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="h-48 text-center text-muted-foreground text-sm">
                      {leaderboardLoading ? "Loading leaderboard..." : "No leaderboard data available. Run an Arena settlement first."}
                    </TableCell>
                  </TableRow>
                ) : (
                  sortedLeaderboard.map((r, i) => {
                    const rank = r.rank ?? i + 1;
                    const alpha = r.daily_return != null ? r.daily_return - 0 : null; // vs benchmark (0 = baseline)
                    return (
                      <Fragment key={i}>
                        <TableRow className="group">
                          <TableCell className="text-center">
                            {rank <= 3 ? (
                              <span className={cn(
                                "inline-flex h-7 w-7 items-center justify-center rounded-full text-white text-xs",
                                rank === 1 ? "bg-amber-400" : rank === 2 ? "bg-slate-400" : "bg-amber-600"
                              )}>
                                {rank}
                              </span>
                            ) : (
                              <span className="text-xs font-mono text-muted-foreground">{rank}</span>
                            )}
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-col">
                              <span className="text-sm font-medium">{r.participant_name || "Unnamed"}</span>
                              <span className="text-[10px] text-muted-foreground font-mono">{r.run_id ? r.run_id.slice(0, 12) : "N/A"}</span>
                            </div>
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs">
                            {r.nav != null ? r.nav.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 }) : "N/A"}
                          </TableCell>
                          <TableCell className={cn(
                            "text-right font-mono text-xs",
                            (r.daily_return || 0) > 0 ? "text-green-500" : (r.daily_return || 0) < 0 ? "text-red-500" : ""
                          )}>
                            {formatPct(r.daily_return)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs text-muted-foreground">
                            {formatPct(r.drawdown)}
                          </TableCell>
                          <TableCell className={cn(
                            "text-right font-mono text-xs font-bold",
                            alpha != null && alpha > 0 ? "text-green-500" : alpha != null && alpha < 0 ? "text-red-500" : "text-muted-foreground"
                          )}>
                            {alpha != null ? formatPct(alpha) : "N/A"}
                          </TableCell>
                        </TableRow>
                        {rank === 1 && r.edge_explanation && (
                          <TableRow className="bg-amber-500/5">
                            <TableCell colSpan={6} className="py-3 px-6 text-left border-l-2 border-amber-500">
                              <div className="flex items-start gap-2">
                                <Trophy className="h-3.5 w-3.5 text-amber-500 mt-0.5 flex-shrink-0" />
                                <div>
                                  <span className="text-[10px] uppercase font-semibold text-amber-600">Edge Analysis</span>
                                  <p className="text-xs text-muted-foreground mt-0.5">&quot;{r.edge_explanation}&quot;</p>
                                </div>
                              </div>
                            </TableCell>
                          </TableRow>
                        )}
                      </Fragment>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* === Comparison Tab (original content) === */}
      {(activeTab === "comparison" || compact) && (
        <div className={cn("grid gap-8", compact ? "grid-cols-1" : "grid-cols-1 xl:grid-cols-4")}>
          {!compact && (
            <Card className="xl:col-span-1 border-none shadow-lg bg-muted/30">
              <CardHeader>
                <CardTitle className="text-sm font-bold uppercase tracking-tight text-left">Active Portfolio</CardTitle>
                <CardDescription className="text-[10px] text-left">Select models to sync with the main engine</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {availableModels.map((m) => {
                  const isActive = selectedIds.includes(m.id);
                  const colorIdx = selectedIds.indexOf(m.id);
                  return (
                    <button
                      key={m.id}
                      onClick={() => toggleModel(m.id)}
                      aria-pressed={isActive}
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
                        <span className="text-[10px] text-muted-foreground uppercase font-black">{m.market} &bull; {m.date}</span>
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
              <Placeholder icon={Target} title="Awaiting Model Selection" description="Select up to 5 models from the Active Portfolio list to begin relative analysis." />
            ) : (
              <>
                {compatWarnings.length > 0 && (
                  <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-left" role="alert">
                    <div className="flex items-center gap-2 mb-1">
                      <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0" />
                      <span className="text-xs font-bold uppercase tracking-wider text-amber-600">
                        Comparison Warning
                      </span>
                      <span className="text-[10px] text-muted-foreground ml-auto font-mono">schema v{METRIC_SCHEMA_VERSION}</span>
                    </div>
                    <ul className="space-y-0.5 ml-6">
                      {compatWarnings.map((w: CompatibilityWarning) => (
                        <li key={w.code} className="text-xs text-amber-700/90">{w.message}</li>
                      ))}
                    </ul>
                  </div>
                )}

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
                          {STANDARD_METRICS.filter((d) => d.required).map((metric) => (
                            <TableRow key={metric.key} className="hover:bg-muted/10 transition-colors border-b last:border-0 text-left">
                              <TableCell className="font-bold text-[10px] uppercase text-muted-foreground pl-6">{metric.label}</TableCell>
                              {selectedModels.map((m) => (<TableCell key={`${m.id}-${metric.key}`} className="text-center font-mono font-black text-xs">{formatMetricValue(m.backtest.metrics[metric.key], metric)}</TableCell>))}
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
                        <Tooltip contentStyle={{ backgroundColor: 'hsl(var(--background))', border: '1px solid hsl(var(--border))', borderRadius: '12px', fontSize: '10px' }} formatter={(v: number | string) => `${(Number(v) * 100).toFixed(2)}%`} />
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
      )}
    </div>
  );
}
