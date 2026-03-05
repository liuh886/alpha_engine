import React, { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Loader2, Trophy, RefreshCw, ExternalLink, Settings2, Target, Users, Calendar, Layers, ShieldCheck, HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";

type Arena = { id: string; name: string; market: string; };
type LeaderboardRow = { rank?: number; participant_name?: string; nav?: number; daily_return?: number; drawdown?: number; turnover?: number; run_id?: string; model_version_id?: string; edge_explanation?: string; };
type ReportRow = { id: string; type: string; ref_id: string; date?: string; paths?: Record<string, string>; };

function formatPct(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return "N/A";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${(value * 100).toFixed(2)}%`;
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
  const [seedFromModelRegistry, setSeedFromModelRegistry] = useState<boolean>(true);
  const [seedLimit, setSeedLimit] = useState<number>(30);
  const [jobId, setJobId] = useState<string>("");
  const [jobStatus, setJobStatus] = useState<string>("");
  const [running, setRunning] = useState<boolean>(false);
  const [report, setReport] = useState<ReportRow | null>(null);

  const selectedArena = useMemo(() => arenas.find((a) => a.id === selectedArenaId) || null, [arenas, selectedArenaId]);

  const loadArenas = async () => {
    const resp = await fetch("/artifacts/arenas.json");
    if (!resp.ok) return;
    const json = await resp.json();
    const parsed = (json?.arenas || []).map((r: any) => ({ id: r.id, name: r.name || r.id, market: r.market || "unknown" }));
    setArenas(parsed);
    if (parsed.length > 0 && !selectedArenaId) setSelectedArenaId(parsed[0].id);
  };

  const loadLeaderboard = async (arena: Arena) => {
    const resp = await fetch(`/artifacts/arena_leaderboard_${encodeURIComponent(arena.id)}.json`);
    if (!resp.ok) return;
    const json = await resp.json();
    setLeaderboard(json?.leaderboard || []);
    setSettledDate(String(json?.date || ""));
  };

  const loadLatestReport = async (arena: Arena) => {
    const resp = await fetch(`/artifacts/reports.json`);
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
    if (!window.confirm(`Start Arena Settlement for ${selectedArena.name}? This will run 'arena_settle.py' to update all model NAVs.`)) return;
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
    <div className="space-y-8 max-w-[1400px] mx-auto text-left pb-20">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b pb-6">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-widest mb-1">
            <Trophy className="h-3.5 w-3.5" /> Competitive Evaluation
          </div>
          <h1 className="text-4xl font-black tracking-tight">Strategy Arena</h1>
          <p className="text-muted-foreground text-sm max-w-md">Real-time "Rolling Out-of-Sample" showdown. Models compete using live market data to prove actual trading efficacy.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={refreshSelected} variant="ghost" size="sm" className="h-9 gap-2 border border-border/50">
            <RefreshCw className={cn("h-3.5 w-3.5", running && "animate-spin")} /> Sync Results
          </Button>
          <Button onClick={startSettle} disabled={running} className="h-9 shadow-lg bg-primary hover:bg-primary/90 px-6 font-black uppercase text-[10px] tracking-widest">
            {running ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Target className="mr-2 h-4 w-4" />}
            {running ? `Settling (${jobStatus})` : "Settle Arena (Daily Update)"}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        <div className="lg:col-span-1 space-y-6">
          {/* Context / Purpose Card */}
          <div className="p-6 glass-panel border-primary/20 bg-primary/10 text-primary-foreground space-y-4 shadow-[0_0_30px_-5px_var(--primary)] text-left relative overflow-hidden">
            <div className="absolute top-0 right-0 w-32 h-32 bg-primary/20 rounded-full blur-2xl -translate-y-1/2 translate-x-1/2 pointer-events-none" />
            <h4 className="text-[10px] font-black uppercase tracking-[0.2em] flex items-center gap-2 opacity-90 relative z-10">
              <ShieldCheck className="h-4 w-4" /> Mission Critical
            </h4>
            <div className="space-y-2">
              <p className="text-xs font-bold leading-relaxed">
                What is Arena Settlement?
              </p>
              <p className="text-[10px] leading-relaxed text-white/60">
                The settlement process runs the actual trading logic on the latest market data for every participant. It recalculates positions, records daily returns, and updates the leaderboard.
              </p>
            </div>
            <div className="pt-2 border-t border-primary-foreground/20 space-y-2">
              <p className="text-[10px] font-black uppercase tracking-widest flex items-center gap-1.5 opacity-80">
                <HelpCircle className="h-3 w-3" /> Parameter Help
              </p>
              <ul className="space-y-1.5 text-[9px] font-medium opacity-90">
                <li><span className="font-bold opacity-100">Include Registry:</span> Automatically add models marked as 'RECOMMENDED' to this arena if they aren't already participating.</li>
                <li><span className="font-bold opacity-100">Max Contestants:</span> Caps the total number of models in the arena to prevent performance degradation.</li>
              </ul>
            </div>
          </div>

          <Card className="glass-panel border-none shadow-sm relative overflow-hidden">
            <CardHeader className="pb-4 relative z-10">
              <CardTitle className="text-[10px] font-black uppercase tracking-widest text-muted-foreground flex items-center gap-2 text-left">
                <Settings2 className="h-3.5 w-3.5" /> Execution Parameters
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2 text-left">
                <label className="text-[10px] uppercase font-bold text-muted-foreground">Active Market</label>
                <select className="w-full bg-background border border-border/50 rounded-lg px-3 py-2 text-xs outline-none transition-all font-bold" value={selectedArenaId} onChange={(e) => setSelectedArenaId(e.target.value)} disabled={!arenas.length}>
                  {arenas.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.market.toUpperCase()})</option>)}
                </select>
              </div>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <label className="text-[10px] uppercase font-bold text-muted-foreground cursor-pointer" htmlFor="seed">Include Registry Models</label>
                  <input id="seed" type="checkbox" className="h-3.5 w-3.5 rounded border-gray-300 text-primary focus:ring-primary" checked={seedFromModelRegistry} onChange={(e) => setSeedFromModelRegistry(e.target.checked)} />
                </div>
                <div className="space-y-2 text-left">
                  <label className="text-[10px] uppercase font-bold text-muted-foreground">Max Contestants</label>
                  <input type="number" className="w-full bg-background border border-border/50 rounded-lg px-3 py-2 text-xs outline-none font-mono" value={seedLimit} onChange={(e) => setSeedLimit(Number(e.target.value || 0))} disabled={!seedFromModelRegistry} />
                </div>
              </div>
              <div className="pt-4 border-t space-y-3">
                <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-tight">
                  <span className="text-muted-foreground flex items-center gap-1.5"><Calendar className="h-3 w-3" /> Last Settlement</span>
                  <span className="text-primary font-mono font-black">{settledDate || "N/A"}</span>
                </div>
                <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-tight">
                  <span className="text-muted-foreground flex items-center gap-1.5"><Users className="h-3 w-3" /> Live Contestants</span>
                  <span className="font-black">{leaderboard.length}</span>
                </div>
              </div>
              {reportHref && <Button asChild variant="outline" className="w-full h-10 gap-2 border-dashed text-[10px] font-black uppercase tracking-widest"><a href={reportHref} target="_blank" rel="noreferrer"><ExternalLink className="h-3.5 w-3.5" /> Full Performance Tearsheet</a></Button>}
            </CardContent>
          </Card>
        </div>

        <Card className="lg:col-span-3 overflow-hidden glass-panel border-none shadow-xl">
          <CardContent className="p-0">
            <Table>
              <TableHeader className="bg-black/20 backdrop-blur-md border-b border-white/5 sticky top-0 z-20 shadow-sm">
                <TableRow className="hover:bg-transparent border-none">
                  <TableHead className="w-[80px] font-bold text-[10px] uppercase text-center py-5 text-muted-foreground">Rank</TableHead>
                  <TableHead className="font-bold text-[10px] uppercase text-muted-foreground">Participant (Alpha Engine)</TableHead>
                  <TableHead className="text-right font-bold text-[10px] uppercase px-6 text-muted-foreground">Current NAV</TableHead>
                  <TableHead className="text-right font-bold text-[10px] uppercase px-6 text-emerald-500/80">24H Δ Return</TableHead>
                  <TableHead className="text-right font-bold text-[10px] uppercase px-6 text-muted-foreground opacity-50">Max Drawdown</TableHead>
                  <TableHead className="text-right font-bold text-[10px] uppercase pr-8 text-muted-foreground">Deep Analysis</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {leaderboard.length === 0 ? (
                  <TableRow><TableCell colSpan={6} className="h-96 text-center text-muted-foreground animate-pulse italic uppercase tracking-[0.3em] text-[10px] font-black">Connecting to Scoreboard API...</TableCell></TableRow>
                ) : (
                  leaderboard.map((r, i) => {
                    const rank = r.rank ?? i + 1;
                    const isTop3 = rank <= 3;
                    return (
                      <React.Fragment key={i}>
                        <TableRow className={cn("group transition-colors h-16", isTop3 && "bg-primary/[0.03] font-semibold")}>
                          <TableCell className="text-center">
                            {rank === 1 ? <div className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-amber-400 text-white shadow-md">🥇</div> :
                              rank === 2 ? <div className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-slate-300 text-white shadow-md">🥈</div> :
                                rank === 3 ? <div className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-amber-600/80 text-white shadow-md">🥉</div> :
                                  <span className="text-xs font-mono font-bold text-muted-foreground">{rank}</span>}
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-col text-left">
                              <span className="text-sm font-black tracking-tight uppercase">{r.participant_name}</span>
                              <span className="text-[9px] text-muted-foreground font-mono opacity-50 uppercase tracking-tighter">Instance: {r.run_id ? r.run_id.slice(0, 12) : "N/A"}</span>
                            </div>
                          </TableCell>
                          <TableCell className="text-right font-mono text-sm px-6 font-bold">{formatNum(r.nav, 4)}</TableCell>
                          <TableCell className={cn("text-right font-mono text-sm px-6 font-black", (r.daily_return || 0) > 0 ? "text-emerald-500" : (r.daily_return || 0) < 0 ? "text-rose-500" : "")}>{formatPct(r.daily_return)}</TableCell>
                          <TableCell className="text-right font-mono text-xs px-6 text-muted-foreground opacity-50">{formatPct(r.drawdown)}</TableCell>
                          <TableCell className="pr-8 text-right">
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-9 gap-2 text-primary opacity-0 group-hover:opacity-100 transition-all rounded-full hover:bg-primary/10 px-4 border border-transparent hover:border-primary/20"
                              onClick={() => (r.model_version_id || r.run_id) && onCompare?.(r.model_version_id || r.run_id || '')}
                            >
                              <span className="text-[10px] font-black uppercase tracking-widest">Compare</span>
                              <Layers className="h-3.5 w-3.5" />
                            </Button>
                          </TableCell>
                        </TableRow>
                        {rank === 1 && r.edge_explanation && (
                          <TableRow className="bg-amber-500/5 hover:bg-amber-500/10 border-b border-border/10">
                            <TableCell colSpan={6} className="py-4 px-8 text-left border-l-4 border-amber-500">
                              <div className="flex items-start gap-3">
                                <Trophy className="h-4 w-4 text-amber-500 mt-1 flex-shrink-0" />
                                <div className="space-y-1">
                                  <span className="text-[10px] uppercase font-black tracking-widest text-amber-600">Engine's Crowned Edge Analysis</span>
                                  <p className="text-xs font-bold text-muted-foreground/80 italic leading-relaxed">"{r.edge_explanation}"</p>
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
