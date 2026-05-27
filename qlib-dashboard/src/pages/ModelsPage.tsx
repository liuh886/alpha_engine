import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Loader2, Cpu, RefreshCw, Star, Trash2, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import { artifactUrl } from "@/lib/artifacts";

type ModelVersion = {
  id: string; tag?: string; name?: string; market?: string; model_type?: string; path?: string; run_id?: string; created_at?: string; description?: string; metrics?: Record<string, any>; params?: Record<string, any>;
};

type MarketFilter = "all" | "us" | "cn";

function shortId(value: string) {
  if (!value) return "";
  return value.length <= 8 ? value : value.slice(0, 8);
}

function safeJson(value: any, fallback: any) {
  if (!value) return fallback;
  if (typeof value === "object") return value;
  try { return JSON.parse(String(value)); } catch { return fallback; }
}

function formatPct(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return "N/A";
  const p = value > 0 ? "+" : "";
  return `${p}${(value * 100).toFixed(2)}%`;
}

export function ModelsPage() {
  const [market, setMarket] = useState<MarketFilter>("all");
  const [versions, setVersions] = useState<ModelVersion[]>([]);
  const [arenaParticipants, setArenaParticipants] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState<boolean>(false);
  const [actionId, setActionId] = useState<string>("");

  const load = async () => {
    setLoading(true);
    try {
      const resp = await fetch(artifactUrl.models);
      if (!resp.ok) return;
      const json = await resp.json();
      let rows = (json?.versions || []) as any[];
      if (market !== "all") rows = rows.filter(r => r.market === market);
      const parsed: ModelVersion[] = rows.filter((r) => r && r.id).map((r) => ({
        id: String(r.id), tag: String(r.tag || ""), name: String(r.name || ""), market: String(r.market || ""), model_type: String(r.model_type || ""), path: String(r.path || ""), run_id: String(r.run_id || ""), created_at: String(r.created_at || ""), description: String(r.description || ""),
        metrics: safeJson(r.metrics_json, {}),
        params: safeJson(r.params_json, {}),
      }));
      setVersions(parsed);

      const arenasResp = await fetch(artifactUrl.arenas);
      const arenasJson = await arenasResp.json();
      const pids = new Set<string>();
      for (const arena of (arenasJson.arenas || [])) {
        const lbResp = await fetch(artifactUrl.arenaLeaderboard(arena.id));
        const lbJson = await lbResp.json();
        (lbJson.leaderboard || []).forEach((p: any) => {
          if (p.run_id) pids.add(p.run_id);
        });
      }
      setArenaParticipants(pids);

    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [market]);

  const toggleArena = async (v: ModelVersion) => {
    if (!v.run_id) return;
    const isJoined = arenaParticipants.has(v.run_id);
    const mkt = String(v.market || "US").toUpperCase();

    setActionId(v.id);
    try {
      if (isJoined) {
        alert("Engine: Manual clear required for participants via CLI 'arena_clear'.");
      } else {
        const ok = window.confirm(`Seed ${v.tag || v.id} into ${mkt} Arena?`);
        if (!ok) return;
        await fetch("/api/arena/participants", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ arena_name: `${mkt} Arena`, run_id: v.run_id, name: v.tag || v.id }),
        });
        load();
      }
    } catch { /* ignore */ }
    finally { setActionId(""); }
  };

  const deleteModel = async (v: ModelVersion) => {
    if (!window.confirm(`PERMANENTLY DELETE model ${v.tag || v.id}? This will physically remove the .pkl file.`)) return;
    setActionId(v.id);
    try {
      const resp = await fetch("/api/models/delete", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version_id: v.id }),
      });
      if (resp.ok) load();
    } catch { /* ignore */ }
    finally { setActionId(""); }
  };

  const togglePromote = async (v: ModelVersion) => {
    const isRecommended = String(v.description).includes("RECOMMENDED");
    const newStage = isRecommended ? "STAGING" : "RECOMMENDED";
    if (!window.confirm(`Mark ${v.tag || v.id} as ${newStage}?`)) return;

    setActionId(v.id);
    try {
      const resp = await fetch("/api/models/promote", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version_id: v.id, stage: newStage }),
      });
      if (resp.ok) load();
    } catch { /* ignore */ }
    finally { setActionId(""); }
  };

  return (
    <div className="space-y-8 max-w-[1600px] mx-auto pb-20 text-left">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b pb-6">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-widest mb-1"><Cpu className="h-3.5 w-3.5" /> Model Asset Management</div>
          <h1 className="text-4xl font-black tracking-tight">Model Registry</h1>
          <p className="text-muted-foreground text-sm max-w-md">Comprehensive inventory of trained model instances, hyperparameters, and cross-market seeding status.</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="bg-muted p-1 rounded-lg flex gap-1 mr-2 border">
            {(["all", "us", "cn"] as const).map(m => (
              <button key={m} onClick={() => setMarket(m)} className={cn("px-3 py-1 text-[10px] uppercase font-black rounded-md transition-all", market === m ? "bg-background shadow-sm text-primary" : "text-muted-foreground hover:text-foreground")}>{m}</button>
            ))}
          </div>
          <Button onClick={load} variant="outline" size="sm" className="h-9 gap-2 shadow-sm border-primary/20 transition-all active:scale-95"><RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> Sync Assets</Button>
        </div>
      </div>

      <Card className="border-none shadow-xl overflow-hidden bg-card ring-1 ring-border/50">
        <CardContent className="p-0">
          <Table>
            <TableHeader className="bg-muted/30 border-b">
              <TableRow className="hover:bg-transparent text-left">
                <TableHead className="font-bold text-[10px] uppercase py-5 pl-8 w-[120px]">Version</TableHead>
                <TableHead className="font-bold text-[10px] uppercase w-[80px]">Mkt</TableHead>
                <TableHead className="font-bold text-[10px] uppercase">Identity & Logic</TableHead>
                <TableHead className="font-bold text-[10px] uppercase">Top Params</TableHead>
                <TableHead className="font-bold text-[10px] uppercase">Metrics</TableHead>
                <TableHead className="font-bold text-[10px] uppercase text-center w-[100px]">Arena</TableHead>
                <TableHead className="text-right font-bold text-[10px] uppercase pr-8 w-[150px]">Management</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {versions.length === 0 ? (
                <TableRow><TableCell colSpan={7} className="h-64 text-center text-muted-foreground italic uppercase tracking-widest text-[10px] font-black">Scanning model database...</TableCell></TableRow>
              ) : (
                versions.map((v) => {
                  const metrics = v.metrics || {};
                  const params = v.params || {};
                  const ann = Number(metrics?.annualized_return || metrics?.ann_ret || 0);
                  const isRecommended = String(v.description).includes("RECOMMENDED");
                  const isDoing = actionId === v.id;
                  const isArenaJoined = v.run_id ? arenaParticipants.has(v.run_id) : false;

                  return (
                    <TableRow key={v.id} className="group hover:bg-muted/10 transition-colors border-b last:border-0 text-left h-20">
                      <TableCell className="pl-8">
                        <div className="flex flex-col">
                          <span className="font-mono text-[11px] font-black text-primary">{shortId(v.id)}</span>
                          <span className="text-[9px] text-muted-foreground font-bold">{v.created_at}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="text-[9px] font-black uppercase px-1.5">{v.market}</Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-0.5">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-black tracking-tight">{v.tag || v.name}</span>
                            {isRecommended && <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400 drop-shadow-sm" />}
                          </div>
                          <span className="text-[10px] text-muted-foreground font-bold uppercase tracking-tighter opacity-60 italic">{v.model_type || 'LGBModel'}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1 max-w-[200px]">
                          {Object.entries(params).filter(([k]) => !['model_path', 'source_model_path', 'experiment_name'].includes(k)).slice(0, 3).map(([k, v]) => (
                            <span key={k} className="text-[9px] bg-muted px-1.5 py-0.5 rounded font-mono text-muted-foreground border border-border/50">
                              {k.split('_').map(word => word[0]).join('').toUpperCase()}:{String(v)}
                            </span>
                          ))}
                          {Object.keys(params).length === 0 && <span className="text-[9px] italic text-muted-foreground opacity-40">N/A</span>}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-4">
                          <div className="flex flex-col">
                            <span className="text-[9px] uppercase font-black text-muted-foreground/40">Ann.R</span>
                            <span className={cn("text-[11px] font-mono font-black", ann > 0 ? "text-emerald-500" : "text-rose-500")}>{formatPct(ann)}</span>
                          </div>
                          <div className="flex flex-col border-l pl-3 border-border/50">
                            <span className="text-[9px] uppercase font-black text-muted-foreground/40">Sharpe</span>
                            <span className="text-[11px] font-mono font-black">{(metrics?.sharpe || metrics?.information_ratio || 0).toFixed(2)}</span>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="text-center">
                        <div className="flex justify-center items-center h-full">
                          <input
                            type="checkbox"
                            checked={isArenaJoined}
                            onChange={() => toggleArena(v)}
                            disabled={isDoing}
                            className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary cursor-pointer transition-all"
                          />
                        </div>
                      </TableCell>
                      <TableCell className="pr-8 text-right">
                        <div className="flex justify-end gap-1.5 opacity-40 group-hover:opacity-100 transition-opacity">
                          <Button size="icon" variant="ghost" className={cn("h-8 w-8", isRecommended ? "text-amber-500 bg-amber-50" : "text-muted-foreground")} onClick={() => togglePromote(v)} disabled={isDoing}>
                            {isDoing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Star className={cn("h-4 w-4", isRecommended && "fill-current")} />}
                          </Button>
                          <Button size="icon" variant="ghost" className="h-8 w-8 text-primary hover:bg-primary/10" onClick={() => load()} title="Sync Details">
                            <Settings className="h-4 w-4" />
                          </Button>
                          <Button size="icon" variant="ghost" className="h-8 w-8 text-rose-500 hover:text-rose-700 hover:bg-rose-50" onClick={() => deleteModel(v)} disabled={isDoing}>
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
