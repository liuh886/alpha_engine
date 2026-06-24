import { useEffect, useRef, useState, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Play, Loader2, CheckCircle2, XCircle, Terminal, Sparkles, BarChart3, ExternalLink, Layers } from "lucide-react";
import { cn } from "@/lib/utils";
import { OverviewCards } from "@/components/OverviewCards";
import { PerformanceCharts } from "@/components/PerformanceCharts";
import { PositionsTable } from "@/components/PositionsTable";
import { Placeholder } from "@/components/Placeholder";
import { parseQlibData, ModelData } from "@/lib/data-parser";
import { formatPct } from "@/lib/format";
import { useGlobalStore } from "@/store/globalStore";
import { useNameMap } from "@/lib/useNameMap";
import { useQuery } from "@/hooks/useQuery";
import { useMutation } from "@/hooks/useMutation";
import { releaseApi } from "@/lib/release-api";
import {
  parseReleaseIdentity,
  releaseSearch,
  resolveEvidenceIdentity,
  resolveWorkflowResult,
  type ReleaseOutcome as ReleaseOutcomeState,
} from "@/lib/release-workflow";
import { ReleaseOutcome } from "@/components/ReleaseOutcome";
import type { WorkflowStatusEntry } from "@/lib/api-types";

type WorkflowStatus = "idle" | "running" | "succeeded" | "failed";

const SESSION_KEY = "alpha_engine_active_workflow";

interface PersistedWorkflow {
  workflowId: string;
  snapshotId: string;
  market: string;
  modelType: string;
  tag: string;
  startedAt: number;
}

function saveWorkflowState(state: PersistedWorkflow | null) {
  if (state) {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(state));
  } else {
    sessionStorage.removeItem(SESSION_KEY);
  }
}

function loadWorkflowState(): PersistedWorkflow | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PersistedWorkflow;
  } catch {
    return null;
  }
}

export function BacktestPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const routeIdentity = parseReleaseIdentity(location.search);
  const persistedWorkflow = loadWorkflowState();

  // --- Form state ---
  const [market, setMarket] = useState("us");
  const [modelType, setModelType] = useState("lgbm");
  const [tag, setTag] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  // --- Job state ---
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus>(routeIdentity.workflowId || persistedWorkflow ? "running" : "idle");
  const [workflowId, setWorkflowId] = useState<string | null>(routeIdentity.workflowId ?? persistedWorkflow?.workflowId ?? null);
  const [snapshotId, setSnapshotId] = useState<string | null>(routeIdentity.snapshotId ?? persistedWorkflow?.snapshotId ?? null);
  const [workflowOutcome, setWorkflowOutcome] = useState<{ state: ReleaseOutcomeState; reason: string }>(() =>
    routeIdentity.snapshotId || persistedWorkflow?.snapshotId
      ? { state: "success", reason: "Snapshot identity is pinned for training." }
      : { state: "blocked", reason: "Select an approved snapshot from Data before training." },
  );
  const [jobError, setJobError] = useState<string | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [resultModel, setResultModel] = useState<ModelData | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const completionRef = useRef("");
  const { getName } = useNameMap();

  // Stock ranking state
  const { selectedModelId } = useGlobalStore();
  const [rankingData, setRankingData] = useState<Array<{
    symbol: string;
    weighted_score: number;
    total_signals: number;
    grade_details: Record<string, { occurrences: number; win_rate: number; mean_return: number; cumulative_return: number }>;
  }>>([]);
  const [rankingLoading, setRankingLoading] = useState(false);
  const [sortBy, setSortBy] = useState("weighted_score");
  const [sortGrade, setSortGrade] = useState("AAA");
  const [rankingMarket, setRankingMarket] = useState("cn");

  // NL Strategy Compiler
  const [nlText, setNlText] = useState("");
  const [nlCompiling, setNlCompiling] = useState(false);
  const [nlResult, setNlResult] = useState<{ market?: string; yaml_path?: string; summary?: Record<string, unknown> } | null>(null);
  const [nlError, setNlError] = useState<string | null>(null);

  // --- Resume on mount ---
  useEffect(() => {
    const persisted = loadWorkflowState();
    if (persisted) {
      // Check if stale (> 15 minutes old)
      if (Date.now() - persisted.startedAt > 15 * 60 * 1000) {
        saveWorkflowState(null);
        return;
      }
      setMarket(persisted.market);
      setModelType(persisted.modelType);
      setTag(persisted.tag);
      setSnapshotId(persisted.snapshotId);
      setWorkflowId(persisted.workflowId);
      setWorkflowStatus("running");
    }
  }, []);

  // Auto-resolve latest snapshot when none is provided
  useEffect(() => {
    if (snapshotId) return; // Already have a snapshot
    let cancelled = false;
    (async () => {
      try {
        const status = await releaseApi.getDataStatus();
        const latestId = status?.data?.latest_snapshot_id;
        if (!cancelled && latestId) {
          setSnapshotId(latestId);
          setWorkflowOutcome({ state: "success", reason: `Auto-resolved latest snapshot: ${latestId}` });
        }
      } catch {
        // Silently fail — user can still navigate to Data page
      }
    })();
    return () => { cancelled = true; };
  }, [snapshotId]);

  // Fetch stock ranking
  const fetchRanking = useCallback(async () => {
    setRankingLoading(true);
    try {
      const json = await releaseApi.getStockRanking({
        market: rankingMarket,
        sort_by: sortBy,
        sort_grade: sortGrade,
        run_id: selectedModelId || undefined,
      });
      setRankingData(json.ranking || []);
    } catch (err) {
      console.warn("[BacktestPage] loadRanking failed:", err);
      setRankingData([]);
    } finally {
      setRankingLoading(false);
    }
  }, [rankingMarket, sortBy, sortGrade, selectedModelId]);

  const compileFromNL = async () => {
    if (!nlText.trim()) return;
    setNlCompiling(true);
    setNlError(null);
    setNlResult(null);
    try {
      const json = await releaseApi.compileStrategy(nlText, market);
      setNlResult(json);
    } catch (e: unknown) {
      setNlError(e instanceof Error ? e.message : String(e));
    } finally {
      setNlCompiling(false);
    }
  };

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logLines]);

  const workflowQuery = useQuery<WorkflowStatusEntry[]>({
    fetcher: () => releaseApi.getWorkflow(workflowId || ""),
    enabled: Boolean(workflowId) && workflowStatus === "running",
  });

  useEffect(() => {
    if (!workflowId || workflowStatus !== "running") return;
    const timer = window.setInterval(workflowQuery.refetch, 1000);
    return () => window.clearInterval(timer);
  }, [workflowId, workflowQuery.refetch, workflowStatus]);

  const loadExactResult = useCallback(async (workflow: WorkflowStatusEntry) => {
    try {
      const [registry, artifact] = await Promise.all([
        releaseApi.listModels(),
        releaseApi.getDashboardArtifact(),
      ]);
      const resolution = resolveWorkflowResult(workflow, registry.versions, snapshotId ?? undefined);
      setWorkflowOutcome({ state: resolution.state, reason: resolution.reason });

      if (resolution.state !== "success" || !resolution.snapshotId || !resolution.runId || !resolution.modelId) return;
      setSnapshotId(resolution.snapshotId);

      const parsed = parseQlibData(artifact);
      const exactModel = parsed.find((candidate) => candidate.id === resolution.runId || candidate.id === resolution.modelId);
      if (!exactModel) {
        setWorkflowOutcome({ state: "partial", reason: `Run ${resolution.runId} is registered but missing from dashboard artifacts.` });
        return;
      }

      const evidence = await releaseApi.getModelEvidence(resolution.modelId);
      const evidenceResolution = resolveEvidenceIdentity(evidence, resolution.modelId);
      setWorkflowOutcome({ state: evidenceResolution.state, reason: evidenceResolution.reason });
      setResultModel(exactModel);
      navigate({
        pathname: location.pathname,
        search: releaseSearch({
          snapshotId: resolution.snapshotId,
          workflowId: workflow.workflow_id,
          runId: resolution.runId,
          modelId: resolution.modelId,
          evidenceId: evidenceResolution.evidenceId,
        }, location.search),
      }, { replace: true });
    } catch (error) {
      setWorkflowOutcome({
        state: "failed",
        reason: error instanceof Error ? error.message : String(error),
      });
    }
  }, [location.pathname, location.search, navigate, snapshotId]);

  useEffect(() => {
    const workflow = workflowQuery.data?.[0];
    if (!workflow || completionRef.current === `${workflow.workflow_id}:${workflow.status}`) return;
    const status = String(workflow.status).toUpperCase();
    if (status === "SUCCESS") {
      completionRef.current = `${workflow.workflow_id}:${workflow.status}`;
      saveWorkflowState(null);
      setWorkflowStatus("succeeded");
      void loadExactResult(workflow);
    } else if (status === "FAILED") {
      completionRef.current = `${workflow.workflow_id}:${workflow.status}`;
      saveWorkflowState(null);
      setWorkflowStatus("failed");
      const reason = String(workflow.error || workflow.details?.summary || "Workflow failed. Check logs for details.");
      setJobError(reason);
      setWorkflowOutcome({ state: "failed", reason });
    }
  }, [loadExactResult, workflowQuery.data]);

  useEffect(() => {
    if (workflowQuery.error && workflowStatus === "running") {
      setWorkflowOutcome({ state: "failed", reason: workflowQuery.error });
    }
  }, [workflowQuery.error, workflowStatus]);

  const validate = (): string | null => {
    if (!snapshotId) return "An approved snapshot identity is required. Start from the Data page.";
    if (!tag.trim()) return "Tag is required (used to identify this run).";
    if (!market) return "Market is required.";
    if (!modelType.trim()) return "Model type is required.";
    return null;
  };

  const trainMutation = useMutation({
    mutateFn: releaseApi.submitTraining,
    onSuccess: (data, variables) => {
      const wfId = data.workflow_id;
      if (!wfId) {
        setWorkflowStatus("failed");
        setWorkflowOutcome({ state: "failed", reason: "Server did not return a workflow ID." });
        return;
      }
      completionRef.current = "";
      setWorkflowId(wfId);
      saveWorkflowState({
        workflowId: wfId,
        snapshotId: variables.snapshot_id,
        market: variables.market,
        modelType: variables.model_type,
        tag: variables.tag,
        startedAt: Date.now(),
      });
      navigate({
        pathname: location.pathname,
        search: releaseSearch({ snapshotId: variables.snapshot_id, workflowId: wfId }, location.search),
      }, { replace: true });
      setWorkflowOutcome({ state: "loading", reason: `Training workflow ${wfId} is running.` });
    },
    onError: (message) => {
      setWorkflowStatus("failed");
      setJobError(message);
      setWorkflowOutcome({ state: "failed", reason: message });
      saveWorkflowState(null);
    },
  });

  const startBacktest = () => {
    const err = validate();
    if (err) {
      setValidationError(err);
      return;
    }
    setValidationError(null);
    setWorkflowStatus("running");
    setJobError(null);
    setLogLines([]);
    setResultModel(null);
    setWorkflowId(null);
    setWorkflowOutcome({ state: "loading", reason: "Submitting snapshot-bound training workflow." });
    trainMutation.mutate({ market, model_type: modelType, tag: tag.trim(), snapshot_id: snapshotId! });
  };

  const resetToIdle = () => {
    saveWorkflowState(null);
    setWorkflowStatus("idle");
    setWorkflowId(null);
    setJobError(null);
    setLogLines([]);
    setResultModel(null);
    setValidationError(null);
    setWorkflowOutcome(snapshotId
      ? { state: "success", reason: "Snapshot identity is pinned for training." }
      : { state: "blocked", reason: "Select an approved snapshot from Data before training." });
  };

  return (
    <div className="space-y-5 max-w-[1400px] mx-auto pb-16">
      {/* Header */}
      <div className="border-b pb-4">
        <h1 className="text-2xl font-bold tracking-tight">Backtest Workbench</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Execute backtests and analyze results.
        </p>
      </div>

      <ReleaseOutcome state={workflowOutcome.state} reason={workflowOutcome.reason} />

      {/* NL Strategy Compiler */}
      <Card>
        <CardHeader className="pb-3 border-b">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Sparkles className="h-4 w-4" /> Natural Language Strategy
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-5">
          <div className="space-y-3">
            <textarea
              value={nlText}
              onChange={(e) => setNlText(e.target.value)}
              placeholder="Describe your strategy in natural language...&#10;&#10;Example: &quot;Hold top 5 stocks, rebalance biweekly, sell below MA60, positive score to buy, negative score to sell, starting capital $100,000&quot;"
              className="w-full h-24 px-3 py-2 text-xs font-mono border rounded-md bg-background resize-none focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
            <div className="flex items-center gap-2">
              <Button
                onClick={compileFromNL}
                disabled={nlCompiling || !nlText.trim()}
                size="sm"
                className="h-7 gap-1.5 px-3 text-xs"
              >
                {nlCompiling ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Sparkles className="h-3 w-3" />
                )}
                {nlCompiling ? "Compiling..." : "Generate Strategy"}
              </Button>
              {nlResult && (
                <Badge variant="default" className="text-xs">
                  <CheckCircle2 className="h-3 w-3 mr-1" /> Compiled
                </Badge>
              )}
            </div>

            {nlError && (
              <div className="p-2.5 bg-destructive/10 border border-destructive/20 rounded text-xs text-destructive font-mono">
                {nlError}
              </div>
            )}

            {nlResult && (
              <div className="p-3 bg-muted/50 border rounded text-xs space-y-2">
                <div className="font-semibold text-sm mb-2">Generated Strategy Profile</div>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                  <div><span className="text-muted-foreground">Market:</span> <span className="font-mono uppercase">{nlResult.market}</span></div>
                  <div><span className="text-muted-foreground">Rebalance:</span> <span className="font-mono">{String(nlResult.summary?.rebalance ?? '')}</span></div>
                  <div><span className="text-muted-foreground">TopK:</span> <span className="font-mono">{String(nlResult.summary?.topk ?? '')}</span></div>
                  <div><span className="text-muted-foreground">Sell MA:</span> <span className="font-mono">{String(nlResult.summary?.sell_ma ?? '')}</span></div>
                  <div><span className="text-muted-foreground">Min Hold:</span> <span className="font-mono">{String(nlResult.summary?.min_hold_days ?? '')} days</span></div>
                  <div><span className="text-muted-foreground">Buy Rule:</span> <span className="font-mono">{String(nlResult.summary?.buy_rule ?? '')}</span></div>
                  <div><span className="text-muted-foreground">Sell Rule:</span> <span className="font-mono">{String(nlResult.summary?.sell_rule ?? '')}</span></div>
                </div>
                <div className="pt-2 text-muted-foreground">
                  <span className="font-mono text-[10px]">YAML: {nlResult.yaml_path}</span>
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Execution Controls */}
      <Card>
        <CardHeader className="pb-3 border-b">
          <CardTitle className="text-sm font-semibold">Parameters</CardTitle>
        </CardHeader>
        <CardContent className="pt-5">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Market</label>
              <div className="flex gap-1">
                {["us", "cn"].map((m) => (
                  <Button
                    key={m}
                    variant={market === m ? "default" : "outline"}
                    size="sm"
                    onClick={() => setMarket(m)}
                    className="h-7 text-xs uppercase"
                  >
                    {m}
                  </Button>
                ))}
              </div>
            </div>

            <div className="space-y-1">
              <label htmlFor="release-model-type" className="text-xs text-muted-foreground">Model</label>
              <Input
                id="release-model-type"
                value={modelType}
                onChange={(e) => setModelType(e.target.value)}
                className="h-7 w-28 text-xs font-mono"
              />
            </div>

            <div className="space-y-1">
              <label htmlFor="release-tag" className="text-xs text-muted-foreground">
                Tag <span className="text-destructive">*</span>
              </label>
              <Input
                id="release-tag"
                value={tag}
                onChange={(e) => setTag(e.target.value)}
                placeholder="required"
                className="h-7 w-40 text-xs font-mono"
              />
            </div>

            <Button
              onClick={startBacktest}
              disabled={workflowStatus === "running"}
              className="h-7 gap-1.5 px-4 text-xs"
            >
              {workflowStatus === "running" ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Play className="h-3 w-3 fill-current" />
              )}
              {workflowStatus === "running" ? "Running..." : "Execute"}
            </Button>

            {workflowStatus !== "idle" && (
              <Badge
                variant={
                  workflowStatus === "succeeded" ? "default" :
                  workflowStatus === "failed" ? "destructive" : "outline"
                }
                className="gap-1 text-xs"
              >
                {workflowStatus === "running" && <Loader2 className="h-3 w-3 animate-spin" />}
                {workflowStatus === "succeeded" && <CheckCircle2 className="h-3 w-3" />}
                {workflowStatus === "failed" && <XCircle className="h-3 w-3" />}
                {workflowStatus}
              </Badge>
            )}

            {(workflowStatus === "succeeded" || workflowStatus === "failed") && (
              <Button variant="ghost" size="sm" onClick={resetToIdle} className="h-7 text-xs text-muted-foreground">
                New Run
              </Button>
            )}
          </div>

          {/* Validation error */}
          {validationError && (
            <div className="mt-3 p-2.5 bg-amber-500/10 border border-amber-500/20 rounded text-xs text-amber-600">
              {validationError}
            </div>
          )}

          {/* Job error */}
          {jobError && (
            <div className="mt-3 p-2.5 bg-destructive/10 border border-destructive/20 rounded text-xs text-destructive font-mono">
              {jobError}
            </div>
          )}

          {/* Workflow ID display */}
          {workflowId && workflowStatus === "running" && (
            <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
              <Terminal className="h-3 w-3" />
              <span>Tracking workflow:</span>
              <code className="font-mono bg-muted px-1.5 py-0.5 rounded text-[10px]">{workflowId}</code>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Log Output */}
      {logLines.length > 0 && (
        <Card>
          <CardHeader className="pb-1.5 border-b flex flex-row items-center justify-between py-2.5">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Terminal className="h-4 w-4" /> Live Log
            </CardTitle>
            {workflowId && (
              <Badge variant="outline" className="font-mono text-xs">
                {workflowId}
              </Badge>
            )}
          </CardHeader>
          <CardContent className="p-0">
            <div
              ref={logRef}
              className="h-48 overflow-y-auto p-3 bg-black font-mono text-xs leading-relaxed"
            >
              {logLines.map((line, i) => (
                <div
                  key={i}
                  className={cn(
                    line.includes("ERROR") || line.includes("FAIL")
                      ? "text-red-400"
                      : line.includes("WARN")
                      ? "text-amber-400"
                      : "text-green-400/80"
                  )}
                >
                  {line}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {resultModel && (
        <div className="space-y-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-green-500 font-medium text-sm">
              <CheckCircle2 className="h-4 w-4" /> Results: {resultModel.name}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="h-7 gap-1.5 text-xs"
                onClick={() => navigate({ pathname: "/models", search: location.search })}
              >
                <ExternalLink className="h-3 w-3" /> View in Model Registry
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-7 gap-1.5 text-xs"
                onClick={() => navigate(
                  { pathname: "/compare", search: location.search },
                  { state: { preselectedIds: [routeIdentity.modelId, routeIdentity.runId, resultModel.id].filter(Boolean) as string[] } },
                )}
                aria-label="Compare exact result"
              >
                <Layers className="h-3 w-3" /> Compare
              </Button>
            </div>
          </div>

          <OverviewCards metrics={resultModel.backtest.metrics} />

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
            <div className="xl:col-span-2">
              {resultModel.backtest.report.length > 0 && (
                <PerformanceCharts report={resultModel.backtest.report} />
              )}
            </div>
            <div>
              {resultModel.backtest.positions.length > 0 && (
                <PositionsTable positions={resultModel.backtest.positions} />
              )}
            </div>
          </div>
        </div>
      )}

      {/* Stock Ranking Section */}
      <Card>
        <CardHeader className="pb-3 border-b">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <BarChart3 className="h-4 w-4" /> Stock Ranking (Model Effectiveness)
            </CardTitle>
            <div className="flex items-center gap-2">
              {/* Market selector */}
              <select
                value={rankingMarket}
                onChange={(e) => setRankingMarket(e.target.value)}
                className="h-7 px-2 text-xs border rounded bg-background"
              >
                <option value="cn">CN</option>
                <option value="us">US</option>
              </select>
              {/* Sort by selector */}
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="h-7 px-2 text-xs border rounded bg-background"
              >
                <option value="weighted_score">Weighted Score</option>
                <option value="win_rate">Win Rate</option>
                <option value="mean_return">Mean Return</option>
                <option value="cumulative_return">Cumulative Return</option>
              </select>
              {/* Grade selector (for grade-specific sorting) */}
              {sortBy !== "weighted_score" && (
                <select
                  value={sortGrade}
                  onChange={(e) => setSortGrade(e.target.value)}
                  className="h-7 px-2 text-xs border rounded bg-background"
                >
                  {["AAA", "AA", "A", "V", "VV", "VVV"].map(g => (
                    <option key={g} value={g}>{g}</option>
                  ))}
                </select>
              )}
              <Button
                onClick={fetchRanking}
                disabled={rankingLoading}
                size="sm"
                className="h-7 gap-1.5 px-3 text-xs"
              >
                {rankingLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <BarChart3 className="h-3 w-3" />}
                Rank
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-4">
          {rankingData.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-muted/5">
                    <th className="text-left py-2 px-2 font-bold text-muted-foreground">#</th>
                    <th className="text-left py-2 px-2 font-bold text-muted-foreground">Symbol</th>
                    <th className="text-right py-2 px-2 font-bold text-muted-foreground">Score</th>
                    <th className="text-right py-2 px-2 font-bold text-muted-foreground">Signals</th>
                    <th className="text-center py-2 px-2 font-bold text-muted-foreground" colSpan={3}>AAA (Buy)</th>
                    <th className="text-center py-2 px-2 font-bold text-muted-foreground" colSpan={3}>VVV (Sell)</th>
                  </tr>
                  <tr className="border-b bg-muted/5">
                    <th></th><th></th><th></th><th></th>
                    <th className="text-right py-1 px-2 text-[10px] text-muted-foreground">WR</th>
                    <th className="text-right py-1 px-2 text-[10px] text-muted-foreground">Avg</th>
                    <th className="text-right py-1 px-2 text-[10px] text-muted-foreground">Cum</th>
                    <th className="text-right py-1 px-2 text-[10px] text-muted-foreground">WR</th>
                    <th className="text-right py-1 px-2 text-[10px] text-muted-foreground">Avg</th>
                    <th className="text-right py-1 px-2 text-[10px] text-muted-foreground">Cum</th>
                  </tr>
                </thead>
                <tbody>
                  {rankingData.map((item, idx) => {
                    const aaa = item.grade_details?.AAA || { occurrences: 0, win_rate: 0, mean_return: 0, cumulative_return: 0 };
                    const vvv = item.grade_details?.VVV || { occurrences: 0, win_rate: 0, mean_return: 0, cumulative_return: 0 };
                    return (
                      <tr
                        key={item.symbol}
                        className="border-b border-dashed hover:bg-muted/5 cursor-pointer"
                        onClick={() => window.location.hash = `#/terminal`}
                      >
                        <td className="py-2 px-2 text-muted-foreground">{idx + 1}</td>
                        <td className="py-2 px-2 font-bold">
                          <div>{getName(item.symbol)}</div>
                          <div className="text-[10px] text-muted-foreground font-mono">{item.symbol}</div>
                        </td>
                        <td className={cn(
                          "py-2 px-2 text-right font-mono font-bold",
                          item.weighted_score > 0 ? "text-green-400" : item.weighted_score < 0 ? "text-red-400" : "text-muted-foreground",
                        )}>
                          {item.weighted_score > 0 ? "+" : ""}{(item.weighted_score * 100).toFixed(2)}
                        </td>
                        <td className="py-2 px-2 text-right text-muted-foreground">{item.total_signals}</td>
                        <td className="py-2 px-2 text-right font-mono">{aaa.win_rate > 0 ? formatPct(aaa.win_rate, 0) : "-"}</td>
                        <td className="py-2 px-2 text-right font-mono">{aaa.occurrences > 0 ? formatPct(aaa.mean_return, 1) : "-"}</td>
                        <td className="py-2 px-2 text-right font-mono">{aaa.occurrences > 0 ? formatPct(aaa.cumulative_return, 1) : "-"}</td>
                        <td className="py-2 px-2 text-right font-mono">{vvv.occurrences > 0 ? formatPct(vvv.win_rate, 0) : "-"}</td>
                        <td className="py-2 px-2 text-right font-mono">{vvv.occurrences > 0 ? formatPct(vvv.mean_return, 1) : "-"}</td>
                        <td className="py-2 px-2 text-right font-mono">{vvv.occurrences > 0 ? formatPct(vvv.cumulative_return, 1) : "-"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <Placeholder 
              className="border-none bg-transparent"
              icon={BarChart3} 
              title="Awaiting Ranking" 
              description="Click 'Rank' to analyze model effectiveness across all stocks. Higher weighted score = model signals are more accurate for that stock." 
            />
          )}
        </CardContent>
      </Card>

      {/* Empty state */}
      {workflowStatus === "idle" && !resultModel && (
        <Placeholder 
          icon={Terminal} 
          title="Ready for Execution" 
          description="Configure parameters and click Execute to run a backtest. Tag is required to identify and track your run." 
        />
      )}
    </div>
  );
}
