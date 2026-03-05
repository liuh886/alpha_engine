import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function formatPercent(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return "N/A";
  return `${(value * 100).toFixed(2)}%`;
}

function formatNumber(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return "N/A";
  return value.toFixed(3);
}

export function MetricsExpanded({
  metrics,
  indicators,
}: {
  metrics: Record<string, number>;
  indicators?: Record<string, any>;
}) {
  const ind = indicators || {};
  const entries = [
    { label: "Annualized Return", value: metrics["Annualized Return"], fmt: formatPercent },
    { label: "Max Drawdown", value: metrics["Max Drawdown"], fmt: formatPercent },
    { label: "Annualized Volatility", value: metrics["Annualized Volatility"], fmt: formatNumber },
    { label: "Sharpe Ratio", value: metrics["Sharpe Ratio"], fmt: formatNumber },
    { label: "Information Ratio", value: metrics["Information Ratio"], fmt: formatNumber },
    { label: "Total Return", value: metrics["Total Return"], fmt: formatPercent },
    { label: "Excess Return", value: ind["excess_return"] ?? ind["excess_return_with_cost"], fmt: formatPercent },
    { label: "Benchmark Return", value: ind["bench"] ?? ind["benchmark_return"], fmt: formatPercent },
    { label: "Turnover", value: ind["turnover"] ?? ind["turnover_rate"], fmt: formatNumber },
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
