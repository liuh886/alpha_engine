import { useOutletContext, useSearchParams } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { StrategyFleet } from '@/components/StrategyFleet';
import { OperationsReadStatus } from '@/components/OperationsReadStatus';
import { DailyResearchBrief } from '@/components/DailyResearchBrief';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

const Racetrack = lazy(() => import('@/components/racetrack/RacetrackWorkspace').then(m => ({ default: m.RacetrackWorkspace })));

export function StrategyOverviewPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const [params, setParams] = useSearchParams();
  const view = params.get('view') === 'racetrack' ? 'racetrack' : 'strategies';
  const setView = (next: 'strategies' | 'racetrack') => setParams(previous => {
    const updated = new URLSearchParams(previous);
    if (next === 'racetrack') updated.set('view', next);
    else updated.delete('view');
    return updated;
  });
  const { formalRuns, snapshots, loading, issues, reload, previousRead } = workspace.operations;
  return (
    <div className="mx-auto max-w-[1500px] space-y-4 pb-16">
      <header>
        <h1 className="text-xl font-bold tracking-tight md:text-2xl">{view === 'racetrack' ? 'Racetrack research' : 'What are the strategies doing now?'}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{view === 'racetrack' ? 'Published local research evidence, with its original dates and limitations.' : 'Latest observations, reasons and next evaluation.'}</p>
      </header>
      <div className="flex gap-2" aria-label="Overview view">
        <button aria-pressed={view === 'strategies'} onClick={() => setView('strategies')} className="min-h-10 rounded-md border px-4 text-sm aria-pressed:bg-muted">Strategy monitor</button>
        <button aria-pressed={view === 'racetrack'} onClick={() => setView('racetrack')} className="min-h-10 rounded-md border px-4 text-sm aria-pressed:bg-muted">Racetrack research</button>
      </div>
      {view === 'racetrack' ? <Suspense fallback={<p role="status">Loading Racetrack…</p>}><Racetrack /></Suspense> : <>
      <OperationsReadStatus loading={loading} issues={issues} reload={reload} previousRead={previousRead} />
      <DailyResearchBrief runs={formalRuns} snapshots={snapshots} loading={loading} reload={reload} />
      <StrategyFleet runs={formalRuns} snapshots={snapshots} />
      </>}
    </div>
  );
}
