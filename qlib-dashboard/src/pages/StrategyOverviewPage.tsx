import { lazy, Suspense } from 'react';
import { Link, useOutletContext, useSearchParams } from 'react-router-dom';
import { ArrowRight, FlaskConical } from 'lucide-react';
import { BenchmarkMarketCards } from '@/components/BenchmarkMarketCards';
import { DailyResearchBrief } from '@/components/DailyResearchBrief';
import { ModelRankingTable } from '@/components/ModelRankingTable';
import { OperationsReadStatus } from '@/components/OperationsReadStatus';
import { useAccessControl } from '@/hooks/useAccessControl';
import { useModelRanking } from '@/hooks/useModelRanking';
import { briefHeadline, buildBriefEntries, nextReviewLabel, summarizeBrief } from '@/lib/research-brief';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

const Racetrack = lazy(() => import('@/components/racetrack/RacetrackWorkspace')
  .then(module => ({ default: module.RacetrackWorkspace })));

function TodayWorkspace({ onOpenRacetrack }: { onOpenRacetrack: () => void }) {
  const { operations } = useOutletContext<RunWorkspaceContext>();
  const ranking = useModelRanking(operations.formalRuns, { includeIndices: true, includeExcess: false });
  const access = useAccessControl();
  const entries = buildBriefEntries(operations.formalRuns, operations.snapshots, operations.loading, access);
  const summary = summarizeBrief(entries, operations.loading, Boolean(access.loading || access.policyLoading));
  const nextReview = nextReviewLabel(summary);

  return <div className="mx-auto max-w-[1500px] space-y-5 pb-16">
    <header className="border-b pb-5">
      <p className="ae-kicker">Decision-first research workspace</p>
      <h1 className="ae-page-title mt-2">What are the strategies doing now?</h1>
      <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
        Start with verified changes, the reason behind each observation and the next allowed review.
        This is research evidence, not an order or live market feed.
      </p>
      <p data-testid="today-decision-summary" role="status" className="mt-3 flex flex-wrap items-baseline gap-x-2 gap-y-1 border-l-2 border-primary/50 pl-2.5 text-sm">
        <span className="font-medium">{briefHeadline(summary, entries.length)}</span>
        {nextReview && <span className="text-muted-foreground">· {nextReview}</span>}
      </p>
    </header>

    <BenchmarkMarketCards
      rows={ranking.rows}
      loading={ranking.loading}
      issues={ranking.issues}
    />

    <section className="space-y-3" aria-label="Model ranking">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="font-semibold">Model ranking</h2>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-muted-foreground">
            Strategies and governed indices, grouped by market. Returns are browser-derived from retained
            observations; every row keeps its own as-of date.
          </p>
        </div>
        <Link to="/strategies" className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline">
          Compare at full density <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </div>
      <ModelRankingTable
        rows={ranking.rows}
        density="compact"
        loading={ranking.loading}
        issues={ranking.issues}
        caption="Model ranking by market and horizon"
      />
    </section>

    <DailyResearchBrief
      runs={operations.formalRuns}
      snapshots={operations.snapshots}
      loading={operations.loading}
      reload={operations.reload}
    />

    <OperationsReadStatus
      loading={operations.loading}
      issues={operations.issues}
      reload={operations.reload}
      previousRead={operations.previousRead}
    />

    <nav aria-label="Research destinations" className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border bg-muted/20 px-4 py-3">
      <Link to="/strategies" className="inline-flex min-h-10 items-center gap-2 text-sm font-semibold text-primary">
        Explore all formal strategies <ArrowRight className="h-4 w-4" aria-hidden="true" />
      </Link>
      <Link to="/system" className="inline-flex min-h-10 items-center text-sm text-primary underline">
        Inspect source and delivery health
      </Link>
    </nav>

    <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/20 p-4"
      aria-label="Independent research">
      <div className="flex items-start gap-3"><FlaskConical className="mt-0.5 h-5 w-5 text-muted-foreground" aria-hidden="true" />
        <div><h2 className="text-sm font-semibold">Independent research</h2>
          <p className="mt-1 text-xs text-muted-foreground">Racetrack and RDI are separate studies, not a fifth formal strategy.</p></div></div>
      <div className="flex flex-wrap gap-3">
        <button type="button" className="min-h-10 rounded-md border bg-card px-3 text-xs"
          onClick={onOpenRacetrack}>Racetrack research</button>
        <Link to="/research?section=rdi" className="inline-flex min-h-10 items-center text-xs text-primary underline">RDI research</Link>
      </div>
    </section>
  </div>;
}

export function StrategyOverviewPage() {
  const [params, setParams] = useSearchParams();

  const legacyRace = params.get('view') === 'racetrack';
  const setLegacyRace = (next: boolean) => setParams(previous => {
    const updated = new URLSearchParams(previous);
    if (next) updated.set('view', 'racetrack');
    else updated.delete('view');
    return updated;
  });
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

  return <TodayWorkspace onOpenRacetrack={() => setLegacyRace(true)} />;
}
