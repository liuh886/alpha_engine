import { lazy, Suspense } from 'react';
import { Link, useOutletContext, useSearchParams } from 'react-router-dom';
import { ArrowRight, FlaskConical } from 'lucide-react';
import { DailyResearchBrief } from '@/components/DailyResearchBrief';
import { OperationsReadStatus } from '@/components/OperationsReadStatus';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

const Racetrack = lazy(() => import('@/components/racetrack/RacetrackWorkspace')
  .then(module => ({ default: module.RacetrackWorkspace })));

export function StrategyOverviewPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const [params, setParams] = useSearchParams();
  const legacyRace = params.get('view') === 'racetrack';
  const setLegacyRace = (next: boolean) => setParams(previous => {
    const updated = new URLSearchParams(previous);
    if (next) updated.set('view', 'racetrack');
    else updated.delete('view');
    return updated;
  });
  const { formalRuns, snapshots, loading, issues, reload, previousRead } = workspace.operations;
  if (legacyRace) return <div className="mx-auto max-w-[1500px] space-y-4 pb-16">
    <header><h1 className="text-xl font-bold tracking-tight md:text-2xl">Racetrack research</h1>
      <p className="mt-2 text-sm text-muted-foreground">Published local research evidence, with its original dates and limitations.</p></header>
    <div className="flex flex-wrap gap-2">
      <button type="button" onClick={() => setLegacyRace(false)}
        className="min-h-10 rounded-md border px-4 text-sm">Strategy monitor</button>
      <Link to="/research" className="inline-flex min-h-10 items-center rounded-md border px-4 text-sm text-primary">
        Open Research Lab
      </Link>
    </div>
    <Suspense fallback={<p role="status">Loading Racetrack…</p>}><Racetrack /></Suspense>
  </div>;

  const markets = ['us', 'cn'] as const;
  return <div className="mx-auto max-w-[1500px] space-y-5 pb-16">
    <header className="border-b pb-5">
      <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Decision-first research workspace</p>
      <h1 className="mt-2 text-xl font-bold tracking-tight md:text-2xl">What are the strategies doing now?</h1>
      <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
        Start with verified changes, the reason behind each observation and the next allowed review.
        This is research evidence, not an order or live market feed.
      </p>
    </header>
    <div className="grid gap-3 sm:grid-cols-2" aria-label="Formal evidence by market">
      {markets.map(market => {
        const entries = formalRuns.filter(run => run.market.toLowerCase() === market);
        return <div key={market} className="rounded-xl border bg-card p-4">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">{market === 'us' ? 'US' : 'China'} formal evidence</p>
          <p className="mt-2 text-sm font-medium">
            {entries.length ? entries.length + ' formal strategies' : 'Formal evidence unavailable'}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Each strategy retains its own formal cutoff. This card does not claim a shared current market date.
          </p>
        </div>;
      })}
    </div>
    <OperationsReadStatus loading={loading} issues={issues} reload={reload} previousRead={previousRead} />
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.8fr)_minmax(270px,0.8fr)]">
      <DailyResearchBrief runs={formalRuns} snapshots={snapshots} loading={loading} reload={reload} />
      <aside className="space-y-3 rounded-2xl border bg-card p-5" aria-label="Where to go next">
        <h2 className="font-semibold">Your next research step</h2>
        <p className="text-sm text-muted-foreground">
          Open a strategy to inspect its current observation, performance, counter-evidence and limitations.
          Dates and review cadence are shown with the individual strategy.
        </p>
        <Link to="/strategies" className="inline-flex min-h-10 items-center gap-2 text-sm font-semibold text-primary">
          Explore all formal strategies <ArrowRight className="h-4 w-4" />
        </Link>
        <div className="border-t pt-3">
          <Link to="/system" className="text-sm text-primary underline">Inspect source and delivery health</Link>
        </div>
      </aside>
    </div>
    <section className="rounded-2xl border bg-card p-5" aria-label="Formal strategy snapshot">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h2 className="font-semibold">Formal strategy fleet</h2>
          <p className="mt-1 text-xs text-muted-foreground">Public formal evidence cutoffs; current targets remain separately access-controlled.</p></div>
        <Link to="/strategies" className="text-sm text-primary underline">Compare performance and risk</Link>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {formalRuns.map(run => <Link key={run.key} to={'/strategies/' + encodeURIComponent(run.modelVersionId)}
          className="rounded-xl border p-3 transition-colors hover:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring">
          <span className="block text-sm font-semibold">{run.title}</span>
          <span className="mt-1 block text-xs uppercase text-muted-foreground">{run.market.toUpperCase()} · Formal</span>
          <span className="mt-3 block text-xs text-muted-foreground">Historical evidence through {run.evidenceCutoff}</span>
          <span className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary">Inspect evidence <ArrowRight className="h-3 w-3" /></span>
        </Link>)}
        {!formalRuns.length && <p className="text-sm text-muted-foreground">Reading verified formal strategy evidence…</p>}
      </div>
    </section>
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/20 p-4"
      aria-label="Independent research">
      <div className="flex items-start gap-3"><FlaskConical className="mt-0.5 h-5 w-5 text-muted-foreground" />
        <div><h2 className="text-sm font-semibold">Independent research</h2>
          <p className="mt-1 text-xs text-muted-foreground">Racetrack and RDI are separate studies, not a fifth formal strategy.</p></div></div>
      <div className="flex flex-wrap gap-3">
        <button type="button" className="min-h-10 rounded-md border bg-card px-3 text-xs"
          onClick={() => setLegacyRace(true)}>Racetrack research</button>
        <Link to="/research?section=rdi" className="inline-flex min-h-10 items-center text-xs text-primary underline">RDI research</Link>
      </div>
    </section>
  </div>;
}
