import { useOutletContext } from 'react-router-dom';
import { FormalBacktestReview } from '@/components/FormalBacktestReview';
import { RunCapabilityReview } from '@/components/RunCapabilityReview';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

export function RunReviewPage() {
  const { activeRun } = useOutletContext<RunWorkspaceContext>();
  if (!activeRun) {
    return <div className="rounded-xl border-2 border-dashed p-12 text-center text-sm text-muted-foreground">Select a governed run from Runs.</div>;
  }
  if (activeRun.channel === 'formal') return <FormalBacktestReview run={activeRun} />;
  return <RunCapabilityReview run={activeRun} />;
}
