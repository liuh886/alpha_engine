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
  Loader2,
  RefreshCw,
  Search,
  ChevronUp,
  ChevronDown,
  Eye,
  X,
  Layers,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatNum, formatPct, useSort } from "@/lib/format";
import {
  STAGE_COLORS,
  ALL_STAGES,
  truncateExpression,
  stageIndex,
} from "./factor-registry/types";
import { FactorDetailDialog } from "./factor-registry/FactorDetailDialog";
import { RegistrySummaryCards } from "./factor-registry/RegistrySummaryCards";
import { apiFetch } from "@/lib/api";
import type {
  FactorStage,
  FactorWithValidation,
  FactorDetail,
  FactorValidationRecord,
  RegistryStats,
  ScanStats,
} from "./factor-registry/types";

type SortKey =
  | "none"
  | "name"
  | "category"
  | "direction"
  | "icir"
  | "t_stat"
  | "quintile_spread"
  | "stage";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function FactorRegistryPage() {
  // Data state
  const [factors, setFactors] = useState<FactorWithValidation[]>([]);
  const [stats, setStats] = useState<RegistryStats | null>(null);
  const [scanStats, setScanStats] = useState<ScanStats | null>(null);
  const [loading, setLoading] = useState(false);

  // Filter / sort state
  const [searchQuery, setSearchQuery] = useState("");
  const [stageFilter, setStageFilter] = useState<FactorStage | "all">("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const { sortKey, sortAsc, toggleSort, SortIcon } = useSort<SortKey>("none");

  // Detail modal state
  const [detailFactorId, setDetailFactorId] = useState<number | null>(null);
  const [detail, setDetail] = useState<FactorDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Action state
  const [actionId, setActionId] = useState<number | null>(null);

  // Expanded expressions
  const [expandedExpressions, setExpandedExpressions] = useState<Set<number>>(new Set());

  // ------------------------------------------------------------------
  // Data fetching
  // ------------------------------------------------------------------

  const loadRegistry = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await apiFetch("/api/factors/registry", { cache: "no-store" });
      if (!resp.ok) return;
      const json = await resp.json();
      if (json.ok) {
        setFactors(json.factors || []);
        setStats(json.stats || null);
        setScanStats(json.scan_stats || null);
      }
    } catch {
      /* server not running */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRegistry();
  }, [loadRegistry]);

  const loadDetail = useCallback(async (factorId: number) => {
    setDetailLoading(true);
    setDetail(null);
    try {
      const resp = await apiFetch(`/api/factors/registry/${factorId}`, {
        cache: "no-store",
      });
      if (!resp.ok) return;
      const json = await resp.json();
      if (json.ok) {
        setDetail(json);
      }
    } catch {
      /* ignore */
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    if (detailFactorId !== null) {
      loadDetail(detailFactorId);
    } else {
      setDetail(null);
    }
  }, [detailFactorId, loadDetail]);

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------

  const promoteFactor = async (factorId: number) => {
    setActionId(factorId);
    try {
      const resp = await apiFetch(`/api/factors/registry/${factorId}/promote`, {
        method: "POST",
      });
      const json = await resp.json();
      if (json.ok) {
        await loadRegistry();
        if (detailFactorId === factorId) await loadDetail(factorId);
      } else {
        alert(`Promotion failed: ${json.detail || "Unknown error"}`);
      }
    } catch {
      alert("Promotion request failed.");
    } finally {
      setActionId(null);
    }
  };

  const demoteFactor = async (factorId: number) => {
    if (!window.confirm("Demote this factor to Deprecated?")) return;
    setActionId(factorId);
    try {
      const resp = await apiFetch(`/api/factors/registry/${factorId}/demote`, {
        method: "POST",
      });
      const json = await resp.json();
      if (json.ok) {
        await loadRegistry();
        if (detailFactorId === factorId) await loadDetail(factorId);
      } else {
        alert(`Demotion failed: ${json.detail || "Unknown error"}`);
      }
    } catch {
      alert("Demotion request failed.");
    } finally {
      setActionId(null);
    }
  };

  // ------------------------------------------------------------------
  // Derived data
  // ------------------------------------------------------------------

  const categories = useMemo(() => {
    const cats = new Set<string>();
    factors.forEach((f) => cats.add(f.category));
    return Array.from(cats).sort();
  }, [factors]);

  const displayed = useMemo(() => {
    let list = [...factors];

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (f) =>
          f.name.toLowerCase().includes(q) ||
          f.expression.toLowerCase().includes(q) ||
          f.thesis.toLowerCase().includes(q)
      );
    }

    if (stageFilter !== "all") {
      list = list.filter((f) => f.stage === stageFilter);
    }

    if (categoryFilter !== "all") {
      list = list.filter((f) => f.category === categoryFilter);
    }

    if (sortKey !== "none") {
      list.sort((a, b) => {
        if (sortKey === "name") {
          return sortAsc ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
        }
        if (sortKey === "category") {
          return sortAsc ? a.category.localeCompare(b.category) : b.category.localeCompare(a.category);
        }
        if (sortKey === "direction") {
          return sortAsc ? a.direction.localeCompare(b.direction) : b.direction.localeCompare(a.direction);
        }
        if (sortKey === "stage") {
          const siA = stageIndex(a.stage);
          const siB = stageIndex(b.stage);
          return sortAsc ? siA - siB : siB - siA;
        }
        const va = a.latest_validation?.[sortKey as keyof FactorValidationRecord];
        const vb = b.latest_validation?.[sortKey as keyof FactorValidationRecord];
        const numA = typeof va === "number" ? va : null;
        const numB = typeof vb === "number" ? vb : null;
        if (numA === null && numB === null) return 0;
        if (numA === null) return 1;
        if (numB === null) return -1;
        return sortAsc ? numA - numB : numB - numA;
      });
    }

    return list;
  }, [factors, searchQuery, stageFilter, categoryFilter, sortKey, sortAsc]);

  // ------------------------------------------------------------------
  // Sort helpers
  // ------------------------------------------------------------------

  const toggleExpressionExpand = (factorId: number) => {
    setExpandedExpressions((prev) => {
      const next = new Set(prev);
      if (next.has(factorId)) {
        next.delete(factorId);
      } else {
        next.add(factorId);
      }
      return next;
    });
  };

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto pb-16">
      {/* Header */}
      <div className="border-b pb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Factor Registry</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Manage the factor lifecycle from proposal through validation and active use.
          </p>
        </div>
        <Button onClick={loadRegistry} variant="outline" size="sm" className="h-7 gap-1.5 text-xs">
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} /> Refresh
        </Button>
      </div>

      {/* Summary Cards */}
      <RegistrySummaryCards stats={stats} scanStats={scanStats} factorCount={factors.length} />

      {/* Factor Table */}
      <Card>
        <CardHeader className="pb-2 border-b flex flex-row items-center justify-between py-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Layers className="h-4 w-4" /> Factor Registry
          </CardTitle>
          <Badge variant="outline" className="text-xs">
            {displayed.length} factor{displayed.length !== 1 ? "s" : ""}
          </Badge>
        </CardHeader>
        <CardContent className="p-0">
          {/* Filters row */}
          <div className="flex flex-wrap items-end gap-3 px-4 py-3 border-b">
            <div className="space-y-1 flex-1 min-w-[200px] max-w-[320px]">
              <label className="text-xs text-muted-foreground">Search name / expression</label>
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                <Input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="e.g. momentum, Ref($close..."
                  className="h-7 pl-7 text-xs font-mono"
                />
                {searchQuery && (
                  <button onClick={() => setSearchQuery("")} className="absolute right-2 top-1/2 -translate-y-1/2">
                    <X className="h-3 w-3 text-muted-foreground hover:text-foreground" />
                  </button>
                )}
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Stage</label>
              <div className="flex gap-1 flex-wrap">
                <Button variant={stageFilter === "all" ? "default" : "outline"} size="sm" onClick={() => setStageFilter("all")} className="h-7 text-xs">All</Button>
                {ALL_STAGES.map((s) => (
                  <Button key={s} variant={stageFilter === s ? "default" : "outline"} size="sm" onClick={() => setStageFilter(s)} className="h-7 text-xs">{s}</Button>
                ))}
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Category</label>
              <select className="bg-background border rounded px-2 py-1.5 text-xs outline-none h-7" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
                <option value="all">All</option>
                {categories.map((c) => (<option key={c} value={c}>{c}</option>))}
              </select>
            </div>
          </div>

          {/* Table */}
          {loading ? (
            <div className="h-64 flex items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-primary opacity-50" />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="cursor-pointer select-none text-xs" onClick={() => toggleSort("name")}>
                    <span className="flex items-center gap-1">Name <SortIcon column="name" /></span>
                  </TableHead>
                  <TableHead className="text-xs">Expression</TableHead>
                  <TableHead className="cursor-pointer select-none text-xs" onClick={() => toggleSort("category")}>
                    <span className="flex items-center gap-1">Category <SortIcon column="category" /></span>
                  </TableHead>
                  <TableHead className="cursor-pointer select-none text-xs" onClick={() => toggleSort("direction")}>
                    <span className="flex items-center gap-1">Direction <SortIcon column="direction" /></span>
                  </TableHead>
                  <TableHead className="cursor-pointer select-none text-xs text-right" onClick={() => toggleSort("icir")}>
                    <span className="flex items-center gap-1 justify-end">ICIR <SortIcon column="icir" /></span>
                  </TableHead>
                  <TableHead className="cursor-pointer select-none text-xs text-right" onClick={() => toggleSort("t_stat")}>
                    <span className="flex items-center gap-1 justify-end">t-stat <SortIcon column="t_stat" /></span>
                  </TableHead>
                  <TableHead className="cursor-pointer select-none text-xs text-right" onClick={() => toggleSort("quintile_spread")}>
                    <span className="flex items-center gap-1 justify-end">Q Spread <SortIcon column="quintile_spread" /></span>
                  </TableHead>
                  <TableHead className="cursor-pointer select-none text-xs" onClick={() => toggleSort("stage")}>
                    <span className="flex items-center gap-1">Stage <SortIcon column="stage" /></span>
                  </TableHead>
                  <TableHead className="text-xs text-right w-[100px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {displayed.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} className="h-48 text-center text-muted-foreground text-sm">
                      {loading ? "Loading registry..." : "No factors found. Run a factor scan to populate the registry."}
                    </TableCell>
                  </TableRow>
                ) : (
                  displayed.map((f) => {
                    const val = f.latest_validation;
                    const isExpanded = expandedExpressions.has(f.id);
                    const isDoing = actionId === f.id;
                    const canPromote = f.stage !== "Active" && f.stage !== "Deprecated";
                    const canDemote = f.stage === "Active";

                    return (
                      <TableRow key={f.id} className="group">
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            <span className="text-sm font-medium">{f.name}</span>
                            <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0", STAGE_COLORS[f.stage])}>{f.stage}</Badge>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1">
                            <span className="font-mono text-xs text-muted-foreground cursor-pointer hover:text-foreground transition-colors" title={f.expression} onClick={() => toggleExpressionExpand(f.id)}>
                              {isExpanded ? f.expression : truncateExpression(f.expression)}
                            </span>
                            {f.expression.length > 45 && (
                              <button onClick={() => toggleExpressionExpand(f.id)} className="text-muted-foreground hover:text-foreground">
                                {isExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                              </button>
                            )}
                          </div>
                        </TableCell>
                        <TableCell><Badge variant="secondary" className="text-[10px]">{f.category}</Badge></TableCell>
                        <TableCell>
                          <span className={cn("text-xs font-mono", f.direction === "long" ? "text-green-500" : f.direction === "short" ? "text-red-500" : "text-muted-foreground")}>{f.direction}</span>
                        </TableCell>
                        <TableCell className="text-right">
                          <span className={cn("font-mono text-xs", val?.icir !== null && val?.icir !== undefined && val.icir >= 0.5 ? "text-green-500" : val?.icir !== null && val?.icir !== undefined && val.icir < 0 ? "text-red-500" : "")}>{formatNum(val?.icir, 2)}</span>
                        </TableCell>
                        <TableCell className="text-right">
                          <span className={cn("font-mono text-xs", val?.t_stat !== null && val?.t_stat !== undefined && val.t_stat >= 2.0 ? "text-green-500" : "")}>{formatNum(val?.t_stat, 2)}</span>
                        </TableCell>
                        <TableCell className="text-right">
                          <span className="font-mono text-xs">{formatPct(val?.quintile_spread)}</span>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={cn("text-[10px]", STAGE_COLORS[f.stage])}>{f.stage}</Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            <Button size="icon" variant="ghost" className="h-7 w-7 text-muted-foreground" title="View Details" onClick={() => setDetailFactorId(f.id)}>
                              <Eye className="h-3.5 w-3.5" />
                            </Button>
                            {canPromote && (
                              <Button size="icon" variant="ghost" className="h-7 w-7 text-green-500" title="Promote" onClick={() => promoteFactor(f.id)} disabled={isDoing}>
                                {isDoing ? <Loader2 className="h-3 w-3 animate-spin" /> : <ChevronUp className="h-3.5 w-3.5" />}
                              </Button>
                            )}
                            {canDemote && (
                              <Button size="icon" variant="ghost" className="h-7 w-7 text-red-500" title="Demote" onClick={() => demoteFactor(f.id)} disabled={isDoing}>
                                {isDoing ? <Loader2 className="h-3 w-3 animate-spin" /> : <ChevronDown className="h-3.5 w-3.5" />}
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Factor Detail Modal */}
      <FactorDetailDialog
        detailFactorId={detailFactorId}
        detail={detail}
        detailLoading={detailLoading}
        actionId={actionId}
        onClose={() => { setDetailFactorId(null); setDetail(null); }}
        onPromote={promoteFactor}
        onDemote={demoteFactor}
      />
    </div>
  );
}
