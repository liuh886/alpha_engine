import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPct, formatNum } from "@/lib/format";

export function MetricsExpanded({
  metrics,
  indicators,
}: {
  metrics: Record<string, number>;
  indicators?: Record<string, unknown>;
}) {
  const ind = indicators || {};
  const num = (v: unknown): number | undefined => typeof v === 'number' ? v : undefined;
  const entries = [
    { label: "Annualized Return", value: metrics["Annualized Return"], fmt: formatPct },
    { label: "Max Drawdown", value: metrics["Max Drawdown"], fmt: formatPct },
    { label: "Annualized Volatility", value: metrics["Annualized Volatility"], fmt: (v?: number) => formatNum(v, 3) },
    { label: "Sharpe Ratio", value: metrics["Sharpe Ratio"], fmt: (v?: number) => formatNum(v, 3) },
    { label: "Information Ratio", value: metrics["Information Ratio"], fmt: (v?: number) => formatNum(v, 3) },
    { label: "Total Return", value: metrics["Total Return"], fmt: formatPct },
    { label: "Excess Return", value: num(ind["excess_return"] ?? ind["excess_return_with_cost"]), fmt: formatPct },
    { label: "Benchmark Return", value: num(ind["bench"] ?? ind["benchmark_return"]), fmt: formatPct },
    { label: "Turnover", value: num(ind["turnover"] ?? ind["turnover_rate"]), fmt: (v?: number) => formatNum(v, 3) },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Metrics (Expanded)</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
          {entries.map((e) => (
            <div key={e.label} className="flex flex-col">
              <span className="text-muted-foreground">{e.label}</span>
              <span className="font-medium">{e.fmt(e.value)}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
