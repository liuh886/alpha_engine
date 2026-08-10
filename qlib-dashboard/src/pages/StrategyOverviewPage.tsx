import { Activity, ShieldCheck, TrendingUp } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import { StrategyFleet } from '@/components/StrategyFleet';
import { useStrategyOperations } from '@/hooks/useStrategyOperations';
import type { CanonicalMetricV2 } from '@/lib/model-run-bundle-v2';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

function metric(run: GovernedRunSummary | undefined, id: string): number | null {
  if (!run || !Array.isArray(run.summary.metrics)) return null;
  const item = (run.summary.metrics as CanonicalMetricV2[]).find((row) => row.metric_id === id);
  return item?.availability_status === 'available' && typeof item.value === 'number' ? item.value : null;
}

function percent(value: number | null): string {
  return value === null ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
}

function decimal(value: number | null): string {
  return value === null ? '—' : value.toFixed(2);
}

export function StrategyOverviewPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const { formalRuns, snapshots, loading } = useStrategyOperations(workspace.runs);
  const operational = Array.from(snapshots.values()).filter((snapshot) => !['pipeline_unavailable', 'awaiting_observation'].includes(snapshot.status)).length;
  const attention = Array.from(snapshots.values()).filter((snapshot) => ['stale', 'blocked', 'delivery_failed'].includes(snapshot.status)).length;
  const featured = formalRuns.find((run) => run.modelFamilyId === 'qqq_rotation') ?? formalRuns[0];

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 pb-16">
      <section className="grid gap-6 border-b pb-6 xl:grid-cols-[minmax(0,1fr)_440px] xl:items-end">
        <div className="max-w-4xl">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">Strategy operating console</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight md:text-5xl">What are the strategies doing now?</h1>
          <p className="mt-4 max-w-3xl text-sm leading-relaxed text-muted-foreground md:text-base">
            Start with formal performance, then move into current state and retained evidence. Return and risk records are public; live holdings, target allocations and current signal drivers are gated only where the strategy requires account or Pro access.
          </p>
        </div>

        <div className="overflow-hidden rounded-2xl border bg-card shadow-sm">
          <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground">Featured formal performance</p>
              <p className="mt-1 truncate text-sm font-semibold">{featured?.title ?? 'Formal strategy'}</p>
            </div>
            <TrendingUp className="h-5 w-5 shrink-0 text-primary" />
          </div>
          <div className="grid grid-cols-2 gap-px bg-border">
            <OverviewMetric label="Total return" value={percent(metric(featured, 'total_return'))} emphasis />
            <OverviewMetric label="CAGR" value={percent(metric(featured, 'annualized_return'))} />
            <OverviewMetric label="Sharpe" value={decimal(metric(featured, 'sharpe_ratio'))} />
            <OverviewMetric label="Max drawdown" value={percent(metric(featured, 'max_drawdown'))} />
          </div>
          <div className="grid grid-cols-3 divide-x border-t bg-muted/15 text-center">
            <div className="px-3 py-2"><p className="text-[9px] uppercase tracking-wide text-muted-foreground">Formal</p><p className="mt-0.5 text-xs font-semibold">{formalRuns.length}</p></div>
            <div className="px-3 py-2"><p className="text-[9px] uppercase tracking-wide text-muted-foreground">Operational</p><p className="mt-0.5 text-xs font-semibold">{operational}</p></div>
            <div className="px-3 py-2"><p className="text-[9px] uppercase tracking-wide text-muted-foreground">Attention</p><p className="mt-0.5 text-xs font-semibold">{attention}</p></div>
          </div>
        </div>
      </section>

      <StrategyFleet runs={formalRuns} snapshots={snapshots} loading={loading} />

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="flex gap-3 rounded-xl border bg-card p-4">
          <Activity className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          <div>
            <h2 className="text-sm font-semibold">Decision-first, evidence-attached</h2>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">A live target is shown only when a governed signal source exists and the viewer has the required access. Formal performance remains visible independently of the execution layer.</p>
          </div>
        </div>
        <div className="flex gap-3 rounded-xl border bg-card p-4">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          <div>
            <h2 className="text-sm font-semibold">No portfolio claim is implied</h2>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">Each row is an independent governed strategy. Alpha Engine does not invent a cross-strategy capital allocation contract that the research system has not defined.</p>
          </div>
        </div>
      </section>
    </div>
  );
}

function OverviewMetric({ label, value, emphasis = false }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className="bg-card px-4 py-3">
      <p className="text-[9px] font-bold uppercase tracking-[0.1em] text-muted-foreground">{label}</p>
      <p className={emphasis ? 'mt-1 text-2xl font-black tabular-nums text-primary' : 'mt-1 text-lg font-bold tabular-nums'}>{value}</p>
    </div>
  );
}
