import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TrendingUp, TrendingDown, Activity, AlertCircle, Zap } from "lucide-react";
import { cn } from "@/lib/utils";

interface OverviewCardsProps {
  metrics: Record<string, number | null | undefined>;
  unavailableReason?: string;
}

export function OverviewCards({ metrics, unavailableReason = 'Not declared by the formal package.' }: OverviewCardsProps) {
  const formatPercent = (val: number | null | undefined) => {
    if (val === undefined || val === null || Number.isNaN(val)) return null;
    return `${(val * 100).toFixed(2)}%`;
  };
  const formatNumber = (val: number | null | undefined) => {
    if (val === undefined || val === null || Number.isNaN(val)) return null;
    return val.toFixed(2);
  };

  const totalReturn = metrics["Total Return"];
  const annualReturn = metrics["Annualized Return"] ?? metrics.CAGR;
  const informationRatio = metrics["Information Ratio"];
  const isPositive = totalReturn !== null && totalReturn !== undefined && totalReturn >= 0;
  const annualReturnText = formatPercent(annualReturn);
  const informationRatioText = formatNumber(informationRatio);

  const stats = [
    {
      title: "Total Return",
      value: formatPercent(totalReturn),
      sub: annualReturnText ? `Ann: ${annualReturnText}` : null,
      icon: isPositive ? TrendingUp : TrendingDown,
      color: totalReturn == null ? "text-muted-foreground" : isPositive ? "text-green-500" : "text-red-500",
      testid: "metric-return",
      valueTestid: "metric-total-return-value",
      subTestid: "metric-annual-return-sub"
    },
    {
      title: "Sharpe Ratio",
      value: formatNumber(metrics["Sharpe Ratio"]),
      sub: informationRatioText ? `IR: ${informationRatioText}` : null,
      icon: Zap,
      color: "text-blue-500",
      testid: "metric-sharpe"
    },
    {
      title: "Max Drawdown",
      value: formatPercent(metrics["Max Drawdown"]),
      sub: null,
      icon: AlertCircle,
      color: "text-orange-500",
      testid: "metric-drawdown"
    },
    {
      title: "Volatility",
      value: formatPercent(metrics["Annualized Volatility"]),
      sub: null,
      icon: Activity,
      color: "text-purple-500",
      testid: "metric-volatility"
    },
  ];

  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat) => (
        <Card key={stat.title} data-testid={stat.testid}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-1.5">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              {stat.title}
            </CardTitle>
            <stat.icon className={cn("h-4 w-4", stat.value === null ? "text-muted-foreground/40" : stat.color)} />
          </CardHeader>
          <CardContent>
            {stat.value === null ? (
              <div>
                <div className="text-sm font-semibold text-muted-foreground">Unavailable</div>
                <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground/80">{unavailableReason}</p>
              </div>
            ) : (
              <div className={cn("text-xl font-semibold tabular-nums", stat.color)} data-testid={stat.valueTestid}>
                {stat.value}
              </div>
            )}
            {stat.sub && (
              <p className="text-xs text-muted-foreground mt-0.5" data-testid={stat.subTestid}>{stat.sub}</p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
