import { useEffect, useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FileText, RefreshCw, Archive, ExternalLink, Download, Calendar, FlaskConical, Target, Zap, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { artifactUrl } from "@/lib/artifacts";

type ReportRow = { id: string; type: string; ref_id: string; date?: string; paths?: Record<string, string>; meta?: Record<string, any>; };
type ReportFilter = "all" | "backtest" | "arena_daily" | "archive";

function shortId(value: string) {
  if (!value) return "";
  return value.length <= 8 ? value : value.slice(0, 8);
}

export function ReportsPage() {
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [filter, setFilter] = useState<ReportFilter>("all");
  const [search, setSearch] = useState<string>("");
  const [exportJobId, setExportJobId] = useState<string>("");
  const [exportRunning, setExportRunning] = useState<boolean>(false);

  const load = async () => {
    setLoading(true);
    try {
      const resp = await fetch(artifactUrl.reports);
      if (!resp.ok) return;
      const json = await resp.json();
      let rpts = json?.reports || [];
      if (filter !== "all") {
        rpts = rpts.filter((r: any) => r.type === filter);
      }
      setReports(rpts);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [filter]);

  const toHref = (r: ReportRow) => {
    const p = r.paths?.html || r.paths?.zip || "";
    return p ? `/${String(p).replace(/^\/+/, "")}` : "";
  };

  const startExport = async () => {
    if (!window.confirm(`Export ${filter} reports to ZIP archive?`)) return;
    setExportRunning(true);
    try {
      const resp = await fetch("/api/reports/export", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: filter === "all" ? "all" : filter, limit: 100 }),
      });
      if (resp.ok) {
        const json = await resp.json();
        setExportJobId(json.job_id);
      } else { setExportRunning(false); }
    } catch { setExportRunning(false); }
  };

  useEffect(() => {
    if (!exportJobId) return;
    const timer = window.setInterval(async () => {
      const resp = await fetch(`/api/jobs/${encodeURIComponent(exportJobId)}`);
      if (!resp.ok) return;
      const json = await resp.json();
      const st = String(json?.job?.status || "");
      if (st === "succeeded" || st === "failed") {
        window.clearInterval(timer);
        setExportRunning(false);
        setExportJobId("");
        if (st === "succeeded") await load();
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [exportJobId]);

  const filteredReports = useMemo(() => {
    return reports.filter(r => {
      if (!search) return true;
      const term = search.toLowerCase();
      return r.id.toLowerCase().includes(term) || r.ref_id.toLowerCase().includes(term) || r.type.toLowerCase().includes(term) || String(r.meta?.market || "").toLowerCase().includes(term);
    });
  }, [reports, search]);

  const getReportIcon = (type: string) => {
    if (type === "arena_daily") return <Target className="h-5 w-5 text-red-500" />;
    if (type === "backtest") return <FlaskConical className="h-5 w-5 text-blue-500" />;
    if (type === "archive") return <Archive className="h-5 w-5 text-orange-500" />;
    return <FileText className="h-5 w-5 text-green-500" />;
  };

  return (
    <div className="space-y-8 max-w-[1600px] mx-auto pb-20 text-left">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 border-b pb-8">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-widest mb-1"><FileText className="h-3.5 w-3.5" /> Institutional Research</div>
          <h1 className="text-4xl font-black tracking-tight">Intelligence Library</h1>
          <p className="text-muted-foreground text-sm max-w-md">Access comprehensive HTML tearsheets for backtest analysis, daily arena updates, and data exports.</p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search ID, Ref, or Market..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 pr-4 py-2 bg-muted/30 border rounded-lg text-xs outline-none focus:border-primary transition-all w-64"
            />
          </div>
          <Button onClick={load} variant="ghost" size="sm" className="h-9 gap-2"><RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> Sync</Button>
          <Button onClick={startExport} disabled={exportRunning} variant="default" className="h-9 gap-2 shadow-md font-bold tracking-tight uppercase text-[10px]"><Download className="h-3.5 w-3.5" /> {exportRunning ? `Exporting` : "Export Archive"}</Button>
        </div>
      </div>

      <div className="flex gap-2 border-b border-border/50 pb-4">
        {(["all", "backtest", "arena_daily", "archive"] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "px-4 py-1.5 text-xs uppercase font-black rounded-full transition-all border",
              filter === f ? "bg-primary text-primary-foreground border-primary shadow-lg scale-105" : "bg-transparent text-muted-foreground hover:bg-muted border-transparent"
            )}
          >
            {f.replace('_', ' ')}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {filteredReports.length === 0 ? (
          <div className="col-span-full py-32 flex flex-col items-center justify-center bg-muted/10 rounded-3xl border-2 border-dashed">
            <Search className="h-10 w-10 text-muted-foreground/30 mb-4" />
            <p className="text-muted-foreground font-medium uppercase tracking-widest text-xs italic">{loading ? "Scanning archive..." : "No Intelligence Found"}</p>
          </div>
        ) : (
          filteredReports.map((r) => {
            const href = toHref(r);
            const market = String(r.meta?.market || "GLOBAL").toUpperCase();
            const isLatest = Date.now() - new Date(r.date || "").getTime() < 86400000 * 2; // within 2 days

            return (
              <Card key={r.id} className="border-none shadow-lg hover:shadow-xl transition-all group overflow-hidden bg-card flex flex-col">
                <CardHeader className="bg-muted/10 pb-4 flex flex-row items-start justify-between border-b">
                  <div className="flex gap-3">
                    <div className="mt-1 p-2 bg-background rounded-lg shadow-sm border border-border/50">
                      {getReportIcon(r.type)}
                    </div>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <CardTitle className="text-sm font-black uppercase tracking-tight">{r.type.replace('_', ' ')}</CardTitle>
                        {isLatest && <span className="bg-green-500/10 text-green-500 text-[8px] font-black uppercase px-1.5 py-0.5 rounded">NEW</span>}
                      </div>
                      <CardDescription className="text-xs font-mono font-bold text-muted-foreground">{shortId(r.id)}</CardDescription>
                    </div>
                  </div>
                  <Badge variant="outline" className="font-black text-[9px] uppercase border-primary/20 text-primary">{market}</Badge>
                </CardHeader>

                <CardContent className="pt-4 pb-4 flex-1 flex flex-col justify-between space-y-4">
                  <div className="space-y-3">
                    <div className="flex justify-between items-center text-xs">
                      <span className="text-muted-foreground flex items-center gap-1.5"><Calendar className="h-3.5 w-3.5" /> Date Created</span>
                      <span className="font-medium">{r.date || "Unknown"}</span>
                    </div>
                    <div className="flex justify-between items-center text-xs">
                      <span className="text-muted-foreground flex items-center gap-1.5"><Zap className="h-3.5 w-3.5" /> Reference Target</span>
                      <span className="font-mono text-primary bg-primary/5 px-2 py-0.5 rounded">{shortId(r.ref_id)}</span>
                    </div>
                    {r.meta?.model_type && (
                      <div className="flex justify-between items-center text-xs">
                        <span className="text-muted-foreground flex items-center gap-1.5"><FlaskConical className="h-3.5 w-3.5" /> Engine Spec</span>
                        <span className="font-medium capitalize">{r.meta.model_type}</span>
                      </div>
                    )}
                  </div>

                  <div className="pt-4 border-t mt-auto">
                    {href ? (
                      <Button asChild className="w-full h-10 gap-2 font-black uppercase tracking-widest text-[10px] group-hover:bg-primary transition-all">
                        <a href={href} target="_blank" rel="noreferrer">
                          Read Tearsheet <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      </Button>
                    ) : (
                      <Button disabled variant="outline" className="w-full h-10 text-[10px] font-bold italic text-muted-foreground bg-muted/50 border-dashed">
                        Artifact Not Bound
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })
        )}
      </div>
    </div>
  );
}
