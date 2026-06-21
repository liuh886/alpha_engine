import { useEffect, useState, useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Loader2, RefreshCw, Star, Trash2, ExternalLink, AlertTriangle, Layers, GitBranch, ChevronDown, ChevronRight, Link2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { shortId, useSort } from "@/lib/format";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { ReleaseOutcome } from "@/components/ReleaseOutcome";
import { useMutation } from "@/hooks/useMutation";
import { useQuery } from "@/hooks/useQuery";
import { releaseApi } from "@/lib/release-api";
import { parseReleaseIdentity, releaseSearch, resolveEvidenceIdentity, type OutcomeSummary } from "@/lib/release-workflow";
import type { EvidenceBundleResponse, ModelPromoteResponse, ModelVersion } from "@/lib/api-types";
import {
  formatMetricValue,
  lookupMetricValue,
  getMetricDefinition,
} from "@/types/metrics";

type MarketFilter = "all" | "us" | "cn";
type SortKey = "none" | "Sharpe Ratio" | "Annualized Return" | "Max Drawdown";

function safeJson<T>(value: unknown, fallback: T): T {
  if (!value) return fallback;
  if (typeof value === "object") return value as T;
  try { return JSON.parse(String(value)) as T; } catch { return fallback; }
}

const BENCHMARK_BY_MARKET: Record<string, string> = { us: "QQQ", cn: "CSI300" };
const STALE_THRESHOLD_DAYS = 14;

const STAGE_ORDER = ["CANDIDATE", "STAGING", "RECOMMENDED"] as const;
type Stage = (typeof STAGE_ORDER)[number];

function parseStage(description: string | undefined): Stage {
  if (!description) return "CANDIDATE";
  const upper = description.toUpperCase();
  for (const stage of STAGE_ORDER) {
    if (upper.includes(stage)) return stage;
  }
  return "CANDIDATE";
}

const STAGE_BADGE: Record<Stage, { variant: "default" | "secondary" | "outline"; className: string }> = {
  CANDIDATE: { variant: "outline", className: "text-[10px] text-muted-foreground border-muted-foreground/30" },
  STAGING: { variant: "secondary", className: "text-[10px] bg-blue-500/10 text-blue-600 border-blue-500/30" },
  RECOMMENDED: { variant: "default", className: "text-[10px] bg-green-500/10 text-green-700 border-green-500/30" },
};

function modelAgeDays(createdAt: string | undefined): number | null {
  if (!createdAt) return null;
  const ms = Date.now() - new Date(createdAt).getTime();
  return ms / 86_400_000;
}

export function ModelsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const routeIdentity = parseReleaseIdentity(location.search);
  const { confirm, ConfirmDialog } = useConfirm();
  const [market, setMarket] = useState<MarketFilter>("all");
  const [actionId, setActionId] = useState("");
  const { sortKey, sortAsc, toggleSort, SortIcon } = useSort<SortKey>("none");
  const [searchText, setSearchText] = useState("");
  const [minSharpe, setMinSharpe] = useState("");
  const [gateFailures, setGateFailures] = useState<Record<string, string[]>>({});
  const [selectedForCompare, setSelectedForCompare] = useState<string[]>([]);
  const [actionOutcome, setActionOutcome] = useState<OutcomeSummary | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const modelsQuery = useQuery({
    queryKey: market,
    fetcher: (signal) => releaseApi.listModels(market, signal),
  });

  const versions = useMemo(() => (modelsQuery.data?.versions ?? [])
    .filter((row) => row?.id)
    .map((row) => ({
      ...row,
      id: String(row.id),
      metrics: safeJson<Record<string, number>>(row.metrics ?? row.metrics_json, {}),
      params: safeJson<Record<string, unknown>>(row.params ?? row.params_json, {}),
    })), [modelsQuery.data]);

  useEffect(() => {
    if (routeIdentity.modelId && versions.some((version) => version.id === routeIdentity.modelId)) {
      setSelectedForCompare((current) => current.length > 0 ? current : [routeIdentity.modelId!]);
    }
  }, [routeIdentity.modelId, versions]);

  // Compare selection is driven by URL identity; toggleCompareSelect removed
  // as the expand button replaced the per-row checkbox.

  const getModelMetric = (v: ModelVersion, key: string): number | null => {
    const def = getMetricDefinition(key);
    if (def) return lookupMetricValue(v.metrics ?? undefined, def);
    const m = v.metrics || {};
    const val = m[key];
    return val != null ? Number(val) : null;
  };

  const displayed = useMemo(() => {
    let list = [...versions];

    // Filter by search text (matches id, tag, name, market, model_type)
    const query = searchText.trim().toLowerCase();
    if (query) {
      list = list.filter(v =>
        v.id?.toLowerCase().includes(query) ||
        v.tag?.toLowerCase().includes(query) ||
        v.name?.toLowerCase().includes(query) ||
        v.market?.toLowerCase().includes(query) ||
        v.model_type?.toLowerCase().includes(query)
      );
    }

    // Filter by min Sharpe
    const threshold = parseFloat(minSharpe);
    if (!isNaN(threshold)) {
      list = list.filter(v => {
        const s = getModelMetric(v, "Sharpe Ratio");
        return s !== null && s >= threshold;
      });
    }

    // Sort
    if (sortKey !== "none") {
      list.sort((a, b) => {
        const va = getModelMetric(a, sortKey);
        const vb = getModelMetric(b, sortKey);
        if (va === null && vb === null) return 0;
        if (va === null) return 1;
        if (vb === null) return -1;
        return sortAsc ? va - vb : vb - va;
      });
    }

    return list;
  }, [versions, sortKey, sortAsc, minSharpe, searchText]);

  const registryOutcome = useMemo<OutcomeSummary>(() => {
    if (modelsQuery.loading && !modelsQuery.data) return { state: "loading", reason: "Loading the model registry." };
    if (modelsQuery.error) return { state: "failed", reason: modelsQuery.error };
    if (versions.length === 0) return { state: "empty", reason: "No registered model artifacts are available." };
    if (!routeIdentity.modelId) return { state: "success", reason: `${versions.length} model artifacts are available.` };

    const exact = versions.find((version) => version.id === routeIdentity.modelId);
    if (!exact) return { state: "partial", reason: `Model ${routeIdentity.modelId} is not present in this registry view.` };
    if (routeIdentity.runId && exact.run_id !== routeIdentity.runId) {
      return { state: "blocked", reason: `Model ${exact.id} is bound to run ${exact.run_id || "unknown"}, not ${routeIdentity.runId}.` };
    }
    const modelSnapshot = String(exact.snapshot_id || exact.params?.data_snapshot_id || "");
    if (routeIdentity.snapshotId && modelSnapshot && modelSnapshot !== routeIdentity.snapshotId) {
      return { state: "blocked", reason: `Model ${exact.id} is bound to snapshot ${modelSnapshot}, not ${routeIdentity.snapshotId}.` };
    }
    const age = modelAgeDays(exact.created_at);
    if (age !== null && age > STALE_THRESHOLD_DAYS) {
      return { state: "stale", reason: `Exact model ${exact.id} is ${Math.floor(age)} days old.` };
    }
    return { state: "success", reason: `Exact release model is available: ${exact.id} / ${exact.run_id || "run unknown"}.` };
  }, [modelsQuery.data, modelsQuery.error, modelsQuery.loading, routeIdentity.modelId, routeIdentity.runId, routeIdentity.snapshotId, versions]);

  const deleteMutation = useMutation<boolean, ModelVersion>({
    mutateFn: async (version) => (await releaseApi.deleteModel(version.id)).ok,
    onSuccess: () => {
      setActionId("");
      setActionOutcome({ state: "success", reason: "Model artifact deleted." });
      modelsQuery.refetch();
    },
    onError: (message) => {
      setActionId("");
      setActionOutcome({ state: "failed", reason: message });
    },
  });

  const promoteMutation = useMutation<ModelPromoteResponse, { version: ModelVersion; stage: string }>({
    mutateFn: ({ version, stage }) => releaseApi.promoteModel(version.id, stage),
    onSuccess: (result, { version }) => {
      setActionId("");
      if (result.ok) {
        setActionOutcome({ state: "success", reason: `Model ${version.id} stage updated.` });
        modelsQuery.refetch();
      } else {
        const failures = result.gate_failures ?? ["Promotion gates did not pass."];
        setGateFailures((current) => ({ ...current, [version.id]: failures }));
        setActionOutcome({ state: "blocked", reason: failures.join(" ") });
      }
    },
    onError: (message, { version }) => {
      setActionId("");
      setActionOutcome({ state: "failed", reason: `Model ${version.id}: ${message}` });
    },
  });

  const evidenceMutation = useMutation<EvidenceBundleResponse, ModelVersion>({
    mutateFn: (version) => releaseApi.getModelEvidence(version.id),
    onSuccess: (response, version) => {
      const outcome = resolveEvidenceIdentity(response, version.id);
      setActionId("");
      setActionOutcome(outcome);
      navigate({
        pathname: location.pathname,
        search: releaseSearch({
          modelId: version.id,
          runId: version.run_id,
          evidenceId: outcome.evidenceId,
        }, location.search),
      }, { replace: true });
    },
    onError: (message) => {
      setActionId("");
      setActionOutcome({ state: "failed", reason: message });
    },
  });

  const deleteModel = async (v: ModelVersion) => {
    const ok = await confirm({
      title: "Delete Model",
      description: `This will permanently remove model "${v.tag || v.name || shortId(v.id)}" from the registry.`,
      impact: "This action cannot be undone. All associated artifacts, metrics, and history will be removed.",
      confirmLabel: "Delete",
      destructive: true,
    });
    if (!ok) return;
    setActionId(v.id);
    deleteMutation.mutate(v);
  };

  const togglePromote = async (v: ModelVersion) => {
    const isRecommended = String(v.description).includes("RECOMMENDED");
    const newStage = isRecommended ? "STAGING" : "RECOMMENDED";

    const ok = await confirm({
      title: `Promote to ${newStage}`,
      description: `Mark "${v.tag || v.name || shortId(v.id)}" as ${newStage}?`,
      impact: newStage === "RECOMMENDED"
        ? "This model will be marked as recommended for production use. Promotion gates will be checked."
        : "This model will be moved back to STAGING.",
      confirmLabel: newStage === "RECOMMENDED" ? "Promote" : "Demote",
      destructive: false,
    });
    if (!ok) return;

    setActionId(v.id);
    // Clear any previous gate failures for this model
    setGateFailures(prev => {
      const next = { ...prev };
      delete next[v.id];
      return next;
    });

    promoteMutation.mutate({ version: v, stage: newStage });
  };

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto pb-16">
      <ConfirmDialog />

      <div className="border-b pb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Model Registry</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Trained models with metrics. Sort by Sharpe, Return, or Max Drawdown.
          </p>
          <p className="text-xs text-muted-foreground/70 mt-1">
            Benchmark: {market === "all" ? "QQQ (US) / CSI300 (CN)" : BENCHMARK_BY_MARKET[market] || "N/A"}
            {' '} | Metrics: Sharpe ratio (risk-adjusted), Ann. Return (annualized), Max DD (worst peak-to-trough)
            {' '} | Models older than {STALE_THRESHOLD_DAYS} days marked stale
          </p>
        </div>
        <div className="flex items-center gap-2">
          {selectedForCompare.length >= 2 && (
            <Button
              size="sm"
              className="h-7 gap-1.5 text-xs"
              onClick={() => navigate(
                { pathname: "/compare", search: location.search },
                { state: { preselectedIds: selectedForCompare } },
              )}
            >
              <Layers className="h-3 w-3" /> Compare Selected ({selectedForCompare.length})
            </Button>
          )}
          {selectedForCompare.length > 0 && selectedForCompare.length < 2 && (
            <Badge variant="outline" className="text-xs h-7">
              Select {2 - selectedForCompare.length} more to compare
            </Badge>
          )}
          <Button onClick={modelsQuery.refetch} variant="outline" size="sm" className="h-7 gap-1.5 text-xs">
            <RefreshCw className={cn("h-3 w-3", modelsQuery.loading && "animate-spin")} /> Refresh
          </Button>
        </div>
      </div>

      <ReleaseOutcome
        state={(actionOutcome ?? registryOutcome).state}
        reason={(actionOutcome ?? registryOutcome).reason}
        details={
          (actionOutcome ?? registryOutcome).state === "blocked"
            ? Object.values(gateFailures).flat()
            : undefined
        }
      />

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">Search</label>
          <Input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Name, tag, market..."
            className="h-7 w-44 text-xs"
          />
        </div>
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
            {([["Sharpe Ratio", "Sharpe"], ["Annualized Return", "Return"], ["Max Drawdown", "MDD"]] as const).map(([key, label]) => (
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
                <TableHead className="w-[32px]">
                  <span className="sr-only">Expand</span>
                </TableHead>
                <TableHead className="w-[100px]">Version</TableHead>
                <TableHead className="w-[60px]">Mkt</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Model</TableHead>
                <TableHead className="w-[90px]">Stage</TableHead>
                <TableHead className="w-[100px]">Snapshot</TableHead>
                <TableHead className="w-[90px]">Run</TableHead>
                <TableHead className="cursor-pointer select-none" onClick={() => toggleSort("Sharpe Ratio")}>
                  <span className="flex items-center gap-1">Sharpe <SortIcon column="Sharpe Ratio" /></span>
                </TableHead>
                <TableHead className="cursor-pointer select-none" onClick={() => toggleSort("Annualized Return")}>
                  <span className="flex items-center gap-1">Ann. Return <SortIcon column="Annualized Return" /></span>
                </TableHead>
                <TableHead className="cursor-pointer select-none" onClick={() => toggleSort("Max Drawdown")}>
                  <span className="flex items-center gap-1">Max DD <SortIcon column="Max Drawdown" /></span>
                </TableHead>
                <TableHead className="text-right w-[100px]">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {displayed.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={12} className="h-48 text-center text-muted-foreground text-sm">
                    {modelsQuery.loading && !modelsQuery.data
                      ? "Loading models..."
                      : "No models found. Train a model via the workflow page first."}
                  </TableCell>
                </TableRow>
              ) : (
                displayed.map((v) => {
                  const sharpeDef = getMetricDefinition("Sharpe Ratio")!;
                  const annRetDef = getMetricDefinition("Annualized Return")!;
                  const mddDef = getMetricDefinition("Max Drawdown")!;
                  const sharpe = getModelMetric(v, "Sharpe Ratio");
                  const annRet = getModelMetric(v, "Annualized Return");
                  const mdd = getModelMetric(v, "Max Drawdown");
                  const stage = parseStage(v.description);
                  const isRecommended = stage === "RECOMMENDED";
                  const isDoing = actionId === v.id;
                  const age = modelAgeDays(v.created_at);
                  const isStale = age !== null && age > STALE_THRESHOLD_DAYS;

                  const isExpanded = expandedId === v.id;
                  const snapshotId = String(v.snapshot_id || (v.params as Record<string, unknown>)?.data_snapshot_id || "");
                  const runIdDisplay = v.run_id ? shortId(v.run_id) : "—";
                  const stageBadge = STAGE_BADGE[stage];

                  return (
                    <TableRow
                      key={v.id}
                      data-model-id={v.id}
                      className={cn("group", routeIdentity.modelId === v.id && "bg-primary/5")}
                    >
                      <TableCell>
                        <button
                          type="button"
                          className="h-5 w-5 flex items-center justify-center rounded hover:bg-muted/50 text-muted-foreground"
                          onClick={() => setExpandedId(isExpanded ? null : v.id)}
                          aria-expanded={isExpanded}
                          aria-label={`Show provenance for ${v.tag || v.name || v.id}`}
                          title="Show provenance chain"
                        >
                          {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                        </button>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <div className="flex items-center gap-1">
                            <span className="font-mono text-xs">{shortId(v.id)}</span>
                            {isStale && (
                              <span title={`Model is ${Math.floor(age!)} days old`} aria-label={`Stale: model is ${Math.floor(age!)} days old`}>
                                <AlertTriangle className="h-3 w-3 text-yellow-500" />
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] text-muted-foreground">{v.created_at?.slice(0, 10)}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="text-[10px] uppercase">{v.market}</Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm font-medium">{v.tag || v.name}</span>
                          {isRecommended && <Star className="h-3 w-3 fill-amber-400 text-amber-400" aria-label="Recommended model" />}
                        </div>
                        <span className="text-[10px] text-muted-foreground">
                          Bench: {BENCHMARK_BY_MARKET[(v.market || "").toLowerCase()] || "N/A"}
                        </span>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{v.model_type || "LGBModel"}</TableCell>
                      <TableCell>
                        <Badge variant={stageBadge.variant} className={stageBadge.className}>{stage}</Badge>
                      </TableCell>
                      <TableCell>
                        <span className="font-mono text-[10px] text-muted-foreground" title={snapshotId || undefined}>
                          {snapshotId ? snapshotId.slice(0, 12) + (snapshotId.length > 12 ? "..." : "") : "—"}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className="font-mono text-[10px] text-muted-foreground" title={v.run_id || undefined}>
                          {runIdDisplay}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className={cn("font-mono text-xs", sharpe !== null && sharpe >= 1 ? "text-green-500" : sharpe !== null && sharpe < 0 ? "text-red-500" : "")}>
                          {formatMetricValue(sharpe, sharpeDef)}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className={cn("font-mono text-xs", annRet !== null && annRet > 0 ? "text-green-500" : annRet !== null ? "text-red-500" : "")}>
                          {formatMetricValue(annRet, annRetDef)}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className={cn("font-mono text-xs", mdd !== null && Math.abs(mdd) > 0.2 ? "text-red-500" : "")}>
                          {formatMetricValue(mdd, mddDef)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-7 w-7 text-muted-foreground"
                            aria-label={`Validate evidence for ${v.tag || v.name || v.id}`}
                            title="Validate evidence bundle"
                            onClick={() => {
                              setActionId(v.id);
                              evidenceMutation.mutate(v);
                            }}
                            disabled={isDoing}
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                          </Button>
                          <Button size="icon" variant="ghost" className={cn("h-7 w-7", isRecommended ? "text-amber-500" : "text-muted-foreground")} aria-label={isRecommended ? "Demote model to staging" : "Promote model to recommended"} onClick={() => togglePromote(v)} disabled={isDoing}>
                            {isDoing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Star className={cn("h-3.5 w-3.5", isRecommended && "fill-current")} />}
                          </Button>
                          <Button size="icon" variant="ghost" className="h-7 w-7 text-red-500" aria-label={`Delete model ${v.tag || v.name || shortId(v.id)}`} onClick={() => deleteModel(v)} disabled={isDoing}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}

              {/* Expanded provenance chain rows */}
              {displayed.map((v) => {
                if (expandedId !== v.id) return null;
                const snapshotId = String(v.snapshot_id || (v.params as Record<string, unknown>)?.data_snapshot_id || "");
                const stage = parseStage(v.description);
                const failures = gateFailures[v.id];

                return (
                  <TableRow key={`${v.id}-provenance`} className="bg-muted/20">
                    <TableCell colSpan={12} className="py-3 px-6">
                      <div className="space-y-3">
                        <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                          <GitBranch className="h-3.5 w-3.5" />
                          Provenance Chain
                        </div>

                        {/* Identity chain: snapshot -> model -> evidence */}
                        <div className="flex items-center gap-2 flex-wrap">
                          <div className="flex items-center gap-1.5 rounded border px-2 py-1 bg-card">
                            <span className="text-[10px] uppercase font-bold text-muted-foreground">Snapshot</span>
                            <span className="font-mono text-[11px]">{snapshotId || "—"}</span>
                          </div>
                          <Link2 className="h-3 w-3 text-muted-foreground rotate-[-30deg]" />
                          <div className="flex items-center gap-1.5 rounded border px-2 py-1 bg-card">
                            <span className="text-[10px] uppercase font-bold text-muted-foreground">Model</span>
                            <span className="font-mono text-[11px]">{shortId(v.id)}</span>
                          </div>
                          <Link2 className="h-3 w-3 text-muted-foreground rotate-[-30deg]" />
                          <div className="flex items-center gap-1.5 rounded border px-2 py-1 bg-card">
                            <span className="text-[10px] uppercase font-bold text-muted-foreground">Run</span>
                            <span className="font-mono text-[11px]">{v.run_id ? shortId(v.run_id) : "—"}</span>
                          </div>
                          <Link2 className="h-3 w-3 text-muted-foreground rotate-[-30deg]" />
                          <div className="flex items-center gap-1.5 rounded border px-2 py-1 bg-card">
                            <span className="text-[10px] uppercase font-bold text-muted-foreground">Evidence</span>
                            <span className="font-mono text-[11px]">{v.evidence_id ? shortId(v.evidence_id) : "—"}</span>
                          </div>
                        </div>

                        {/* Stage progress */}
                        <div className="flex items-center gap-1">
                          {STAGE_ORDER.map((s, i) => {
                            const currentIdx = STAGE_ORDER.indexOf(stage);
                            const isActive = i <= currentIdx;
                            const isCurrent = s === stage;
                            return (
                              <div key={s} className="flex items-center gap-1">
                                {i > 0 && (
                                  <div className={cn("w-6 h-0.5", isActive ? "bg-primary" : "bg-muted-foreground/20")} />
                                )}
                                <div className={cn(
                                  "flex items-center justify-center rounded-full px-2.5 py-0.5 text-[10px] font-semibold border",
                                  isCurrent ? "bg-primary text-primary-foreground border-primary" : isActive ? "bg-primary/10 text-primary border-primary/30" : "bg-muted/30 text-muted-foreground border-muted-foreground/20",
                                )}>
                                  {s}
                                </div>
                              </div>
                            );
                          })}
                        </div>

                        {/* Gate failures */}
                        {failures && failures.length > 0 && (
                          <div className="rounded border border-destructive/30 bg-destructive/5 px-3 py-2">
                            <div className="flex items-start gap-2">
                              <AlertTriangle className="h-3.5 w-3.5 text-destructive mt-0.5 shrink-0" />
                              <div>
                                <span className="text-xs font-semibold text-destructive">Gate Failures</span>
                                <ul className="mt-1 space-y-0.5">
                                  {failures.map((f, i) => (
                                    <li key={i} className="text-[11px] text-destructive/80 font-mono">{f}</li>
                                  ))}
                                </ul>
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Full identity table */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px]">
                          <div><span className="font-bold text-muted-foreground">Artifact ID:</span> <span className="font-mono">{v.id}</span></div>
                          <div><span className="font-bold text-muted-foreground">Snapshot ID:</span> <span className="font-mono">{snapshotId || "—"}</span></div>
                          <div><span className="font-bold text-muted-foreground">Run ID:</span> <span className="font-mono">{v.run_id || "—"}</span></div>
                          <div><span className="font-bold text-muted-foreground">Evidence ID:</span> <span className="font-mono">{v.evidence_id || "—"}</span></div>
                          <div><span className="font-bold text-muted-foreground">Stage:</span> <span className="font-mono">{stage}</span></div>
                          <div><span className="font-bold text-muted-foreground">Market:</span> <span className="font-mono uppercase">{v.market || "—"}</span></div>
                          <div><span className="font-bold text-muted-foreground">Type:</span> <span className="font-mono">{v.model_type || "LGBModel"}</span></div>
                          <div><span className="font-bold text-muted-foreground">Created:</span> <span className="font-mono">{v.created_at?.slice(0, 10) || "—"}</span></div>
                        </div>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}

              {/* Gate failure rows (rendered inline below the model rows) */}
              {displayed.map((v) => {
                const failures = gateFailures[v.id];
                if (!failures || failures.length === 0) return null;
                return (
                  <TableRow key={`${v.id}-gates`} className="bg-destructive/5">
                    <TableCell colSpan={12} className="py-3 px-6">
                      <div className="flex items-start gap-2">
                        <AlertTriangle className="h-4 w-4 text-destructive mt-0.5 flex-shrink-0" />
                        <div>
                          <span className="text-xs font-semibold text-destructive">
                            Promotion blocked for {v.tag || v.name || shortId(v.id)}:
                          </span>
                          <ul className="mt-1 space-y-0.5">
                            {failures.map((f, i) => (
                              <li key={i} className="text-xs text-destructive/80 font-mono">
                                {f}
                              </li>
                            ))}
                          </ul>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="ml-auto h-6 text-xs text-muted-foreground"
                          onClick={() => setGateFailures(prev => {
                            const next = { ...prev };
                            delete next[v.id];
                            return next;
                          })}
                        >
                          Dismiss
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
