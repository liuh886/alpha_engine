import { useEffect, useState, useMemo, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";
import { Loader2, RefreshCw, Target, AlertTriangle, PieChart, ChevronDown, ChevronUp, TrendingUp, ExternalLink, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatNum, formatPct, useSort } from "@/lib/format";
import { ContributionBar } from "./attribution/ContributionBar";
import { AttributionSummaryCards } from "./attribution/AttributionSummaryCards";
import { apiFetch } from "@/lib/api";
import {
  STATUS_COLORS,
  formatSignedPct,
  truncateExpression,
} from "./attribution/types";
import type {
  FactorAttribution,
  AttributionSummary,
  AttributionResponse,
} from "./attribution/types";

type MarketFilter = "US" | "CN";
type SortKey = "none" | "name" | "ic" | "return" | "risk" | "exposure";

const BENCHMARK_LABEL: Record<MarketFilter, string> = { US: "QQQ", CN: "CSI300" };

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AttributionPage() {
  const [summary, setSummary] = useState<AttributionSummary | null>(null);
  const [factors, setFactors] = useState<FactorAttribution[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [market, setMarket] = useState<MarketFilter>("US");
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 1);
    return d.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10));

  // Rolling attribution state
  const [showRolling, setShowRolling] = useState(false);
  const [rollingData, setRollingData] = useState<Array<Record<string, unknown>>>([]);
  const [rollingLoading, setRollingLoading] = useState(false);
  const [rollingFactors, setRollingFactors] = useState<string[]>([]);

  const { sortKey, sortAsc, toggleSort, SortIcon } = useSort<SortKey>("none");

  // ------------------------------------------------------------------
  // Data fetching
  // ------------------------------------------------------------------

  const loadAttribution = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiFetch("/api/factors/attribute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          market: market.toLowerCase(),
          start_date: startDate,
          end_date: endDate,
        }),
        cache: "no-store",
      });
      if (!resp.ok) {
        setError(`Server returned HTTP ${resp.status}`);
        return;
      }
      const json: AttributionResponse = await resp.json();
      if (json.ok) {
        setSummary(json.summary);
        setFactors(json.factors || []);
      } else {
        setError(json.error || "Attribution request failed");
      }
    } catch {
      setError("Cannot reach server. Check if the backend is running.");
    } finally {
      setLoading(false);
    }
  }, [market, startDate, endDate]);

  useEffect(() => {
    loadAttribution();
  }, [loadAttribution]);

  // Fetch rolling attribution
  const loadRolling = useCallback(async () => {
    setRollingLoading(true);
    try {
      const resp = await apiFetch("/api/factors/attribute/rolling", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          market: market.toLowerCase(),
          start_date: startDate,
          end_date: endDate,
          window_months: 12,
          step_months: 3,
        }),
        cache: "no-store",
      });
      const json = await resp.json().catch(() => ({}));
      // Backend returns { ok, result: { windows, factor_trends, window_labels } }
      const result = json.result as Record<string, unknown> | undefined;
      if (json.ok && result?.windows) {
        const windows = result.windows as Array<Record<string, unknown>>;
        const labels = (result.window_labels as string[]) || [];
        const trends = (result.factor_trends as Record<string, number[]>) || {};

        // Factor names from factor_trends keys (authoritative)
        const factorNames = Object.keys(trends);
        setRollingFactors(factorNames);

        // Build chart data: one point per window
        const chartData = windows.map((w: Record<string, unknown>, i: number) => {
          const point: Record<string, unknown> = { window: labels[i] || w.period || `W${i + 1}` };
          // Map each factor's contribution from its trend array
          factorNames.forEach((name) => {
            const arr = trends[name];
            if (arr && i < arr.length) {
              point[name] = arr[i];
            }
          });
          return point;
        });
        setRollingData(chartData);
      }
    } catch {
      // silent
    } finally {
      setRollingLoading(false);
    }
  }, [market, startDate, endDate]);

  useEffect(() => {
    if (showRolling && rollingData.length === 0) loadRolling();
  }, [showRolling]);

  // ------------------------------------------------------------------
  // Derived data
  // ------------------------------------------------------------------

  const sortedFactors = useMemo(() => {
    if (sortKey === "none") {
      return [...factors].sort(
        (a, b) => Math.abs(b.return_contribution) - Math.abs(a.return_contribution)
      );
    }
    const list = [...factors];
    list.sort((a, b) => {
      let va: number | string;
      let vb: number | string;
      switch (sortKey) {
        case "name":
          va = a.factor_name;
          vb = b.factor_name;
          return sortAsc ? (va as string).localeCompare(vb as string) : (vb as string).localeCompare(va as string);
        case "ic":
          va = a.ic; vb = b.ic; break;
        case "return":
          va = a.return_contribution; vb = b.return_contribution; break;
        case "risk":
          va = a.risk_contribution; vb = b.risk_contribution; break;
        case "exposure":
          va = a.exposure; vb = b.exposure; break;
        default:
          return 0;
      }
      if (va === vb) return 0;
      return sortAsc ? (va as number) - (vb as number) : (vb as number) - (va as number);
    });
    return list;
  }, [factors, sortKey, sortAsc]);

  const maxAbsContribution = useMemo(() => {
    if (!factors.length) return 0;
    return Math.max(...factors.map((f) => Math.abs(f.return_contribution)));
  }, [factors]);

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto pb-16">
      {/* Header */}
      <div className="border-b pb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Factor Attribution</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Decompose portfolio returns into factor contributions and residual alpha.
          </p>
          {/* Decision-ready metadata bar */}
          <div className="flex flex-wrap items-center gap-3 mt-2 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <Info className="h-3 w-3" />
              Benchmark: <span className="font-medium text-foreground">{BENCHMARK_LABEL[market]}</span>
            </span>
            <span className="text-muted-foreground/40">|</span>
            <span>Period: <span className="font-mono">{startDate}</span> to <span className="font-mono">{endDate}</span></span>
            <span className="text-muted-foreground/40">|</span>
            <span>Market: <span className="font-medium text-foreground">{market}</span></span>
            <span className="text-muted-foreground/40">|</span>
            <a
              href={`/api/evidence/research_run/attribution_${market.toLowerCase()}_${startDate}_${endDate}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 hover:text-foreground transition-colors"
            >
              Evidence <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        </div>
        <Button onClick={loadAttribution} variant="outline" size="sm" className="h-7 gap-1.5 text-xs">
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} /> Refresh
        </Button>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Market</label>
          <div className="flex gap-1">
            {(["US", "CN"] as const).map((m) => (
              <Button key={m} variant={market === m ? "default" : "outline"} size="sm" onClick={() => setMarket(m)} className="h-7 text-xs uppercase">{m}</Button>
            ))}
          </div>
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Start Date</label>
          <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-7 w-36 text-xs font-mono" />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">End Date</label>
          <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-7 w-36 text-xs font-mono" />
        </div>
        <Badge variant="outline" className="text-xs h-7">
          {factors.length} factor{factors.length !== 1 ? "s" : ""}
        </Badge>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-2 text-sm text-red-500 bg-red-500/10 border border-red-500/20 rounded p-3">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Summary Cards */}
      <AttributionSummaryCards summary={summary} />

      {/* Factor Contribution Bar Chart */}
      <Card>
        <CardHeader className="pb-3 border-b">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <PieChart className="h-4 w-4" /> Factor Return Contributions
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-4">
          {loading ? (
            <div className="h-48 flex items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-primary opacity-50" />
            </div>
          ) : sortedFactors.length === 0 ? (
            <div className="h-32 flex items-center justify-center text-muted-foreground text-sm">
              {error ? "Unable to load attribution data." : "No factor data available. Run an attribution analysis first."}
            </div>
          ) : (
            <div className="space-y-1.5">
              {sortedFactors.map((f) => (
                <ContributionBar key={f.factor_id} name={f.factor_name} value={f.return_contribution} maxValue={maxAbsContribution} />
              ))}
              <div className="flex items-center justify-center gap-6 pt-3 mt-3 border-t text-[10px] text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-sm bg-green-500/70" /> Positive contribution
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-sm bg-red-500/70" /> Negative contribution
                </span>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Rolling Attribution (collapsible) */}
      <Card>
        <CardHeader
          className="pb-3 border-b cursor-pointer"
          onClick={() => setShowRolling(!showRolling)}
        >
          <CardTitle className="text-sm font-semibold flex items-center justify-between">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4" /> Rolling Factor Attribution (12M Window)
            </div>
            {showRolling ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </CardTitle>
        </CardHeader>
        {showRolling && (
          <CardContent className="pt-4">
            {rollingLoading ? (
              <div className="h-48 flex items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-primary opacity-50" />
              </div>
            ) : rollingData.length === 0 ? (
              <div className="h-32 flex flex-col items-center justify-center gap-1 text-muted-foreground text-sm">
                <span>No rolling attribution data available.</span>
                <span className="text-xs text-muted-foreground/70">Ensure sufficient history exists (&gt;12 months) and re-run attribution.</span>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={rollingData}>
                  <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.1} />
                  <XAxis dataKey="window" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
                  <Tooltip
                    contentStyle={{ fontSize: 11, borderRadius: 8 }}
                    formatter={(value: number) => [`${value?.toFixed(2)}%`, ""]}
                  />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  {rollingFactors.slice(0, 8).map((name, i) => {
                    const colors = ["#22c55e", "#3b82f6", "#eab308", "#ef4444", "#8b5cf6", "#06b6d4", "#f97316", "#ec4899"];
                    return (
                      <Line
                        key={name}
                        type="monotone"
                        dataKey={name}
                        stroke={colors[i % colors.length]}
                        strokeWidth={1.5}
                        dot={false}
                      />
                    );
                  })}
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        )}
      </Card>

      {/* Detailed Attribution Table */}
      <Card>
        <CardHeader className="pb-2 border-b flex flex-row items-center justify-between py-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Target className="h-4 w-4" /> Detailed Factor Attribution
          </CardTitle>
          <Badge variant="outline" className="text-xs">
            {sortedFactors.length} factor{sortedFactors.length !== 1 ? "s" : ""}
          </Badge>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="h-64 flex items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-primary opacity-50" />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="cursor-pointer select-none text-xs" onClick={() => toggleSort("name")}>
                    <span className="flex items-center gap-1">Factor Name <SortIcon column="name" /></span>
                  </TableHead>
                  <TableHead className="text-xs">Factor Expression</TableHead>
                  <TableHead className="cursor-pointer select-none text-xs text-right" onClick={() => toggleSort("ic")}>
                    <span className="flex items-center gap-1 justify-end">IC <SortIcon column="ic" /></span>
                  </TableHead>
                  <TableHead className="cursor-pointer select-none text-xs text-right" onClick={() => toggleSort("return")}>
                    <span className="flex items-center gap-1 justify-end">Return Contrib. <SortIcon column="return" /></span>
                  </TableHead>
                  <TableHead className="cursor-pointer select-none text-xs text-right" onClick={() => toggleSort("risk")}>
                    <span className="flex items-center gap-1 justify-end">Risk Contrib. <SortIcon column="risk" /></span>
                  </TableHead>
                  <TableHead className="cursor-pointer select-none text-xs text-right" onClick={() => toggleSort("exposure")}>
                    <span className="flex items-center gap-1 justify-end">Exposure (&#946;) <SortIcon column="exposure" /></span>
                  </TableHead>
                  <TableHead className="text-xs">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedFactors.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="h-48 text-center text-muted-foreground text-sm">
                      {loading ? "Loading attribution data..." : "No factor attribution data available."}
                    </TableCell>
                  </TableRow>
                ) : (
                  sortedFactors.map((f) => (
                    <TableRow key={f.factor_id} className="group">
                      <TableCell>
                        <span className="text-sm font-medium">{f.factor_name}</span>
                      </TableCell>
                      <TableCell>
                        <span className="font-mono text-xs text-muted-foreground" title={f.factor_expression}>
                          {truncateExpression(f.factor_expression)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <span className={cn("font-mono text-xs", f.ic >= 0.05 ? "text-green-500" : f.ic < 0 ? "text-red-500" : "")}>
                          {formatNum(f.ic, 4)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <span className={cn("font-mono text-xs", f.return_contribution >= 0 ? "text-green-500" : "text-red-500")}>
                          {formatSignedPct(f.return_contribution)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <span className="font-mono text-xs">{formatPct(f.risk_contribution)}</span>
                      </TableCell>
                      <TableCell className="text-right">
                        <span className={cn("font-mono text-xs", f.exposure > 0.5 ? "text-blue-500" : f.exposure < -0.5 ? "text-yellow-500" : "")}>
                          {formatNum(f.exposure, 3)}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={cn("text-[10px]", STATUS_COLORS[f.status])}>{f.status}</Badge>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
