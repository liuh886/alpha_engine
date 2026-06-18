import { useEffect, useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Loader2, RefreshCw, Star, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { shortId, formatPct, formatNum, useSort } from "@/lib/format";
import { artifactUrl } from "@/lib/artifacts";
import { apiFetch } from "@/lib/api";

type ModelVersion = {
  id: string; tag?: string; name?: string; market?: string; model_type?: string; path?: string; run_id?: string; created_at?: string; description?: string; metrics?: Record<string, number>; metrics_json?: string; params?: Record<string, unknown>; params_json?: string;
};

type MarketFilter = "all" | "us" | "cn";
type SortKey = "none" | "sharpe" | "return" | "mdd";

function safeJson(value: unknown, fallback: unknown) {
  if (!value) return fallback;
  if (typeof value === "object") return value;
  try { return JSON.parse(String(value)); } catch { return fallback; }
}

export function ModelsPage() {
  const [market, setMarket] = useState<MarketFilter>("all");
  const [versions, setVersions] = useState<ModelVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionId, setActionId] = useState("");
  const { sortKey, sortAsc, toggleSort, SortIcon } = useSort<SortKey>("none");
  const [minSharpe, setMinSharpe] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const resp = await apiFetch(artifactUrl.models);
      if (!resp.ok) return;
      const json = await resp.json();
      let rows = (json?.versions || []) as ModelVersion[];
      if (market !== "all") rows = rows.filter(r => r.market === market);
      const parsed: ModelVersion[] = rows.filter((r) => r && r.id).map((r) => ({
        id: String(r.id), tag: String(r.tag || ""), name: String(r.name || ""), market: String(r.market || ""), model_type: String(r.model_type || ""), path: String(r.path || ""), run_id: String(r.run_id || ""), created_at: String(r.created_at || ""), description: String(r.description || ""),
        metrics: safeJson(r.metrics_json, {}),
        params: safeJson(r.params_json, {}),
      }));
      setVersions(parsed);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [market]);

  const getMetric = (v: ModelVersion, key: string): number | null => {
    const m = v.metrics || {};
    const val = m[key] ?? m[key === "sharpe" ? "information_ratio" : key === "return" ? "annualized_return" : key === "mdd" ? "max_drawdown" : key];
    return val != null ? Number(val) : null;
  };

  const displayed = useMemo(() => {
    let list = [...versions];

    // Filter by min Sharpe
    const threshold = parseFloat(minSharpe);
    if (!isNaN(threshold)) {
      list = list.filter(v => {
        const s = getMetric(v, "sharpe");
        return s !== null && s >= threshold;
      });
    }

    // Sort
    if (sortKey !== "none") {
      const metricKey = sortKey === "sharpe" ? "sharpe" : sortKey === "return" ? "annualized_return" : "max_drawdown";
      list.sort((a, b) => {
        const va = getMetric(a, metricKey);
        const vb = getMetric(b, metricKey);
        if (va === null && vb === null) return 0;
        if (va === null) return 1;
        if (vb === null) return -1;
        return sortAsc ? va - vb : vb - va;
      });
    }

    return list;
  }, [versions, sortKey, sortAsc, minSharpe]);

  const deleteModel = async (v: ModelVersion) => {
    if (!window.confirm(`Delete model ${v.tag || v.id}?`)) return;
    setActionId(v.id);
    try {
      const resp = await apiFetch("/api/models/delete", {
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
      const resp = await apiFetch("/api/models/promote", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version_id: v.id, stage: newStage }),
      });
      const json = await resp.json();
      if (json.ok) {
        load();
      } else if (json.gate_failures?.length) {
        alert(`Promotion blocked:\n\n${json.gate_failures.join("\n")}`);
      }
    } catch { /* ignore */ }
    finally { setActionId(""); }
  };

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto pb-16">
      <div className="border-b pb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Model Registry</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Trained models with metrics. Sort by Sharpe, Return, or Max Drawdown.
          </p>
        </div>
        <Button onClick={load} variant="outline" size="sm" className="h-7 gap-1.5 text-xs">
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} /> Refresh
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Market</label>
          <div className="flex gap-1">
            {(["all", "us", "cn"] as const).map(m => (
              <Button key={m} variant={market === m ? "default" : "outline"} size="sm" onClick={() => setMarket(m)} className="h-7 text-xs uppercase">
                {m}
              </Button>
            ))}
          </div>
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Min Sharpe</label>
          <Input
            value={minSharpe}
            onChange={(e) => setMinSharpe(e.target.value)}
            placeholder="e.g. 0.5"
            className="h-7 w-28 text-xs font-mono"
            type="number"
            step="0.1"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Sort by</label>
          <div className="flex gap-1">
            {([["sharpe", "Sharpe"], ["return", "Return"], ["mdd", "MDD"]] as const).map(([key, label]) => (
              <Button key={key} variant={sortKey === key ? "default" : "outline"} size="sm" onClick={() => toggleSort(key)} className="h-7 text-xs gap-1">
                {label} <SortIcon column={key} />
              </Button>
            ))}
            {sortKey !== "none" && (
              <Button variant="ghost" size="sm" onClick={() => toggleSort("none")} className="h-7 text-xs text-muted-foreground">
                Clear
              </Button>
            )}
          </div>
        </div>
        <Badge variant="outline" className="text-xs h-7">
          {displayed.length} model{displayed.length !== 1 ? "s" : ""}
        </Badge>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[100px]">Version</TableHead>
                <TableHead className="w-[60px]">Mkt</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Model</TableHead>
                <TableHead className="cursor-pointer select-none" onClick={() => toggleSort("sharpe")}>
                  <span className="flex items-center gap-1">Sharpe <SortIcon column="sharpe" /></span>
                </TableHead>
                <TableHead className="cursor-pointer select-none" onClick={() => toggleSort("return")}>
                  <span className="flex items-center gap-1">Ann. Return <SortIcon column="return" /></span>
                </TableHead>
                <TableHead className="cursor-pointer select-none" onClick={() => toggleSort("mdd")}>
                  <span className="flex items-center gap-1">Max DD <SortIcon column="mdd" /></span>
                </TableHead>
                <TableHead className="text-right w-[80px]">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {displayed.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="h-48 text-center text-muted-foreground text-sm">
                    {loading ? "Loading models..." : "No models found."}
                  </TableCell>
                </TableRow>
              ) : (
                displayed.map((v) => {
                  const sharpe = getMetric(v, "sharpe");
                  const annRet = getMetric(v, "annualized_return");
                  const mdd = getMetric(v, "max_drawdown");
                  const isRecommended = String(v.description).includes("RECOMMENDED");
                  const isDoing = actionId === v.id;

                  return (
                    <TableRow key={v.id} className="group">
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-mono text-xs">{shortId(v.id)}</span>
                          <span className="text-[10px] text-muted-foreground">{v.created_at?.slice(0, 10)}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="text-[10px] uppercase">{v.market}</Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm font-medium">{v.tag || v.name}</span>
                          {isRecommended && <Star className="h-3 w-3 fill-amber-400 text-amber-400" />}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{v.model_type || "LGBModel"}</TableCell>
                      <TableCell>
                        <span className={cn("font-mono text-xs", sharpe !== null && sharpe >= 1 ? "text-green-500" : sharpe !== null && sharpe < 0 ? "text-red-500" : "")}>
                          {formatNum(sharpe)}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className={cn("font-mono text-xs", annRet !== null && annRet > 0 ? "text-green-500" : annRet !== null ? "text-red-500" : "")}>
                          {formatPct(annRet)}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className={cn("font-mono text-xs", mdd !== null && Math.abs(mdd) > 0.2 ? "text-red-500" : "")}>
                          {formatPct(mdd)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <Button size="icon" variant="ghost" className={cn("h-7 w-7", isRecommended ? "text-amber-500" : "text-muted-foreground")} onClick={() => togglePromote(v)} disabled={isDoing}>
                            {isDoing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Star className={cn("h-3.5 w-3.5", isRecommended && "fill-current")} />}
                          </Button>
                          <Button size="icon" variant="ghost" className="h-7 w-7 text-red-500" onClick={() => deleteModel(v)} disabled={isDoing}>
                            <Trash2 className="h-3.5 w-3.5" />
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
