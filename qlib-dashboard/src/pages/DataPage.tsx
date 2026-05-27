import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Database, Loader2, CheckCircle2, AlertCircle, RefreshCw, Activity, Server, ShieldAlert, Download, HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { artifactUrl } from "@/lib/artifacts";

type DataStatus = {
  latest_calendar_day?: string;
  latest_snapshot_id?: string;
  dashboard_db_generated_at?: string;
  quality_warnings?: string[];
  quality_warnings_count?: number;
};

type QualityAll = {
  snapshot_id?: string;
  latest_calendar_day?: string;
  markets?: Record<string, any>;
  warnings?: string[];
  generated_at?: string;
};

export function DataPage() {
  const [loading, setLoading] = useState<boolean>(false);
  const [updating, setUpdating] = useState<boolean>(false);
  const [dataStatus, setDataStatus] = useState<DataStatus>({});
  const [quality, setQuality] = useState<QualityAll | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const resp = await fetch(artifactUrl.dataStatus, { cache: "no-store" });
      if (resp.ok) {
        const json = await resp.json();
        setDataStatus((json?.data || {}) as DataStatus);
      }
    } catch { /* ignore */ }

    try {
      const resp = await fetch(artifactUrl.dataQuality, { cache: "no-store" });
      if (resp.ok) {
        const json = await resp.json();
        const rep = json?.quality;
        const summary = rep?.summary || null;
        if (summary && typeof summary === "object") {
          setQuality(summary as QualityAll);
        } else {
          setQuality(null);
        }
      }
    } catch (e) {
      setQuality(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const triggerUpdate = async (full: boolean) => {
    const type = full ? "FULL RE-INGESTION" : "INCREMENTAL UPDATE";
    if (!window.confirm(`Start ${type}? 
Full re-ingestion will wipe local cache and fetch everything. 
Incremental update only fetches the last 30 days.`)) return;

    setUpdating(true);
    try {
      const resp = await fetch("/api/data/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full, lookback_days: full ? 3650 : 30 })
      });
      if (resp.ok) {
        alert("Engine: Data pipeline task dispatched. Use System Console to track progress.");
      }
    } catch (e) {
      console.error(e);
    } finally {
      setUpdating(false);
    }
  };

  const marketRows = useMemo(() => {
    const m = quality?.markets || {};
    if (!m || typeof m !== "object") return [];
    return Object.keys(m).sort().map((k) => ({ market: k, ...(m[k] || {}) }));
  }, [quality]);

  const warnings = (quality?.warnings || dataStatus.quality_warnings || []) as string[];
  const hasWarnings = warnings.length > 0;

  return (
    <div className="space-y-8 max-w-[1400px] mx-auto pb-20 text-left">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b pb-6">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-widest mb-1">
            <Server className="h-3.5 w-3.5" /> Data Infrastructure
          </div>
          <h1 className="text-4xl font-black tracking-tight">Market Data Hub</h1>
          <p className="text-muted-foreground text-sm max-w-md">Global dataset synchronization, snapshot integrity monitoring, and ingestion pipeline control.</p>
        </div>

        <div className="flex items-center gap-3">
          <Button onClick={load} disabled={loading} variant="ghost" size="sm" className="h-9 gap-2 border border-border/50 font-bold uppercase text-[10px]">
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            Sync Dashboard
          </Button>
          <Button onClick={() => triggerUpdate(false)} disabled={updating} variant="outline" className="h-9 gap-2 font-black uppercase text-[10px] tracking-widest px-4 border-primary/20 text-primary">
            <Activity className="h-3.5 w-3.5" />
            Incremental
          </Button>
          <Button onClick={() => triggerUpdate(true)} disabled={updating} variant="default" className="h-9 gap-2 shadow-lg font-black uppercase text-[10px] tracking-widest px-6">
            {updating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            Full Ingest
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
        <div className="space-y-6">
          <Card className="border-none shadow-lg bg-card overflow-hidden ring-1 ring-border/50">
            <CardHeader className="bg-muted/10 pb-4 border-b">
              <CardTitle className="text-[10px] font-black uppercase tracking-widest flex items-center gap-2 text-left">
                <Activity className="h-4 w-4 text-blue-500" /> Ingestion Status
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-6 space-y-4">
              <div className="flex justify-between items-center border-b border-dashed pb-3">
                <span className="text-[10px] font-bold text-muted-foreground uppercase">Universal Calendar</span>
                <span className="font-mono text-xs font-black text-primary">{dataStatus.latest_calendar_day || "OFFLINE"}</span>
              </div>
              <div className="flex justify-between items-center border-b border-dashed pb-3">
                <span className="text-[10px] font-bold text-muted-foreground uppercase">Active Snapshot</span>
                <span className="font-mono text-[10px] bg-primary/10 text-primary px-2 py-0.5 rounded font-black tracking-tighter">
                  {dataStatus.latest_snapshot_id || "NONE_LOADED"}
                </span>
              </div>
              <div className="flex justify-between items-center border-b border-dashed pb-3">
                <span className="text-[10px] font-bold text-muted-foreground uppercase">Data Directory</span>
                <span className="font-mono text-[9px] text-muted-foreground font-bold truncate max-w-[120px]">
                  /data/watchlist
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-[10px] font-bold text-muted-foreground uppercase">Hub Last Sync</span>
                <span className="font-mono text-[9px] text-muted-foreground font-bold">
                  {dataStatus.dashboard_db_generated_at ? new Date(dataStatus.dashboard_db_generated_at).toLocaleString() : "N/A"}
                </span>
              </div>
            </CardContent>
          </Card>

          <div className="p-6 bg-blue-500/5 rounded-2xl border border-blue-500/10 space-y-4">
            <h4 className="text-[10px] font-black uppercase tracking-widest text-blue-600 flex items-center gap-2">
              <HelpCircle className="h-3.5 w-3.5" /> Ingestion Guide
            </h4>
            <div className="space-y-3">
              <div className="space-y-1">
                <p className="text-[10px] font-black text-blue-700 uppercase">Incremental Update</p>
                <p className="text-[9px] leading-relaxed text-muted-foreground font-medium">Fetches only the last 30 days of market data. Best for daily maintenance.</p>
              </div>
              <div className="space-y-1 pt-1 border-t border-blue-500/5">
                <p className="text-[10px] font-black text-blue-700 uppercase">Full Re-Ingest</p>
                <p className="text-[9px] leading-relaxed text-muted-foreground font-medium">Reloads 10 years of historical data. Required if local cache is corrupted or starting fresh.</p>
              </div>
            </div>
          </div>
        </div>

        <div className="xl:col-span-2 space-y-8">
          <Card className="border-none shadow-xl bg-card overflow-hidden ring-1 ring-border/50">
            <CardHeader className="bg-muted/10 pb-4 border-b flex flex-row items-center justify-between px-8 py-5">
              <div className="flex items-center gap-3">
                <Database className="h-5 w-5 text-emerald-500" />
                <div className="space-y-0.5">
                  <CardTitle className="text-sm font-black uppercase tracking-widest text-left">Market Coverage Analytics</CardTitle>
                  <p className="text-[9px] font-bold text-muted-foreground uppercase">Real-time stats from local watchlist binary cache</p>
                </div>
              </div>
              {hasWarnings ? (
                <Badge variant="destructive" className="animate-pulse gap-1 font-black text-[9px] px-2 py-0.5"><AlertCircle className="h-3 w-3" /> ISSUES</Badge>
              ) : (
                <Badge variant="outline" className="text-green-600 border-green-500/30 gap-1 font-black text-[9px] px-2 py-0.5 bg-green-50"><CheckCircle2 className="h-3 w-3" /> HEALTHY</Badge>
              )}
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader className="bg-muted/5 border-b">
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="font-black text-[10px] uppercase py-4 pl-8">Venue</TableHead>
                    <TableHead className="text-right font-black text-[10px] uppercase">Instruments</TableHead>
                    <TableHead className="text-right font-black text-[10px] uppercase">Data Range</TableHead>
                    <TableHead className="text-right font-black text-[10px] uppercase text-orange-500">Stale</TableHead>
                    <TableHead className="text-right font-black text-[10px] uppercase text-rose-500 pr-8">Parse Errors</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {marketRows.length === 0 ? (
                    <TableRow><TableCell colSpan={5} className="h-48 text-center text-muted-foreground italic uppercase tracking-[0.2em] text-[10px] font-black">Connecting to Telemetry Hub...</TableCell></TableRow>
                  ) : (
                    marketRows.map((r) => (
                      <TableRow key={r.market} className="hover:bg-muted/20 transition-colors border-b last:border-0 h-16">
                        <TableCell className="pl-8">
                          <Badge variant="outline" className="uppercase font-black border-primary/20 text-primary px-3 py-0.5 tracking-widest text-[9px]">{String(r.market)}</Badge>
                        </TableCell>
                        <TableCell className="text-right font-mono text-sm font-black">{String(r.instruments ?? "0")}</TableCell>
                        <TableCell className="text-right font-mono text-[10px] font-bold text-muted-foreground">
                          {r.instrument_end_max ? `${String(r.instrument_end_max)}` : "N/A"}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs text-orange-500 font-bold">{String(r.stale_instruments ?? "0")}</TableCell>
                        <TableCell className="text-right font-mono text-xs text-rose-500 pr-8 font-bold">{String(r.csv_parse_errors ?? "0")}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {hasWarnings && (
            <Card className="border-none shadow-lg bg-rose-500/[0.03] border border-rose-500/20 text-left">
              <CardHeader className="pb-3 border-b border-rose-500/10">
                <CardTitle className="text-[10px] font-black uppercase tracking-[0.2em] text-rose-600 flex items-center gap-2">
                  <ShieldAlert className="h-4 w-4" /> Integrity Faults ({warnings.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4">
                <ul className="text-[10px] text-rose-600 font-mono space-y-2 list-none">
                  {warnings.map((w, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="opacity-40">→</span>
                      <span className="font-bold">{String(w)}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
