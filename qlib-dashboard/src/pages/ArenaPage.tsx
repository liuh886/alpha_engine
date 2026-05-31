import React, { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Loader2, Trophy, RefreshCw, ExternalLink, Target, Users, Calendar } from "lucide-react";
import { cn } from "@/lib/utils";
import { artifactUrl } from "@/lib/artifacts";

type Arena = { id: string; name: string; market: string; };
type LeaderboardRow = { rank?: number; participant_name?: string; nav?: number; daily_return?: number; drawdown?: number; turnover?: number; run_id?: string; model_version_id?: string; edge_explanation?: string; };
type ReportRow = { id: string; type: string; ref_id: string; date?: string; paths?: Record<string, string>; };

function formatPct(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return "N/A";
  return `${(value * 100).toFixed(2)}%`;
}

function formatNum(value?: number, digits = 4) {
  if (value === undefined || value === null || Number.isNaN(value)) return "N/A";
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

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

  const selectedArena = useMemo(() => arenas.find((a) => a.id === selectedArenaId) || null, [arenas, selectedArenaId]);

  const loadArenas = async () => {
    const resp = await fetch(artifactUrl.arenas);
    if (!resp.ok) return;
    const json = await resp.json();
    const parsed = (json?.arenas || []).map((r: any) => ({ id: r.id, name: r.name || r.id, market: r.market || "unknown" }));
    setArenas(parsed);
    if (parsed.length > 0 && !selectedArenaId) setSelectedArenaId(parsed[0].id);
  };

  const loadLeaderboard = async (arena: Arena) => {
    const resp = await fetch(artifactUrl.arenaLeaderboard(arena.id));
    if (!resp.ok) return;
    const json = await resp.json();
    setLeaderboard(json?.leaderboard || []);
    setSettledDate(String(json?.date || ""));
  };

  const loadLatestReport = async (arena: Arena) => {
    const resp = await fetch(artifactUrl.reports);
    if (!resp.ok) return;
    const json = await resp.json();
    const r = (json?.reports || []).find((rep: any) => rep.type === "arena_daily" && rep.ref_id === arena.id);
    if (r) setReport({ id: r.id, type: r.type, ref_id: r.ref_id, date: r.date, paths: r.paths });
  };

  const refreshSelected = async () => {
    if (!selectedArena) return;
    await loadLeaderboard(selectedArena);
    await loadLatestReport(selectedArena);
  };

  useEffect(() => { loadArenas(); }, []);
  useEffect(() => { if (selectedArena) refreshSelected(); }, [selectedArenaId]);

  const startSettle = async () => {
    if (!selectedArena) return;
    if (!window.confirm(`Start Arena Settlement for ${selectedArena.name}?`)) return;
    setRunning(true);
    const resp = await fetch("/api/arena/settle", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ market: selectedArena.market, arena_name: selectedArena.name, date: "latest", seed_from_model_registry: seedFromModelRegistry, limit: seedLimit }),
    });
    if (resp.ok) {
      const json = await resp.json();
      setJobId(json.job_id);
    } else { setRunning(false); }
  };

  useEffect(() => {
    if (!jobId) return;
    const timer = window.setInterval(async () => {
      const resp = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
      if (!resp.ok) return;
      const json = await resp.json();
      const st = String(json?.job?.status || "");
      setJobStatus(st);
      if (st === "succeeded" || st === "failed") {
        window.clearInterval(timer);
        setRunning(false);
        setJobId("");
        if (st === "succeeded") await refreshSelected();
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [jobId]);

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
                  <TableHead className="text-right w-[80px]">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {leaderboard.length === 0 ? (
                  <TableRow><TableCell colSpan={6} className="h-48 text-center text-muted-foreground text-sm">Loading leaderboard...</TableCell></TableRow>
                ) : (
                  leaderboard.map((r, i) => {
                    const rank = r.rank ?? i + 1;
                    return (
                      <React.Fragment key={i}>
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
                          <TableCell className="text-right">
                            <Button size="sm" variant="ghost" className="h-7 text-xs opacity-0 group-hover:opacity-100 transition-opacity" onClick={() => (r.model_version_id || r.run_id) && onCompare?.(r.model_version_id || r.run_id || "")}>
                              Compare
                            </Button>
                          </TableCell>
                        </TableRow>
                        {rank === 1 && r.edge_explanation && (
                          <TableRow className="bg-amber-500/5">
                            <TableCell colSpan={6} className="py-3 px-6 text-left border-l-2 border-amber-500">
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
                      </React.Fragment>
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
