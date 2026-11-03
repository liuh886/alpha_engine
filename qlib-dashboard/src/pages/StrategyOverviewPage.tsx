import { lazy, Suspense } from 'react';
import { Link, useOutletContext, useSearchParams } from 'react-router-dom';
import { ArrowRight, FlaskConical } from 'lucide-react';
import { DailyResearchBrief } from '@/components/DailyResearchBrief';
import { OperationsReadStatus } from '@/components/OperationsReadStatus';
import { useAccessControl } from '@/hooks/useAccessControl';
import { describeStrategyObservation, type StrategyObservationBrief } from '@/lib/strategy-operations';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

const Racetrack = lazy(() => import('@/components/racetrack/RacetrackWorkspace')
  .then(module => ({ default: module.RacetrackWorkspace })));

function observationBadgeClass(kind: StrategyObservationBrief['kind']): string {
  switch (kind) {
    case 'changed':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300';
    case 'attention':
      return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300';
    case 'retained':
      return 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-300';
    case 'access':
      return 'border-purple-200 bg-purple-50 text-purple-700 dark:border-purple-800 dark:bg-purple-950/40 dark:text-purple-300';
    case 'unchanged':
    case 'pending':
    default:
      return 'border-border bg-muted/40 text-muted-foreground';
  }
}

export function StrategyOverviewPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const access = useAccessControl();
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
        const formalCutoffs = Array.from(new Set(entries.map(e => e.evidenceCutoff))).filter(Boolean);
        const formalCutoffSummary = formalCutoffs.length ? formalCutoffs.join(', ') : 'Unavailable';
        return <div key={market} className="rounded-xl border bg-card p-4">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">{market === 'us' ? 'US' : 'China'} formal evidence</p>
          <p className="mt-2 text-sm font-medium">
            {entries.length ? entries.length + ' formal strategies' : 'Formal evidence unavailable'}
          </p>
          <div className="mt-2 space-y-1 text-xs text-muted-foreground">
            <p>
              <span className="font-medium text-foreground">Formal evidence:</span> Through {formalCutoffSummary}
            </p>
            <p>
              <span className="font-medium text-foreground">Target dates:</span> Evaluated per strategy cadence
            </p>
          </div>
          <p className="mt-3 border-t pt-2 text-[11px] leading-relaxed text-muted-foreground">
            Each strategy retains its own formal cutoff. Target dates are evaluated separately; this card does not infer a shared current market date. Provider status is verified on <Link to="/system" className="text-primary underline">Operating Status</Link>.
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
        <div className="space-y-2 pt-1">
          <div>
            <Link to="/strategies" className="inline-flex min-h-10 items-center gap-2 text-sm font-semibold text-primary">
              Explore all formal strategies <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
          <div className="flex flex-col gap-2 border-t pt-3">
            <Link to="/system" className="text-sm text-primary underline">
              Inspect source and delivery health
            </Link>
            <Link to="/research" className="text-sm text-muted-foreground underline hover:text-primary">
              Open Research Lab (Racetrack & RDI)
            </Link>
          </div>
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
        {formalRuns.map(run => {
          const snapshot = snapshots.get(run.modelVersionId);
          const accessPending = access.loading || access.policyLoading;
          const accessible = snapshot
            ? Boolean(snapshot.strategyId) && !accessPending && access.canAccess(access.requiredTier('strategy', snapshot.strategyId))
            : true;
          const visibleSnapshot = accessible && (!snapshot?.readState || snapshot.readState === 'retained') ? snapshot : undefined;
          const checking = accessPending || (loading && !visibleSnapshot);
          const brief: StrategyObservationBrief = checking
            ? {
                kind: 'pending',
                label: 'Checking observation',
                reason: 'Verifying access and current observations…',
                nextStep: 'Formal historical evidence remains available while verification completes.',
                recovery: null,
              }
            : !snapshot?.strategyId
              ? describeStrategyObservation()
              : describeStrategyObservation(snapshot, accessible);

          return (
            <Link
              key={run.key}
              to={'/strategies/' + encodeURIComponent(run.modelVersionId)}
              className="flex flex-col justify-between rounded-xl border p-4 transition-colors hover:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring"
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <span className="block text-sm font-semibold">{run.title}</span>
                  <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {run.market.toUpperCase()} · Formal
                  </span>
                </div>
                <div className="mt-2.5">
                  <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium ${observationBadgeClass(brief.kind)}`}>
                    {brief.label}
                  </span>
                </div>
                <span className="mt-3 block text-xs text-muted-foreground">Historical evidence through {run.evidenceCutoff}</span>
                {snapshot?.latestCompletedSession && accessible && (
                  <span className="mt-1 block text-[11px] text-muted-foreground">
                    Observed session {snapshot.latestCompletedSession}
                  </span>
                )}
              </div>
              <div className="mt-4 border-t pt-2">
                <span className="inline-flex items-center gap-1 text-xs font-medium text-primary">
                  Inspect evidence <ArrowRight className="h-3 w-3" />
                </span>
              </div>
            </Link>
          );
        })}
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
