import { useState, useEffect, useCallback, useRef } from "react";
import { useOutletContext } from "react-router-dom";
import { createChart, ColorType, CandlestickSeries, HistogramSeries, createSeriesMarkers } from "lightweight-charts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { apiFetch } from "@/lib/api";
import { formatNum, formatCompact } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useGlobalStore } from "@/store/globalStore";
import { useNameMap } from "@/lib/useNameMap";
import type { ModelData } from "@/lib/data-parser";
import {
  Search, ShieldAlert, Activity, Zap, Compass,
  ArrowUpRight, ArrowDownRight, Loader2,
  TrendingUp, TrendingDown, Minus, BarChart3,
  CheckCircle, XCircle, AlertTriangle, List, ClipboardList,
  Filter, Trophy,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StockDecision {
  symbol: string;
  signal: "BUY" | "HOLD" | "SELL";
  confidence: number;
  score: number | null;
  rank: number | null;
  reasons: string[];
  factor_snapshot: Record<string, {
    name: string;
    expression: string;
    value: number | null;
    z_score: number | null;
    percentile: number | null;
    category: string;
  }>;
  guardrail_status: Record<string, {
    passed: boolean;
    reason?: string;
    metric?: number;
  }>;
  risk_flags: string[];
  timestamp: string;
  recommended_strategy?: {
    name: string;
    display_name: string;
    reason: string;
    confidence: number;
  };
  price_targets?: {
    current_price: number | null;
    buy_range_low: number | null;
    buy_range_high: number | null;
    stop_loss_price: number | null;
    target_price: number | null;
    atr_20: number | null;
    support: number | null;
    resistance: number | null;
  };
}

interface WatchlistItem {
  symbol: string;
  signal: "BUY" | "HOLD" | "SELL";
  confidence: number;
  score: number | null;
  rank: number | null;
  risk_flags: string[];
  // G3: Enhanced fields
  price?: number | null;
  change_pct?: number | null;
  change_5d_pct?: number | null;
  recommended_strategy?: string;
}

interface ScreenerItem {
  symbol: string;
  market: string;
  weighted_score: number;
  total_signals: number;
  data_start: string;
  data_end: string;
  grade_details: Record<string, {
    occurrences: number;
    win_rate: number;
    mean_return: number;
    cumulative_return: number;
    contribution: number;
  }>;
}

interface AutocompleteItem {
  symbol: string;
  name: string;
  market: string;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SignalBadge({ signal }: { signal: "BUY" | "HOLD" | "SELL" }) {
  const styles = {
    BUY: "bg-green-500/20 text-green-400 border-green-500/30",
    HOLD: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    SELL: "bg-red-500/20 text-red-400 border-red-500/30",
  };
  const icons = {
    BUY: <TrendingUp className="h-3 w-3" />,
    HOLD: <Minus className="h-3 w-3" />,
    SELL: <TrendingDown className="h-3 w-3" />,
  };
  return (
    <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-black uppercase border", styles[signal])}>
      {icons[signal]} {signal}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? "bg-green-500" : pct >= 40 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-bold text-muted-foreground w-8 text-right">{pct}%</span>
    </div>
  );
}

function ReasonItem({ reason }: { reason: string }) {
  const isPositive = reason.startsWith("✅");
  const isWarning = reason.startsWith("⚠") || reason.startsWith("⚡");
  const isDanger = reason.startsWith("🔴") || reason.startsWith("📉");
  const icon = isPositive
    ? <CheckCircle className="h-3.5 w-3.5 text-green-500 mt-0.5 flex-shrink-0" />
    : isDanger
      ? <XCircle className="h-3.5 w-3.5 text-red-500 mt-0.5 flex-shrink-0" />
      : isWarning
        ? <AlertTriangle className="h-3.5 w-3.5 text-yellow-500 mt-0.5 flex-shrink-0" />
        : <div className="h-3.5 w-3.5 rounded-full bg-muted-foreground/20 mt-0.5 flex-shrink-0" />;

  return (
    <div className="flex items-start gap-2 text-xs leading-relaxed">
      {icon}
      <span className={cn(isPositive && "text-green-400", isDanger && "text-red-400", isWarning && "text-yellow-400")}>
        {reason}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function StockTerminal() {
  const [symbol, setSymbol] = useState("AAPL");
  const [market, setMarket] = useState<"us" | "cn">("us");
  const [loading, setLoading] = useState(false);
  // Get selected model from global store
  const { selectedModelId, selectedModelMarket } = useGlobalStore();
  // Get name map for Chinese company names
  const { getName } = useNameMap();
  // Get models from outlet context for display name lookup
  const { models } = useOutletContext<{ models: ModelData[] }>() || { models: [] as ModelData[] };
  const selectedModel = models.find(m => m.id === selectedModelId || m.run_id === selectedModelId);
  const modelLabel = selectedModel
    ? (selectedModel.name || selectedModel.tag || selectedModelId?.slice(0, 16) || "No model")
    : (selectedModelId ? selectedModelId.slice(0, 16) + '...' : "No model selected");
  const [error, setError] = useState<string>("");
  const [view, setView] = useState<"analysis" | "watchlist" | "screener">("analysis");

  // Stock analysis state
  const [ohlcData, setOhlcData] = useState<Record<string, unknown> | null>(null);
  const [decision, setDecision] = useState<StockDecision | null>(null);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [dataFreshness, setDataFreshness] = useState<{ pred_age_days?: number; is_stale?: boolean } | null>(null);
  const [signalHistory, setSignalHistory] = useState<Array<{ signal: string; confidence: number; score: number | null; recorded_at: string; price_targets?: Record<string, number | null> }>>([]);
  // Signal grade state (S4)
  const [signalMarkers, setSignalMarkers] = useState<Array<{ time: string; position: string; color: string; shape: string; text: string; size: number }>>([]);
  const [signalPerformance, setSignalPerformance] = useState<Record<string, { grade: string; grade_name: string; total_occurrences: number; win_rate: number; mean_return: number; cumulative_return: number; median_return: number; max_return: number; min_return: number; avg_score: number }> | null>(null);
  const [totalScore, setTotalScore] = useState<{ total_score: number; buy_score: number; sell_score: number; grade: string; description: string; total_signals: number; buy_signals: number; sell_signals: number } | null>(null);
  const stepSize = 10;
  const [showSignalOverlay, setShowSignalOverlay] = useState(true);
  const [dailySignalSeries, setDailySignalSeries] = useState<Array<{ date: string; percentile: number; grade: string; score: number; rank: number; total: number }>>([]);

  // Watchlist state
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [watchlistLoading, setWatchlistLoading] = useState(false);

  // Screener state
  const [screenerData, setScreenerData] = useState<ScreenerItem[]>([]);
  const [screenerLoading, setScreenerLoading] = useState(false);
  const [screenerMarket, setScreenerMarket] = useState<"us" | "cn">("us");
  const [screenerSortBy, setScreenerSortBy] = useState("weighted_score");
  const screenerLimit = 50;

  // Autocomplete state
  const [autocompleteItems, setAutocompleteItems] = useState<AutocompleteItem[]>([]);
  const [showAutocomplete, setShowAutocomplete] = useState(false);
  const [autocompleteIndex, setAutocompleteIndex] = useState(-1);
  const searchRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // ------------------------------------------------------------------
  // Fetch stock OHLCV data (existing endpoint)
  // ------------------------------------------------------------------
  const fetchStockData = useCallback(async (targetSymbol: string) => {
    const querySymbol = targetSymbol.trim().toUpperCase();
    if (!querySymbol) return;

    setLoading(true);
    setError("");
    try {
      const resp = await apiFetch(`/api/data/stock/${encodeURIComponent(querySymbol)}`, { cache: "no-store" });
      const json = await resp.json().catch(() => ({}));
      if (!resp.ok || !json.ok) {
        setOhlcData(null);
        setError(json.detail || json.error || `No data found for ${querySymbol}.`);
        return;
      }
      setOhlcData(json);
    } catch (err) {
      console.warn("[StockTerminal] fetchStockData failed:", err);
      setOhlcData(null);
      setError("API unavailable.");
    } finally {
      setLoading(false);
    }
  }, []);

  // ------------------------------------------------------------------
  // Fetch stock decision (new endpoint)
  // ------------------------------------------------------------------
  const fetchDecision = useCallback(async (targetSymbol: string) => {
    const querySymbol = targetSymbol.trim().toUpperCase();
    if (!querySymbol) return;

    // Auto-detect market from symbol suffix
    const detectedMarket = querySymbol.endsWith(".SH") || querySymbol.endsWith(".SZ") ? "cn" : "us";

    setDecisionLoading(true);
    try {
      const resp = await apiFetch(
        `/api/stock-analysis/${encodeURIComponent(querySymbol)}/decision?market=${detectedMarket}&include_factors=true`,
        { cache: "no-store" },
      );
      const json = await resp.json().catch(() => ({}));
      if (resp.ok && json.ok) {
        setDecision(json.decision);
        setDataFreshness(json.data_freshness || null);
      } else {
        setDecision(null);
        setDataFreshness(null);
      }
    } catch (err) {
      console.warn("[StockTerminal] fetchDecision failed:", err);
      setDecision(null);
    } finally {
      setDecisionLoading(false);
    }
  }, []);

  // ------------------------------------------------------------------
  // Fetch signal markers and performance (S4)
  // ------------------------------------------------------------------
  const fetchSignalData = useCallback(async (targetSymbol: string, currentStepSize?: number) => {
    const querySymbol = targetSymbol.trim().toUpperCase();
    if (!querySymbol) return;
    const ss = currentStepSize ?? stepSize;
    const detectedMarket = querySymbol.endsWith(".SH") || querySymbol.endsWith(".SZ") ? "cn" : "us";

    // Build run_id parameter if a specific model is selected
    const runIdParam = selectedModelId ? `&run_id=${encodeURIComponent(selectedModelId)}` : "";

    try {
      // Fetch markers
      const markersResp = await apiFetch(
        `/api/stock-analysis/${encodeURIComponent(querySymbol)}/signal-markers?market=${detectedMarket}&step_size=${ss}${runIdParam}`,
        { cache: "no-store" },
      );
      const markersJson = await markersResp.json().catch(() => ({}));
      if (markersResp.ok && markersJson.ok) {
        setSignalMarkers(markersJson.markers || []);
      }

      // Fetch performance
      const perfResp = await apiFetch(
        `/api/stock-analysis/${encodeURIComponent(querySymbol)}/signal-performance?market=${detectedMarket}&step_size=${ss}&forward_days=10${runIdParam}`,
        { cache: "no-store" },
      );
      const perfJson = await perfResp.json().catch(() => ({}));
      if (perfResp.ok && perfJson.ok) {
        setSignalPerformance(perfJson.performance || null);
        setTotalScore(perfJson.total_score || null);
      }

      // Fetch daily signal series for chart overlay
      const dailyResp = await apiFetch(
        `/api/stock-analysis/${encodeURIComponent(querySymbol)}/signal-daily?market=${detectedMarket}&step_size=${ss}&days=120${runIdParam}`,
        { cache: "no-store" },
      );
      const dailyJson = await dailyResp.json().catch(() => ({}));
      if (dailyResp.ok && dailyJson.ok) {
        setDailySignalSeries(dailyJson.series || []);
      }
    } catch (err) {
      console.warn("[StockTerminal] fetchSignalData failed:", err);
      setSignalMarkers([]);
      setSignalPerformance(null);
      setDailySignalSeries([]);
    }
  }, [stepSize, selectedModelId]);

  // ------------------------------------------------------------------
  // Fetch signal history (T6)
  // ------------------------------------------------------------------
  const fetchSignalHistory = useCallback(async (targetSymbol: string) => {
    const querySymbol = targetSymbol.trim().toUpperCase();
    if (!querySymbol) return;
    try {
      const resp = await apiFetch(`/api/stock-analysis/${encodeURIComponent(querySymbol)}/history?days=30`, { cache: "no-store" });
      const json = await resp.json().catch(() => ({}));
      if (resp.ok && json.ok) {
        setSignalHistory(json.history || []);
      }
    } catch (err) {
      console.warn("[StockTerminal] fetchSignalHistory failed:", err);
      setSignalHistory([]);
    }
  }, []);

  // ------------------------------------------------------------------
  // Fetch watchlist summary
  // ------------------------------------------------------------------
  const fetchWatchlist = useCallback(async () => {
    setWatchlistLoading(true);
    try {
      const resp = await apiFetch(`/api/stock-analysis/watchlist/summary?market=${market}`, { cache: "no-store" });
      const json = await resp.json().catch(() => ({}));
      if (resp.ok && json.ok) {
        setWatchlist(json.summary || []);
      }
    } catch (err) {
      console.warn("[StockTerminal] fetchWatchlist failed:", err);
    } finally {
      setWatchlistLoading(false);
    }
  }, [market]);

  // ------------------------------------------------------------------
  // Fetch screener data (model effectiveness per stock)
  // ------------------------------------------------------------------
  const fetchScreener = useCallback(async () => {
    setScreenerLoading(true);
    try {
      const resp = await apiFetch(
        `/api/stock-analysis/ranking?market=${screenerMarket}&step_size=${stepSize}&forward_days=10&sort_by=${screenerSortBy}&limit=${screenerLimit}`,
        { cache: "no-store" },
      );
      const json = await resp.json().catch(() => ({}));
      if (resp.ok && json.ok) {
        setScreenerData(json.ranking || []);
      }
    } catch (err) {
      console.warn("[StockTerminal] fetchScreener failed:", err);
    } finally {
      setScreenerLoading(false);
    }
  }, [screenerMarket, stepSize, screenerSortBy, screenerLimit]);

  // ------------------------------------------------------------------
  // Fetch autocomplete data (instruments + name map)
  // ------------------------------------------------------------------
  const fetchAutocompleteData = useCallback(async () => {
    try {
      const [instrUsResp, instrCnResp, nameResp] = await Promise.all([
        apiFetch("/api/data/instruments?market=us", { cache: "force-cache" }),
        apiFetch("/api/data/instruments?market=cn", { cache: "force-cache" }),
        apiFetch("/api/data/name-map", { cache: "force-cache" }),
      ]);
      const instrUsJson = await instrUsResp.json().catch(() => ({}));
      const instrCnJson = await instrCnResp.json().catch(() => ({}));
      const nameJson = await nameResp.json().catch(() => ({}));

      const nameMap = nameJson.name_map || {};
      const items: AutocompleteItem[] = [];
      const seen = new Set<string>();

      for (const sym of (instrUsJson.instruments || [])) {
        const ticker = String(sym).split("\t")[0].trim();
        if (ticker) {
          items.push({ symbol: ticker, name: nameMap[ticker] || "", market: "us" });
          seen.add(ticker);
        }
      }
      for (const sym of (instrCnJson.instruments || [])) {
        const ticker = String(sym).split("\t")[0].trim();
        if (ticker) {
          items.push({ symbol: ticker, name: nameMap[ticker] || "", market: "cn" });
          seen.add(ticker);
        }
      }

      // Add name_map entries not already in instruments (so all mapped stocks are searchable)
      for (const [ticker, name] of Object.entries(nameMap)) {
        if (!seen.has(ticker)) {
          const isCN = /^\d{6}$/.test(ticker);
          items.push({ symbol: ticker, name: String(name), market: isCN ? "cn" : "us" });
        }
      }

      setAutocompleteItems(items);
    } catch {
      // Silently fail — autocomplete is non-critical
    }
  }, []);

  // ------------------------------------------------------------------
  // Autocomplete filtered results
  // ------------------------------------------------------------------
  const filteredSuggestions = symbol.trim().length >= 1
    ? autocompleteItems
        .filter(item => {
          const q = symbol.trim().toUpperCase();
          return item.symbol.toUpperCase().includes(q) ||
            (item.name && item.name.toUpperCase().includes(q));
        })
        .slice(0, 10)
    : [];

  // ------------------------------------------------------------------
  // Handle search
  // ------------------------------------------------------------------
  const handleSearch = useCallback(() => {
    const q = symbol.trim().toUpperCase();
    if (!q) return;
    setView("analysis");
    fetchStockData(q);
    fetchDecision(q);
    fetchSignalHistory(q);
    fetchSignalData(q);
  }, [symbol, fetchStockData, fetchDecision, fetchSignalHistory, fetchSignalData]);

  // ------------------------------------------------------------------
  // K-line chart rendering
  // ------------------------------------------------------------------
  useEffect(() => {
    const chartContainer = document.getElementById("kline-chart");
    if (!chartContainer || !ohlcData?.ohlcv) return;

    const renderChart = () => {
      chartContainer.innerHTML = "";
      const width = chartContainer.clientWidth || chartContainer.parentElement?.clientWidth || 800;

      const chart = createChart(chartContainer, {
        layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "inherit" },
        grid: { vertLines: { color: "rgba(128,128,128,0.1)" }, horzLines: { color: "rgba(128,128,128,0.1)" } },
        width,
        height: 500,
        timeScale: { borderColor: "rgba(128,128,128,0.2)" },
      });

      const seriesOptions = {
        upColor: "#26a69a", downColor: "#ef5350", borderVisible: false,
        wickUpColor: "#26a69a", wickDownColor: "#ef5350",
      };
      const candlestickSeries = chart.addSeries(CandlestickSeries, seriesOptions);

      candlestickSeries.setData(ohlcData.ohlcv as never);

      // S4: Add signal grade markers (AAA/AA/A/V/VV/VVV) from historical data
      let allMarkers: Array<Record<string, unknown>> = [];
      if (signalMarkers.length > 0) {
        allMarkers = signalMarkers as Array<Record<string, unknown>>;
      } else if (decision && decision.signal && ohlcData.ohlcv && Array.isArray(ohlcData.ohlcv) && ohlcData.ohlcv.length > 0) {
        // Fallback: show current decision signal marker
        const lastBar = ohlcData.ohlcv[ohlcData.ohlcv.length - 1] as Record<string, unknown>;
        const lastTime = lastBar.time;
        const markerColor = decision.signal === "BUY" ? "#22c55e"
          : decision.signal === "SELL" ? "#ef4444"
          : "#eab308";
        const markerShape = decision.signal === "BUY" ? "arrowUp"
          : decision.signal === "SELL" ? "arrowDown"
          : "circle";
        allMarkers = [{
          time: lastTime,
          position: decision.signal === "BUY" ? "belowBar" : "aboveBar",
          color: markerColor,
          shape: markerShape,
          text: decision.signal,
          size: decision.signal === "HOLD" ? 1 : 2,
        }];
      }
      // Use v5 createSeriesMarkers API
      try {
        if (allMarkers.length > 0) {
          createSeriesMarkers(candlestickSeries, allMarkers as never[]);
        }
      } catch (err) {
        console.debug("[StockTerminal] createSeriesMarkers failed:", err);
      }

      // Add price lines for buy range, stop loss, target
      if (decision?.price_targets) {
        // Price lines are added regardless of markers
        if (decision.price_targets) {
          const pt = decision.price_targets;
          if (pt.buy_range_low != null) {
            candlestickSeries.createPriceLine({
              price: pt.buy_range_low,
              color: "#22c55e",
              lineWidth: 1,
              lineStyle: 2, // Dashed
              axisLabelVisible: true,
              title: "Buy Low",
            });
          }
          if (pt.buy_range_high != null) {
            candlestickSeries.createPriceLine({
              price: pt.buy_range_high,
              color: "#22c55e",
              lineWidth: 1,
              lineStyle: 2,
              axisLabelVisible: true,
              title: "Buy High",
            });
          }
          if (pt.stop_loss_price != null) {
            candlestickSeries.createPriceLine({
              price: pt.stop_loss_price,
              color: "#ef4444",
              lineWidth: 1,
              lineStyle: 2,
              axisLabelVisible: true,
              title: "Stop Loss",
            });
          }
          if (pt.target_price != null) {
            candlestickSeries.createPriceLine({
              price: pt.target_price,
              color: "#3b82f6",
              lineWidth: 1,
              lineStyle: 2,
              axisLabelVisible: true,
              title: "Target",
            });
          }
        }
      }

      // S4: Daily signal overlay - colored histogram bars at the bottom
      if (showSignalOverlay && dailySignalSeries.length > 0) {
        try {
          const gradeColorMap: Record<string, string> = {
            AAA: "#22c55e", AA: "#4ade80", A: "#86efac",
            V: "#fca5a5", VV: "#f87171", VVV: "#ef4444",
          };

          const signalHist = chart.addSeries(HistogramSeries, {
            priceScaleId: "signal",
            lastValueVisible: false,
            priceLineVisible: false,
          });

          // Signal grade scale on the right (y2)
          chart.priceScale("signal").applyOptions({
            scaleMargins: { top: 0.78, bottom: 0.0 },
          });

          // Map grade to numeric value for the histogram
          const gradeToValue: Record<string, number> = {
            AAA: 6, AA: 5, A: 4, V: -4, VV: -5, VVV: -6,
          };

          const signalData = dailySignalSeries
            .filter(d => d.grade && d.grade in gradeToValue)
            .map(d => ({
              time: d.date,
              value: gradeToValue[d.grade] ?? 0,
              color: gradeColorMap[d.grade] || "rgba(99, 102, 241, 0.3)",
            }));

          if (signalData.length > 0) {
            signalHist.setData(signalData);
          }

          // Add extreme grade markers on candlestick
          const gradeMarkers = dailySignalSeries
            .filter(d => d.grade && ["AAA", "VVV"].includes(d.grade))
            .map(d => ({
              time: d.date,
              position: d.grade === "AAA" ? "belowBar" : "aboveBar",
              color: d.grade === "AAA" ? "#22c55e" : "#ef4444",
              shape: "circle" as const,
              text: d.grade,
              size: 1,
            }));

          if (gradeMarkers.length > 0) {
            const combinedMarkers = [
              ...gradeMarkers,
              ...(signalMarkers.length > 0 ? signalMarkers : []),
            ];
            try {
              createSeriesMarkers(candlestickSeries, combinedMarkers as never[]);
            } catch {
              // ignore
            }
          }
        } catch (e) {
          // Signal overlay may not be supported in all chart versions
        }
      }

      chart.timeScale().fitContent();
    };

    const timer = setTimeout(renderChart, 50);
    return () => {
      clearTimeout(timer);
      chartContainer.innerHTML = "";
    };
  }, [ohlcData, decision, signalMarkers, dailySignalSeries, showSignalOverlay]);

  // ------------------------------------------------------------------
  // Load watchlist on mount when view switches
  // ------------------------------------------------------------------
  useEffect(() => {
    if (view === "watchlist") {
      fetchWatchlist();
    }
  }, [view, market, fetchWatchlist]);

  // ------------------------------------------------------------------
  // Load screener when view switches
  // ------------------------------------------------------------------
  useEffect(() => {
    if (view === "screener") {
      fetchScreener();
    }
  }, [view, fetchScreener]);

  // ------------------------------------------------------------------
  // Load autocomplete data on mount
  // ------------------------------------------------------------------
  useEffect(() => {
    fetchAutocompleteData();
  }, [fetchAutocompleteData]);

  // ------------------------------------------------------------------
  // Close autocomplete on outside click
  // ------------------------------------------------------------------
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowAutocomplete(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // ------------------------------------------------------------------
  // Factor keys for display
  // ------------------------------------------------------------------
  const factorEntries = decision?.factor_snapshot
    ? Object.entries(decision.factor_snapshot)
        .filter(([, v]) => v.value !== null)
        .sort((a, b) => {
          const za = Math.abs(a[1].z_score ?? 0);
          const zb = Math.abs(b[1].z_score ?? 0);
          return zb - za;
        })
        .slice(0, 15)
    : [];

  const guardrailEntries = decision?.guardrail_status
    ? Object.entries(decision.guardrail_status).filter(([k]) => k !== "overall_passed")
    : [];

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div className="space-y-8 max-w-[1600px] mx-auto pb-20">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 border-b pb-8">
        <div className="space-y-1 text-left">
          <div className="flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-widest mb-1">
            <Compass className="h-3.5 w-3.5" />
            Market Intelligence
          </div>
          <h1 className="text-4xl font-black tracking-tight">Alpha Terminal</h1>
          <p className="text-muted-foreground text-sm max-w-md">
            Individual stock analysis with model-driven BUY / HOLD / SELL signals, factor exposure, and risk guardrails.
          </p>
          {/* Active model indicator */}
          <div className="flex items-center gap-2 mt-3">
            <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Signal Source:</span>
            <Badge
              variant="outline"
              className={cn(
                "text-xs font-mono gap-1.5 py-1",
                selectedModelId
                  ? "bg-primary/5 text-primary border-primary/30"
                  : "bg-muted/30 text-muted-foreground border-dashed"
              )}
              title={selectedModelId || "Select a model from the top-left dropdown"}
            >
              <Activity className="h-3 w-3" />
              {modelLabel}
            </Badge>
            {selectedModelMarket && (
              <Badge variant="outline" className="text-[9px] uppercase bg-muted/20 font-bold">
                {selectedModelMarket}
              </Badge>
            )}
            {!selectedModelId && (
              <span className="text-[10px] text-yellow-500/80 font-medium ml-1">
                ⚠ Use model selector (top-left) to choose a model for signals
              </span>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-3 items-end">
          {/* Search bar with autocomplete */}
          <div ref={searchRef} className="relative flex w-full md:w-96 gap-2 bg-card p-1.5 rounded-xl shadow-lg border">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                ref={inputRef}
                type="text"
                placeholder="Enter ticker (e.g. AAPL, 600519.SH)"
                className="w-full bg-transparent border-none pl-10 pr-4 py-2 text-sm focus:ring-0 outline-none font-bold placeholder:font-normal"
                value={symbol}
                onChange={(e) => {
                  setSymbol(e.target.value.toUpperCase());
                  setShowAutocomplete(true);
                  setAutocompleteIndex(-1);
                }}
                onFocus={() => setShowAutocomplete(true)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    if (autocompleteIndex >= 0 && filteredSuggestions[autocompleteIndex]) {
                      const picked = filteredSuggestions[autocompleteIndex];
                      setSymbol(picked.symbol);
                      setShowAutocomplete(false);
                      handleSearch();
                    } else {
                      handleSearch();
                    }
                  } else if (e.key === "ArrowDown") {
                    e.preventDefault();
                    setAutocompleteIndex(prev => Math.min(prev + 1, filteredSuggestions.length - 1));
                  } else if (e.key === "ArrowUp") {
                    e.preventDefault();
                    setAutocompleteIndex(prev => Math.max(prev - 1, -1));
                  } else if (e.key === "Escape") {
                    setShowAutocomplete(false);
                  }
                }}
              />
            </div>
            <Button onClick={handleSearch} disabled={loading || decisionLoading} size="sm" className="rounded-lg px-6 font-bold uppercase tracking-tighter">
              {loading || decisionLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Query"}
            </Button>

            {/* Autocomplete dropdown */}
            {showAutocomplete && filteredSuggestions.length > 0 && (
              <div className="absolute top-full left-0 right-16 mt-1 bg-card border rounded-lg shadow-xl z-50 max-h-60 overflow-y-auto">
                {filteredSuggestions.map((item, i) => (
                  <button
                    key={item.symbol}
                    className={cn(
                      "w-full text-left px-3 py-2 text-xs flex items-center justify-between hover:bg-muted/50 transition-colors",
                      i === autocompleteIndex && "bg-muted/50",
                    )}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setSymbol(item.symbol);
                      setShowAutocomplete(false);
                      // Auto-switch market to match the selected instrument
                      if (item.market) {
                        setMarket(item.market as "cn" | "us");
                      }
                      setView("analysis");
                      // Trigger search directly with the symbol
                      fetchStockData(item.symbol);
                      fetchDecision(item.symbol);
                      fetchSignalHistory(item.symbol);
                      fetchSignalData(item.symbol);
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-bold font-mono">{item.symbol}</span>
                      {item.name && <span className="text-muted-foreground truncate max-w-[160px]">{item.name}</span>}
                    </div>
                    <span className={cn(
                      "text-[9px] font-bold uppercase px-1.5 py-0.5 rounded",
                      item.market === "us" ? "bg-blue-500/10 text-blue-400" : "bg-red-500/10 text-red-400",
                    )}>
                      {item.market}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* View toggle */}
          <div className="flex gap-1 bg-muted/30 p-0.5 rounded-lg">
            <button
              onClick={() => setView("analysis")}
              className={cn(
                "px-3 py-1 text-[10px] font-bold uppercase tracking-wider rounded-md transition-all",
                view === "analysis" ? "bg-card shadow text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <BarChart3 className="h-3 w-3 inline mr-1" /> Stock Analysis
            </button>
            <button
              onClick={() => setView("watchlist")}
              className={cn(
                "px-3 py-1 text-[10px] font-bold uppercase tracking-wider rounded-md transition-all",
                view === "watchlist" ? "bg-card shadow text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <List className="h-3 w-3 inline mr-1" /> Watchlist Overview
            </button>
            <button
              onClick={() => setView("screener")}
              className={cn(
                "px-3 py-1 text-[10px] font-bold uppercase tracking-wider rounded-md transition-all",
                view === "screener" ? "bg-card shadow text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Trophy className="h-3 w-3 inline mr-1" /> Stock Screener
            </button>
          </div>
        </div>
      </div>

      {/* G1: Stale data warning banner */}
      {dataFreshness?.is_stale && (
        <div className="flex items-center gap-3 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
          <AlertTriangle className="h-4 w-4 text-yellow-500 flex-shrink-0" />
          <span className="text-xs text-yellow-400">
            Predictions are {dataFreshness.pred_age_days} days old. Consider retraining for fresher signals.
          </span>
        </div>
      )}

      {/* ================================================================ */}
      {/* WATCHLIST OVERVIEW VIEW */}
      {/* ================================================================ */}
      {view === "watchlist" && (
        <Card className="border shadow-lg bg-card text-card-foreground">
          <CardHeader className="border-b bg-muted/10 py-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <CardTitle className="text-lg font-bold tracking-tight">Watchlist Signal Overview</CardTitle>
                {/* Market toggle */}
                <div className="flex gap-1 bg-muted/30 p-0.5 rounded-lg">
                  <button
                    onClick={() => { setMarket("us"); setWatchlist([]); }}
                    className={cn(
                      "px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider rounded-md transition-all",
                      market === "us" ? "bg-card shadow text-foreground" : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    US
                  </button>
                  <button
                    onClick={() => { setMarket("cn"); setWatchlist([]); }}
                    className={cn(
                      "px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider rounded-md transition-all",
                      market === "cn" ? "bg-card shadow text-foreground" : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    CN
                  </button>
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={fetchWatchlist} disabled={watchlistLoading}>
                {watchlistLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : "Refresh"}
              </Button>
            </div>
            {/* Signal stats */}
            {watchlist.length > 0 && (
              <div className="flex gap-4 mt-3">
                <span className="text-xs font-bold text-green-400">
                  BUY: {watchlist.filter(w => w.signal === "BUY").length}
                </span>
                <span className="text-xs font-bold text-yellow-400">
                  HOLD: {watchlist.filter(w => w.signal === "HOLD").length}
                </span>
                <span className="text-xs font-bold text-red-400">
                  SELL: {watchlist.filter(w => w.signal === "SELL").length}
                </span>
                <span className="text-xs text-muted-foreground">
                  Total: {watchlist.length}
                </span>
              </div>
            )}
          </CardHeader>
          <CardContent className="p-0">
            {watchlistLoading && watchlist.length === 0 ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/5">
                      <th className="text-left py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Symbol</th>
                      <th className="text-center py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Signal</th>
                      <th className="text-right py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Price</th>
                      <th className="text-right py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Chg%</th>
                      <th className="text-center py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Confidence</th>
                      <th className="text-right py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Score</th>
                      <th className="text-right py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Rank</th>
                      <th className="text-left py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Strategy</th>
                      <th className="text-center py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Risk</th>
                      <th className="text-center py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {watchlist.map((item) => (
                      <tr
                        key={item.symbol}
                        className="border-b border-dashed hover:bg-muted/5 transition-colors cursor-pointer"
                        onClick={() => {
                          setSymbol(item.symbol);
                          setView("analysis");
                          fetchStockData(item.symbol);
                          fetchDecision(item.symbol);
                          fetchSignalHistory(item.symbol);
                          fetchSignalData(item.symbol);
                        }}
                      >
                        <td className="py-3 px-3 font-bold">
                          <div>{getName(item.symbol)}</div>
                          <div className="text-[10px] text-muted-foreground font-mono">{item.symbol}</div>
                        </td>
                        <td className="py-3 px-3 text-center">
                          <SignalBadge signal={item.signal} />
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs">
                          {item.price != null ? `$${item.price.toFixed(2)}` : "—"}
                        </td>
                        <td className={cn(
                          "py-3 px-3 text-right font-mono text-xs font-bold",
                          (item.change_pct ?? 0) > 0 ? "text-green-400" : (item.change_pct ?? 0) < 0 ? "text-red-400" : "text-muted-foreground",
                        )}>
                          {item.change_pct != null ? `${item.change_pct > 0 ? "+" : ""}${item.change_pct.toFixed(2)}%` : "—"}
                        </td>
                        <td className="py-3 px-3 w-32">
                          <ConfidenceBar value={item.confidence} />
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs">
                          {formatNum(item.score, 4)}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs">
                          {item.rank !== null ? `#${item.rank + 1}` : "N/A"}
                        </td>
                        <td className="py-3 px-3 text-left text-[10px] text-muted-foreground">
                          {item.recommended_strategy || "—"}
                        </td>
                        <td className="py-3 px-3 text-center">
                          {item.risk_flags.length > 0 ? (
                            <Badge variant="destructive" className="text-[10px]">
                              {item.risk_flags.join(", ")}
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </td>
                        <td className="py-3 px-3 text-center">
                          <Button variant="ghost" size="sm" className="text-[10px] font-bold uppercase">
                            Analyze
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {watchlist.length === 0 && !watchlistLoading && (
                  <div className="flex items-center justify-center py-20 text-muted-foreground text-sm">
                    No watchlist data available. Run training first.
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ================================================================ */}
      {/* STOCK SCREENER VIEW — model effectiveness per stock */}
      {/* ================================================================ */}
      {view === "screener" && (
        <Card className="border shadow-lg bg-card text-card-foreground">
          <CardHeader className="border-b bg-muted/10 py-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <CardTitle className="text-lg font-bold tracking-tight">Stock Screener</CardTitle>
                <span className="text-[10px] text-muted-foreground uppercase">
                  Rank by how well the model predicts each stock
                </span>
              </div>
              <div className="flex items-center gap-2">
                {/* Market toggle */}
                <div className="flex gap-1 bg-muted/30 p-0.5 rounded-lg">
                  {(["us", "cn"] as const).map(m => (
                    <button
                      key={m}
                      onClick={() => { setScreenerMarket(m); }}
                      className={cn(
                        "px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider rounded-md transition-all",
                        screenerMarket === m ? "bg-card shadow text-foreground" : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {m.toUpperCase()}
                    </button>
                  ))}
                </div>
                {/* Sort selector */}
                <div className="flex items-center gap-1">
                  <Filter className="h-3 w-3 text-muted-foreground" />
                  <select
                    value={screenerSortBy}
                    onChange={(e) => setScreenerSortBy(e.target.value)}
                    className="bg-muted text-muted-foreground text-[10px] font-bold uppercase rounded px-2 py-1 border-none outline-none"
                  >
                    <option value="weighted_score">Model Score</option>
                    <option value="win_rate">Win Rate (AAA)</option>
                    <option value="mean_return">Mean Return (AAA)</option>
                    <option value="cumulative_return">Cumulative Return</option>
                  </select>
                </div>
                <Button variant="outline" size="sm" onClick={fetchScreener} disabled={screenerLoading}>
                  {screenerLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : "Refresh"}
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {screenerLoading && screenerData.length === 0 ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/5">
                      <th className="text-center py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground w-10">#</th>
                      <th className="text-left py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Symbol</th>
                      <th className="text-right py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Total Score</th>
                      <th className="text-right py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Model Score</th>
                      <th className="text-center py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">AAA WR</th>
                      <th className="text-center py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">AAA Ret</th>
                      <th className="text-center py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">VVV WR</th>
                      <th className="text-center py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">VVV Ret</th>
                      <th className="text-right py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Signals</th>
                      <th className="text-left py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Period</th>
                      <th className="text-center py-3 px-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {screenerData.map((item, idx) => {
                      const aaa = item.grade_details["AAA"];
                      const vvv = item.grade_details["VVV"];
                      const scoreColor = item.weighted_score > 0 ? "text-green-400" : item.weighted_score < 0 ? "text-red-400" : "text-muted-foreground";
                      return (
                        <tr
                          key={item.symbol}
                          className="border-b border-dashed hover:bg-muted/5 transition-colors cursor-pointer"
                          onClick={() => {
                            setSymbol(item.symbol);
                            setView("analysis");
                            fetchStockData(item.symbol);
                            fetchDecision(item.symbol);
                            fetchSignalHistory(item.symbol);
                            fetchSignalData(item.symbol);
                          }}
                        >
                          <td className="py-3 px-3 text-center text-[10px] font-bold text-muted-foreground">{idx + 1}</td>
                          <td className="py-3 px-3 font-bold">
                            <div>{getName(item.symbol)}</div>
                            <div className="text-[10px] text-muted-foreground font-mono">{item.symbol}</div>
                          </td>
                          <td className="py-3 px-3 text-right">
                            {(() => {
                              // Compute total score using mean return (per signal)
                              const buyGrades = ["AAA", "AA", "A"];
                              const sellGrades = ["V", "VV", "VVV"];
                              let buyScore = 0;
                              let sellScore = 0;
                              let buyCount = 0;
                              let sellCount = 0;
                              for (const g of buyGrades) {
                                const d = item.grade_details[g];
                                if (d && d.occurrences > 0) {
                                  buyScore += d.mean_return * (g === "AAA" ? 3 : g === "AA" ? 2 : 1);
                                  buyCount += d.occurrences;
                                }
                              }
                              for (const g of sellGrades) {
                                const d = item.grade_details[g];
                                if (d && d.occurrences > 0) {
                                  sellScore += Math.abs(d.mean_return) * (g === "VVV" ? 3 : g === "VV" ? 2 : 1);
                                  sellCount += d.occurrences;
                                }
                              }
                              const avgBuy = buyCount > 0 ? buyScore / buyCount : 0;
                              const avgSell = sellCount > 0 ? sellScore / sellCount : 0;
                              const totalScore = avgBuy + avgSell;
                              const scoreColor = totalScore > 0.015 ? "text-green-400" : totalScore > 0 ? "text-yellow-400" : "text-red-400";
                              const grade = totalScore > 0.03 ? "A+" : totalScore > 0.015 ? "A" : totalScore > 0.005 ? "B" : totalScore > 0 ? "C" : totalScore > -0.005 ? "D" : "F";
                              return (
                                <div className="flex items-center gap-1">
                                  <span className={cn("text-xs font-black", scoreColor)}>
                                    {(totalScore * 100).toFixed(2)}%
                                  </span>
                                  <span className={cn(
                                    "text-[10px] font-bold px-1 py-0.5 rounded",
                                    grade.startsWith("A") ? "bg-green-500/20 text-green-400" :
                                    grade === "B" ? "bg-blue-500/20 text-blue-400" :
                                    grade === "C" ? "bg-yellow-500/20 text-yellow-400" :
                                    "bg-red-500/20 text-red-400"
                                  )}>
                                    {grade}
                                  </span>
                                </div>
                              );
                            })()}
                          </td>
                          <td className="py-3 px-3 text-right">
                            <span className={cn("font-mono text-sm font-black", scoreColor)}>
                              {item.weighted_score.toFixed(3)}
                            </span>
                          </td>
                          <td className="py-3 px-3 text-center">
                            {aaa ? (
                              <span className={cn("text-[11px] font-bold", aaa.win_rate >= 0.5 ? "text-green-400" : "text-red-400")}>
                                {Math.round(aaa.win_rate * 100)}%
                              </span>
                            ) : <span className="text-muted-foreground text-[11px]">—</span>}
                          </td>
                          <td className="py-3 px-3 text-center">
                            {aaa ? (
                              <span className={cn("text-[11px] font-mono", aaa.mean_return >= 0 ? "text-green-400" : "text-red-400")}>
                                {aaa.mean_return >= 0 ? "+" : ""}{(aaa.mean_return * 100).toFixed(1)}%
                              </span>
                            ) : <span className="text-muted-foreground text-[11px]">—</span>}
                          </td>
                          <td className="py-3 px-3 text-center">
                            {vvv ? (
                              <span className={cn("text-[11px] font-bold", vvv.win_rate <= 0.5 ? "text-green-400" : "text-red-400")}>
                                {Math.round(vvv.win_rate * 100)}%
                              </span>
                            ) : <span className="text-muted-foreground text-[11px]">—</span>}
                          </td>
                          <td className="py-3 px-3 text-center">
                            {vvv ? (
                              <span className={cn("text-[11px] font-mono", vvv.mean_return <= 0 ? "text-green-400" : "text-red-400")}>
                                {vvv.mean_return >= 0 ? "+" : ""}{(vvv.mean_return * 100).toFixed(1)}%
                              </span>
                            ) : <span className="text-muted-foreground text-[11px]">—</span>}
                          </td>
                          <td className="py-3 px-3 text-right font-mono text-[11px] text-muted-foreground">
                            {item.total_signals}
                          </td>
                          <td className="py-3 px-3 text-[10px] text-muted-foreground">
                            {item.data_start} ~ {item.data_end}
                          </td>
                          <td className="py-3 px-3 text-center">
                            <Button variant="ghost" size="sm" className="text-[10px] font-bold uppercase">
                              Analyze
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {screenerData.length === 0 && !screenerLoading && (
                  <div className="flex items-center justify-center py-20 text-muted-foreground text-sm">
                    No screener data available. Run training first.
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* ================================================================ */}
      {/* STOCK ANALYSIS VIEW */}
      {/* ================================================================ */}
      {view === "analysis" && !ohlcData && !loading && (
        <div className="flex flex-col items-center justify-center py-32 bg-muted/10 rounded-3xl border-2 border-dashed border-border/50">
          <Activity className="h-12 w-12 text-muted-foreground/30 mb-4" />
          <p className="text-muted-foreground font-medium uppercase tracking-widest text-xs italic">
            {error || "Enter a ticker to begin analysis"}
          </p>
        </div>
      )}

      {view === "analysis" && ohlcData && (
        <div className="space-y-8">
          {/* Portfolio Decision Summary */}
          {decision && (
            <Card className="border-2 border-primary/20 bg-primary/5 shadow-lg">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <Compass className="h-4 w-4 text-primary" />
                  Portfolio Decision: {decision.symbol}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                  {/* Signal */}
                  <div className="space-y-1">
                    <div className="text-xs text-muted-foreground">Signal</div>
                    <div className="flex items-center gap-2">
                      <SignalBadge signal={decision.signal} />
                      <span className="text-sm font-bold">{Math.round(decision.confidence * 100)}% confidence</span>
                    </div>
                  </div>

                  {/* Model Rank */}
                  <div className="space-y-1">
                    <div className="text-xs text-muted-foreground">Model Rank</div>
                    <div className="text-lg font-bold">
                      {decision.rank !== null ? `#${decision.rank + 1}` : "N/A"}
                      <span className="text-xs text-muted-foreground ml-1">/ {decision.score !== null ? formatNum(decision.score, 4) : "N/A"}</span>
                    </div>
                  </div>

                  {/* Risk Status */}
                  <div className="space-y-1">
                    <div className="text-xs text-muted-foreground">Risk Status</div>
                    <div className="flex items-center gap-2">
                      {decision.risk_flags.length > 0 ? (
                        <Badge variant="destructive" className="gap-1">
                          <AlertTriangle className="h-3 w-3" /> {decision.risk_flags.length} flags
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-green-400 gap-1">
                          <CheckCircle className="h-3 w-3" /> Clear
                        </Badge>
                      )}
                    </div>
                  </div>

                  {/* Action */}
                  <div className="space-y-1">
                    <div className="text-xs text-muted-foreground">Action</div>
                    <div className={cn(
                      "text-lg font-bold",
                      decision.signal === "BUY" && "text-green-500",
                      decision.signal === "SELL" && "text-red-500",
                      decision.signal === "HOLD" && "text-yellow-500",
                    )}>
                      {decision.signal === "BUY" ? "Add to Portfolio" :
                       decision.signal === "SELL" ? "Remove from Portfolio" :
                       "Hold Position"}
                    </div>
                  </div>
                </div>

                {/* Key Reasons */}
                {decision.reasons.length > 0 && (
                  <div className="mt-4 pt-4 border-t">
                    <div className="text-xs text-muted-foreground mb-2">Key Reasons:</div>
                    <div className="flex flex-wrap gap-2">
                      {decision.reasons.slice(0, 3).map((r, i) => (
                        <Badge key={i} variant="outline" className="text-[10px]">
                          {r.length > 50 ? r.substring(0, 50) + "..." : r}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Row 1: Decision Panel + Model Confidence */}
          {decision && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Decision Card */}
              <Card className={cn(
                "border-2 shadow-lg overflow-hidden",
                decision.signal === "BUY" && "border-green-500/30 bg-green-500/5",
                decision.signal === "SELL" && "border-red-500/30 bg-red-500/5",
                decision.signal === "HOLD" && "border-yellow-500/30 bg-yellow-500/5",
              )}>
                <CardHeader className="pb-2 border-b border-dashed">
                  <CardTitle className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] uppercase font-black tracking-widest text-muted-foreground">
                        Trading Signal
                      </span>
                      {getName(decision.symbol) !== decision.symbol && (
                        <span className="text-xs font-medium text-muted-foreground">· {getName(decision.symbol)}</span>
                      )}
                    </div>
                    <SignalBadge signal={decision.signal} />
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-4 space-y-3">
                  <div className="text-center">
                    <div className={cn(
                      "text-6xl font-black tracking-tighter",
                      decision.signal === "BUY" && "text-green-400",
                      decision.signal === "SELL" && "text-red-400",
                      decision.signal === "HOLD" && "text-yellow-400",
                    )}>
                      {decision.signal}
                    </div>
                    <p className="text-[10px] text-muted-foreground mt-1 uppercase font-bold">
                      Confidence: {Math.round(decision.confidence * 100)}%
                    </p>
                  </div>
                  <ConfidenceBar value={decision.confidence} />
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>Score: {formatNum(decision.score, 4)}</span>
                    <span>Rank: {decision.rank !== null ? `#${decision.rank + 1}` : "N/A"}</span>
                  </div>

                  {/* Price Targets (P1-2) */}
                  {decision.price_targets && decision.signal === "BUY" && (
                    <div className="mt-3 pt-3 border-t border-dashed space-y-1.5">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-2">Price Targets</div>
                      {decision.price_targets.buy_range_low != null && decision.price_targets.buy_range_high != null && (
                        <div className="flex justify-between text-xs">
                          <span className="text-muted-foreground">Buy Range</span>
                          <span className="font-mono font-bold text-green-400">
                            {decision.price_targets.buy_range_low.toFixed(2)} - {decision.price_targets.buy_range_high.toFixed(2)}
                          </span>
                        </div>
                      )}
                      {decision.price_targets.stop_loss_price != null && (
                        <div className="flex justify-between text-xs">
                          <span className="text-muted-foreground">Stop Loss</span>
                          <span className="font-mono font-bold text-red-400">{decision.price_targets.stop_loss_price.toFixed(2)}</span>
                        </div>
                      )}
                      {decision.price_targets.target_price != null && (
                        <div className="flex justify-between text-xs">
                          <span className="text-muted-foreground">Target</span>
                          <span className="font-mono font-bold text-blue-400">{decision.price_targets.target_price.toFixed(2)}</span>
                        </div>
                      )}
                      {decision.price_targets.atr_20 != null && (
                        <div className="flex justify-between text-xs">
                          <span className="text-muted-foreground">ATR(20)</span>
                          <span className="font-mono text-muted-foreground">{decision.price_targets.atr_20.toFixed(2)}</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Strategy Recommendation (P1-1) */}
                  {decision.recommended_strategy && (
                    <div className="mt-3 pt-3 border-t border-dashed">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground mb-2">Recommended Strategy</div>
                      <div className="text-sm font-bold">{decision.recommended_strategy.display_name}</div>
                      <div className="text-[11px] text-muted-foreground mt-1">{decision.recommended_strategy.reason}</div>
                      <div className="flex items-center gap-1 mt-1">
                        <span className="text-[10px] text-muted-foreground">Fit:</span>
                        <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
                          <div
                            className="h-full bg-primary rounded-full"
                            style={{ width: `${Math.round(decision.recommended_strategy.confidence * 100)}%` }}
                          />
                        </div>
                        <span className="text-[10px] font-bold">{Math.round(decision.recommended_strategy.confidence * 100)}%</span>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Decision Reasons */}
              <Card className="lg:col-span-2 border shadow-lg bg-card text-card-foreground">
                <CardHeader className="pb-2 border-b border-dashed">
                  <CardTitle className="text-[10px] uppercase font-black tracking-widest text-muted-foreground">
                    Decision Analysis ({decision.reasons.length} factors)
                  </CardTitle>
                </CardHeader>
                <CardContent className="pt-4 max-h-[300px] overflow-y-auto space-y-2">
                  {decision.reasons.map((r, i) => (
                    <ReasonItem key={i} reason={r} />
                  ))}
                  {decision.reasons.length === 0 && (
                    <p className="text-muted-foreground text-xs italic">No specific reasons generated.</p>
                  )}
                </CardContent>
              </Card>
            </div>
          )}

          {/* Row 2: K-line Chart + Side Panels */}
          <div className="grid grid-cols-1 xl:grid-cols-4 gap-8">
            <div className="xl:col-span-3 space-y-8">
              <Card className="border shadow-lg bg-card text-card-foreground overflow-hidden">
                <CardHeader className="border-b bg-muted/10 flex flex-row items-center justify-between py-4">
                  <div className="flex items-center gap-4">
                    <div className="bg-primary px-3 py-1 rounded text-xs text-primary-foreground font-black uppercase">{ohlcData.symbol as string}</div>
                    <div className="flex items-baseline gap-2">
                      <CardTitle className="text-lg font-bold tracking-tight">Interactive Price Action</CardTitle>
                      {getName(ohlcData.symbol as string) !== (ohlcData.symbol as string) && (
                        <span className="text-sm text-muted-foreground font-medium">{getName(ohlcData.symbol as string)}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-4 text-[10px] uppercase font-bold text-muted-foreground">
                    <span className="flex items-center gap-1"><div className="h-2 w-2 rounded-full bg-emerald-500" /> T+5 Outlook</span>
                    <span className="flex items-center gap-1"><div className="h-2 w-2 rounded-full bg-primary" /> Daily Resolution</span>
                    {/* Signal overlay toggle */}
                    <button
                      onClick={() => setShowSignalOverlay(!showSignalOverlay)}
                      className={cn(
                        "flex items-center gap-1 px-2 py-0.5 rounded transition-all",
                        showSignalOverlay
                          ? "bg-indigo-500/20 text-indigo-400"
                          : "bg-muted text-muted-foreground hover:text-foreground",
                      )}
                    >
                      <div className={cn("h-2 w-2 rounded-full", showSignalOverlay ? "bg-indigo-400" : "bg-muted-foreground")} />
                      Signal Overlay
                    </button>
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  <div id="kline-chart" className="w-full h-[500px]" />
                </CardContent>
              </Card>

              {/* Factor Exposure Visualization + Table */}
              {factorEntries.length > 0 && (
                <Card className="border shadow-lg bg-card text-card-foreground">
                  <CardHeader className="border-b bg-muted/10 py-4">
                    <CardTitle className="text-[10px] uppercase font-black tracking-widest text-muted-foreground flex items-center gap-2">
                      <BarChart3 className="h-3.5 w-3.5" /> Factor Exposure (Top {factorEntries.length} Active Factors)
                    </CardTitle>
                  </CardHeader>
                  {/* Factor Z-Score Bar Chart */}
                  <CardContent className="pt-4 pb-2">
                    <div className="space-y-2">
                      {factorEntries.slice(0, 8).map(([name, snap]) => {
                        const z = snap.z_score ?? 0;
                        const barWidth = Math.min(Math.abs(z) / 3 * 100, 100); // 3σ = 100%
                        const isPositive = z >= 0;
                        return (
                          <div key={name} className="flex items-center gap-2">
                            <div className="w-32 text-[10px] font-mono text-muted-foreground truncate text-right">{name}</div>
                            <div className="flex-1 flex items-center h-4">
                              {/* Negative side */}
                              <div className="w-1/2 flex justify-end">
                                {!isPositive && (
                                  <div
                                    className="h-3 bg-red-500/60 rounded-l"
                                    style={{ width: `${barWidth}%` }}
                                  />
                                )}
                              </div>
                              {/* Center line */}
                              <div className="w-px h-4 bg-border" />
                              {/* Positive side */}
                              <div className="w-1/2 flex justify-start">
                                {isPositive && (
                                  <div
                                    className="h-3 bg-green-500/60 rounded-r"
                                    style={{ width: `${barWidth}%` }}
                                  />
                                )}
                              </div>
                            </div>
                            <div className={cn(
                              "w-12 text-[10px] font-mono font-bold text-right",
                              z > 1 ? "text-green-400" : z < -1 ? "text-red-400" : "text-muted-foreground",
                            )}>
                              {z > 0 ? "+" : ""}{z.toFixed(2)}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    <div className="flex justify-between mt-2 text-[9px] text-muted-foreground/50">
                      <span>-3σ</span>
                      <span>0</span>
                      <span>+3σ</span>
                    </div>
                  </CardContent>
                  <CardContent className="p-0">
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b bg-muted/5">
                            <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Factor</th>
                            <th className="text-left py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Category</th>
                            <th className="text-right py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Value</th>
                            <th className="text-right py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Z-Score</th>
                            <th className="text-right py-3 px-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Percentile</th>
                          </tr>
                        </thead>
                        <tbody>
                          {factorEntries.map(([name, snap]) => (
                            <tr key={name} className="border-b border-dashed hover:bg-muted/5">
                              <td className="py-2.5 px-4 font-mono text-xs">{name}</td>
                              <td className="py-2.5 px-4">
                                <Badge variant="outline" className="text-[10px]">{snap.category}</Badge>
                              </td>
                              <td className="py-2.5 px-4 text-right font-mono text-xs">{formatNum(snap.value, 4)}</td>
                              <td className={cn(
                                "py-2.5 px-4 text-right font-mono text-xs font-bold",
                                (snap.z_score ?? 0) > 2 && "text-green-400",
                                (snap.z_score ?? 0) < -2 && "text-red-400",
                              )}>
                                {snap.z_score !== null ? `${snap.z_score > 0 ? "+" : ""}${snap.z_score.toFixed(2)}` : "N/A"}
                              </td>
                              <td className="py-2.5 px-4 text-right text-xs text-muted-foreground">
                                {snap.percentile !== null ? `${snap.percentile.toFixed(0)}th` : "N/A"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* T6: Signal History Timeline */}
              {signalHistory.length > 0 && (
                <Card className="border shadow-lg bg-card text-card-foreground">
                  <CardHeader className="border-b bg-muted/10 py-4">
                    <CardTitle className="text-[10px] uppercase font-black tracking-widest text-muted-foreground flex items-center gap-2">
                      <ClipboardList className="h-3.5 w-3.5" /> Signal History (Last {signalHistory.length} Records)
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="pt-4">
                    <div className="space-y-3">
                      {signalHistory.slice(0, 10).map((record, i) => {
                        const sig = record.signal as "BUY" | "HOLD" | "SELL";
                        const colors = { BUY: "border-green-500/30 bg-green-500/5", HOLD: "border-yellow-500/30 bg-yellow-500/5", SELL: "border-red-500/30 bg-red-500/5" };
                        const dotColors = { BUY: "bg-green-500", HOLD: "bg-yellow-500", SELL: "bg-red-500" };
                        return (
                          <div key={i} className={cn("flex items-center gap-4 p-3 rounded-lg border", colors[sig] || colors.HOLD)}>
                            <div className={cn("h-2.5 w-2.5 rounded-full flex-shrink-0", dotColors[sig] || dotColors.HOLD)} />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-bold">{sig}</span>
                                <span className="text-[10px] text-muted-foreground">
                                  {record.confidence ? `${Math.round(record.confidence * 100)}%` : ""}
                                </span>
                                <span className="text-[10px] font-mono text-muted-foreground">
                                  score: {record.score != null ? record.score.toFixed(4) : "N/A"}
                                </span>
                              </div>
                              {record.price_targets?.stop_loss_price != null && (
                                <div className="text-[10px] text-muted-foreground mt-0.5">
                                  SL: {record.price_targets.stop_loss_price.toFixed(2)}
                                </div>
                              )}
                            </div>
                            <div className="text-[10px] text-muted-foreground flex-shrink-0">
                              {record.recorded_at ? new Date(record.recorded_at).toLocaleDateString() : ""}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>

            {/* Right sidebar */}
            <div className="space-y-6">
              {/* Model Confidence — use decision engine confidence as primary, ohlcData as fallback */}
              {(() => {
                const displayConfidence = decision?.confidence ?? (typeof ohlcData.confidence === "number" ? ohlcData.confidence as number : null);
                const displayTrend = ohlcData.trend as number | null;
                return (
                  <Card className="border-none shadow-lg overflow-hidden group hover:shadow-xl transition-all">
                    <CardHeader className="pb-2 bg-muted/20 border-b mb-4">
                      <CardTitle className="flex items-center gap-2 text-[10px] uppercase font-black tracking-widest text-muted-foreground">
                        <Zap className="h-3.5 w-3.5 text-yellow-500" /> Model Confidence
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="flex items-baseline gap-2">
                        <div className="text-5xl font-black tracking-tighter">
                          {displayConfidence != null ? displayConfidence.toFixed(2) : "N/A"}
                        </div>
                        {displayTrend != null && (
                          <div className={cn("text-xs font-bold flex items-center gap-0.5", displayTrend >= 0 ? "text-green-500" : "text-red-500")}>
                            {displayTrend >= 0
                              ? <ArrowUpRight className="h-3 w-3" />
                              : <ArrowDownRight className="h-3 w-3" />}
                            {Math.abs(displayTrend * 100).toFixed(1)}%
                          </div>
                        )}
                      </div>
                      <p className="text-[10px] text-muted-foreground mt-2 font-bold uppercase">
                        {decision ? "Decision engine composite score" : "Estimated probability of alpha generation"}
                      </p>
                      <div className="mt-6 h-1.5 w-full bg-muted rounded-full overflow-hidden">
                        <div className="h-full bg-primary rounded-full group-hover:bg-primary/80 transition-all" style={{ width: `${(displayConfidence ?? 0) * 100}%` }} />
                      </div>
                      {/* Sub-scores breakdown when decision is available */}
                      {decision && (
                        <div className="mt-4 space-y-1.5 text-[10px]">
                          <div className="flex justify-between">
                            <span className="text-muted-foreground uppercase">Signal</span>
                            <span className="font-bold">{decision.signal}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground uppercase">Score</span>
                            <span className="font-mono font-bold">{formatNum(decision.score, 4)}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground uppercase">Rank</span>
                            <span className="font-mono font-bold">{decision.rank != null ? `#${decision.rank + 1}` : "N/A"}</span>
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                );
              })()}

              {/* S4: Signal Performance Card — comprehensive view */}
              {signalPerformance && (
                <Card className="border-none shadow-lg overflow-hidden">
                  <CardHeader className="pb-2 bg-muted/20 border-b mb-4">
                    <CardTitle className="flex items-center gap-2 text-[10px] uppercase font-black tracking-widest text-muted-foreground">
                      <BarChart3 className="h-3.5 w-3.5 text-blue-500" /> Signal Performance (10d Forward Returns)
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1">
                    {/* Total Score */}
                    {totalScore && (
                      <div className="mb-3 p-3 rounded-lg bg-primary/5 border border-primary/10">
                        <div className="flex items-center justify-between mb-2">
                          <div className="text-[10px] uppercase font-bold text-muted-foreground">Model Effectiveness (per signal)</div>
                          <div className={cn(
                            "text-lg font-black",
                            totalScore.total_score > 0.015 ? "text-green-500" :
                            totalScore.total_score > 0 ? "text-yellow-500" :
                            "text-red-500"
                          )}>
                            {totalScore.total_score > 0 ? "+" : ""}{(totalScore.total_score * 100).toFixed(2)}%
                          </div>
                        </div>
                        <div className="flex items-center gap-2 mb-1">
                          <div className={cn(
                            "text-2xl font-black px-2 py-0.5 rounded",
                            totalScore.grade.startsWith("A") ? "bg-green-500/20 text-green-400" :
                            totalScore.grade === "B" ? "bg-blue-500/20 text-blue-400" :
                            totalScore.grade === "C" ? "bg-yellow-500/20 text-yellow-400" :
                            "bg-red-500/20 text-red-400"
                          )}>
                            {totalScore.grade}
                          </div>
                          <div className="text-xs text-muted-foreground">{totalScore.description}</div>
                        </div>
                        <div className="grid grid-cols-4 gap-2 mt-2 text-[10px]">
                          <div className="text-center">
                            <div className="text-muted-foreground">Buy Avg</div>
                            <div className="font-bold text-green-400">+{(totalScore.buy_score * 100).toFixed(2)}%</div>
                          </div>
                          <div className="text-center">
                            <div className="text-muted-foreground">Sell Avg</div>
                            <div className="font-bold text-red-400">+{(totalScore.sell_score * 100).toFixed(2)}%</div>
                          </div>
                          <div className="text-center">
                            <div className="text-muted-foreground">Buy N</div>
                            <div className="font-bold">{totalScore.buy_signals}</div>
                          </div>
                          <div className="text-center">
                            <div className="text-muted-foreground">Sell N</div>
                            <div className="font-bold">{totalScore.sell_signals}</div>
                          </div>
                        </div>
                      </div>
                    )}
                    {/* Table header */}
                    <div className="grid grid-cols-[36px_1fr_50px_50px_50px_40px] gap-1 text-[9px] uppercase font-bold text-muted-foreground border-b border-dashed pb-1 mb-1">
                      <span>Grade</span>
                      <span>Win Rate</span>
                      <span className="text-right">Mean</span>
                      <span className="text-right">Median</span>
                      <span className="text-right">Cumul.</span>
                      <span className="text-right">Count</span>
                    </div>

                    {["AAA", "AA", "A", "V", "VV", "VVV"].map(grade => {
                      const p = signalPerformance[grade];
                      if (!p || p.total_occurrences === 0) return null;
                      const isBuy = ["AAA", "AA", "A"].includes(grade);
                      const wrBarWidth = Math.round(p.win_rate * 100);
                      return (
                        <div key={grade} className="grid grid-cols-[36px_1fr_50px_50px_50px_40px] gap-1 items-center text-xs py-1 border-b border-dashed/50 last:border-0">
                          <div className={cn(
                            "font-black text-center",
                            isBuy ? "text-green-400" : "text-red-400",
                          )}>
                            {grade}
                          </div>
                          <div className="flex items-center gap-1">
                            <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                              <div
                                className={cn("h-full rounded-full", p.win_rate >= 0.5 ? "bg-green-500" : "bg-red-500")}
                                style={{ width: `${wrBarWidth}%` }}
                              />
                            </div>
                            <span className="text-[10px] font-mono font-bold w-8 text-right">{wrBarWidth}%</span>
                          </div>
                          <div className={cn(
                            "text-right font-mono text-[11px] font-bold",
                            p.mean_return >= 0 ? "text-green-400" : "text-red-400",
                          )}>
                            {p.mean_return >= 0 ? "+" : ""}{(p.mean_return * 100).toFixed(1)}%
                          </div>
                          <div className={cn(
                            "text-right font-mono text-[11px]",
                            (p.median_return ?? 0) >= 0 ? "text-green-400/70" : "text-red-400/70",
                          )}>
                            {p.median_return != null ? `${p.median_return >= 0 ? "+" : ""}${(p.median_return * 100).toFixed(1)}%` : "—"}
                          </div>
                          <div className={cn(
                            "text-right font-mono text-[11px] font-bold",
                            p.cumulative_return >= 0 ? "text-green-400" : "text-red-400",
                          )}>
                            {p.cumulative_return >= 0 ? "+" : ""}{(p.cumulative_return * 100).toFixed(1)}%
                          </div>
                          <div className="text-right text-muted-foreground text-[10px]">
                            {p.total_occurrences}×
                          </div>
                        </div>
                      );
                    })}

                    {/* Summary footer */}
                    <div className="pt-2 border-t border-dashed text-[10px] text-muted-foreground space-y-0.5">
                      <div className="flex justify-between">
                        <span>Buy signals avg win rate</span>
                        <span className="font-bold text-green-400">{Math.round(
                          ((signalPerformance["AAA"]?.win_rate ?? 0) + (signalPerformance["AA"]?.win_rate ?? 0) + (signalPerformance["A"]?.win_rate ?? 0)) / 3 * 100
                        )}%</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Sell signals avg win rate</span>
                        <span className="font-bold text-red-400">{Math.round(
                          ((signalPerformance["V"]?.win_rate ?? 0) + (signalPerformance["VV"]?.win_rate ?? 0) + (signalPerformance["VVV"]?.win_rate ?? 0)) / 3 * 100
                        )}%</span>
                      </div>
                      {/* Best/worst extremes */}
                      {(() => {
                        const allGrades = ["AAA", "AA", "A", "V", "VV", "VVV"]
                          .map(g => signalPerformance[g])
                          .filter(p => p && p.total_occurrences > 0);
                        if (allGrades.length === 0) return null;
                        const bestReturn = Math.max(...allGrades.map(p => p.max_return ?? 0));
                        const worstReturn = Math.min(...allGrades.map(p => p.min_return ?? 0));
                        return (
                          <div className="flex justify-between pt-1">
                            <span>Range</span>
                            <span className="font-mono">
                              <span className="text-red-400">{(worstReturn * 100).toFixed(1)}%</span>
                              <span className="mx-0.5">~</span>
                              <span className="text-green-400">+{(bestReturn * 100).toFixed(1)}%</span>
                            </span>
                          </div>
                        );
                      })()}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Guardrails (enhanced with decision data) */}
              <Card className="border-none shadow-lg overflow-hidden">
                <CardHeader className="pb-2 bg-muted/20 border-b mb-4">
                  <CardTitle className="flex items-center gap-2 text-[10px] uppercase font-black tracking-widest text-muted-foreground">
                    <ShieldAlert className="h-3.5 w-3.5 text-primary" /> Risk Guardrails
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {guardrailEntries.length > 0 ? (
                    guardrailEntries.map(([name, detail]) => (
                      <div key={name} className="flex justify-between items-center border-b border-dashed pb-2 last:border-0">
                        <span className="text-xs font-bold text-muted-foreground uppercase">{name.replace("_", " ")}</span>
                        <div className="flex items-center gap-2">
                          {detail.metric !== undefined && (
                            <span className="text-[10px] font-mono text-muted-foreground">
                              {typeof detail.metric === "number" ? formatCompact(detail.metric) : detail.metric}
                            </span>
                          )}
                          <span className={cn(
                            "text-[10px] font-black uppercase tracking-tighter px-2 py-0.5 rounded border",
                            detail.passed
                              ? "bg-green-500/10 text-green-500 border-green-500/30"
                              : "bg-red-500/10 text-red-500 border-red-500/30",
                          )}>
                            {detail.passed ? "PASS" : "FAIL"}
                          </span>
                        </div>
                      </div>
                    ))
                  ) : (
                    // Fallback to original guardrails
                    ((ohlcData.guardrails as Array<{ label: string; status: string; color?: string }>) || []).map((risk, i) => (
                      <div key={i} className="flex justify-between items-center border-b border-dashed pb-2 last:border-0">
                        <span className="text-xs font-bold text-muted-foreground uppercase">{risk.label}</span>
                        <span className={cn(
                          "text-[10px] font-black uppercase tracking-tighter px-2 py-0.5 rounded border",
                          (risk.color || "text-muted-foreground").replace("text", "bg").replace("500", "500/10"),
                          (risk.color || "text-muted-foreground").replace("text", "border"),
                          risk.color,
                        )}>
                          {risk.status}
                        </span>
                      </div>
                    ))
                  )}
                </CardContent>
              </Card>

              {/* Risk Flags */}
              {decision && decision.risk_flags.length > 0 && (
                <Card className="border-red-500/30 bg-red-500/5 shadow-lg overflow-hidden">
                  <CardHeader className="pb-2 border-b border-red-500/20 mb-4">
                    <CardTitle className="flex items-center gap-2 text-[10px] uppercase font-black tracking-widest text-red-400">
                      <AlertTriangle className="h-3.5 w-3.5" /> Active Risk Flags
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {decision.risk_flags.map((flag, i) => (
                      <Badge key={i} variant="destructive" className="mr-2 mb-2 text-[10px]">
                        {flag.replace("_", " ")}
                      </Badge>
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Data Provenance */}
              <div className="p-6 bg-primary/5 rounded-2xl border border-primary/10">
                <h4 className="text-[10px] font-black uppercase tracking-widest text-primary mb-3 text-left">Data Provenance</h4>
                <p className="text-xs leading-relaxed text-muted-foreground italic text-left">
                  Served from Qlib market data and the current recommended model artifact.
                  {decision && (
                    <span className="block mt-1 not-italic text-foreground/60">
                      Decision timestamp: {decision.timestamp}
                    </span>
                  )}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
