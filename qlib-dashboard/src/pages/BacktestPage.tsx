import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Play, Loader2, CheckCircle2, XCircle, Terminal, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { OverviewCards } from "@/components/OverviewCards";
import { PerformanceCharts } from "@/components/PerformanceCharts";
import { PositionsTable } from "@/components/PositionsTable";
import { parseQlibData, ModelData } from "@/lib/data-parser";
import { artifactUrl } from "@/lib/artifacts";

type JobStatus = "idle" | "running" | "succeeded" | "failed";

export function BacktestPage() {
  const [market, setMarket] = useState("us");
  const [modelType, setModelType] = useState("lgbm");
  const [tag, setTag] = useState("");
  const [jobStatus, setJobStatus] = useState<JobStatus>("idle");
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [resultModel, setResultModel] = useState<ModelData | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<number | null>(null);
  const timeoutRef = useRef<number | null>(null);

  // NL Strategy Compiler
  const [nlText, setNlText] = useState("");
  const [nlCompiling, setNlCompiling] = useState(false);
  const [nlResult, setNlResult] = useState<any>(null);
  const [nlError, setNlError] = useState<string | null>(null);

  const compileFromNL = async () => {
    if (!nlText.trim()) return;
    setNlCompiling(true);
    setNlError(null);
    setNlResult(null);
    try {
      const resp = await fetch("/api/strategy/compile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: nlText, market }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      const json = await resp.json();
      setNlResult(json);
    } catch (e: any) {
      setNlError(e.message);
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

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    };
  }, []);

  const startBacktest = async () => {
    setJobStatus("running");
    setJobError(null);
    setLogLines([]);
    setResultModel(null);
    setJobId(null);

    try {
      const resp = await fetch("/api/workflow/train", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ market, model_type: modelType, tag: tag || undefined }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      // Start polling for the job
      findAndWatchJob();
    } catch (e: any) {
      setJobStatus("failed");
      setJobError(e.message);
    }
  };

  const findAndWatchJob = () => {
    let foundJobId: string | null = null;
    let streamStarted = false;

    // Phase 1: Find the running job
    pollRef.current = window.setInterval(async () => {
      try {
        if (!foundJobId) {
          // Look for a running job
          const resp = await fetch("/api/jobs?status=running&limit=1", { cache: "no-store" });
          if (!resp.ok) return;
          const json = await resp.json();
          const jobs = json.jobs || [];
          if (jobs.length > 0) {
            foundJobId = jobs[0].id;
            setJobId(foundJobId);
          }
        }

        if (foundJobId) {
          // Check specific job status
          const jobResp = await fetch(`/api/jobs/${encodeURIComponent(foundJobId)}`, { cache: "no-store" });
          if (!jobResp.ok) return;
          const jobJson = await jobResp.json();
          const status = jobJson?.job?.status || "";

          // Start log streaming once
          if (!streamStarted) {
            streamStarted = true;
            streamLogs(foundJobId);
          }

          if (status === "succeeded") {
            cleanup();
            setJobStatus("succeeded");
            loadResults();
          } else if (status === "failed") {
            cleanup();
            setJobStatus("failed");
            setJobError(jobJson?.job?.error || "Backtest failed. Check logs for details.");
          }
        }
      } catch {
        /* ignore transient errors */
      }
    }, 2000);

    // Timeout after 10 minutes
    timeoutRef.current = window.setTimeout(() => {
      cleanup();
      setJobStatus("failed");
      setJobError("Timeout: backtest took longer than 10 minutes.");
    }, 600000);
  };

  const cleanup = () => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (timeoutRef.current) {
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  };

  const streamLogs = (id: string) => {
    const es = new EventSource(`/api/jobs/${encodeURIComponent(id)}/stream`);
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.line) {
          setLogLines((prev) => [...prev, data.line]);
        }
      } catch {
        /* ignore */
      }
    };
    es.addEventListener("done", () => es.close());
    es.onerror = () => es.close();
  };

  const loadResults = async () => {
    try {
      const resp = await fetch(artifactUrl.dashboardDb, { cache: "no-store" });
      if (!resp.ok) return;
      const json = await resp.json();
      const models = parseQlibData(json);
      if (models.length > 0) {
        setResultModel(models[0]);
      }
    } catch {
      /* ignore */
    }
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
                  <div><span className="text-muted-foreground">Rebalance:</span> <span className="font-mono">{nlResult.summary?.rebalance}</span></div>
                  <div><span className="text-muted-foreground">TopK:</span> <span className="font-mono">{nlResult.summary?.topk}</span></div>
                  <div><span className="text-muted-foreground">Sell MA:</span> <span className="font-mono">{nlResult.summary?.sell_ma}</span></div>
                  <div><span className="text-muted-foreground">Min Hold:</span> <span className="font-mono">{nlResult.summary?.min_hold_days} days</span></div>
                  <div><span className="text-muted-foreground">Buy Rule:</span> <span className="font-mono">{nlResult.summary?.buy_rule}</span></div>
                  <div><span className="text-muted-foreground">Sell Rule:</span> <span className="font-mono">{nlResult.summary?.sell_rule}</span></div>
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
              <label className="text-xs text-muted-foreground">Model</label>
              <Input
                value={modelType}
                onChange={(e) => setModelType(e.target.value)}
                className="h-7 w-28 text-xs font-mono"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Tag</label>
              <Input
                value={tag}
                onChange={(e) => setTag(e.target.value)}
                placeholder="optional"
                className="h-7 w-40 text-xs font-mono"
              />
            </div>

            <Button
              onClick={startBacktest}
              disabled={jobStatus === "running"}
              className="h-7 gap-1.5 px-4 text-xs"
            >
              {jobStatus === "running" ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Play className="h-3 w-3 fill-current" />
              )}
              {jobStatus === "running" ? "Running..." : "Execute"}
            </Button>

            {jobStatus !== "idle" && (
              <Badge
                variant={
                  jobStatus === "succeeded" ? "default" :
                  jobStatus === "failed" ? "destructive" : "outline"
                }
                className="gap-1 text-xs"
              >
                {jobStatus === "running" && <Loader2 className="h-3 w-3 animate-spin" />}
                {jobStatus === "succeeded" && <CheckCircle2 className="h-3 w-3" />}
                {jobStatus === "failed" && <XCircle className="h-3 w-3" />}
                {jobStatus}
              </Badge>
            )}
          </div>

          {jobError && (
            <div className="mt-3 p-2.5 bg-destructive/10 border border-destructive/20 rounded text-xs text-destructive font-mono">
              {jobError}
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
            {jobId && (
              <Badge variant="outline" className="font-mono text-xs">
                {jobId.slice(0, 8)}
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
          <div className="flex items-center gap-2 text-green-500 font-medium text-sm">
            <CheckCircle2 className="h-4 w-4" /> Results: {resultModel.name}
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

      {/* Empty state */}
      {jobStatus === "idle" && !resultModel && (
        <div className="flex flex-col items-center justify-center py-16 border-2 border-dashed rounded-lg bg-muted/30">
          <Terminal className="h-10 w-10 text-muted-foreground/30 mb-3" />
          <p className="text-muted-foreground text-sm">
            Configure parameters and click Execute to run a backtest.
          </p>
        </div>
      )}
    </div>
  );
}
