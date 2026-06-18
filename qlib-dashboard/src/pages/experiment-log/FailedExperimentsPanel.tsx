import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, AlertTriangle, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  TYPE_COLORS,
  TYPE_LABELS,
  formatTimestamp,
  formatMetricValue,
} from "./types";
import type { FailedExperiment } from "./types";

interface FailedExperimentsPanelProps {
  failures: FailedExperiment[];
  loading: boolean;
}

export function FailedExperimentsPanel({ failures, loading }: FailedExperimentsPanelProps) {
  return (
    <Card>
      <CardHeader className="pb-2 border-b flex flex-row items-center justify-between py-3">
        <CardTitle className="text-sm font-semibold flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-red-500" />
          Failed Experiments
        </CardTitle>
        <Badge variant="outline" className="text-xs">
          {failures.length} failure{failures.length !== 1 ? "s" : ""}
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        {loading ? (
          <div className="h-32 flex items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-primary opacity-50" />
          </div>
        ) : failures.length === 0 ? (
          <div className="h-32 flex items-center justify-center text-muted-foreground text-sm">
            No failed experiments recorded.
          </div>
        ) : (
          <div className="divide-y">
            {failures.map((f) => (
              <div
                key={f.id}
                className="px-4 py-3 hover:bg-muted/30 transition-colors"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge
                        variant="outline"
                        className={cn("text-[10px] px-1.5 py-0", TYPE_COLORS[f.type])}
                      >
                        {TYPE_LABELS[f.type]}
                      </Badge>
                      <span className="text-sm font-medium">{f.name}</span>
                      <span className="text-xs text-muted-foreground font-mono">
                        {formatTimestamp(f.timestamp)}
                      </span>
                    </div>
                    <div className="flex items-start gap-1.5">
                      <XCircle className="h-3.5 w-3.5 text-red-500 mt-0.5 flex-shrink-0" />
                      <p className="text-xs text-red-400">{f.failure_reason}</p>
                    </div>
                    {f.details && Object.keys(f.details).length > 0 && (
                      <div className="flex gap-4 flex-wrap mt-1.5 pl-5">
                        {Object.entries(f.details).map(([key, value]) => (
                          <span key={key} className="text-xs">
                            <span className="text-muted-foreground">{key}: </span>
                            <span className="font-mono">{formatMetricValue(value)}</span>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
