import { useOutletContext } from 'react-router-dom';
import { FormalBacktestReview } from '@/components/FormalBacktestReview';
import { RunCapabilityReview } from '@/components/RunCapabilityReview';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

export function usesStructuredBundleReview(run: GovernedRunSummary): boolean {
  return run.channel === 'formal'
    || (run.channel === 'preview' && run.evidenceStatus === 'complete');
}

export function RunReviewPage() {
  const { activeRun } = useOutletContext<RunWorkspaceContext>();
  if (!activeRun) {
    return <div className="rounded-xl border-2 border-dashed p-12 text-center text-sm text-muted-foreground">Select a governed run from Runs.</div>;
  }
  if (usesStructuredBundleReview(activeRun)) return <FormalBacktestReview run={activeRun} />;
  return <RunCapabilityReview run={activeRun} />;
}
