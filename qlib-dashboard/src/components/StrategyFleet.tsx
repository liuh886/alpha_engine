import { ArrowRight, CircleSlash2, Clock3, Crown, LockKeyhole, ShieldCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAlphaMembership } from '@/hooks/useAlphaMembership';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { isProModelRun } from '@/lib/model-access';
import type { CanonicalMetricV2 } from '@/lib/model-run-bundle-v2';
import { STRATEGY_STATUS_LABEL, type StrategyOperationsSnapshot } from '@/lib/strategy-operations';
import { cn } from '@/lib/utils';

function metric(run: GovernedRunSummary, id: string): CanonicalMetricV2 | null {
  const metrics = Array.isArray(run.summary.metrics) ? run.summary.metrics : [];
  return (metrics as CanonicalMetricV2[]).find((item) => item.metric_id === id) ?? null;
}

function metricPercent(run: GovernedRunSummary, id: string): string {
  const item = metric(run, id);
  return item?.availability_status === 'available' && typeof item.value === 'number'
    ? `${(item.value * 100).toFixed(1)}%`
    : '—';
}

function allocationSummary(snapshot: StrategyOperationsSnapshot | undefined, side: 'current' | 'target'): string {
  if (!snapshot || snapshot.allocations.length === 0) return 'Not published';
  return snapshot.allocations
    .filter((leg) => Math.abs(leg[side]) > 1e-9)
    .map((leg) => `${leg.asset} ${(leg[side] * 100).toFixed(0)}%`)
    .join(' · ') || 'Cash / flat';
}

function changeSummary(snapshot: StrategyOperationsSnapshot | undefined): string {
  if (!snapshot || snapshot.allocations.length === 0) return 'No governed live target';
  const changes = snapshot.allocations.filter((leg) => Math.abs(leg.delta) > 1e-9);
  if (changes.length === 0) return 'No allocation change';
  return changes
    .map((leg) => `${leg.delta > 0 ? '+' : ''}${(leg.delta * 100).toFixed(0)}pp ${leg.asset}`)
    .join(' · ');
}

function statusClass(status: StrategyOperationsSnapshot['status'] | undefined): string {
  if (status === 'current_no_change' || status === 'execution_observed') return 'border-emerald-500/25 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300';
  if (status === 'target_pending_execution') return 'border-sky-500/25 bg-sky-500/5 text-sky-700 dark:text-sky-300';
  if (status === 'pipeline_unavailable' || status === 'awaiting_observation') return 'border-muted-foreground/25 bg-muted/30 text-muted-foreground';
  return 'border-amber-500/30 bg-amber-500/5 text-amber-800 dark:text-amber-200';
}

function StatusIcon({ status }: { status: StrategyOperationsSnapshot['status'] | undefined }) {
  if (status === 'current_no_change' || status === 'execution_observed') return <ShieldCheck className="h-3.5 w-3.5" />;
  if (status === 'pipeline_unavailable') return <CircleSlash2 className="h-3.5 w-3.5" />;
  return <Clock3 className="h-3.5 w-3.5" />;
}

export function StrategyFleet({
  runs,
  snapshots,
  loading = false,
}: {
  runs: GovernedRunSummary[];
  snapshots: Map<string, StrategyOperationsSnapshot>;
  loading?: boolean;
}) {
  const navigate = useNavigate();
  const membership = useAlphaMembership();

  return (
    <section className="overflow-hidden rounded-2xl border bg-card shadow-sm" aria-label="Formal strategy fleet">
      <div className="hidden grid-cols-[minmax(220px,1.35fr)_minmax(180px,1fr)_minmax(180px,1fr)_minmax(160px,0.8fr)_120px_36px] gap-4 border-b bg-muted/25 px-5 py-3 text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground lg:grid">
        <span>Strategy</span><span>Now</span><span>Target / change</span><span>Next decision</span><span>Risk</span><span />
      </div>
      <div className="divide-y">
        {runs.map((run) => {
          const snapshot = snapshots.get(run.modelVersionId);
          const locked = isProModelRun(run) && !membership.isPro;
          const label = snapshot ? STRATEGY_STATUS_LABEL[snapshot.status] : loading ? 'Loading operations' : 'Operating status unavailable';
          return (
            <button
              key={run.key}
              type="button"
              onClick={() => locked ? membership.openAccount() : navigate(`/strategies/${encodeURIComponent(run.modelVersionId)}`)}
              className="group grid w-full gap-4 px-5 py-5 text-left transition-colors hover:bg-muted/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary lg:grid-cols-[minmax(220px,1.35fr)_minmax(180px,1fr)_minmax(180px,1fr)_minmax(160px,0.8fr)_120px_36px] lg:items-center"
              aria-label={locked ? `${run.title}, AlphaEngine Pro model` : run.title}
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="truncate text-base font-semibold">{run.title}</h3>
                  {isProModelRun(run) && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-[10px] font-black uppercase tracking-[0.12em] text-primary">
                      <Crown className="h-3 w-3" /> Pro
                    </span>
                  )}
                  {!locked && (
                    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold', statusClass(snapshot?.status))}>
                      <StatusIcon status={snapshot?.status} />{label}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{run.market.toUpperCase()} · {run.benchmark} · evidence {run.evidenceCutoff}</p>
              </div>

              {locked ? (
                <>
                  <div className="lg:col-span-4">
                    <p className="flex items-center gap-1.5 text-sm font-semibold text-primary"><LockKeyhole className="h-4 w-4" />AlphaEngine Pro access</p>
                    <p className="mt-1 text-xs text-muted-foreground">Unlock current allocation, target changes, formal backtests, attribution and retained evidence.</p>
                  </div>
                  <Crown className="hidden h-4 w-4 text-primary lg:block" />
                </>
              ) : (
                <>
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground lg:hidden">Now</p>
                    <p className="mt-1 text-sm font-medium lg:mt-0">{snapshot?.stateLabel || 'Formal evidence only'}</p>
                    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{allocationSummary(snapshot, 'current')}</p>
                  </div>

                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground lg:hidden">Target / change</p>
                    <p className="mt-1 text-sm font-medium lg:mt-0">{allocationSummary(snapshot, 'target')}</p>
                    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{changeSummary(snapshot)}</p>
                  </div>

                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground lg:hidden">Next decision</p>
                    <p className="mt-1 text-sm font-medium lg:mt-0">{snapshot?.nextDecision || 'Not declared'}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{snapshot?.decisionCadence || '—'}</p>
                  </div>

                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground lg:hidden">Risk</p>
                    <p className="mt-1 font-mono text-sm font-semibold lg:mt-0">{metricPercent(run, 'max_drawdown')}</p>
                    <p className="mt-1 text-[10px] text-muted-foreground">Max drawdown</p>
                  </div>

                  <ArrowRight className="hidden h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary lg:block" />
                </>
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
