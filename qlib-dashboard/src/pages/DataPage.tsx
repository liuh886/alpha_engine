import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Loader2,
  RefreshCw,
  Activity,
  Download,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DataHeatmap } from "@/components/DataHeatmap";

type HeatmapData = {
  symbols: string[];
  dates: string[];
  values: (number | null)[][];
};

const FEATURE_OPTIONS = [
  { value: "close", label: "Close (coverage)" },
  { value: "open", label: "Open" },
  { value: "high", label: "High" },
  { value: "low", label: "Low" },
  { value: "volume", label: "Volume" },
  { value: "amount", label: "Amount" },
  { value: "vwap", label: "VWAP" },
  { value: "money", label: "Money" },
  { value: "factor", label: "Factor" },
];

export function DataPage() {
  const [market, setMarket] = useState("us");
  const [feature, setFeature] = useState("close");
  const [heatmapData, setHeatmapData] = useState<HeatmapData | null>(null);
  const [loading, setLoading] = useState(false);
  const [updating, setUpdating] = useState(false);

  const loadHeatmap = async () => {
    setLoading(true);
    try {
      const resp = await fetch(
        `/api/data/completeness?market=${market}&feature=${feature}`,
        { cache: "no-store" }
      );
      if (resp.ok) {
        const json = await resp.json();
        setHeatmapData(json.data);
      }
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHeatmap();
  }, [market, feature]);

  const triggerUpdate = async (full: boolean) => {
    const type = full ? "FULL RE-INGESTION" : "INCREMENTAL UPDATE";
    if (
      !window.confirm(
        `Start ${type}?\nFull re-ingestion will wipe local cache and fetch everything.\nIncremental update only fetches the last 30 days.`
      )
    )
      return;

    setUpdating(true);
    try {
      const resp = await fetch("/api/data/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full, lookback_days: full ? 3650 : 30 }),
      });
      if (resp.ok) {
        alert("Data pipeline task dispatched.");
      }
    } catch (e) {
      console.error(e);
    } finally {
      setUpdating(false);
    }
  };

  const coverageStats = useMemo(() => {
    if (!heatmapData || heatmapData.values.length === 0)
      return { total: 0, filled: 0, pct: 0 };
    let total = 0;
    let filled = 0;
    for (const row of heatmapData.values) {
      for (const v of row) {
        total++;
        if (v !== null && v !== undefined) filled++;
      }
    }
    return { total, filled, pct: total > 0 ? (filled / total) * 100 : 0 };
  }, [heatmapData]);

  return (
    <div className="space-y-5 max-w-[1400px] mx-auto pb-16">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-3 border-b pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Data Completeness</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Visualize data coverage across instruments and time. Identify gaps that affect backtest reliability.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            onClick={() => triggerUpdate(false)}
            disabled={updating}
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 text-xs"
          >
            <Activity className="h-3.5 w-3.5" />
            Incremental
          </Button>
          <Button
            onClick={() => triggerUpdate(true)}
            disabled={updating}
            size="sm"
            className="h-8 gap-1.5 text-xs"
          >
            {updating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            Full Ingest
          </Button>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1">
          {["us", "cn"].map((m) => (
            <Button
              key={m}
              variant={market === m ? "default" : "outline"}
              size="sm"
              onClick={() => setMarket(m)}
              className="h-8 text-xs font-medium uppercase"
            >
              {m}
            </Button>
          ))}
        </div>

        <select
          value={feature}
          onChange={(e) => setFeature(e.target.value)}
          className="h-8 rounded border border-input bg-transparent px-2 text-xs font-mono"
        >
          {FEATURE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <Button
          onClick={loadHeatmap}
          disabled={loading}
          variant="ghost"
          size="sm"
          className="h-8 gap-1.5 text-xs"
        >
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
          Refresh
        </Button>

        <div className="flex-1" />

        <div className="flex items-center gap-4 text-xs text-muted-foreground font-mono">
          <span>
            Symbols: <span className="text-foreground">{heatmapData?.symbols.length ?? 0}</span>
          </span>
          <span>
            Days: <span className="text-foreground">{heatmapData?.dates.length ?? 0}</span>
          </span>
          <span>
            Coverage:{" "}
            <span
              className={cn(
                "font-medium",
                coverageStats.pct >= 95
                  ? "text-green-500"
                  : coverageStats.pct >= 80
                  ? "text-amber-500"
                  : "text-red-500"
              )}
            >
              {coverageStats.pct.toFixed(1)}%
            </span>
          </span>
        </div>
      </div>

      {/* Heatmap */}
      <Card>
        <CardHeader className="pb-2 border-b flex flex-row items-center justify-between py-3">
          <CardTitle className="text-sm font-semibold">
            {market.toUpperCase()} — {feature}
          </CardTitle>
          {feature === "close" && (
            <div className="flex items-center gap-3 text-xs">
              <div className="flex items-center gap-1.5">
                <div className="w-3 h-3 rounded-sm bg-green-500" />
                <span className="text-muted-foreground">Data</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-3 h-3 rounded-sm bg-[#1a1a1a] border border-border" />
                <span className="text-muted-foreground">Missing</span>
              </div>
            </div>
          )}
        </CardHeader>
        <CardContent className="p-0" style={{ height: 500 }}>
          {loading ? (
            <div className="h-full flex items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-primary opacity-50" />
            </div>
          ) : heatmapData && heatmapData.symbols.length > 0 ? (
            <DataHeatmap data={heatmapData} feature={feature} />
          ) : (
            <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
              No data available. Run a data update first.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
