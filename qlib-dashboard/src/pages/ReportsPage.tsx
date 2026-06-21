import { useEffect, useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { FileText, RefreshCw, ExternalLink, Download, Calendar, FlaskConical, Target, Archive } from "lucide-react";
import { cn } from "@/lib/utils";
import { shortId } from "@/lib/format";
import { apiFetch } from "@/lib/api";

type ReportRow = { id: string; type: string; ref_id: string; date?: string; paths?: Record<string, string>; meta?: Record<string, unknown>; };
type ReportFilter = "all" | "backtest" | "arena_daily" | "archive";

export function ReportsPage() {
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<ReportFilter>("all");
  const [search, setSearch] = useState("");
  const [exportRunning, setExportRunning] = useState(false);
  const [openingId, setOpeningId] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const typeQuery = filter === "all" ? "" : `&type=${encodeURIComponent(filter)}`;
      const resp = await apiFetch(`/api/reports?limit=100${typeQuery}`);
      if (!resp.ok) return;
      const json = await resp.json();
      setReports(json?.reports || []);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [filter]);

  const openReport = async (r: ReportRow) => {
    const format = r.paths?.html ? "html" : r.paths?.zip ? "zip" : "";
    if (!format) return;
    const reportWindow = window.open("about:blank", "_blank");
    if (reportWindow) reportWindow.opener = null;
    setOpeningId(r.id);
    try {
      const resp = await apiFetch(`/api/reports/${encodeURIComponent(r.id)}/file?format=${format}`);
      if (!resp.ok) {
        reportWindow?.close();
        return;
      }
      const url = URL.createObjectURL(await resp.blob());
      if (reportWindow) reportWindow.location.href = url;
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      reportWindow?.close();
    } finally {
      setOpeningId("");
    }
  };

  const startExport = async () => {
    if (!window.confirm(`Export ${filter} reports to ZIP?`)) return;
    setExportRunning(true);
    try {
      const resp = await apiFetch("/api/reports/export", {
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
            const hasArtifact = Boolean(r.paths?.html || r.paths?.zip);
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
                  {r.meta?.model_type != null && (
                    <div className="flex justify-between text-xs">
                      <span className="text-muted-foreground flex items-center gap-1"><FlaskConical className="h-3 w-3" /> Model</span>
                      <span>{String(r.meta.model_type)}</span>
                    </div>
                  )}
                  <div className="pt-2 border-t">
                    {hasArtifact ? (
                      <Button
                        variant="outline"
                        className="w-full h-8 gap-1.5 text-xs"
                        disabled={openingId === r.id}
                        onClick={() => openReport(r)}
                      >
                        <ExternalLink className="h-3 w-3" /> {openingId === r.id ? "Opening..." : "Open"}
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
