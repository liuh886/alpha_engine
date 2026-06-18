import { cn } from "@/lib/utils";
import { formatSignedPct } from "./types";

export function ContributionBar({
  name,
  value,
  maxValue,
}: {
  name: string;
  value: number;
  maxValue: number;
}) {
  const pct = maxValue > 0 ? (Math.abs(value) / maxValue) * 100 : 0;
  const isPositive = value >= 0;

  return (
    <div className="flex items-center gap-3 group">
      <div className="w-28 text-xs font-medium text-right truncate" title={name}>
        {name}
      </div>
      <div className="flex-1 h-6 bg-muted/30 rounded-sm overflow-hidden relative">
        <div
          className={cn(
            "absolute top-0 h-full rounded-sm transition-all duration-300",
            isPositive
              ? "left-1/2 bg-green-500/70 group-hover:bg-green-500/90"
              : "right-1/2 bg-red-500/70 group-hover:bg-red-500/90"
          )}
          style={{ width: `${Math.min(pct, 50)}%` }}
        />
        <div className="absolute left-1/2 top-0 h-full w-px bg-border" />
      </div>
      <div
        className={cn(
          "w-16 text-xs font-mono text-right",
          isPositive ? "text-green-500" : "text-red-500"
        )}
      >
        {formatSignedPct(value)}
      </div>
    </div>
  );
}
