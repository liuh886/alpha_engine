import { AlertCircle, CheckCircle2, Info, Loader2, WifiOff } from "lucide-react";
import { cn } from "@/lib/utils";

interface GlobalStatusBarProps {
  latestCalendarDay: string;
  qualityStatus: "ok" | "warning" | "error";
  warnings: string[];
  activeJobsCount: number;
  dataGeneratedAt?: string;
  apiError?: string | null;
  onOpenConsole?: () => void;
}

function formatAge(isoStr: string): string {
  if (!isoStr) return "";
  try {
    const ms = Date.now() - new Date(isoStr).getTime();
    if (ms < 0) return "just now";
    const mins = Math.floor(ms / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch { return ""; }
}

export function GlobalStatusBar({
  latestCalendarDay,
  qualityStatus,
  warnings,
  activeJobsCount,
  dataGeneratedAt,
  apiError,
  onOpenConsole,
}: GlobalStatusBarProps) {
  const statusColor =
    qualityStatus === "ok" ? "text-green-500" :
    qualityStatus === "warning" ? "text-yellow-500" : "text-red-500";

  const StatusIcon =
    qualityStatus === "ok" ? CheckCircle2 :
    qualityStatus === "warning" ? AlertCircle : Info;

  const tooltipText = warnings.length > 0 ? warnings.join('\n') : "Data quality checks passed.";
  const age = formatAge(dataGeneratedAt || "");

  return (
    <div className="flex items-center gap-3 px-4 py-1 bg-muted/30 border-b text-xs h-7">
      {/* API Error Banner */}
      {apiError && (
        <div className="flex items-center gap-1.5 text-red-500">
          <WifiOff className="h-3 w-3" />
          <span className="font-medium">{apiError}</span>
        </div>
      )}
      {!apiError && (
        <>
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">Calendar:</span>
            <span className="font-mono text-primary">{latestCalendarDay || "OFFLINE"}</span>
          </div>

          {age && (
            <>
              <div className="h-3 w-px bg-border" />
              <span className={cn("text-muted-foreground", age.includes("d ago") && parseInt(age) > 2 && "text-yellow-500")}>
                Data: {age}
              </span>
            </>
          )}

          <div className="h-3 w-px bg-border" />

          <button
            onClick={onOpenConsole}
            className={cn("flex items-center gap-1 cursor-pointer hover:opacity-80", statusColor)}
            title={tooltipText}
          >
            <StatusIcon className="h-3.5 w-3.5" />
            <span className="capitalize">{qualityStatus}</span>
            {warnings.length > 0 && (
              <span className="ml-1 px-1.5 py-0.5 rounded-full bg-red-100 text-red-800 text-[10px] font-medium">
                {warnings.length}
              </span>
            )}
          </button>

          <div className="flex-1" />

          <button
            onClick={onOpenConsole}
            className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground"
          >
            {activeJobsCount > 0 ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                <span>{activeJobsCount} active</span>
              </>
            ) : (
              <>
                <CheckCircle2 className="h-3 w-3" />
                <span>Idle</span>
              </>
            )}
          </button>
        </>
      )}
    </div>
  );
}
