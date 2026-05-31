import { useEffect, useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { FileText, RefreshCw, ExternalLink, Download, Calendar, FlaskConical, Target, Archive } from "lucide-react";
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
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<ReportFilter>("all");
  const [search, setSearch] = useState("");
  const [exportRunning, setExportRunning] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const resp = await fetch(artifactUrl.reports);
      if (!resp.ok) return;
      const json = await resp.json();
      let rpts = json?.reports || [];
      if (filter !== "all") rpts = rpts.filter((r: any) => r.type === filter);
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
    if (!window.confirm(`Export ${filter} reports to ZIP?`)) return;
    setExportRunning(true);
    try {
      const resp = await fetch("/api/reports/export", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: filter === "all" ? "all" : filter, limit: 100 }),
      });
      if (!resp.ok) setExportRunning(false);
    } catch { setExportRunning(false); }
  };

  const filteredReports = useMemo(() => {
    return reports.filter(r => {
      if (!search) return true;
      const term = search.toLowerCase();
      return r.id.toLowerCase().includes(term) || r.ref_id.toLowerCase().includes(term) || r.type.toLowerCase().includes(term);
    });
  }, [reports, search]);

  const getReportIcon = (type: string) => {
    if (type === "arena_daily") return <Target className="h-4 w-4 text-red-500" />;
    if (type === "backtest") return <FlaskConical className="h-4 w-4 text-blue-500" />;
    if (type === "archive") return <Archive className="h-4 w-4 text-orange-500" />;
    return <FileText className="h-4 w-4 text-green-500" />;
  };

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto pb-16">
      <div className="border-b pb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Reports</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Backtest tearsheets, arena updates, and data exports.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={load} variant="outline" size="sm" className="h-7 gap-1.5 text-xs">
            <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} /> Refresh
          </Button>
          <Button onClick={startExport} disabled={exportRunning} size="sm" className="h-7 gap-1.5 text-xs">
            <Download className="h-3 w-3" /> {exportRunning ? "Exporting..." : "Export"}
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Type</label>
          <div className="flex gap-1">
            {(["all", "backtest", "arena_daily", "archive"] as const).map(f => (
              <Button key={f} variant={filter === f ? "default" : "outline"} size="sm" onClick={() => setFilter(f)} className="h-7 text-xs">
                {f === "all" ? "All" : f.replace("_", " ")}
              </Button>
            ))}
          </div>
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Search</label>
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="ID, ref, market..." className="h-7 w-48 text-xs" />
        </div>
        <Badge variant="outline" className="text-xs h-7">
          {filteredReports.length} report{filteredReports.length !== 1 ? "s" : ""}
        </Badge>
      </div>

      {/* Report Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {filteredReports.length === 0 ? (
          <div className="col-span-full py-16 flex flex-col items-center justify-center border-2 border-dashed rounded-lg bg-muted/30">
            <FileText className="h-8 w-8 text-muted-foreground/30 mb-2" />
            <p className="text-muted-foreground text-sm">{loading ? "Loading..." : "No reports found."}</p>
          </div>
        ) : (
          filteredReports.map((r) => {
            const href = toHref(r);
            const market = String(r.meta?.market || "global").toUpperCase();

            return (
              <Card key={r.id} className="group">
                <CardHeader className="pb-3 border-b">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2">
                      {getReportIcon(r.type)}
                      <div>
                        <CardTitle className="text-sm font-semibold">{r.type.replace("_", " ")}</CardTitle>
                        <span className="text-[10px] text-muted-foreground font-mono">{shortId(r.id)}</span>
                      </div>
                    </div>
                    <Badge variant="secondary" className="text-[10px] uppercase">{market}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="pt-3 space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground flex items-center gap-1"><Calendar className="h-3 w-3" /> Date</span>
                    <span>{r.date || "Unknown"}</span>
                  </div>
                  {r.meta?.model_type && (
                    <div className="flex justify-between text-xs">
                      <span className="text-muted-foreground flex items-center gap-1"><FlaskConical className="h-3 w-3" /> Model</span>
                      <span>{r.meta.model_type}</span>
                    </div>
                  )}
                  <div className="pt-2 border-t">
                    {href ? (
                      <Button asChild variant="outline" className="w-full h-8 gap-1.5 text-xs">
                        <a href={href} target="_blank" rel="noreferrer"><ExternalLink className="h-3 w-3" /> Open</a>
                      </Button>
                    ) : (
                      <Button disabled variant="outline" className="w-full h-8 text-xs text-muted-foreground">No artifact</Button>
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
