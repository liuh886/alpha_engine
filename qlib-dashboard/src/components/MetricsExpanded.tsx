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

  // Core performance metrics (always shown)
  const entries = [
    { label: "Total Return", value: metrics["Total Return"] ?? num(ind["total_return"]), fmt: formatPct },
    { label: "Benchmark Return", value: metrics["Benchmark Return"] ?? num(ind["bench"] ?? ind["benchmark_return"]), fmt: formatPct },
    { label: "Excess Return", value: metrics["Excess Return"] ?? num(ind["excess_return"] ?? ind["excess_return_with_cost"]), fmt: formatPct },
    { label: "Annualized Return", value: metrics["Annualized Return"], fmt: formatPct },
    { label: "Max Drawdown", value: metrics["Max Drawdown"], fmt: formatPct },
    { label: "Annualized Volatility", value: metrics["Annualized Volatility"], fmt: (v?: number) => formatNum(v, 3) },
    { label: "Sharpe Ratio", value: metrics["Sharpe Ratio"] ?? metrics["sharpe"], fmt: (v?: number) => formatNum(v, 3) },
    { label: "Information Ratio", value: metrics["Information Ratio"], fmt: (v?: number) => formatNum(v, 3) },
    { label: "Turnover", value: num(ind["turnover"] ?? ind["turnover_rate"]), fmt: (v?: number) => formatNum(v, 3) },
  ];

  // Walk-forward / signal quality metrics (shown when available)
  const wfMetrics = [
    { label: "Mean IC", value: metrics["IC"] ?? metrics["Mean IC"], fmt: (v?: number) => formatNum(v, 4) },
    { label: "ICIR", value: metrics["ICIR"], fmt: (v?: number) => formatNum(v, 3) },
    { label: "Positive IC Ratio", value: metrics["Positive IC Ratio"], fmt: formatPct },
    { label: "Consistency", value: metrics["Consistency"], fmt: formatPct },
  ];
  const hasWfData = wfMetrics.some(m => m.value !== undefined && m.value !== null);

  // WF split counts
  const wfSuccessful = metrics["WF Successful Splits"];
  const wfTotal = metrics["WF Total Splits"];
  const hasSplitData = wfSuccessful !== undefined && wfTotal !== undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Metrics (Expanded)</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm mb-4">
          {entries.map((e) => (
            <div key={e.label} className="flex flex-col">
              <span className="text-muted-foreground">{e.label}</span>
              <span className="font-medium">{e.fmt(e.value)}</span>
            </div>
          ))}
        </div>

        {hasWfData && (
          <>
            <h4 className="text-sm font-semibold mb-2 mt-4">Walk-Forward / Signal Quality</h4>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              {wfMetrics.map((e) => (
                <div key={e.label} className="flex flex-col">
                  <span className="text-muted-foreground">{e.label}</span>
                  <span className="font-medium">{e.fmt(e.value)}</span>
                </div>
              ))}
              {hasSplitData && (
                <div className="flex flex-col">
                  <span className="text-muted-foreground">WF Splits</span>
                  <span className="font-medium">
                    {wfSuccessful}/{wfTotal} successful
                  </span>
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
