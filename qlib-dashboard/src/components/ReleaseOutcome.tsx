import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Inbox,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ReleaseOutcome as ReleaseOutcomeState } from "@/lib/release-workflow";

const OUTCOME_PRESENTATION = {
  loading: { label: "Loading", icon: CircleDashed, className: "border-blue-500/30 bg-blue-500/5 text-blue-700 dark:text-blue-300" },
  empty: { label: "Empty", icon: Inbox, className: "border-border bg-muted/30 text-muted-foreground" },
  partial: { label: "Partial", icon: AlertTriangle, className: "border-amber-500/30 bg-amber-500/5 text-amber-700 dark:text-amber-300" },
  stale: { label: "Stale", icon: Clock3, className: "border-yellow-500/30 bg-yellow-500/5 text-yellow-700 dark:text-yellow-300" },
  failed: { label: "Failed", icon: XCircle, className: "border-destructive/30 bg-destructive/5 text-destructive" },
  blocked: { label: "Blocked", icon: Ban, className: "border-destructive/30 bg-destructive/5 text-destructive" },
  success: { label: "Success", icon: CheckCircle2, className: "border-green-500/30 bg-green-500/5 text-green-700 dark:text-green-300" },
} satisfies Record<ReleaseOutcomeState, { label: string; icon: typeof CheckCircle2; className: string }>;

export interface ReleaseOutcomeProps {
  state: ReleaseOutcomeState;
  reason: string;
  /** Optional list of detailed failure/blocked reasons (e.g. gate failures). */
  details?: string[];
  className?: string;
}

export function ReleaseOutcome({
  state,
  reason,
  details,
  className,
}: ReleaseOutcomeProps) {
  const presentation = OUTCOME_PRESENTATION[state];
  const Icon = presentation.icon;
  const role = state === "failed" || state === "blocked" ? "alert" : "status";

  return (
    <div
      role={role}
      data-outcome={state}
      className={cn("flex items-start gap-2 border px-3 py-2 text-xs", presentation.className, className)}
    >
      <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", state === "loading" && "animate-spin")} />
      <div className="min-w-0 flex-1">
        <div>
          <span className="font-semibold">{presentation.label}</span>
          <span className="ml-2">{reason}</span>
        </div>
        {details && details.length > 0 && (
          <ul className="mt-1.5 space-y-0.5" data-outcome-details>
            {details.map((detail, i) => (
              <li key={i} className="flex items-start gap-1.5 text-[11px] opacity-90">
                <span className="mt-0.5 h-1 w-1 rounded-full bg-current shrink-0" />
                <span>{detail}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
