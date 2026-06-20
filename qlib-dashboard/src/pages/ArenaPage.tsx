import { Fragment, useEffect, useMemo, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Loader2, Trophy, RefreshCw, ExternalLink, Target, Users, Calendar, AlertTriangle, CheckCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatPct, formatNum } from "@/lib/format";
import { apiFetch } from "@/lib/api";

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 600_000; // 10 minutes

type Arena = { id: string; name: string; market: string; };
type LeaderboardRow = {
  rank?: number;
  participant_name?: string;
  nav?: number;
  daily_return?: number;
  drawdown?: number;
  turnover?: number;
  run_id?: string;
  model_version_id?: string;
  edge_explanation?: string;
  // Enhanced fields for decision making
  ic?: number;
  ic_ir?: number;
  consistency?: number;
  risk_status?: "normal" | "warning" | "downgrade";
  factor_exposure?: string;
  walk_forward_stable?: boolean;
};
type ReportRow = { id: string; type: string; ref_id: string; date?: string; paths?: Record<string, string>; };

export function ArenaPage({ onCompare }: { onCompare?: (runId: string) => void }) {
  const [arenas, setArenas] = useState<Arena[]>([]);
  const [selectedArenaId, setSelectedArenaId] = useState<string>("");
  const [leaderboard, setLeaderboard] = useState<LeaderboardRow[]>([]);
  const [settledDate, setSettledDate] = useState<string>("");
  const [seedFromModelRegistry, setSeedFromModelRegistry] = useState(true);
  const [seedLimit, setSeedLimit] = useState(30);
  const [jobId, setJobId] = useState("");
  const [jobStatus, setJobStatus] = useState("");
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<ReportRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedArena = useMemo(() => arenas.find((a) => a.id === selectedArenaId) || null, [arenas, selectedArenaId]);

  const loadArenas = useCallback(async () => {
    try {
      const resp = await apiFetch("/api/arena/list");
      if (!resp.ok) return;
      const json = await resp.json();
      const parsed = (json?.arenas || []).map((r: { id: string; name?: string; market?: string }) => ({ id: r.id, name: r.name || r.id, market: r.market || "unknown" }));
      setArenas(parsed);
      if (parsed.length > 0 && !selectedArenaId) setSelectedArenaId(parsed[0].id);
    } catch (err) {
      console.warn("[ArenaPage] loadArenas failed:", err);
    }
  }, [selectedArenaId]);

  const loadLeaderboard = useCallback(async (arena: Arena) => {
    try {
      const resp = await apiFetch(`/api/arena/leaderboard?arena_id=${encodeURIComponent(arena.id)}`);
      if (!resp.ok) return;
      const json = await resp.json();
      setLeaderboard(json?.leaderboard || []);
      setSettledDate(String(json?.date || ""));
    } catch (err) {
      console.warn("[ArenaPage] loadLeaderboard failed:", err);
    }
  }, []);

  const loadLatestReport = useCallback(async (arena: Arena) => {
    try {
      const resp = await apiFetch(`/api/reports?type=arena_daily&ref_id=${encodeURIComponent(arena.id)}`);
      if (!resp.ok) return;
      const json = await resp.json();
      const r = (json?.reports || []).find((rep: { type: string; ref_id?: string }) => rep.type === "arena_daily" && rep.ref_id === arena.id);
      if (r) setReport({ id: r.id, type: r.type, ref_id: r.ref_id, date: r.date, paths: r.paths });
    } catch (err) {
      console.warn("[ArenaPage] loadLatestReport failed:", err);
    }
  }, []);

  const refreshSelected = useCallback(async () => {
    if (!selectedArena) return;
    await loadLeaderboard(selectedArena);
    await loadLatestReport(selectedArena);
  }, [selectedArena, loadLeaderboard, loadLatestReport]);

  useEffect(() => { loadArenas(); }, [loadArenas]);
  useEffect(() => { if (selectedArena) refreshSelected(); }, [selectedArenaId, selectedArena, refreshSelected]);

  const startSettle = useCallback(async () => {
    if (!selectedArena) return;
    if (!window.confirm(`Start Arena Settlement for ${selectedArena.name}?`)) return;
    setRunning(true);
    setError(null);
    try {
      const resp = await apiFetch("/api/arena/settle", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ market: selectedArena.market, arena_name: selectedArena.name, date: "latest", seed_from_model_registry: seedFromModelRegistry, limit: seedLimit }),
      });
      if (resp.ok) {
        const json = await resp.json();
        setJobId(json.job_id);
      } else {
        const text = await resp.text().catch(() => "Unknown error");
        setError(`Settle failed: HTTP ${resp.status}`);
        console.warn("[ArenaPage] startSettle HTTP error:", resp.status, text);
        setRunning(false);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Network error";
      setError(`Settle failed: ${msg}`);
      console.warn("[ArenaPage] startSettle error:", err);
      setRunning(false);
    }
  }, [selectedArena, seedFromModelRegistry, seedLimit]);

  useEffect(() => {
    if (!jobId) return;
    const startTime = Date.now();
    const timer = window.setInterval(async () => {
      // Timeout guard
      if (Date.now() - startTime > POLL_TIMEOUT_MS) {
        window.clearInterval(timer);
        setRunning(false);
        setJobId("");
        setError("Settlement timed out after 10 minutes.");
        console.warn("[ArenaPage] poll timeout for job:", jobId);
        return;
      }
      try {
        const resp = await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}`);
        if (!resp.ok) return;
        const json = await resp.json();
        const st = String(json?.job?.status || "");
        setJobStatus(st);
        if (st === "succeeded" || st === "failed") {
          window.clearInterval(timer);
          setRunning(false);
          setJobId("");
          if (st === "succeeded") {
            await refreshSelected();
          } else {
            setError("Settlement job failed.");
          }
        }
      } catch (err) {
        console.warn("[ArenaPage] poll error:", err);
        // Don't stop polling on transient errors
      }
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [jobId, refreshSelected]);

  const reportHref = report?.paths?.html ? `/${String(report.paths.html).replace(/^\/+/, "")}` : "";

  return (
    <div className="space-y-5 max-w-[1400px] mx-auto pb-16">
      <div className="border-b pb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Strategy Arena</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Rolling out-of-sample evaluation. Models compete on live data.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={refreshSelected} variant="outline" size="sm" className="h-7 gap-1.5 text-xs">
            <RefreshCw className={cn("h-3 w-3", running && "animate-spin")} /> Refresh
          </Button>
          <Button onClick={startSettle} disabled={running} size="sm" className="h-7 gap-1.5 text-xs">
            {running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Target className="h-3 w-3" />}
            {running ? `Settling (${jobStatus})` : "Settle"}
          </Button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-400">
          {error}
          <button onClick={() => setError(null)} className="ml-auto text-red-400/60 hover:text-red-400">✕</button>
        </div>
      )}

      {/* Decision Panel - "Which strategy should I trust today?" */}
      {leaderboard.length > 0 && (
        <Card className="border-amber-500/20 bg-amber-500/5">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Target className="h-4 w-4 text-amber-500" />
              Strategy Decision Panel
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Top Recommendation */}
              <div className="space-y-2">
                <div className="text-xs text-muted-foreground">Recommended Strategy</div>
                <div className="text-lg font-bold text-amber-500">
                  {leaderboard[0]?.participant_name || "N/A"}
                </div>
                <div className="text-xs text-muted-foreground">
                  Rank #1 • NAV {formatNum(leaderboard[0]?.nav)} • Return {formatPct(leaderboard[0]?.daily_return)}
                </div>
              </div>

              {/* Key Metrics */}
              <div className="space-y-2">
                <div className="text-xs text-muted-foreground">Key Metrics</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="flex justify-between">
                    <span>Max Drawdown:</span>
                    <span className={cn("font-mono", (leaderboard[0]?.drawdown || 0) < -0.1 ? "text-red-500" : "text-green-500")}>
                      {formatPct(leaderboard[0]?.drawdown)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Turnover:</span>
                    <span className="font-mono">{formatPct(leaderboard[0]?.turnover)}</span>
                  </div>
                </div>
              </div>

              {/* Risk Status */}
              <div className="space-y-2">
                <div className="text-xs text-muted-foreground">Risk Status</div>
                <div className="flex items-center gap-2">
                  {(leaderboard[0]?.drawdown || 0) < -0.15 ? (
                    <Badge variant="destructive" className="gap-1">
                      <AlertTriangle className="h-3 w-3" /> High Drawdown
                    </Badge>
                  ) : (leaderboard[0]?.drawdown || 0) < -0.1 ? (
                    <Badge variant="outline" className="gap-1 text-yellow-400 border-yellow-500/30">
                      <AlertTriangle className="h-3 w-3" /> Moderate Risk
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="gap-1 text-green-400 border-green-500/30">
                      <CheckCircle className="h-3 w-3" /> Low Risk
                    </Badge>
                  )}
                </div>
                <div className="text-xs text-muted-foreground">
                  {leaderboard.filter(r => (r.drawdown || 0) < -0.1).length} of {leaderboard.length} strategies have elevated risk
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        {/* Sidebar */}
        <div className="lg:col-span-1 space-y-4">
          <Card>
            <CardHeader className="pb-3 border-b">
              <CardTitle className="text-sm font-semibold">Parameters</CardTitle>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs text-muted-foreground">Arena</label>
                <select className="w-full bg-background border rounded px-2 py-1.5 text-xs outline-none" value={selectedArenaId} onChange={(e) => setSelectedArenaId(e.target.value)} disabled={!arenas.length}>
                  {arenas.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.market.toUpperCase()})</option>)}
                </select>
              </div>
              <div className="flex items-center justify-between">
                <label className="text-xs text-muted-foreground">Include Registry</label>
                <input type="checkbox" className="h-3.5 w-3.5 rounded" checked={seedFromModelRegistry} onChange={(e) => setSeedFromModelRegistry(e.target.checked)} />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs text-muted-foreground">Max Contestants</label>
                <input type="number" className="w-full bg-background border rounded px-2 py-1.5 text-xs font-mono outline-none" value={seedLimit} onChange={(e) => setSeedLimit(Number(e.target.value || 0))} disabled={!seedFromModelRegistry} />
              </div>
              <div className="pt-3 border-t space-y-2 text-xs">
                <div className="flex justify-between">
                  <span className="text-muted-foreground flex items-center gap-1"><Calendar className="h-3 w-3" /> Last Settlement</span>
                  <span className="font-mono">{settledDate || "N/A"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground flex items-center gap-1"><Users className="h-3 w-3" /> Contestants</span>
                  <span>{leaderboard.length}</span>
                </div>
              </div>
              {reportHref && (
                <Button asChild variant="outline" className="w-full h-8 gap-1.5 text-xs">
                  <a href={reportHref} target="_blank" rel="noreferrer"><ExternalLink className="h-3 w-3" /> Full Report</a>
                </Button>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Leaderboard */}
        <Card className="lg:col-span-3">
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[60px] text-center">Rank</TableHead>
                  <TableHead>Participant</TableHead>
                  <TableHead className="text-right">NAV</TableHead>
                  <TableHead className="text-right">Daily Return</TableHead>
                  <TableHead className="text-right">Max DD</TableHead>
                  <TableHead className="text-right">Turnover</TableHead>
                  <TableHead className="text-center">Risk</TableHead>
                  <TableHead className="text-right w-[80px]">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {leaderboard.length === 0 ? (
                  <TableRow><TableCell colSpan={8} className="h-48 text-center text-muted-foreground text-sm">Loading leaderboard...</TableCell></TableRow>
                ) : (
                  leaderboard.map((r, i) => {
                    const rank = r.rank ?? i + 1;
                    return (
                      <Fragment key={i}>
                        <TableRow className="group">
                          <TableCell className="text-center">
                            {rank <= 3 ? (
                              <span className={cn("inline-flex h-7 w-7 items-center justify-center rounded-full text-white text-xs", rank === 1 ? "bg-amber-400" : rank === 2 ? "bg-slate-400" : "bg-amber-600")}>
                                {rank}
                              </span>
                            ) : (
                              <span className="text-xs font-mono text-muted-foreground">{rank}</span>
                            )}
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-col">
                              <span className="text-sm font-medium">{r.participant_name}</span>
                              <span className="text-[10px] text-muted-foreground font-mono">{r.run_id ? r.run_id.slice(0, 12) : "N/A"}</span>
                            </div>
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs">{formatNum(r.nav)}</TableCell>
                          <TableCell className={cn("text-right font-mono text-xs", (r.daily_return || 0) > 0 ? "text-green-500" : (r.daily_return || 0) < 0 ? "text-red-500" : "")}>
                            {formatPct(r.daily_return)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs text-muted-foreground">{formatPct(r.drawdown)}</TableCell>
                          <TableCell className="text-right font-mono text-xs">{formatPct(r.turnover)}</TableCell>
                          <TableCell className="text-center">
                            {(r.drawdown || 0) < -0.15 ? (
                              <Badge variant="destructive" className="text-[10px] px-1.5 py-0">High</Badge>
                            ) : (r.drawdown || 0) < -0.1 ? (
                              <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-yellow-400 border-yellow-500/30">Med</Badge>
                            ) : (
                              <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-green-400 border-green-500/30">Low</Badge>
                            )}
                          </TableCell>
                          <TableCell className="text-right">
                            <Button size="sm" variant="ghost" className="h-7 text-xs opacity-0 group-hover:opacity-100 transition-opacity" onClick={() => (r.model_version_id || r.run_id) && onCompare?.(r.model_version_id || r.run_id || "")}>
                              Compare
                            </Button>
                          </TableCell>
                        </TableRow>
                        {rank === 1 && r.edge_explanation && (
                          <TableRow className="bg-amber-500/5">
                            <TableCell colSpan={8} className="py-3 px-6 text-left border-l-2 border-amber-500">
                              <div className="flex items-start gap-2">
                                <Trophy className="h-3.5 w-3.5 text-amber-500 mt-0.5 flex-shrink-0" />
                                <div>
                                  <span className="text-[10px] uppercase font-semibold text-amber-600">Edge Analysis</span>
                                  <p className="text-xs text-muted-foreground mt-0.5">"{r.edge_explanation}"</p>
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
      </div>
    </div>
  );
}
