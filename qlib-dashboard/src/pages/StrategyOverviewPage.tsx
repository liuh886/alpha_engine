import { Activity, ShieldCheck } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import { StrategyFleet } from '@/components/StrategyFleet';
import { useStrategyOperations } from '@/hooks/useStrategyOperations';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

export function StrategyOverviewPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const { formalRuns, snapshots, loading } = useStrategyOperations(workspace.runs);
  const operational = Array.from(snapshots.values()).filter((snapshot) => !['pipeline_unavailable', 'awaiting_observation'].includes(snapshot.status)).length;
  const attention = Array.from(snapshots.values()).filter((snapshot) => ['stale', 'blocked', 'delivery_failed'].includes(snapshot.status)).length;

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 pb-16">
      <section className="grid gap-6 border-b pb-6 xl:grid-cols-[minmax(0,1fr)_380px] xl:items-end">
        <div className="max-w-4xl">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">Strategy operating console</p>
          <h1 className="mt-2 text-3xl font-black tracking-tight md:text-5xl">What are the strategies doing now?</h1>
          <p className="mt-4 max-w-3xl text-sm leading-relaxed text-muted-foreground md:text-base">
            Start with the current state, target allocation, next decision and operating health. Historical performance and retained evidence stay attached to each strategy and remain available on drill-down.
          </p>
        </div>
        <div className="grid grid-cols-3 divide-x rounded-xl border bg-card shadow-sm">
          <div className="p-4"><p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground">Formal</p><p className="mt-2 text-2xl font-bold">{formalRuns.length}</p></div>
          <div className="p-4"><p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground">Operational</p><p className="mt-2 text-2xl font-bold">{operational}</p></div>
          <div className="p-4"><p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground">Attention</p><p className="mt-2 text-2xl font-bold">{attention}</p></div>
        </div>
      </section>

      <StrategyFleet runs={formalRuns} snapshots={snapshots} loading={loading} />

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="flex gap-3 rounded-xl border bg-card p-4">
          <Activity className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          <div>
            <h2 className="text-sm font-semibold">Decision-first, evidence-attached</h2>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">A live target is shown only when a governed signal source exists. US/CN remain explicit as signal-unavailable until their 10-session publication pipelines are implemented.</p>
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
