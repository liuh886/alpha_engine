import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, BarChart3, CheckCircle2, Clock3, ShieldCheck } from 'lucide-react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { FormalBacktestReview } from '@/components/FormalBacktestReview';
import { Badge } from '@/components/ui/badge';
import {
  fetchFormalFreshness,
  type FormalFreshnessSnapshot,
  type FormalFreshnessStatus,
} from '@/lib/formal-freshness';
import { metricById } from '@/lib/formal-run-evidence';
import { governedRunQuery, type GovernedRunSummary } from '@/lib/governed-run';
import type { CanonicalMetricV2 } from '@/lib/model-run-bundle-v2';
import type { RunWorkspaceContext } from '@/lib/run-workspace';
import { cn } from '@/lib/utils';

function summaryMetrics(run: GovernedRunSummary): CanonicalMetricV2[] {
  const raw = run.summary.metrics;
  return Array.isArray(raw) ? raw.filter((value): value is CanonicalMetricV2 => Boolean(value) && typeof value === 'object') : [];
}

function metricText(run: GovernedRunSummary, metricId: string): string {
  const metric = metricById(summaryMetrics(run), metricId);
  if (!metric || metric.availability_status !== 'available' || metric.value === null) return 'Unavailable';
  if (metricId === 'turnover') return metric.value.toFixed(3);
  return `${(metric.value * 100).toFixed(2)}%`;
}

function FormalRunCard({ run, selected, onSelect }: { run: GovernedRunSummary; selected: boolean; onSelect: () => void }) {
  const completeness = typeof run.summary.evidence_completeness === 'object' && run.summary.evidence_completeness
    ? String((run.summary.evidence_completeness as Record<string, unknown>).status ?? run.evidenceStatus)
    : run.evidenceStatus;
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'min-w-0 rounded-xl border bg-card p-4 text-left shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
        selected ? 'border-primary ring-1 ring-primary/30' : 'hover:border-primary/40',
      )}
      aria-pressed={selected}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-semibold">{run.title}</p>
          <p className="mt-1 text-xs text-muted-foreground">{run.market.toUpperCase()} · {run.benchmark} · cutoff {run.evidenceCutoff}</p>
        </div>
        {selected ? <CheckCircle2 className="h-5 w-5 shrink-0 text-primary" /> : <BarChart3 className="h-5 w-5 shrink-0 text-muted-foreground/50" />}
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2 border-t pt-3 text-xs">
        <div><p className="text-[10px] text-muted-foreground">Return</p><p className="mt-1 font-mono font-semibold">{metricText(run, 'total_return')}</p></div>
        <div><p className="text-[10px] text-muted-foreground">Excess</p><p className="mt-1 font-mono font-semibold">{metricText(run, 'excess_return')}</p></div>
        <div><p className="text-[10px] text-muted-foreground">Drawdown</p><p className="mt-1 font-mono font-semibold">{metricText(run, 'max_drawdown')}</p></div>
      </div>
      <div className="mt-3"><Badge variant="outline" className={completeness === 'complete' ? 'text-emerald-700 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-300'}>{completeness} evidence</Badge></div>
    </button>
  );
}

const FRESHNESS_STYLE: Record<FormalFreshnessStatus, string> = {
  current: 'border-emerald-500/25 bg-emerald-500/5 text-emerald-800 dark:text-emerald-200',
  stale: 'border-amber-500/30 bg-amber-500/8 text-amber-900 dark:text-amber-100',
  blocked: 'border-destructive/30 bg-destructive/5 text-destructive',
  unknown: 'border-muted-foreground/25 bg-muted/30 text-muted-foreground',
};

function FreshnessBanner({ snapshot }: { snapshot: FormalFreshnessSnapshot | null }) {
  const status = snapshot?.status ?? 'unknown';
  const Icon = status === 'current' ? CheckCircle2 : status === 'stale' ? Clock3 : AlertTriangle;
  const label = status === 'current'
    ? 'Formal evidence current'
    : status === 'stale'
      ? 'Formal evidence stale'
      : status === 'blocked'
        ? 'Freshness verification blocked'
        : 'Freshness status unknown';
  return (
    <section className={cn('flex items-start gap-3 rounded-xl border px-4 py-3 text-sm', FRESHNESS_STYLE[status])} data-testid="formal-freshness-status">
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <p className="font-semibold">{label}</p>
        <p className="mt-1 text-xs leading-relaxed opacity-90">
          {snapshot?.message ?? 'The browser has not loaded a valid formal freshness policy. Historical evidence remains readable but is not presented as current.'}
        </p>
        {snapshot?.policy ? (
          <p className="mt-1 font-mono text-[10px] opacity-80">
            {Object.entries(snapshot.policy.markets).map(([market, cutoff]) => `${market.toUpperCase()} ${cutoff}`).join(' · ')}
          </p>
        ) : null}
      </div>
    </section>
  );
}

export function FormalBacktestsPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const navigate = useNavigate();
  const [freshness, setFreshness] = useState<FormalFreshnessSnapshot | null>(null);
  const formalRuns = useMemo(() => workspace.runs.filter((run) => run.channel === 'formal'), [workspace.runs]);
  const activeRun = formalRuns.find((run) => run.key === workspace.activeRunKey) ?? formalRuns[0] ?? null;

  useEffect(() => {
    let active = true;
    void fetchFormalFreshness().then((snapshot) => {
      if (active) setFreshness(snapshot);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (activeRun && activeRun.key !== workspace.activeRunKey) workspace.selectRun(activeRun);
  }, [activeRun?.key, workspace.activeRunKey, workspace.selectRun]);

  if (!activeRun) {
    return <div className="rounded-xl border-2 border-dashed p-12 text-center text-sm text-muted-foreground">No accepted formal baseline is declared by the verified catalog.</div>;
  }

  const selectFormalRun = (run: GovernedRunSummary) => {
    workspace.selectRun(run);
    navigate(`/backtests?${governedRunQuery(run)}`);
  };

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 pb-16">
      <section className="rounded-xl border bg-card p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Accepted evidence workspace</p>
            <h2 className="mt-1 text-2xl font-semibold">Formal Backtests</h2>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">
              Review the complete retained evidence for accepted formal baselines. Metrics, paths, holdings, trades and attribution are loaded from hash-verified Model Run Bundle v2 sections; missing evidence remains visible and is never reconstructed in the browser.
            </p>
          </div>
          <div className="flex items-start gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-3 text-sm">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
            <div><div className="font-semibold">{formalRuns.length} governed baselines</div><div className="mt-1 text-xs text-muted-foreground">research_only=true · trade_ready=false</div></div>
          </div>
        </div>
      </section>

      <FreshnessBanner snapshot={freshness} />

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4" aria-label="Accepted formal backtest baselines">
        {formalRuns.map((run) => (
          <FormalRunCard key={run.key} run={run} selected={run.key === activeRun.key} onSelect={() => selectFormalRun(run)} />
        ))}
      </section>

      <FormalBacktestReview run={activeRun} />
    </div>
  );
}
