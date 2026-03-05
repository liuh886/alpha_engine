import { AlertCircle, CheckCircle2, Info, Loader2 } from "lucide-react";

interface GlobalStatusBarProps {
  latestCalendarDay: string;
  qualityStatus: "ok" | "warning" | "error";
  warnings: string[];
  activeJobsCount: number;
  onOpenConsole?: () => void;
}

export function GlobalStatusBar({
  latestCalendarDay,
  qualityStatus,
  warnings,
  activeJobsCount,
  onOpenConsole
}: GlobalStatusBarProps) {
  const statusColor =
    qualityStatus === "ok"
      ? "text-green-500"
      : qualityStatus === "warning"
      ? "text-yellow-500"
      : "text-red-500";

  const StatusIcon =
    qualityStatus === "ok"
      ? CheckCircle2
      : qualityStatus === "warning"
      ? AlertCircle
      : Info;

  const tooltipText = warnings.length > 0 
    ? warnings.join('\n') 
    : "Data quality checks passed. All markets aligned with calendar.";

  return (
    <div className="flex items-center gap-4 px-4 py-1 bg-muted/30 border-b text-xs transition-all animate-in fade-in slide-in-from-top-1 h-8">
      <div className="flex items-center gap-2">
        <span className="font-black text-[9px] uppercase text-muted-foreground tracking-widest">Global Market:</span>
        <span className="font-mono font-bold text-primary">{latestCalendarDay || "OFFLINE"}</span>
      </div>

      <div className="h-3 w-px bg-border mx-1" />

      <button 
        onClick={onOpenConsole}
        className={`flex items-center gap-1 cursor-pointer hover:opacity-80 transition-opacity ${statusColor}`} 
        title={tooltipText}
      >
        <StatusIcon className="h-3.5 w-3.5" />
        <span className="capitalize font-bold text-[10px] tracking-tight">{qualityStatus}</span>
        {warnings.length > 0 && (
          <span className="ml-1 px-1.5 py-0.5 rounded-full bg-red-100 text-red-800 font-black text-[8px]">
            {warnings.length}
          </span>
        )}
      </button>

      <div className="flex-1" />

      <button 
        onClick={onOpenConsole}
        className="flex items-center gap-2 text-primary hover:opacity-80 transition-opacity font-bold text-[10px] tracking-tight group"
      >
        {activeJobsCount > 0 ? (
          <>
            <Loader2 className="h-3 w-3 animate-spin" />
            <span className="uppercase">{activeJobsCount} Active Task{activeJobsCount > 1 ? "s" : ""}</span>
          </>
        ) : (
          <div className="flex items-center gap-1.5 text-muted-foreground/40 italic">
            <CheckCircle2 className="h-3 w-3" />
            <span className="uppercase text-[9px]">Engine Idle</span>
          </div>
        )}
      </button>
    </div>
  );
}
