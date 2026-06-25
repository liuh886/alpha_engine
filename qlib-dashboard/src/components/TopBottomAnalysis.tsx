import { useState, useEffect, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";
import { LoadingSpinner } from "@/components/ui/loading-state";
import { BarChart3, TrendingUp, TrendingDown, Trophy } from "lucide-react";

interface BacktestMetric {
  total_return: number;
  excess_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  annual_return: number;
  volatility: number;
  mean_ic: number;
  n_periods: number;
}

interface ModelAnalysis {
  model_id: string;
  run_id: string;
  market: string;
  benchmark: string;
  test_period: string;
  n_instruments: number;
  n_dates: number;
  top_results: Record<string, BacktestMetric>;
  bottom_results: Record<string, BacktestMetric>;
}

const K_VALUES = [5, 10, 15, 20];

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function colorReturn(v: number): string {
  if (v > 0.05) return "text-green-400";
  if (v > 0) return "text-green-500/70";
  if (v < -0.1) return "text-red-400";
  return "text-red-500/70";
}

function MetricRow({
  label, top, bottom,
}: {
  label: string;
  top: (k: number) => number;
  bottom: (k: number) => number;
}) {
  return (
    <tr className="border-b border-dashed border-border/50">
      <td className="py-1.5 pr-4 text-xs font-medium text-muted-foreground whitespace-nowrap">{label}</td>
      {K_VALUES.map(k => (
        <td key={`top${k}`} className={cn("text-center px-2 text-xs font-mono", colorReturn(top(k)))}>
          {label.startsWith("sharpe") ? top(k).toFixed(2) : pct(top(k))}
        </td>
      ))}
      {K_VALUES.map(k => (
        <td key={`bot${k}`} className={cn("text-center px-2 text-xs font-mono", colorReturn(bottom(k)))}>
          {label.startsWith("sharpe") ? bottom(k).toFixed(2) : pct(bottom(k))}
        </td>
      ))}
    </tr>
  );
}

export function TopBottomAnalysis() {
  const [data, setData] = useState<ModelAnalysis[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedModel, setSelectedModel] = useState(0);

  useEffect(() => {
    apiFetch("/api/artifacts/top-bottom-analysis", { cache: "no-store" })
      .then(r => r.json())
      .then(json => {
        setData(json.models || []);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  const models = useMemo(() => data.filter(m => m.top_results["5"]), [data]);
  const model = models[selectedModel];

  if (loading) return <LoadingSpinner message="Running backtest analysis..." />;
  if (error) return <div className="text-destructive text-sm">{error}</div>;
  if (!model) return <div className="text-muted-foreground text-sm">No analysis data. Run scripts/run_top_bottom_analysis.py first.</div>;

  const labels: { label: string; top: (k: number) => number; bottom: (k: number) => number }[] = [
    { label: "Total Return", top: k => model.top_results[String(k)].total_return, bottom: k => model.bottom_results[String(k)].total_return },
    { label: "Excess Return", top: k => model.top_results[String(k)].excess_return, bottom: k => model.bottom_results[String(k)].excess_return },
    { label: "sharpe", top: k => model.top_results[String(k)].sharpe_ratio, bottom: k => model.bottom_results[String(k)].sharpe_ratio },
    { label: "Max Drawdown", top: k => model.top_results[String(k)].max_drawdown, bottom: k => model.bottom_results[String(k)].max_drawdown },
    { label: "Annual Return", top: k => model.top_results[String(k)].annual_return, bottom: k => model.bottom_results[String(k)].annual_return },
    { label: "Volatility", top: k => model.top_results[String(k)].volatility, bottom: k => model.bottom_results[String(k)].volatility },
    { label: "Mean IC", top: k => model.top_results[String(k)].mean_ic, bottom: k => model.bottom_results[String(k)].mean_ic },
  ];

  const bestTopK = K_VALUES.reduce((best, k) => {
    const s = model.top_results[String(k)].sharpe_ratio;
    return s > best.sharpe ? { k, sharpe: s } : best;
  }, { k: 5, sharpe: -Infinity });

  return (
    <div className="space-y-6 max-w-[1400px] mx-auto pb-16">
      {/* Header */}
      <div className="border-b pb-4">
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <BarChart3 className="h-6 w-6" /> Top / Bottom Analysis
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          Layered backtest: TOP K vs BOTTOM K, 10-day hold, daily rebalancing. Benchmark: {model.benchmark}
        </p>
      </div>

      {/* Model selector */}
      {models.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {models.map((m, i) => (
            <button
              key={m.run_id}
              onClick={() => setSelectedModel(i)}
              className={cn(
                "px-3 py-1.5 text-xs font-bold rounded-lg border transition-all",
                i === selectedModel
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-card hover:bg-muted border-border",
              )}
            >
              {m.model_id} <Badge variant="outline" className="ml-1 text-[9px]">{m.market.toUpperCase()}</Badge>
            </button>
          ))}
        </div>
      )}

      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card>
          <CardHeader className="py-2 px-4"><CardTitle className="text-[10px] uppercase text-muted-foreground">Market</CardTitle></CardHeader>
          <CardContent className="py-1 px-4 text-lg font-black">{model.market.toUpperCase()}</CardContent>
        </Card>
        <Card>
          <CardHeader className="py-2 px-4"><CardTitle className="text-[10px] uppercase text-muted-foreground">Benchmark</CardTitle></CardHeader>
          <CardContent className="py-1 px-4 text-lg font-black">{model.benchmark}</CardContent>
        </Card>
        <Card>
          <CardHeader className="py-2 px-4"><CardTitle className="text-[10px] uppercase text-muted-foreground">Instruments</CardTitle></CardHeader>
          <CardContent className="py-1 px-4 text-lg font-black">{model.n_instruments}</CardContent>
        </Card>
        <Card>
          <CardHeader className="py-2 px-4"><CardTitle className="text-[10px] uppercase text-muted-foreground">Best K</CardTitle></CardHeader>
          <CardContent className="py-1 px-4 text-lg font-black flex items-center gap-1">
            <Trophy className="h-4 w-4 text-yellow-500" /> K={bestTopK.k} (sharpe={bestTopK.sharpe.toFixed(2)})
          </CardContent>
        </Card>
      </div>

      {/* Main comparison table */}
      <Card>
        <CardHeader className="pb-3 border-b">
          <CardTitle className="text-sm font-semibold">
            {model.model_id} — {model.test_period} — {model.n_dates} trading days
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b-2 border-border">
                <th className="text-left py-2 pr-4 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Metric</th>
                <th colSpan={4} className="text-center py-2 px-2 text-[10px] font-bold uppercase tracking-wider">
                  <span className="flex items-center justify-center gap-1"><TrendingUp className="h-3 w-3 text-green-500" /> TOP K</span>
                </th>
                <th colSpan={4} className="text-center py-2 px-2 text-[10px] font-bold uppercase tracking-wider">
                  <span className="flex items-center justify-center gap-1"><TrendingDown className="h-3 w-3 text-red-500" /> BOTTOM K</span>
                </th>
              </tr>
              <tr className="border-b border-border">
                <th className="text-left py-1 pr-4"></th>
                {K_VALUES.map(k => <th key={`tht${k}`} className="text-center px-2 py-1 text-[10px] font-bold font-mono">K={k}</th>)}
                {K_VALUES.map(k => <th key={`thb${k}`} className="text-center px-2 py-1 text-[10px] font-bold font-mono">K={k}</th>)}
              </tr>
            </thead>
            <tbody>
              {labels.map(l => (
                <MetricRow key={l.label} label={l.label} top={l.top} bottom={l.bottom} />
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* Interpretation */}
      <Card>
        <CardHeader className="pb-3 border-b">
          <CardTitle className="text-sm font-semibold">Interpretation</CardTitle>
        </CardHeader>
        <CardContent className="pt-4 text-xs text-muted-foreground space-y-2">
          <p><strong>TOP K</strong> selects the K stocks with the <em>highest</em> predicted scores. Positive excess return confirms the model ranks future winners correctly.</p>
          <p><strong>BOTTOM K</strong> (inverse) selects the K stocks with the <em>lowest</em> predicted scores. If BOTTOM K underperforms TOP K, the ranking is directionally correct.</p>
          <p>The <strong>spread</strong> between TOP K and BOTTOM K measures ranking quality — wider spread = better discrimination.</p>
          <p className="text-[10px]">Backtest engine: layered daily rebalancing (1/10 capital per day), 10-day hold, 20bps cost. Benchmark: {model.benchmark}.</p>
        </CardContent>
      </Card>
    </div>
  );
}
