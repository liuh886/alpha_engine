import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TrendingUp, TrendingDown, Activity, AlertCircle, Zap, BarChart } from "lucide-react";
import { cn } from "@/lib/utils";

export function OverviewCards({ metrics }: { metrics: Record<string, number> }) {
  const formatPercent = (val: number | undefined) => {
    if (val === undefined || val === null || isNaN(val)) return "0.00%";
    return `${(val * 100).toFixed(2)}%`;
  };
  const formatNumber = (val: number | undefined) => {
    if (val === undefined || val === null || isNaN(val)) return "0.00";
    return val.toFixed(2);
  };

  const stats = [
    {
      title: "Total Return",
      value: formatPercent(metrics["Total Return"]),
      sub: `Ann: ${formatPercent(metrics["Annualized Return"])}`,
      icon: (metrics["Total Return"] || 0) >= 0 ? TrendingUp : TrendingDown,
      color: (metrics["Total Return"] || 0) >= 0 ? "text-green-500" : "text-red-500",
      bg: (metrics["Total Return"] || 0) >= 0 ? "bg-green-500/10" : "bg-red-500/10",
    },
    {
      title: "Sharpe Ratio",
      value: formatNumber(metrics["Sharpe Ratio"]),
      sub: `IR: ${formatNumber(metrics["Information Ratio"])}`,
      icon: Zap,
      color: "text-blue-500",
      bg: "bg-blue-500/10",
    },
    {
      title: "Max Drawdown",
      value: formatPercent(metrics["Max Drawdown"]),
      sub: "Historical peak-to-trough",
      icon: AlertCircle,
      color: "text-orange-500",
      bg: "bg-orange-500/10",
    },
    {
      title: "Volatility",
      value: formatPercent(metrics["Annualized Volatility"]),
      sub: "252-day annualized",
      icon: Activity,
      color: "text-purple-500",
      bg: "bg-purple-500/10",
    },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat, i) => (
        <Card
          key={i}
          className="overflow-hidden border-none shadow-md bg-card/50 backdrop-blur-sm hover:shadow-lg transition-all duration-500 group animate-in fade-in slide-in-from-bottom-4"
          style={{ animationFillMode: "both", animationDelay: `${i * 150}ms` }}
        >
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground group-hover:text-primary transition-colors duration-300 delay-75">
              {stat.title}
            </CardTitle>
            <div className={cn("p-2 rounded-lg transition-transform duration-500 group-hover:scale-125 group-hover:rotate-12", stat.bg)}>
              <stat.icon className={cn("h-4 w-4", stat.color)} />
            </div>
          </CardHeader>
          <CardContent>
            <div className={cn("text-2xl font-black tracking-tight tabular-nums transition-transform duration-300 group-hover:translate-x-1", stat.color)}>
              {stat.value}
            </div>
            <p className="text-[10px] font-medium text-muted-foreground mt-1 flex items-center gap-1 opacity-80 group-hover:opacity-100 transition-opacity">
              <BarChart className="h-3 w-3 inline" />
              {stat.sub}
            </p>
          </CardContent>
          <div className={cn("h-1 w-full mt-4", stat.bg)}>
            <div className={cn("h-full w-1/3 rounded-full opacity-50 transition-all duration-700 ease-out group-hover:w-full group-hover:opacity-100", stat.color.replace('text', 'bg'))}></div>
          </div>
        </Card>
      ))}
    </div>
  );
}
