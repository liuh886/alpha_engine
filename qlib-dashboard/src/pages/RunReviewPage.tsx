import { useOutletContext } from 'react-router-dom';
import { RunCapabilityReview } from '@/components/RunCapabilityReview';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

export function RunReviewPage() {
  const { activeRun } = useOutletContext<RunWorkspaceContext>();
  if (!activeRun) {
    return <div className="rounded-xl border-2 border-dashed p-12 text-center text-sm text-muted-foreground">Select a governed run from Runs.</div>;
  }
  return <RunCapabilityReview run={activeRun} />;
}
