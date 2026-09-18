import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowUpRight,
  ChevronDown,
  CircleSlash2,
  FileCode2,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import type { GovernedRunSummary } from '@/lib/governed-run';
import {
  summarizeStrategySignal,
  type StrategyOperationsSnapshot,
} from '@/lib/strategy-operations';
import { cn } from '@/lib/utils';

export interface StrategySignalDrawerProps {
  run: GovernedRunSummary | null;
  snapshot: StrategyOperationsSnapshot | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function StrategySignalDrawer({
  run,
  snapshot,
  open,
  onOpenChange,
}: StrategySignalDrawerProps) {
  const navigate = useNavigate();
  const [showEvidence, setShowEvidence] = useState(false);

  if (!run) return null;

  const signalSummary = summarizeStrategySignal(snapshot ?? undefined);
  const allocations = snapshot?.allocations ?? [];
  const hasAllocations = allocations.length > 0;
  const factorEvidence = snapshot?.factorEvidence ?? [];
  const sourceIdentity = snapshot?.sourceIdentity;

  const statusToneClass = () => {
    switch (signalSummary.direction) {
      case 'increase':
        return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300';
      case 'reduce':
        return 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300';
      case 'hold':
        return 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300';
      case 'attention':
        return 'border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300';
      default:
        return 'border-muted-foreground/30 bg-muted/40 text-muted-foreground';
    }
  };

  const StatusIcon = () => {
    switch (signalSummary.direction) {
      case 'increase':
        return <TrendingUp className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />;
      case 'reduce':
        return <TrendingDown className="h-5 w-5 text-amber-600 dark:text-amber-400" />;
      case 'hold':
        return <ShieldCheck className="h-5 w-5 text-blue-600 dark:text-blue-400" />;
      case 'attention':
        return <ShieldAlert className="h-5 w-5 text-rose-600 dark:text-rose-400" />;
      default:
        return <CircleSlash2 className="h-5 w-5 text-muted-foreground" />;
    }
  };

  const handleNavigateDetail = () => {
    onOpenChange(false);
    navigate(`/strategies/${encodeURIComponent(run.modelVersionId)}`);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              Operational Signal & Targets
            </span>
            <Badge variant="outline" className="text-[10px] uppercase tracking-wider">
              {run.market}
            </Badge>
          </div>
          <DialogTitle className="text-xl font-bold tracking-tight">
            {run.title}
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            {run.modelVersionId} · Benchmark {run.benchmark} · Evidence through {run.evidenceCutoff}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 pt-2">
          {/* Signal callout box */}
          <div className={cn('rounded-xl border p-4 transition-colors', statusToneClass())}>
            <div className="flex items-start gap-3">
              <div className="mt-0.5 shrink-0">
                <StatusIcon />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-base font-bold tracking-tight">
                    {signalSummary.badgeLabel} · {signalSummary.actionText}
                  </span>
                </div>
                <p className="mt-1 text-xs leading-relaxed opacity-90">
                  {snapshot?.decisionReason || snapshot?.note || 'Latest governed evaluation recorded.'}
                </p>
              </div>
            </div>
          </div>

          {/* Model Targets Table */}
          <div className="rounded-xl border bg-card p-4">
            <div className="flex items-center justify-between pb-3 border-b">
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  Model Targets
                </h4>
                <p className="text-[11px] text-muted-foreground">
                  Model target allocations, not actual holdings
                </p>
              </div>
              {snapshot?.turnover !== null && snapshot?.turnover !== undefined && (
                <span className="text-xs font-medium tabular-nums text-muted-foreground">
                  Turnover {(snapshot.turnover * 100).toFixed(1)}%
                </span>
              )}
            </div>

            {hasAllocations ? (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b text-[10px] uppercase tracking-wider text-muted-foreground">
                      <th className="pb-2 font-semibold">Sleeve / Asset</th>
                      <th className="pb-2 text-right font-semibold">Previous</th>
                      <th className="pb-2 text-right font-semibold">Target</th>
                      <th className="pb-2 text-right font-semibold">Delta</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {allocations.map((leg) => {
                      const deltaPositive = leg.delta > 0;
                      const deltaNegative = leg.delta < 0;
                      return (
                        <tr key={leg.asset} className="hover:bg-muted/30">
                          <td className="py-2.5 font-medium">{leg.asset}</td>
                          <td className="py-2.5 text-right font-mono tabular-nums text-muted-foreground">
                            {pct(leg.current)}
                          </td>
                          <td className="py-2.5 text-right font-mono font-semibold tabular-nums">
                            {pct(leg.target)}
                          </td>
                          <td
                            className={cn(
                              'py-2.5 text-right font-mono font-medium tabular-nums',
                              deltaPositive && 'text-emerald-600 dark:text-emerald-400',
                              deltaNegative && 'text-amber-600 dark:text-amber-400',
                              !deltaPositive && !deltaNegative && 'text-muted-foreground',
                            )}
                          >
                            {leg.delta > 0 ? `+${pct(leg.delta)}` : pct(leg.delta)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-6 text-center text-xs text-muted-foreground">
                <p className="font-medium">First target / no prior comparison record</p>
                <p className="mt-1 text-[11px]">
                  Formal historical evidence is available. Target allocations are not currently published.
                </p>
              </div>
            )}
          </div>

          {/* Timing and Decision Cadence */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 rounded-xl border bg-muted/20 p-4 text-xs">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                Applicable Session
              </p>
              <p className="mt-0.5 font-medium">
                {snapshot?.asOf ? `${snapshot.asOf} model session` : 'Formal evidence only'}
              </p>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                Data Cutoff
              </p>
              <p className="mt-0.5 font-medium">
                {snapshot?.latestCompletedSession ?? run.evidenceCutoff ?? '—'}
              </p>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                Decision Cadence
              </p>
              <p className="mt-0.5 font-medium">
                {snapshot?.decisionCadence ?? 'Session close'}
              </p>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                Next Decision Policy
              </p>
              <p className="mt-0.5 line-clamp-2 text-muted-foreground font-medium">
                {snapshot?.nextDecision ?? 'Next eligible session'}
              </p>
            </div>
          </div>

          {/* Evidence Toggle Section */}
          <div className="rounded-xl border bg-card p-4">
            <button
              type="button"
              onClick={() => setShowEvidence(!showEvidence)}
              aria-expanded={showEvidence}
              className="flex w-full items-center justify-between text-xs font-semibold text-primary hover:underline focus:outline-none"
            >
              <span className="flex items-center gap-1.5">
                <FileCode2 className="h-4 w-4" />
                {showEvidence ? 'Hide governed evidence details' : 'View governed evidence details'}
              </span>
              <ChevronDown
                className={cn('h-4 w-4 transition-transform duration-200', showEvidence && 'rotate-180')}
              />
            </button>

            {showEvidence && (
              <div className="mt-4 space-y-3 pt-3 border-t text-xs">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                    Source Identities
                  </p>
                  <div className="mt-1.5 space-y-1 font-mono text-[11px] text-muted-foreground break-all">
                    <p><span className="font-semibold text-foreground">Bundle ID:</span> {sourceIdentity?.formalBundleId ?? run.bundleId ?? '—'}</p>
                    <p><span className="font-semibold text-foreground">Run ID:</span> {sourceIdentity?.formalRunId ?? run.runId}</p>
                    {sourceIdentity?.signalSha256 && (
                      <p><span className="font-semibold text-foreground">Signal SHA256:</span> {sourceIdentity.signalSha256}</p>
                    )}
                    {sourceIdentity?.ledgerFingerprint && (
                      <p><span className="font-semibold text-foreground">Ledger Fingerprint:</span> {sourceIdentity.ledgerFingerprint}</p>
                    )}
                    {sourceIdentity?.commitSha && (
                      <p><span className="font-semibold text-foreground">Commit:</span> {sourceIdentity.commitSha}</p>
                    )}
                  </div>
                </div>

                {factorEvidence.length > 0 && (
                  <div className="pt-2">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                      Active Factor Drivers
                    </p>
                    <div className="mt-1.5 space-y-1.5">
                      {factorEvidence.map((factor) => (
                        <div
                          key={factor.factorId}
                          className="flex items-center justify-between rounded-md border bg-muted/30 px-2.5 py-1.5 text-[11px]"
                        >
                          <div className="min-w-0 flex-1 pr-2">
                            <span className="font-semibold">{factor.displayName}</span>
                            <span className="ml-1.5 text-muted-foreground">({factor.state})</span>
                          </div>
                          <div className="shrink-0 font-mono text-muted-foreground">
                            {typeof factor.value === 'number' ? factor.value.toFixed(4) : String(factor.value)}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-col-reverse sm:flex-row sm:justify-between items-center gap-2 pt-4 border-t">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
            className="w-full sm:w-auto"
          >
            Close
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={handleNavigateDetail}
            className="w-full sm:w-auto flex items-center gap-1.5"
          >
            View full strategy analysis
            <ArrowUpRight className="h-4 w-4" />
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
