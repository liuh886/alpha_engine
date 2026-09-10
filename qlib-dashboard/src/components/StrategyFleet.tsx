import { ArrowRight, ChevronDown, CircleSlash2, Clock3, Crown, LockKeyhole, ShieldCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { useAccessControl } from '@/hooks/useAccessControl';
import type { GovernedRunSummary } from '@/lib/governed-run';
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
    ? `${item.value >= 0 ? '+' : ''}${(item.value * 100).toFixed(1)}%`
    : '—';
}

function metricDecimal(run: GovernedRunSummary, id: string): string {
  const item = metric(run, id);
  return item?.availability_status === 'available' && typeof item.value === 'number'
    ? item.value.toFixed(2)
    : '—';
}

function allocationSummary(snapshot: StrategyOperationsSnapshot | undefined, side: 'current' | 'target'): string {
  if (!snapshot || snapshot.allocations.length === 0) return 'Not published';
  return snapshot.allocations
    .filter((leg) => Math.abs(leg[side]) > 1e-9)
    .map((leg) => `${leg.asset} ${(leg[side] * 100).toFixed(0)}%`)
    .join(' · ') || 'Cash / flat';
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
  const access = useAccessControl();
  const [expandedKey, setExpandedKey] = useState<string | null>(null);

  return (
    <section className="overflow-hidden rounded-2xl border bg-card shadow-sm" aria-label="Formal strategy fleet">
      <div className="hidden grid-cols-[minmax(220px,1.35fr)_112px_112px_88px_108px_minmax(210px,1fr)_36px] gap-4 border-b bg-muted/25 px-5 py-3 text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground lg:grid">
        <span>Strategy</span><span>Total return</span><span>CAGR</span><span>Sharpe</span><span>Max DD</span><span>Live decision</span><span />
      </div>
      <div className="divide-y">
        {runs.map((run) => {
          const snapshot = snapshots.get(run.modelVersionId);
          const requiredTier = snapshot ? access.requiredTier('strategy', snapshot.strategyId) : 'owner';
          const liveLocked = !access.canAccess(requiredTier);
          const label = snapshot ? STRATEGY_STATUS_LABEL[snapshot.status] : loading ? 'Loading operations' : 'Operating status unavailable';
          const expanded = expandedKey === run.key;
          const totalReturn = metricPercent(run, 'total_return');
          const sharpe = metricDecimal(run, 'sharpe_ratio');
          const maxDd = metricPercent(run, 'max_drawdown');
          return (
            <article
              key={run.key}
              className="group px-5 py-4 transition-colors hover:bg-muted/20 lg:grid lg:grid-cols-[minmax(220px,1.35fr)_112px_112px_88px_108px_minmax(210px,1fr)_36px] lg:items-center lg:gap-4 lg:py-5"
            >
              <button
                type="button"
                onClick={() => navigate(`/strategies/${encodeURIComponent(run.modelVersionId)}`)}
                className="block w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary lg:contents"
                aria-label={liveLocked ? `${run.title}, historical evidence public, live operations require ${requiredTier}` : run.title}
              >
                <span className="block min-w-0">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-base font-semibold">{run.title}</span>
                    {requiredTier !== 'public' && (
                      <span className="inline-flex items-center gap-1 rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-[10px] font-black uppercase tracking-[0.12em] text-primary">
                        <Crown className="h-3 w-3" /> {requiredTier === 'pro' ? 'Pro live' : requiredTier}
                      </span>
                    )}
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">{run.market.toUpperCase()} · {run.benchmark} · evidence {run.evidenceCutoff}</span>
                </span>

                <span className="mt-2 flex items-center gap-4 font-mono text-sm font-semibold tabular-nums lg:hidden" aria-label={`Total return ${totalReturn}, Sharpe ${sharpe}, max drawdown ${maxDd}`}>
                  <span>{totalReturn}</span>
                  <span className="text-muted-foreground">S {sharpe}</span>
                  <span className="text-muted-foreground">DD {maxDd}</span>
                </span>

                <span className="mt-3 hidden lg:contents">
                  <PublicMetric label="Total return" value={metricPercent(run, 'total_return')} emphasis />
                  <PublicMetric label="CAGR" value={metricPercent(run, 'annualized_return')} />
                  <PublicMetric label="Sharpe" value={metricDecimal(run, 'sharpe_ratio')} />
                  <PublicMetric label="Max DD" value={metricPercent(run, 'max_drawdown')} />
                </span>
              </button>

              <div className="mt-3 lg:contents">
                {liveLocked ? (
                  <div className="rounded-lg border border-primary/15 bg-primary/[0.035] p-3 lg:border-0 lg:bg-transparent lg:p-0">
                    <p className="flex items-center gap-1.5 text-sm font-semibold text-primary"><LockKeyhole className="h-4 w-4" />Live holdings & signals</p>
                    <p className="mt-1 text-xs text-muted-foreground">AlphaEngine {requiredTier === 'pro' ? 'Pro' : requiredTier} unlocks the current-operations layer.</p>
                  </div>
                ) : (
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold', statusClass(snapshot?.status))}>
                        <StatusIcon status={snapshot?.status} />{label}
                      </span>
                    </div>
                    <p className="mt-2 text-sm font-medium">{snapshot?.stateLabel || 'Formal evidence only'}</p>
                    <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{allocationSummary(snapshot, 'current')} → {allocationSummary(snapshot, 'target')}</p>
                  </div>
                )}
              </div>

              <div className="mt-3 flex items-center justify-between lg:hidden">
                <button
                  type="button"
                  onClick={() => setExpandedKey(expanded ? null : run.key)}
                  aria-expanded={expanded}
                  className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-3 text-xs font-semibold text-primary hover:bg-primary/5"
                >
                  {expanded ? 'Hide details' : 'Strategy details'}
                  <ChevronDown className={cn('h-4 w-4 transition-transform', expanded && 'rotate-180')} />
                </button>
                <button
                  type="button"
                  onClick={() => navigate(`/strategies/${encodeURIComponent(run.modelVersionId)}`)}
                  className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-muted-foreground hover:text-primary"
                  aria-label={`Open ${run.title} strategy detail`}
                >
                  <ArrowRight className="h-4 w-4" />
                </button>
              </div>

              {expanded && (
                <div className="mt-2 space-y-2 rounded-lg border bg-muted/30 p-3 text-xs lg:hidden">
                  <p><span className="font-semibold">CAGR:</span> <span className="font-mono tabular-nums">{metricPercent(run, 'annualized_return')}</span></p>
                  <p><span className="font-semibold">Signal:</span> {label}</p>
                  <p><span className="font-semibold">Allocations:</span> {allocationSummary(snapshot, 'current')} → {allocationSummary(snapshot, 'target')}</p>
                  <p className="text-muted-foreground">Benchmark {run.benchmark} · evidence cutoff {run.evidenceCutoff}</p>
                </div>
              )}

              <ArrowRight className="hidden h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary lg:block" />
            </article>
          );
        })}
      </div>
    </section>
  );
}

function PublicMetric({ label, value, emphasis = false }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div>
      <p className="text-[9px] font-bold uppercase tracking-[0.1em] text-muted-foreground lg:hidden">{label}</p>
      <p className={cn('mt-1 font-mono text-sm font-semibold tabular-nums lg:mt-0', emphasis && value !== '—' && 'text-primary')}>{value}</p>
    </div>
  );
}
