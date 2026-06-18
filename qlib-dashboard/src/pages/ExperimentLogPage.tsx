import { useEffect, useState, useMemo, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Loader2,
  RefreshCw,
  Search,
  X,
  ClipboardList,
  Activity,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSort } from "@/lib/format";
import { FailedExperimentsPanel } from "./experiment-log/FailedExperimentsPanel";
import { apiFetch } from "@/lib/api";
import {
  TYPE_COLORS,
  TYPE_LABELS,
  RESULT_COLORS,
  ALL_TYPES,
  formatTimestamp,
  formatMetricValue,
} from "./experiment-log/types";
import type {
  ExperimentSummary,
  ExperimentEntry,
  FailedExperiment,
} from "./experiment-log/types";

type SortKey = "timestamp" | "type" | "name" | "result";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ExperimentLogPage() {
  const [summary, setSummary] = useState<ExperimentSummary | null>(null);
  const [experiments, setExperiments] = useState<ExperimentEntry[]>([]);
  const [failures, setFailures] = useState<FailedExperiment[]>([]);
  const [loading, setLoading] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<import("./experiment-log/types").ExperimentType | "all">("all");
  const { sortKey, sortAsc, toggleSort, SortIcon } = useSort<SortKey>("timestamp");

  // ------------------------------------------------------------------
  // Data fetching
  // ------------------------------------------------------------------

  const loadSummary = useCallback(async () => {
    try {
      const resp = await apiFetch("/api/factors/experiments/summary", { cache: "no-store" });
      if (!resp.ok) return;
      const json = await resp.json();
      if (json.ok) setSummary(json.summary || null);
    } catch { /* server not running */ }
  }, []);

  const loadExperiments = useCallback(async () => {
    try {
      const resp = await apiFetch("/api/factors/experiments?query=tried", { cache: "no-store" });
      if (!resp.ok) return;
      const json = await resp.json();
      if (json.ok) setExperiments(json.experiments || []);
    } catch { /* server not running */ }
  }, []);

  const loadFailures = useCallback(async () => {
    try {
      const resp = await apiFetch("/api/factors/experiments/failed", { cache: "no-store" });
      if (!resp.ok) return;
      const json = await resp.json();
      if (json.ok) setFailures(json.failures || []);
    } catch { /* server not running */ }
  }, []);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      await Promise.all([loadSummary(), loadExperiments(), loadFailures()]);
    } finally {
      setLoading(false);
    }
  }, [loadSummary, loadExperiments, loadFailures]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // ------------------------------------------------------------------
  // Derived data
  // ------------------------------------------------------------------

  const displayed = useMemo(() => {
    let list = [...experiments];

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (e) => e.name.toLowerCase().includes(q) || e.type.toLowerCase().includes(q)
      );
    }

    if (typeFilter !== "all") {
      list = list.filter((e) => e.type === typeFilter);
    }

    list.sort((a, b) => {
      if (sortKey === "timestamp") {
        return sortAsc
          ? new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
          : new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
      }
      if (sortKey === "type") {
        return sortAsc ? a.type.localeCompare(b.type) : b.type.localeCompare(a.type);
      }
      if (sortKey === "name") {
        return sortAsc ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
      }
      if (sortKey === "result") {
        const order = { in_progress: 0, fail: 1, pass: 2 };
        const ra = order[a.result] ?? 0;
        const rb = order[b.result] ?? 0;
        return sortAsc ? ra - rb : rb - ra;
      }
      return 0;
    });

    return list;
  }, [experiments, searchQuery, typeFilter, sortKey, sortAsc]);

  const getKeyMetrics = (entry: ExperimentEntry): { label: string; value: string }[] => {
    const metrics: { label: string; value: string }[] = [];
    if (entry.metrics) {
      const metricKeys = Object.keys(entry.metrics).slice(0, 3);
      for (const key of metricKeys) {
        metrics.push({ label: key, value: formatMetricValue(entry.metrics[key]) });
      }
    }
    return metrics;
  };

  const totalExperiments = summary?.total_experiments ?? experiments.length;
  const activeFactors = summary?.active_factors ?? 0;
  const wfResults = summary?.wf_results ?? 0;
  const failedExperiments = summary?.failed_experiments ?? failures.length;

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto pb-16">
      {/* Header */}
      <div className="border-b pb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Experiment Log</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Chronological history of all factor, model, and walk-forward experiments.
          </p>
        </div>
        <Button onClick={loadAll} variant="outline" size="sm" className="h-7 gap-1.5 text-xs">
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} /> Refresh
        </Button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-primary/10"><ClipboardList className="h-4 w-4 text-primary" /></div>
              <div>
                <p className="text-xs text-muted-foreground">Total Experiments</p>
                <p className="text-2xl font-bold">{totalExperiments}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-green-500/10"><CheckCircle2 className="h-4 w-4 text-green-500" /></div>
              <div>
                <p className="text-xs text-muted-foreground">Active Factors</p>
                <p className="text-2xl font-bold text-green-500">{activeFactors}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-orange-500/10"><Activity className="h-4 w-4 text-orange-500" /></div>
              <div>
                <p className="text-xs text-muted-foreground">Walk-Forward Results</p>
                <p className="text-2xl font-bold text-orange-500">{wfResults}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-red-500/10"><XCircle className="h-4 w-4 text-red-500" /></div>
              <div>
                <p className="text-xs text-muted-foreground">Failed Experiments</p>
                <p className="text-2xl font-bold text-red-500">{failedExperiments}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Experiment Timeline */}
      <Card>
        <CardHeader className="pb-2 border-b flex flex-row items-center justify-between py-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <ClipboardList className="h-4 w-4" /> Experiment Timeline
          </CardTitle>
          <Badge variant="outline" className="text-xs">
            {displayed.length} experiment{displayed.length !== 1 ? "s" : ""}
          </Badge>
        </CardHeader>
        <CardContent className="p-0">
          <div className="flex flex-wrap items-end gap-3 px-4 py-3 border-b">
            <div className="space-y-1 flex-1 min-w-[200px] max-w-[320px]">
              <label className="text-xs text-muted-foreground">Search by name</label>
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                <Input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="e.g. momentum, vol_breakout..." className="h-7 pl-7 text-xs" />
                {searchQuery && (
                  <button onClick={() => setSearchQuery("")} className="absolute right-2 top-1/2 -translate-y-1/2">
                    <X className="h-3 w-3 text-muted-foreground hover:text-foreground" />
                  </button>
                )}
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Type</label>
              <div className="flex gap-1 flex-wrap">
                <Button variant={typeFilter === "all" ? "default" : "outline"} size="sm" onClick={() => setTypeFilter("all")} className="h-7 text-xs">All</Button>
                {ALL_TYPES.map((t) => (
                  <Button key={t} variant={typeFilter === t ? "default" : "outline"} size="sm" onClick={() => setTypeFilter(t)} className="h-7 text-xs">{TYPE_LABELS[t]}</Button>
                ))}
              </div>
            </div>
          </div>

          {loading ? (
            <div className="h-64 flex items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-primary opacity-50" />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="cursor-pointer select-none text-xs" onClick={() => toggleSort("timestamp")}>
                    <span className="flex items-center gap-1">Timestamp <SortIcon column="timestamp" /></span>
                  </TableHead>
                  <TableHead className="cursor-pointer select-none text-xs" onClick={() => toggleSort("type")}>
                    <span className="flex items-center gap-1">Type <SortIcon column="type" /></span>
                  </TableHead>
                  <TableHead className="cursor-pointer select-none text-xs" onClick={() => toggleSort("name")}>
                    <span className="flex items-center gap-1">Name <SortIcon column="name" /></span>
                  </TableHead>
                  <TableHead className="cursor-pointer select-none text-xs" onClick={() => toggleSort("result")}>
                    <span className="flex items-center gap-1">Result <SortIcon column="result" /></span>
                  </TableHead>
                  <TableHead className="text-xs">Key Metrics</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {displayed.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="h-48 text-center text-muted-foreground text-sm">
                      {loading ? "Loading experiments..." : "No experiments found."}
                    </TableCell>
                  </TableRow>
                ) : (
                  displayed.map((entry) => {
                    const metrics = getKeyMetrics(entry);
                    return (
                      <TableRow key={entry.id} className="group">
                        <TableCell className="text-xs font-mono text-muted-foreground">
                          {formatTimestamp(entry.timestamp)}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0", TYPE_COLORS[entry.type])}>
                            {TYPE_LABELS[entry.type]}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <span className="text-sm font-medium">{entry.name}</span>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            <div className={cn("h-2 w-2 rounded-full", entry.result === "pass" ? "bg-green-500" : entry.result === "fail" ? "bg-red-500" : "bg-yellow-500 animate-pulse")} />
                            <span className={cn("text-xs font-medium capitalize", RESULT_COLORS[entry.result])}>
                              {entry.result === "in_progress" ? "In Progress" : entry.result === "pass" ? "Passed" : "Failed"}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell>
                          {metrics.length > 0 ? (
                            <div className="flex gap-3 flex-wrap">
                              {metrics.map((m, i) => (
                                <span key={i} className="text-xs">
                                  <span className="text-muted-foreground">{m.label}: </span>
                                  <span className="font-mono">{m.value}</span>
                                </span>
                              ))}
                            </div>
                          ) : (
                            <span className="text-xs text-muted-foreground">--</span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Failed Experiments Panel */}
      <FailedExperimentsPanel failures={failures} loading={loading} />
    </div>
  );
}
