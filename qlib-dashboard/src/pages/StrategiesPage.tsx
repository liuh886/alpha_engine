import { useOutletContext } from 'react-router-dom';
import { StrategyFleet } from '@/components/StrategyFleet';
import { useStrategyOperations } from '@/hooks/useStrategyOperations';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

export function StrategiesPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const { formalRuns, snapshots, loading } = useStrategyOperations(workspace.runs);

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 pb-16">
      <header className="max-w-3xl">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">Formal strategy registry</p>
        <h1 className="mt-2 text-3xl font-black tracking-tight">Strategies</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          Compare accepted formal baselines by return and risk before opening a strategy. Historical performance is public; live holdings, target allocations and current signal drivers follow each strategy's account or Pro access policy.
        </p>
      </header>
      <StrategyFleet runs={formalRuns} snapshots={snapshots} loading={loading} />
    </div>
  );
}
