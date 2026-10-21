import { useOutletContext } from 'react-router-dom';
import { StrategyFleet } from '@/components/StrategyFleet';
import { OperationsReadStatus } from '@/components/OperationsReadStatus';
import { DailyResearchBrief } from '@/components/DailyResearchBrief';
import { useStrategyOperations } from '@/hooks/useStrategyOperations';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

export function StrategyOverviewPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const { formalRuns, snapshots, loading, issues, reload } = useStrategyOperations(workspace.runs);
  return (
    <div className="mx-auto max-w-[1500px] space-y-4 pb-16">
      <header>
        <h1 className="text-xl font-bold tracking-tight md:text-2xl">What are the strategies doing now?</h1>
        <p className="mt-2 text-sm text-muted-foreground">Latest observations, reasons and next evaluation.</p>
      </header>
      <OperationsReadStatus loading={loading} issues={issues} reload={reload} />
      <DailyResearchBrief runs={formalRuns} snapshots={snapshots} loading={loading} reload={reload} />
      <StrategyFleet runs={formalRuns} snapshots={snapshots} loading={loading} />
    </div>
  );
}
