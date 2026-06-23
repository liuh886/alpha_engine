import { useEffect, useState, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Loader2, RefreshCw, Activity, Download, Plus, Trash2,
  ChevronDown, ChevronUp, Search, Database, Table,
  CheckCircle2, XCircle, Clock, AlertTriangle, Terminal,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useNameMap } from "@/lib/useNameMap";
import { useQuery } from "@/hooks/useQuery";
import { useMutation } from "@/hooks/useMutation";
import { LoadingSpinner, EmptyState, ErrorState } from "@/components/ui/loading-state";
import { ReleaseOutcome } from "@/components/ReleaseOutcome";
import { releaseApi } from "@/lib/release-api";
import { classifyDataOutcome, parseReleaseIdentity, releaseSearch } from "@/lib/release-workflow";
import type {
  WatchlistResponse,
  DataStatusResponse,
  JobSubmitResponse,
  JobDetailResponse,
  AddSymbolsResponse,
  RemoveSymbolsResponse,
} from "@/lib/api-types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface WatchlistEntry {
  symbol: string;
  name: string;
}

type HeatmapData = {
  symbols: string[];
  dates: string[];
  values: (number | null)[][];
};

type UpdateJobPhase = "idle" | "submitting" | "running" | "succeeded" | "failed";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format a unix timestamp or ISO string into a human-readable relative label. */
function formatAge(ts: number | string | undefined | null): string {
  if (!ts) return "unknown";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (isNaN(d.getTime())) return "unknown";
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) return "just now";
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatTimestamp(ts: number | string | undefined | null): string {
  if (!ts) return "—";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString();
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Status card showing data freshness / last update. */
function DataStatusCard({ refreshKey = 0 }: { refreshKey?: number }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { data, loading, error, refetch } = useQuery<DataStatusResponse>({
    fetcher: (signal) => releaseApi.getDataStatus(signal),
  });

  useEffect(() => {
    if (refreshKey > 0) refetch();
  }, [refreshKey, refetch]);

  const status = data?.data as Record<string, unknown> | undefined;
  const latestCal = status?.latest_calendar_date as string | undefined;
  const dashboardAt = status?.dashboard_generated_at as string | undefined;
  const snapshotId = status?.latest_snapshot_id as string | undefined;
  const qualityStatus = (status?.quality_status as string) || "unknown";
  const qualityWarnings = (status?.quality_warnings as string[]) || [];
  const symbolsConfigured = status?.symbols_configured as number | undefined;
  const symbolsUpdated = status?.symbols_updated as number | undefined;
  const symbolsFailed = status?.symbols_failed as number | undefined;
  const symbolsStale = status?.symbols_stale as number | undefined;
  const hasSymbolAccounting = symbolsConfigured !== undefined || symbolsUpdated !== undefined;
  const outcome = loading && !data
    ? { state: "loading" as const, reason: "Checking published snapshot identity." }
    : error
      ? { state: "failed" as const, reason: error as string }
      : classifyDataOutcome(data?.data ?? null);

  return (
    <Card>
      <CardHeader className="py-3 border-b">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Data Freshness
          </CardTitle>
          <Button onClick={refetch} disabled={loading} variant="ghost" size="sm" className="h-7 text-xs gap-1">
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-4">
        <ReleaseOutcome state={outcome.state} reason={outcome.reason} className="mb-4" />
        {!loading && !error && (
          <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <div className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">Calendar</div>
              <div className="text-sm font-bold mt-1 font-mono">{latestCal ?? "—"}</div>
              <div className="text-[10px] text-muted-foreground">{formatAge(latestCal)}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">Dashboard DB</div>
              <div className="text-sm font-bold mt-1">{dashboardAt ? formatTimestamp(dashboardAt) : "—"}</div>
              <div className="text-[10px] text-muted-foreground">{formatAge(dashboardAt)}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">Snapshot</div>
              <div className="text-sm font-bold mt-1 font-mono truncate" title={snapshotId}>
                {snapshotId ? snapshotId.slice(0, 12) + (snapshotId.length > 12 ? "..." : "") : "—"}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">Quality Verdict</div>
              <div className="flex items-center gap-1.5 mt-1">
                {qualityStatus === "ok" ? (
                  <Badge variant="outline" className="text-[10px] bg-green-500/10 text-green-600 border-green-500/30">
                    <CheckCircle2 className="h-3 w-3 mr-1" /> Pass
                  </Badge>
                ) : qualityStatus === "warning" ? (
                  <Badge variant="outline" className="text-[10px] bg-yellow-500/10 text-yellow-600 border-yellow-500/30">
                    <AlertTriangle className="h-3 w-3 mr-1" /> Warning
                  </Badge>
                ) : qualityStatus === "failed" || qualityStatus === "invalid" || qualityStatus === "rejected" ? (
                  <Badge variant="outline" className="text-[10px] bg-red-500/10 text-red-600 border-red-500/30">
                    <XCircle className="h-3 w-3 mr-1" /> Fail
                  </Badge>
                ) : (
                  <Badge variant="outline" className="text-[10px]">unknown</Badge>
                )}
              </div>
              {qualityWarnings.length > 0 && (
                <div className="text-[10px] text-yellow-600 mt-1">
                  {qualityWarnings[0]}
                </div>
              )}
            </div>
          </div>

          {/* Symbol accounting */}
          {hasSymbolAccounting && (
            <div className="mt-4 pt-3 border-t">
              <div className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider mb-2">Symbol Accounting</div>
              <div className="flex gap-3 flex-wrap">
                {symbolsConfigured !== undefined && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-mono font-bold">{symbolsConfigured}</span>
                    <span className="text-[10px] text-muted-foreground">configured</span>
                  </div>
                )}
                {symbolsUpdated !== undefined && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-mono font-bold text-green-600">{symbolsUpdated}</span>
                    <span className="text-[10px] text-muted-foreground">updated</span>
                  </div>
                )}
                {symbolsFailed !== undefined && symbolsFailed > 0 && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-mono font-bold text-destructive">{symbolsFailed}</span>
                    <span className="text-[10px] text-muted-foreground">failed</span>
                  </div>
                )}
                {symbolsStale !== undefined && symbolsStale > 0 && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-mono font-bold text-yellow-600">{symbolsStale}</span>
                    <span className="text-[10px] text-muted-foreground">stale</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {snapshotId && outcome.state === "success" && (
            <div className="mt-4 flex justify-end">
              <Button
                size="sm"
                onClick={() => navigate({
                  pathname: "/backtest",
                  search: releaseSearch({ snapshotId, jobId: null }, location.search),
                })}
              >
                Train on this snapshot
              </Button>
            </div>
          )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

/** Job progress panel with SSE log streaming. */
function JobProgressPanel({
  jobId,
  onDone,
}: {
  jobId: string;
  onDone: (success: boolean) => void;
}) {
  const doneRef = useState({ current: false })[0];
  const onDoneRef = useState({ current: onDone })[0];
  onDoneRef.current = onDone;
  const jobQuery = useQuery<JobDetailResponse>({
    fetcher: () => releaseApi.getJob(jobId),
    enabled: Boolean(jobId),
  });
  const job = jobQuery.data?.job ?? null;

  useEffect(() => {
    if (!jobId) return;
    const timer = window.setInterval(jobQuery.refetch, 1000);
    return () => window.clearInterval(timer);
  }, [jobId, jobQuery.refetch]);

  const status = job?.status?.toLowerCase() || "running";
  const isTerminal = status === "succeeded" || status === "failed" || status === "succeeded_with_warnings";

  useEffect(() => {
    if (isTerminal && !doneRef.current) {
      doneRef.current = true;
      onDoneRef.current(status === "succeeded" || status === "succeeded_with_warnings");
    }
  }, [doneRef, isTerminal, onDoneRef, status]);

  return (
    <Card className="border-primary/30">
      <CardHeader className="py-3 border-b">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Terminal className="h-4 w-4" />
            Data Update Job
            <Badge
              variant="outline"
              className={cn(
                "text-[10px] ml-1",
                status === "running" && "bg-blue-500/10 text-blue-600 border-blue-500/30",
                status === "succeeded" && "bg-green-500/10 text-green-600 border-green-500/30",
                status === "succeeded_with_warnings" && "bg-yellow-500/10 text-yellow-600 border-yellow-500/30",
                status === "failed" && "bg-red-500/10 text-red-600 border-red-500/30",
              )}
            >
              {status === "running" && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
              {status === "succeeded" && <CheckCircle2 className="h-3 w-3 mr-1" />}
              {status === "succeeded_with_warnings" && <AlertTriangle className="h-3 w-3 mr-1" />}
              {status === "failed" && <XCircle className="h-3 w-3 mr-1" />}
              {status === "succeeded_with_warnings" ? "Completed with warnings" : status}
            </Badge>
          </CardTitle>
          <span className="text-[10px] font-mono text-muted-foreground">{jobId.slice(0, 12)}...</span>
        </div>
      </CardHeader>
      <CardContent className="p-4">
        {jobQuery.loading && !job && <ReleaseOutcome state="loading" reason={`Reconnecting job ${jobId}.`} />}
        {jobQuery.error && <ReleaseOutcome state="failed" reason={jobQuery.error} />}
        {job && (
          <ReleaseOutcome
            state={status.startsWith("succeeded") ? "success" : status === "failed" ? "failed" : "loading"}
            reason={status === "succeeded" ? "Data update published." : status === "succeeded_with_warnings" ? "Data update published with missing symbols." : status === "failed" ? (job.error || "Data update failed.") : "Data update is running."}
          />
        )}
        {isTerminal && status === "failed" && job?.error && (
          <div className="pt-3 text-sm text-destructive">
            {job.error}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function DataPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const initialIdentity = parseReleaseIdentity(location.search);
  const [market, setMarket] = useState<"us" | "cn" | "hk">("cn");

  // Symbol management
  const [addInput, setAddInput] = useState("");
  const [addValidation, setAddValidation] = useState<string | null>(null);
  const [selectedSymbols, setSelectedSymbols] = useState<Set<string>>(new Set());

  // Heatmap (optional view)
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [heatmapData, setHeatmapData] = useState<HeatmapData | null>(null);
  const [heatmapLoading, setHeatmapLoading] = useState(false);
  const [heatmapError, setHeatmapError] = useState<string | null>(null);
  const [heatmapFeature, setHeatmapFeature] = useState("close");

  // Job tracking
  const [activeJobId, setActiveJobId] = useState<string | null>(initialIdentity.jobId ?? null);
  const [updatePhase, setUpdatePhase] = useState<UpdateJobPhase>(initialIdentity.jobId ? "running" : "idle");
  const [statusRefreshKey, setStatusRefreshKey] = useState(0);

  const { getName } = useNameMap();

  // ------------------------------------------------------------------
  // Queries
  // ------------------------------------------------------------------
  const watchlistQuery = useQuery<WatchlistResponse>({
    fetcher: (signal) => releaseApi.getWatchlist(signal),
  });

  // ------------------------------------------------------------------
  // Mutations
  // ------------------------------------------------------------------
  const addMutation = useMutation<AddSymbolsResponse, { symbols: string[]; market: string }>({
    mutateFn: releaseApi.addSymbols,
    onSuccess: () => {
      setAddInput("");
      setAddValidation(null);
      watchlistQuery.refetch();
    },
    onError: (msg) => {
      setAddValidation(msg);
    },
  });

  const removeMutation = useMutation<RemoveSymbolsResponse, { symbols: string[]; market: string }>({
    mutateFn: releaseApi.removeSymbols,
    onSuccess: () => {
      setSelectedSymbols(new Set());
      watchlistQuery.refetch();
    },
  });

  const updateMutation = useMutation<JobSubmitResponse, { full: boolean; market: "us" | "cn" | "hk" }>({
    mutateFn: ({ full, market: selectedMarket }) => releaseApi.submitDataUpdate(full, selectedMarket),
    onSuccess: (data) => {
      const jid = data.job_id;
      if (jid) {
        setActiveJobId(jid);
        setUpdatePhase("running");
        navigate({ pathname: location.pathname, search: releaseSearch({ jobId: jid }, location.search) }, { replace: true });
      } else {
        // No job ID returned — treat as fire-and-forget
        setUpdatePhase("idle");
        watchlistQuery.refetch();
      }
    },
    onError: () => {
      setUpdatePhase("failed");
    },
  });

  // ------------------------------------------------------------------
  // Symbol input validation
  // ------------------------------------------------------------------
  const validateSymbols = useCallback((raw: string): { valid: string[]; error: string | null } => {
    if (!raw.trim()) return { valid: [], error: null };
    const symbols = raw.split(/[,\s\n]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
    if (symbols.length === 0) return { valid: [], error: "No valid symbols entered." };

    // Basic format validation: alphanumeric + optional exchange suffix
    const bad = symbols.filter((s) => !/^[A-Z0-9]+(\.[A-Z]+)?$/.test(s));
    if (bad.length > 0) {
      return { valid: [], error: `Invalid format: ${bad.join(", ")}` };
    }

    // Check for duplicates in current watchlist
    const currentSet = new Set((watchlistQuery.data?.watchlist?.[market] || []).map((e) => e.symbol));
    const dupes = symbols.filter((s) => currentSet.has(s));
    if (dupes.length === symbols.length) {
      return { valid: [], error: `All symbols already in ${market.toUpperCase()} watchlist.` };
    }

    return { valid: symbols, error: null };
  }, [market, watchlistQuery.data]);

  // ------------------------------------------------------------------
  // Handlers
  // ------------------------------------------------------------------
  const handleAddSymbols = () => {
    const { valid, error } = validateSymbols(addInput);
    if (error) {
      setAddValidation(error);
      return;
    }
    if (valid.length === 0) return;
    addMutation.mutate({ symbols: valid, market });
  };

  const handleRemoveSelected = () => {
    if (selectedSymbols.size === 0) return;
    removeMutation.mutate({ symbols: Array.from(selectedSymbols), market });
  };

  const triggerUpdate = (full: boolean) => {
    const type = full ? "FULL RE-INGESTION" : "INCREMENTAL UPDATE";
    if (!window.confirm(`Start ${type}?\nFull re-ingestion will wipe local cache and fetch everything.\nIncremental update only fetches the last 30 days.`)) return;
    setUpdatePhase("submitting");
    updateMutation.mutate({ full, market });
  };

  const handleJobDone = useCallback(async (success: boolean) => {
    setUpdatePhase(success ? "succeeded" : "failed");
    if (success) {
      watchlistQuery.refetch();
      setStatusRefreshKey((value) => value + 1);
      const status = await releaseApi.getDataStatus().catch(() => null);
      navigate({
        pathname: location.pathname,
        search: releaseSearch({ snapshotId: status?.data.latest_snapshot_id }, location.search),
      }, { replace: true });
    }
  }, [location.pathname, location.search, navigate, watchlistQuery]);

  const dismissJob = () => {
    setActiveJobId(null);
    setUpdatePhase("idle");
    navigate({ pathname: location.pathname, search: releaseSearch({ jobId: null }, location.search) }, { replace: true });
  };

  // ------------------------------------------------------------------
  // Heatmap
  // ------------------------------------------------------------------
  const loadHeatmap = useCallback(async () => {
    setHeatmapLoading(true);
    setHeatmapError(null);
    try {
      const json = await releaseApi.getCompleteness(market, heatmapFeature);
      setHeatmapData(json.data as unknown as HeatmapData);
    } catch (e) {
      setHeatmapError(e instanceof Error ? e.message : String(e));
    } finally {
      setHeatmapLoading(false);
    }
  }, [market, heatmapFeature]);

  useEffect(() => {
    if (showHeatmap) loadHeatmap();
  }, [showHeatmap, loadHeatmap]);

  // ------------------------------------------------------------------
  // Derived data
  // ------------------------------------------------------------------
  const watchlistData = watchlistQuery.data?.watchlist || {};
  const currentSymbols: WatchlistEntry[] = watchlistData[market] || [];
  const totalSymbols = Object.values(watchlistData).reduce((sum, arr) => sum + arr.length, 0);

  const toggleSelect = (sym: string) => {
    setSelectedSymbols((prev) => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym);
      else next.add(sym);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedSymbols.size === currentSymbols.length) {
      setSelectedSymbols(new Set());
    } else {
      setSelectedSymbols(new Set(currentSymbols.map((s) => s.symbol)));
    }
  };

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div className="space-y-6 max-w-[1400px] mx-auto pb-16">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-3 border-b pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Data Management</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Manage watchlist symbols and update market data.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            onClick={() => triggerUpdate(false)}
            disabled={updatePhase === "submitting" || updatePhase === "running"}
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 text-xs"
          >
            <Activity className="h-3.5 w-3.5" />
            Incremental
          </Button>
          <Button
            onClick={() => triggerUpdate(true)}
            disabled={updatePhase === "submitting" || updatePhase === "running"}
            size="sm"
            className="h-8 gap-1.5 text-xs"
          >
            {updatePhase === "submitting" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            Full Ingest
          </Button>
        </div>
      </div>

      {/* Update mutation error */}
      {updateMutation.error && updatePhase === "failed" && !activeJobId && (
        <ErrorState
          message={`Update failed: ${updateMutation.error}`}
          onRetry={() => {
            updateMutation.reset();
            setUpdatePhase("idle");
          }}
        />
      )}

      {/* Job Progress Panel */}
      {activeJobId && (
        <JobProgressPanel jobId={activeJobId} onDone={handleJobDone} />
      )}

      {/* Post-job banners */}
      {updatePhase === "succeeded" && !activeJobId && (
        <div className="flex items-center gap-3 rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm">
          <CheckCircle2 className="h-4 w-4 text-green-600 flex-shrink-0" />
          <span className="flex-1">Data update completed successfully.</span>
          <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={dismissJob}>
            Dismiss
          </Button>
        </div>
      )}

      {/* Data Freshness Status */}
      <DataStatusCard refreshKey={statusRefreshKey} />

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {(["us", "cn", "hk"] as const).map((m) => (
          <div
            key={m}
            role="button"
            tabIndex={0}
            aria-label={`Select ${m.toUpperCase()} market`}
            aria-pressed={market === m}
            className={cn(
              "p-3 rounded-lg border cursor-pointer transition-all",
              market === m ? "border-primary bg-primary/5 shadow-sm" : "border-border hover:border-primary/50",
            )}
            onClick={() => {
              setMarket(m);
              setSelectedSymbols(new Set());
              setAddValidation(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setMarket(m);
                setSelectedSymbols(new Set());
                setAddValidation(null);
              }
            }}
          >
            <div className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">{m} Market</div>
            <div className="text-2xl font-black mt-1">{(watchlistData[m] || []).length}</div>
            <div className="text-[10px] text-muted-foreground">symbols</div>
          </div>
        ))}
        <div className="p-3 rounded-lg border border-border">
          <div className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">Total</div>
          <div className="text-2xl font-black mt-1">{totalSymbols}</div>
          <div className="text-[10px] text-muted-foreground">across all markets</div>
        </div>
      </div>

      {/* Add Symbols */}
      <Card>
        <CardHeader className="py-3 border-b">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Plus className="h-4 w-4" /> Add Symbols to {market.toUpperCase()}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-4">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                placeholder="Enter symbols (comma or space separated): 688521, 600487, 002222.SZ"
                className="w-full bg-transparent border rounded-lg pl-10 pr-4 py-2 text-sm focus:ring-1 focus:ring-primary outline-none font-mono"
                value={addInput}
                onChange={(e) => {
                  setAddInput(e.target.value.toUpperCase());
                  setAddValidation(null);
                }}
                onKeyDown={(e) => e.key === "Enter" && handleAddSymbols()}
              />
            </div>
            <Button onClick={handleAddSymbols} disabled={addMutation.loading || !addInput.trim()} size="sm" className="h-10 px-4 gap-1.5">
              {addMutation.loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
              Add
            </Button>
          </div>
          {addValidation && (
            <p className="text-xs text-destructive mt-2">{addValidation}</p>
          )}
          {addMutation.error && !addValidation && (
            <p className="text-xs text-destructive mt-2">{addMutation.error}</p>
          )}
          <p className="text-[10px] text-muted-foreground mt-2">
            Supports formats: <span className="font-mono">688521</span>, <span className="font-mono">688521.SH</span>, <span className="font-mono">002222.SZ</span>. Exchange suffix is auto-stripped.
          </p>
        </CardContent>
      </Card>

      {/* Symbol Table */}
      <Card>
        <CardHeader className="py-3 border-b">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Database className="h-4 w-4" />
              {market.toUpperCase()} Watchlist ({currentSymbols.length} symbols)
            </CardTitle>
            <div className="flex items-center gap-2">
              {selectedSymbols.size > 0 && (
                <Button
                  onClick={handleRemoveSelected}
                  disabled={removeMutation.loading}
                  variant="destructive"
                  size="sm"
                  className="h-7 text-xs gap-1"
                >
                  {removeMutation.loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                  Remove ({selectedSymbols.size})
                </Button>
              )}
              <Button onClick={() => watchlistQuery.refetch()} disabled={watchlistQuery.loading} variant="ghost" size="sm" className="h-7 text-xs gap-1">
                <RefreshCw className={cn("h-3 w-3", watchlistQuery.loading && "animate-spin")} />
                Refresh
              </Button>
            </div>
          </div>
          {removeMutation.error && (
            <p className="text-xs text-destructive mt-2">Remove failed: {removeMutation.error}</p>
          )}
        </CardHeader>
        <CardContent className="p-0">
          {watchlistQuery.loading && !watchlistQuery.data ? (
            <LoadingSpinner message="Loading watchlist..." />
          ) : watchlistQuery.error ? (
            <ErrorState message={watchlistQuery.error} onRetry={() => watchlistQuery.refetch()} />
          ) : currentSymbols.length === 0 ? (
            <EmptyState
              message={`No symbols in ${market.toUpperCase()} watchlist`}
              description="Add symbols above to get started."
            />
          ) : (
            <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-card z-10">
                  <tr className="border-b bg-muted/30">
                    <th className="text-center py-2 px-3 w-10">
                      <input
                        type="checkbox"
                        aria-label="Select all symbols"
                        checked={selectedSymbols.size === currentSymbols.length && currentSymbols.length > 0}
                        onChange={toggleSelectAll}
                        className="rounded"
                      />
                    </th>
                    <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">#</th>
                    <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Symbol</th>
                    <th className="text-left py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Name</th>
                    <th className="text-center py-2 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Market</th>
                  </tr>
                </thead>
                <tbody>
                  {currentSymbols.map((entry, idx) => {
                    const isSelected = selectedSymbols.has(entry.symbol);
                    const displayName = entry.name || getName(entry.symbol);
                    return (
                      <tr
                        key={entry.symbol}
                        className={cn(
                          "border-b border-dashed transition-colors cursor-pointer",
                          isSelected ? "bg-primary/5" : "hover:bg-muted/5",
                        )}
                        onClick={() => toggleSelect(entry.symbol)}
                      >
                        <td className="text-center py-2 px-3">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelect(entry.symbol)}
                            onClick={(e) => e.stopPropagation()}
                            className="rounded"
                          />
                        </td>
                        <td className="py-2 px-3 text-[10px] text-muted-foreground font-mono">{idx + 1}</td>
                        <td className="py-2 px-3 font-bold font-mono text-xs">{entry.symbol}</td>
                        <td className="py-2 px-3 text-xs text-muted-foreground">
                          {displayName !== entry.symbol ? displayName : <span className="italic">—</span>}
                        </td>
                        <td className="py-2 px-3 text-center">
                          <Badge variant="outline" className="text-[9px] uppercase">{market}</Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Heatmap (collapsible) */}
      <Card>
        <CardHeader
          className="py-3 border-b cursor-pointer"
          role="button"
          tabIndex={0}
          aria-expanded={showHeatmap}
          aria-label={showHeatmap ? "Collapse data completeness heatmap" : "Expand data completeness heatmap"}
          onClick={() => setShowHeatmap(!showHeatmap)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setShowHeatmap(!showHeatmap); } }}
        >
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Table className="h-4 w-4" />
              Data Completeness Heatmap
              <span className="text-[10px] font-normal text-muted-foreground">(optional)</span>
            </CardTitle>
            <div className="flex items-center gap-2">
              {showHeatmap && (
                <select
                  value={heatmapFeature}
                  onChange={(e) => { e.stopPropagation(); setHeatmapFeature(e.target.value); }}
                  onClick={(e) => e.stopPropagation()}
                  className="h-7 rounded border border-input bg-transparent px-2 text-xs font-mono"
                >
                  {["close", "open", "high", "low", "volume", "amount", "vwap"].map((f) => (
                    <option key={f} value={f}>{f}</option>
                  ))}
                </select>
              )}
              {showHeatmap ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
            </div>
          </div>
        </CardHeader>
        {showHeatmap && (
          <CardContent className="p-0" style={{ height: 400 }}>
            {heatmapLoading ? (
              <LoadingSpinner message="Loading completeness data..." />
            ) : heatmapError ? (
              <ErrorState message={heatmapError} onRetry={loadHeatmap} />
            ) : heatmapData && heatmapData.symbols.length > 0 ? (
              <div className="h-full overflow-auto p-4">
                <div className="text-xs text-muted-foreground mb-2">
                  {heatmapData.symbols.length} symbols x {heatmapData.dates.length} days
                  {heatmapFeature === "close" && (
                    <span className="ml-2">
                      <span className="inline-block w-2 h-2 rounded-sm bg-green-500 mr-0.5 align-middle" /> Data
                      <span className="inline-block w-2 h-2 rounded-sm bg-red-900/50 ml-2 mr-0.5 align-middle" /> Missing
                    </span>
                  )}
                </div>
                {/* Simple text-based table instead of complex heatmap */}
                <div className="overflow-x-auto">
                  <table className="text-[9px] font-mono border-collapse">
                    <thead>
                      <tr>
                        <th className="text-left pr-2 py-0.5 sticky left-0 bg-card">Symbol</th>
                        {heatmapData.dates.slice(-30).map((d) => (
                          <th key={d} className="px-0.5 py-0.5 text-center min-w-[12px]">
                            {d.slice(5)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {heatmapData.symbols.slice(0, 50).map((sym, i) => {
                        const row = heatmapData.values[i] || [];
                        return (
                          <tr key={sym}>
                            <td className="text-left pr-2 py-0.5 sticky left-0 bg-card font-bold">{sym}</td>
                            {row.slice(-30).map((v, j) => (
                              <td
                                key={j}
                                className={cn(
                                  "px-0.5 py-0.5 text-center min-w-[12px]",
                                  v !== null && v !== undefined ? "bg-green-500/30" : "bg-red-900/20",
                                )}
                                title={`${heatmapData.dates[heatmapData.dates.length - 30 + j] || ""}: ${v ?? "missing"}`}
                              >
                                {v !== null && v !== undefined ? "." : ""}
                              </td>
                            ))}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {heatmapData.symbols.length > 50 && (
                    <div className="text-[10px] text-muted-foreground mt-2">
                      Showing 50 of {heatmapData.symbols.length} symbols. Scroll to see more.
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <EmptyState
                message="No completeness data"
                description="Run a data update first to populate the heatmap."
              />
            )}
          </CardContent>
        )}
      </Card>
    </div>
  );
}
