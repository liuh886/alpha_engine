import { Card, CardContent } from "@/components/ui/card";
import { TrendingUp, Target, Shield, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatSignedPct } from "./types";
import type { AttributionSummary } from "./types";

export function AttributionSummaryCards({ summary }: { summary: AttributionSummary | null }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10">
              <TrendingUp className="h-4 w-4 text-primary" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Total Return</p>
              <p className={cn("text-2xl font-bold", summary ? (summary.total_return >= 0 ? "text-green-500" : "text-red-500") : "")}>
                {summary ? formatSignedPct(summary.total_return) : "--"}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-green-500/10">
              <Target className="h-4 w-4 text-green-500" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Excess Return (Alpha)</p>
              <p className={cn("text-2xl font-bold", summary ? (summary.excess_return >= 0 ? "text-green-500" : "text-red-500") : "")}>
                {summary ? formatSignedPct(summary.excess_return) : "--"}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-500/10">
              <Shield className="h-4 w-4 text-blue-500" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Factor Coverage (R&#178;)</p>
              <p className="text-2xl font-bold">
                {summary ? `${(summary.factor_coverage * 100).toFixed(1)}%` : "--"}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-yellow-500/10">
              <AlertTriangle className="h-4 w-4 text-yellow-500" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Unexplained Return</p>
              <p className={cn("text-2xl font-bold", summary ? (summary.unexplained_return >= 0 ? "text-green-500" : "text-red-500") : "")}>
                {summary ? formatSignedPct(summary.unexplained_return) : "--"}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
