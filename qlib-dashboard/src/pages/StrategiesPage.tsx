import { Link, useOutletContext } from 'react-router-dom';
import { OperationsReadStatus } from '@/components/OperationsReadStatus';
import { StrategyFleet } from '@/components/StrategyFleet';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

export function StrategiesPage() {
  const { operations } = useOutletContext<RunWorkspaceContext>();
  return <div className="mx-auto max-w-[1500px] space-y-5 pb-16">
    <header className="border-b pb-5">
      <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Formal strategy evidence</p>
      <h1 className="mt-2 text-2xl font-bold tracking-tight">Strategies</h1>
      <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
        Compare accepted models using declared benchmarks and actual evidence windows.
        Historical backtest returns are not live account returns.
      </p>
      <Link to="/app" className="mt-3 inline-block text-sm text-primary underline">Back to today's brief</Link>
    </header>
    <OperationsReadStatus loading={operations.loading} issues={operations.issues}
      reload={operations.reload} previousRead={operations.previousRead} />
    <StrategyFleet runs={operations.formalRuns} snapshots={operations.snapshots} />
  </div>;
}
