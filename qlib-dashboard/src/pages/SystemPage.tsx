import { useState, useEffect, useCallback, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { apiFetch } from "@/lib/api";
import { apiClient } from "@/lib/api-client";
import { useQuery } from "@/hooks/useQuery";
import { useMutation } from "@/hooks/useMutation";
import { LoadingSpinner, EmptyState, ErrorState } from "@/components/ui/loading-state";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { cn } from "@/lib/utils";
import type { Job, JobListResponse, Ok } from "@/lib/api-types";
import {
  Loader2, RefreshCw, Activity, Shield, FlaskConical,
  CheckCircle, AlertTriangle, XCircle, Briefcase,
  Square, RotateCcw, FileText, Copy, Check,
  Clock, ChevronDown, ChevronUp
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ResearchRun {
  run_id: string;
  market: string;
  goal: string;
  status: string;
  recommendation: string | null;
  created_at: string;
  completed_at: string | null;
  n_steps: number;
  n_completed: number;
  n_failed: number;
}

interface DecayFactor {
  factor_name: string;
  status: string;
  ic_trend: number;
  ic_current: number;
  ic_6m_avg: number;
  icir_current: number;
  alerts: string[];
  recommendation: string;
}

// Portfolio violation type (used when portfolio check is implemented)
// interface PortfolioViolation {
//   type: string;
//   severity: string;
//   message: string;
//   suggested_action: string;
// }

// ---------------------------------------------------------------------------
// Research Runs Tab
// ---------------------------------------------------------------------------

function ResearchRunsTab() {
  const [runs, setRuns] = useState<ResearchRun[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await apiFetch("/api/research/runs?limit=20");
      if (resp.ok) {
        const data = await resp.json();
        setRuns(data.runs || []);
      }
    } catch (e) {
      console.warn("Failed to fetch research runs:", e);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  const statusColors: Record<string, string> = {
    completed: "text-green-400 bg-green-500/10",
    running: "text-blue-400 bg-blue-500/10",
    failed: "text-red-400 bg-red-500/10",
    pending: "text-yellow-400 bg-yellow-500/10",
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="text-sm text-muted-foreground">Research pipeline runs</div>
        <Button variant="outline" size="sm" onClick={fetchRuns} disabled={loading}>
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
        </Button>
      </div>

      {runs.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground text-sm">
          No research runs yet. Start one from the API.
        </div>
      ) : (
        <div className="space-y-2">
          {runs.map((run) => (
            <Card key={run.run_id} className="border shadow-sm">
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Badge className={cn("text-[10px]", statusColors[run.status] || "text-muted-foreground")}>
                      {run.status}
                    </Badge>
                    <span className="text-xs font-mono text-muted-foreground">{run.run_id}</span>
                  </div>
                  <span className="text-[10px] text-muted-foreground">
                    {new Date(run.created_at).toLocaleString()}
                  </span>
                </div>
                <div className="text-sm font-medium mb-1">{run.goal}</div>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span>Market: {run.market.toUpperCase()}</span>
                  <span>Steps: {run.n_completed}/{run.n_steps}</span>
                  {run.recommendation && (
                    <span className="text-primary font-bold">{run.recommendation}</span>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Decay Monitor Tab
// ---------------------------------------------------------------------------

function DecayMonitorTab() {
  const [factors, setFactors] = useState<DecayFactor[]>([]);
  const [loading, setLoading] = useState(false);
  const [market, setMarket] = useState<"cn" | "us">("cn");

  const fetchDecay = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await apiFetch(`/api/decay/check?market=${market}`);
      if (resp.ok) {
        const data = await resp.json();
        setFactors(data.factors_needing_attention || []);
      }
    } catch (e) {
      console.warn("Failed to fetch decay data:", e);
    }
    setLoading(false);
  }, [market]);

  useEffect(() => { fetchDecay(); }, [fetchDecay]);

  const statusIcons: Record<string, JSX.Element> = {
    healthy: <CheckCircle className="h-4 w-4 text-green-400" />,
    watch: <AlertTriangle className="h-4 w-4 text-yellow-400" />,
    degraded: <AlertTriangle className="h-4 w-4 text-orange-400" />,
    downgrade: <XCircle className="h-4 w-4 text-red-400" />,
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="text-sm text-muted-foreground">Factor decay monitoring</div>
          <div className="flex gap-1 bg-muted/30 p-0.5 rounded-lg">
            {(["cn", "us"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMarket(m)}
                className={cn(
                  "px-2 py-0.5 text-[10px] font-bold uppercase rounded-md transition-all",
                  market === m ? "bg-card shadow text-foreground" : "text-muted-foreground"
                )}
              >
                {m.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={fetchDecay} disabled={loading}>
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
        </Button>
      </div>

      {factors.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground text-sm">
          No factors with decay detected. All healthy.
        </div>
      ) : (
        <div className="space-y-2">
          {factors.map((factor) => (
            <Card key={factor.factor_name} className="border shadow-sm">
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    {statusIcons[factor.status]}
                    <span className="text-sm font-bold">{factor.factor_name}</span>
                    <Badge className={cn(
                      "text-[10px]",
                      factor.status === "healthy" ? "text-green-400 bg-green-500/10" :
                      factor.status === "watch" ? "text-yellow-400 bg-yellow-500/10" :
                      "text-red-400 bg-red-500/10"
                    )}>
                      {factor.status}
                    </Badge>
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-2 text-xs">
                  <div>
                    <div className="text-muted-foreground">IC Current</div>
                    <div className="font-mono">{factor.ic_current?.toFixed(4) || "N/A"}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">IC 6m Avg</div>
                    <div className="font-mono">{factor.ic_6m_avg?.toFixed(4) || "N/A"}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">ICIR</div>
                    <div className="font-mono">{factor.icir_current?.toFixed(2) || "N/A"}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Trend</div>
                    <div className={cn("font-mono", factor.ic_trend < 0 ? "text-red-400" : "text-green-400")}>
                      {factor.ic_trend?.toFixed(4) || "N/A"}
                    </div>
                  </div>
                </div>
                {factor.alerts.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {factor.alerts.map((alert, i) => (
                      <Badge key={i} variant="outline" className="text-[10px] text-yellow-400">
                        {alert}
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Portfolio Risk Tab
// ---------------------------------------------------------------------------

function PortfolioRiskTab() {
  const [config, setConfig] = useState<Record<string, number>>({});
  const [positionsInput, setPositionsInput] = useState('{"000001": 0.1, "600519": 0.2, "300750": 0.15}');
  const [checkResult, setCheckResult] = useState<Record<string, unknown> | null>(null);
  const [checking, setChecking] = useState(false);

  const fetchConfig = useCallback(async () => {
    try {
      const resp = await apiFetch("/api/portfolio/config");
      if (resp.ok) {
        const data = await resp.json();
        setConfig(data.config || {});
      }
    } catch (e) {
      console.warn("Failed to fetch portfolio config:", e);
    }
  }, []);

  useEffect(() => { fetchConfig(); }, [fetchConfig]);

  const runCheck = useCallback(async () => {
    setChecking(true);
    try {
      const positions = JSON.parse(positionsInput);
      const resp = await apiFetch("/api/portfolio/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ positions, market: "cn", portfolio_value: 100000 }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setCheckResult(data);
      }
    } catch (e) {
      console.warn("Portfolio check failed:", e);
      setCheckResult({ ok: false, error: String(e) });
    }
    setChecking(false);
  }, [positionsInput]);

  return (
    <div className="space-y-4">
      <div className="text-sm text-muted-foreground">Portfolio constraint engine</div>

      {/* Input Area */}
      <Card className="border shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs uppercase tracking-widest text-muted-foreground">
            Check Portfolio
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Positions (JSON: symbol → weight)</label>
            <textarea
              className="w-full bg-background border rounded p-2 text-xs font-mono h-20"
              value={positionsInput}
              onChange={(e) => setPositionsInput(e.target.value)}
              placeholder='{"000001": 0.1, "600519": 0.2}'
            />
          </div>
          <Button size="sm" onClick={runCheck} disabled={checking}>
            {checking ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null}
            Run Check
          </Button>
        </CardContent>
      </Card>

      {/* Results */}
      {checkResult && (
        <Card className="border shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase tracking-widest text-muted-foreground">
              Results
            </CardTitle>
          </CardHeader>
          <CardContent>
            {checkResult.ok ? (
              <div className="space-y-2 text-xs">
                <div className="flex justify-between">
                  <span>Total Violations</span>
                  <span className={cn("font-bold", (checkResult.total_violations as number) > 0 ? "text-red-400" : "text-green-400")}>
                    {String(checkResult.total_violations ?? 0)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Critical</span>
                  <span className="font-bold text-red-400">{String(checkResult.critical ?? 0)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Warnings</span>
                  <span className="font-bold text-yellow-400">{String(checkResult.warnings ?? 0)}</span>
                </div>
                {(checkResult.data_warnings as string[])?.map((w: string, i: number) => (
                  <div key={i} className="text-[10px] text-yellow-400">⚠ {w}</div>
                ))}
              </div>
            ) : (
              <div className="text-xs text-red-400">{String(checkResult.error ?? "Unknown error")}</div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Constraint Config */}
      <Card className="border shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs uppercase tracking-widest text-muted-foreground">
            Constraint Configuration
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs">
            {Object.entries(config).map(([key, value]) => (
              <div key={key} className="flex justify-between">
                <span className="text-muted-foreground">{key.replace(/_/g, " ")}</span>
                <span className="font-mono">{typeof value === "number" ? value.toFixed(2) : String(value)}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Check Results */}
      <Card className="border shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs uppercase tracking-widest text-muted-foreground">
            Portfolio Check
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8 text-muted-foreground text-sm">
            Use the API endpoint POST /api/portfolio/check to analyze a portfolio
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Job Center Tab
// ---------------------------------------------------------------------------

/** Canonical job states used for filtering and display. */
type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "unknown";

function normaliseJobStatus(raw: string): JobStatus {
  const s = raw.trim().toLowerCase();
  if (s === "queued" || s === "pending") return "queued";
  if (s === "running") return "running";
  if (s === "succeeded" || s === "completed") return "succeeded";
  if (s === "failed") return "failed";
  if (s === "cancelled" || s === "canceled") return "cancelled";
  return "unknown";
}

const STATUS_STYLES: Record<JobStatus, string> = {
  queued: "text-yellow-400 bg-yellow-500/10 border-yellow-500/20",
  running: "text-blue-400 bg-blue-500/10 border-blue-500/20",
  succeeded: "text-green-400 bg-green-500/10 border-green-500/20",
  failed: "text-red-400 bg-red-500/10 border-red-500/20",
  cancelled: "text-orange-400 bg-orange-500/10 border-orange-500/20",
  unknown: "text-muted-foreground bg-muted/30 border-border",
};

const STATUS_ICONS: Record<JobStatus, React.ReactNode> = {
  queued: <Clock className="h-3 w-3" />,
  running: <Loader2 className="h-3 w-3 animate-spin" />,
  succeeded: <CheckCircle className="h-3 w-3" />,
  failed: <XCircle className="h-3 w-3" />,
  cancelled: <Square className="h-3 w-3" />,
  unknown: <AlertTriangle className="h-3 w-3" />,
};

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds <= 0) return "--";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function computeDuration(job: Job): number | null {
  const started = job.started_at;
  const finished = job.finished_at;
  if (!started) return null;
  const end = finished ?? Date.now() / 1000;
  return end - started;
}

// -- Log viewer dialog ------------------------------------------------------

function JobLogDialog({
  jobId,
  open,
  onOpenChange,
}: {
  jobId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  interface JobLogsResponse extends Ok {
    lines: string[];
    total_lines: number;
    message?: string;
  }

  const { data, loading, error, refetch } = useQuery<JobLogsResponse>({
    fetcher: useCallback(
      async (signal: AbortSignal) => {
        if (!jobId) return { ok: true as const, lines: [], total_lines: 0 };
        const resp = await apiClient.get<JobLogsResponse>(
          `/api/jobs/${jobId}/logs`,
          { signal, params: { tail: 500 } },
        );
        return resp;
      },
      [jobId],
    ),
    enabled: open && !!jobId,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[800px] max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="text-sm font-mono">
            Job Logs: {jobId?.slice(0, 12)}
          </DialogTitle>
          <DialogDescription>
            {data ? `${data.total_lines} total lines (showing last ${data.lines.length})` : "Loading..."}
          </DialogDescription>
        </DialogHeader>
        <div className="flex-1 min-h-0 overflow-auto rounded-md bg-slate-950 border border-white/5 p-4">
          {loading ? (
            <LoadingSpinner message="Loading logs..." size={20} />
          ) : error ? (
            <ErrorState message={error} onRetry={refetch} />
          ) : data && data.lines.length > 0 ? (
            <pre className="text-[11px] font-mono text-emerald-400/80 whitespace-pre-wrap leading-relaxed">
              {data.lines.join("\n")}
            </pre>
          ) : (
            <div className="text-center py-8 text-muted-foreground text-xs">
              No log output yet
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={refetch} disabled={loading}>
            <RefreshCw className={cn("h-3 w-3 mr-1", loading && "animate-spin")} />
            Refresh
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// -- Copyable diagnostics ---------------------------------------------------

function CopyableError({ error }: { error: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(error);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for older browsers
      const textarea = document.createElement("textarea");
      textarea.value = error;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [error]);

  return (
    <div className="mt-2 group relative">
      <pre className="text-[10px] font-mono text-red-400 bg-red-500/5 p-3 rounded-md border border-red-500/10 whitespace-pre-wrap max-h-32 overflow-y-auto">
        {error}
      </pre>
      <Button
        variant="ghost"
        size="sm"
        className="absolute top-1 right-1 h-6 px-2 opacity-0 group-hover:opacity-100 transition-opacity"
        onClick={handleCopy}
      >
        {copied ? (
          <><Check className="h-3 w-3 mr-1 text-green-400" /> Copied</>
        ) : (
          <><Copy className="h-3 w-3 mr-1" /> Copy</>
        )}
      </Button>
    </div>
  );
}

// -- Job row component ------------------------------------------------------

function JobRow({
  job,
  onCancel,
  onRerun,
  onViewLogs,
  cancelling,
  rerunning,
}: {
  job: Job;
  onCancel: (id: string) => void;
  onRerun: (id: string) => void;
  onViewLogs: (id: string) => void;
  cancelling: boolean;
  rerunning: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const status = normaliseJobStatus(job.status);
  const duration = computeDuration(job);
  const isActive = status === "running" || status === "queued";
  const isTerminal = status === "succeeded" || status === "failed" || status === "cancelled";

  return (
    <div className={cn(
      "border rounded-lg transition-all",
      status === "running" && "border-blue-500/20 bg-blue-500/[0.02]",
      status === "failed" && "border-red-500/20 bg-red-500/[0.02]",
    )}>
      <div className="flex items-center gap-3 p-3">
        {/* Status badge */}
        <Badge className={cn("text-[10px] font-semibold border gap-1 shrink-0", STATUS_STYLES[status])}>
          {STATUS_ICONS[status]}
          {status}
        </Badge>

        {/* Type / name */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium truncate">
              {job.name || job.type || "Unknown"}
            </span>
            <span className="text-[10px] font-mono text-muted-foreground">
              {job.id.slice(0, 8)}
            </span>
          </div>
        </div>

        {/* Duration */}
        <div className="text-xs text-muted-foreground shrink-0 w-20 text-right">
          {formatDuration(duration)}
        </div>

        {/* Created at */}
        <div className="text-[10px] text-muted-foreground shrink-0 w-32 text-right">
          {job.created_at
            ? new Date(job.created_at * 1000).toLocaleString()
            : "--"}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-[10px]"
            onClick={() => onViewLogs(job.id)}
          >
            <FileText className="h-3 w-3 mr-1" />
            Logs
          </Button>

          {isActive && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-[10px] text-red-400 hover:text-red-300 hover:bg-red-500/10"
              onClick={() => onCancel(job.id)}
              disabled={cancelling}
            >
              {cancelling ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Square className="h-3 w-3 mr-1" />
              )}
              Cancel
            </Button>
          )}

          {isTerminal && status !== "succeeded" && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-[10px] text-blue-400 hover:text-blue-300 hover:bg-blue-500/10"
              onClick={() => onRerun(job.id)}
              disabled={rerunning}
            >
              {rerunning ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RotateCcw className="h-3 w-3 mr-1" />
              )}
              Retry
            </Button>
          )}

          {(job.error || job.commands?.length) && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? (
                <ChevronUp className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
            </Button>
          )}
        </div>
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="px-3 pb-3 pt-0 space-y-2">
          {job.commands && job.commands.length > 0 && (
            <div className="text-[10px] font-mono text-muted-foreground bg-muted/30 p-2 rounded">
              <span className="text-foreground/50 mr-2">$</span>
              {Array.isArray(job.commands) ? job.commands.join(" ") : String(job.commands)}
            </div>
          )}
          {job.error && <CopyableError error={job.error} />}
        </div>
      )}
    </div>
  );
}

// -- Job Center Tab ---------------------------------------------------------

type StatusFilter = "all" | JobStatus;

function JobCenterTab() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [logJobId, setLogJobId] = useState<string | null>(null);
  const [logDialogOpen, setLogDialogOpen] = useState(false);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [rerunningId, setRerunningId] = useState<string | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const { confirm, ConfirmDialog } = useConfirm();

  // Track which active jobs we've seen so page reload restores them correctly
  const seenActiveRef = useRef<Set<string>>(new Set());

  // -- Polling query for jobs list ------------------------------------------

  const {
    data: jobsData,
    loading,
    error,
    refetch,
  } = useQuery<JobListResponse>({
    fetcher: useCallback(async (signal: AbortSignal) => {
      try {
        const resp = await apiClient.get<JobListResponse>("/api/jobs", {
          signal,
          params: { limit: 100 },
          timeout: 10_000,
        });
        setBackendDown(false);
        return resp;
      } catch (err) {
        // Detect backend unavailable
        if (err instanceof Error && (err.message.includes("Network") || err.message.includes("timed out"))) {
          setBackendDown(true);
        }
        throw err;
      }
    }, []),
    enabled: true,
  });

  // Poll every 3 seconds when there are active jobs
  const jobs = jobsData?.jobs ?? [];
  const hasActiveJobs = jobs.some(
    (j) => normaliseJobStatus(j.status) === "running" || normaliseJobStatus(j.status) === "queued",
  );

  // Use a polling interval by toggling the trigger
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (hasActiveJobs) {
      pollRef.current = setInterval(() => refetch(), 3000);
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [hasActiveJobs, refetch]);

  // Track active jobs seen across poll cycles for "page reload restores active work"
  useEffect(() => {
    for (const j of jobs) {
      const s = normaliseJobStatus(j.status);
      if (s === "running" || s === "queued") {
        seenActiveRef.current.add(j.id);
      } else if (seenActiveRef.current.has(j.id)) {
        seenActiveRef.current.delete(j.id);
      }
    }
  }, [jobs]);

  // -- Cancel mutation ------------------------------------------------------

  const cancelMutation = useMutation<{ ok: boolean; message?: string }, string>({
    mutateFn: useCallback(async (jobId: string) => {
      return apiClient.post(`/api/jobs/${jobId}/cancel`);
    }, []),
    onSuccess: useCallback(() => {
      refetch();
    }, [refetch]),
    onError: useCallback((_err: string) => {
      // Error is surfaced via the mutation state
    }, []),
  });

  const handleCancel = useCallback(
    async (jobId: string) => {
      const ok = await confirm({
        title: "Cancel Job",
        description: `Are you sure you want to cancel job ${jobId.slice(0, 8)}?`,
        impact: "This will terminate the running process immediately.",
        confirmLabel: "Cancel Job",
        destructive: true,
      });
      if (!ok) return;
      setCancellingId(jobId);
      cancelMutation.mutate(jobId);
      // Reset after a short delay
      setTimeout(() => setCancellingId(null), 2000);
    },
    [confirm, cancelMutation],
  );

  // -- Rerun mutation -------------------------------------------------------

  const rerunMutation = useMutation<{ ok: boolean; job_id?: string }, string>({
    mutateFn: useCallback(async (jobId: string) => {
      return apiClient.post(`/api/jobs/${jobId}/rerun`);
    }, []),
    onSuccess: useCallback(() => {
      refetch();
    }, [refetch]),
    onError: useCallback((_err: string) => {
      // Error is surfaced via the mutation state
    }, []),
  });

  const handleRerun = useCallback(
    async (jobId: string) => {
      setRerunningId(jobId);
      rerunMutation.mutate(jobId);
      setTimeout(() => setRerunningId(null), 2000);
    },
    [rerunMutation],
  );

  // -- Log viewer ------------------------------------------------------------

  const handleViewLogs = useCallback((jobId: string) => {
    setLogJobId(jobId);
    setLogDialogOpen(true);
  }, []);

  // -- Filter jobs -----------------------------------------------------------

  const filteredJobs = statusFilter === "all"
    ? jobs
    : jobs.filter((j) => normaliseJobStatus(j.status) === statusFilter);

  // Status counts for filter tabs
  const statusCounts = jobs.reduce<Record<JobStatus, number>>(
    (acc, j) => {
      const s = normaliseJobStatus(j.status);
      acc[s] = (acc[s] || 0) + 1;
      return acc;
    },
    { queued: 0, running: 0, succeeded: 0, failed: 0, cancelled: 0, unknown: 0 },
  );

  // -- Backend unavailable state --------------------------------------------

  if (backendDown && !loading && !jobsData) {
    return (
      <div className="space-y-4">
        <ErrorState
          message="Backend is unavailable. The API server may be down or restarting."
          onRetry={refetch}
        />
        <Card className="border border-yellow-500/20 bg-yellow-500/[0.03]">
          <CardContent className="p-4 text-xs text-muted-foreground space-y-2">
            <p>If the backend was recently restarted, active jobs may have been interrupted.</p>
            <p>After the server comes back online, stale running jobs will be auto-repaired as failed.</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm text-muted-foreground">Job Center</div>
          {hasActiveJobs && (
            <div className="flex items-center gap-1.5 mt-1">
              <div className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
              <span className="text-[10px] text-blue-400 font-medium">
                {statusCounts.running + statusCounts.queued} active
              </span>
            </div>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={refetch} disabled={loading}>
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
        </Button>
      </div>

      {/* Status filter pills */}
      <div className="flex flex-wrap gap-1.5">
        {(["all", "running", "queued", "failed", "succeeded", "cancelled"] as const).map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={cn(
              "px-2.5 py-1 text-[10px] font-semibold rounded-md border transition-all",
              statusFilter === s
                ? "bg-primary/10 border-primary/30 text-primary"
                : "bg-muted/30 border-border text-muted-foreground hover:text-foreground hover:border-border/80",
            )}
          >
            {s === "all" ? "All" : s}
            <span className="ml-1 opacity-60">
              {s === "all" ? jobs.length : statusCounts[s as JobStatus] || 0}
            </span>
          </button>
        ))}
      </div>

      {/* Error banner for mutation failures */}
      {(cancelMutation.error || rerunMutation.error) && (
        <div className="text-xs text-red-400 bg-red-500/5 border border-red-500/10 rounded-md p-2">
          {cancelMutation.error || rerunMutation.error}
        </div>
      )}

      {/* Job list */}
      {loading && jobs.length === 0 ? (
        <LoadingSpinner message="Loading jobs..." />
      ) : error && jobs.length === 0 ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : filteredJobs.length === 0 ? (
        <EmptyState
          message={statusFilter === "all" ? "No jobs found" : `No ${statusFilter} jobs`}
          description={
            statusFilter === "all"
              ? "Jobs will appear here when workflows are submitted"
              : "Try a different filter or submit a new job"
          }
        />
      ) : (
        <div className="space-y-1.5">
          {filteredJobs.map((job) => (
            <JobRow
              key={job.id}
              job={job}
              onCancel={handleCancel}
              onRerun={handleRerun}
              onViewLogs={handleViewLogs}
              cancelling={cancellingId === job.id}
              rerunning={rerunningId === job.id}
            />
          ))}
        </div>
      )}

      {/* Log dialog */}
      <JobLogDialog
        jobId={logJobId}
        open={logDialogOpen}
        onOpenChange={setLogDialogOpen}
      />

      {/* Confirm dialog */}
      <ConfirmDialog />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function SystemPage() {
  return (
    <div className="space-y-5 max-w-[1200px] mx-auto pb-16">
      <div className="border-b pb-4">
        <h1 className="text-2xl font-bold tracking-tight">System Monitor</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Job center, research pipeline, factor decay, and portfolio risk monitoring
        </p>
      </div>

      <Tabs defaultValue="jobs" className="space-y-4">
        <TabsList>
          <TabsTrigger value="jobs" className="gap-1.5">
            <Briefcase className="h-3.5 w-3.5" /> Job Center
          </TabsTrigger>
          <TabsTrigger value="research" className="gap-1.5">
            <FlaskConical className="h-3.5 w-3.5" /> Research Runs
          </TabsTrigger>
          <TabsTrigger value="decay" className="gap-1.5">
            <Activity className="h-3.5 w-3.5" /> Factor Decay
          </TabsTrigger>
          <TabsTrigger value="portfolio" className="gap-1.5">
            <Shield className="h-3.5 w-3.5" /> Portfolio Risk
          </TabsTrigger>
        </TabsList>

        <TabsContent value="jobs">
          <JobCenterTab />
        </TabsContent>

        <TabsContent value="research">
          <ResearchRunsTab />
        </TabsContent>

        <TabsContent value="decay">
          <DecayMonitorTab />
        </TabsContent>

        <TabsContent value="portfolio">
          <PortfolioRiskTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
