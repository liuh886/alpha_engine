import { FileQuestion, ShieldCheck } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

export function DecisionsPage() {
  const { activeRun } = useOutletContext<RunWorkspaceContext>();
  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <section className="rounded-xl border bg-card p-6 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="rounded-lg bg-primary/10 p-3 text-primary"><ShieldCheck className="h-6 w-6" /></div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Governed decision boundary</p>
            <h2 className="mt-1 text-2xl font-semibold">Decisions</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              This workspace only renders manifest-bound research decision receipts. The browser does not infer, strengthen or synthesize a verdict from charts or metrics.
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-xl border-2 border-dashed p-10 text-center">
        <FileQuestion className="mx-auto h-9 w-9 text-muted-foreground" />
        <h3 className="mt-4 text-lg font-semibold">No completed decision receipt</h3>
        <p className="mx-auto mt-2 max-w-2xl text-sm text-muted-foreground">
          {activeRun
            ? `${activeRun.title} declares decision status “${activeRun.decisionStatus.replaceAll('_', ' ')}”. PR 6 will add verified decision.json loading and review.`
            : 'Select a governed run. Absent and pending receipts remain explicit rather than being replaced by browser heuristics.'}
        </p>
      </section>
    </div>
  );
}
