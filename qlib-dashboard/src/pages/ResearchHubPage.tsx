import { lazy, Suspense } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { RdiResearchStatus } from '@/components/RdiResearchStatus';

const Racetrack = lazy(() => import('@/components/racetrack/RacetrackWorkspace')
  .then(module => ({ default: module.RacetrackWorkspace })));

export function ResearchHubPage() {
  const [params, setParams] = useSearchParams();
  const section = params.get('section') === 'rdi' ? 'rdi' : 'racetrack';
  const select = (next: 'racetrack' | 'rdi') => setParams(previous => {
    const updated = new URLSearchParams(previous);
    updated.set('section', next);
    if (next === 'rdi') {
      for (const key of ['raceRunner', 'raceDetail']) updated.delete(key);
    }
    return updated;
  });
  return <div className="mx-auto max-w-[1500px] space-y-5 pb-16">
    <header className="border-b pb-5">
      <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Independent research · not live strategies</p>
      <h1 className="mt-2 text-2xl font-bold tracking-tight">Research Lab</h1>
      <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
        Examine hypotheses and retained results. Research Runners and historical risk observations
        do not become formal strategies or trading signals without separate validation.
      </p>
      <Link to="/app" className="mt-3 inline-block text-sm text-primary underline">Back to today's brief</Link>
    </header>
    <div className="grid gap-3 sm:grid-cols-2" aria-label="Independent research areas">
      <button type="button" aria-pressed={section === 'racetrack'} onClick={() => select('racetrack')}
        className={'rounded-xl border p-4 text-left focus-visible:ring-2 focus-visible:ring-ring ' +
          (section === 'racetrack' ? 'border-primary bg-primary/5' : 'bg-card hover:bg-muted/30')}>
        <span className="block font-semibold">Racetrack · Strategy experiments</span>
        <span className="mt-1 block text-xs text-muted-foreground">
          Local-only NAV, season scoreboards and Runner theses. Hosted pages do not publish private projections.
        </span>
      </button>
      <button type="button" aria-pressed={section === 'rdi'} onClick={() => select('rdi')}
        className={'rounded-xl border p-4 text-left focus-visible:ring-2 focus-visible:ring-ring ' +
          (section === 'rdi' ? 'border-primary bg-primary/5' : 'bg-card hover:bg-muted/30')}>
        <span className="block font-semibold">RDI · A-share risk research</span>
        <span className="mt-1 block text-xs text-muted-foreground">
          Source-bound historical price comparisons; no validated risk probability or score.
        </span>
      </button>
    </div>
    {section === 'rdi' ? <RdiResearchStatus attempt={0} /> :
      <Suspense fallback={<p role="status">Loading Racetrack research…</p>}><Racetrack /></Suspense>}
  </div>;
}
