import { lazy, Suspense, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { RdiResearchStatus } from '@/components/RdiResearchStatus';
import { StudyReviewDesk } from '@/components/research/StudyReviewDesk';
import { cn } from '@/lib/utils';

const Racetrack = lazy(() => import('@/components/racetrack/RacetrackWorkspace')
  .then(module => ({ default: module.RacetrackWorkspace })));

type ResearchSection = 'racetrack' | 'reviews' | 'rdi';

const AREAS: { id: ResearchSection; title: string; description: string }[] = [
  {
    id: 'racetrack',
    title: 'Racetrack · Strategy experiments',
    description: 'Local-only NAV, season scoreboards and Runner theses. Hosted pages do not publish private projections.',
  },
  {
    id: 'reviews',
    title: 'Review Desk · Hypothesis review',
    description: 'Continuous empirical lifecycle: frozen thesis tracking, counter-evidence collection, and review checkpoints.',
  },
  {
    id: 'rdi',
    title: 'RDI · A-share risk research',
    description: 'Source-bound historical price comparisons; no validated risk probability or score.',
  },
];

export function ResearchHubPage() {
  const [params, setParams] = useSearchParams();
  const [attempt, setAttempt] = useState(0);
  const rawSection = params.get('section');
  const section: ResearchSection =
    rawSection === 'rdi' ? 'rdi' : rawSection === 'reviews' ? 'reviews' : 'racetrack';

  const select = (next: ResearchSection) => setParams(previous => {
    const updated = new URLSearchParams(previous);
    updated.set('section', next);
    if (next !== 'racetrack') {
      for (const key of ['raceRunner', 'raceDetail']) updated.delete(key);
    }
    return updated;
  });

  return <div className="mx-auto max-w-[1500px] space-y-5 pb-16">
    <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border/80 pb-5">
      <div className="min-w-0">
        <p className="ae-kicker">Independent research · not live strategies</p>
        <h1 className="ae-page-title mt-2">Research Lab</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
          Examine hypotheses and retained results. Research Runners, continuous review records, and historical risk observations
          do not become formal strategies or trading signals without separate validation.
        </p>
        <Link to="/app" className="mt-3 inline-block text-sm text-primary underline underline-offset-2">Back to today's brief</Link>
      </div>
      <Button variant="outline" onClick={() => setAttempt(value => value + 1)}>Refresh status</Button>
    </header>
    <div className="ae-surface grid overflow-hidden divide-y divide-border/70 sm:grid-cols-3 sm:divide-x sm:divide-y-0"
      aria-label="Independent research areas">
      {AREAS.map(area => {
        const active = section === area.id;
        return <button key={area.id} type="button" aria-pressed={active} onClick={() => select(area.id)}
          className={cn(
            'relative flex min-h-[44px] flex-col gap-1.5 p-4 text-left transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
            active ? 'bg-primary/5 shadow-[inset_3px_0_0_hsl(var(--primary))]' : 'hover:bg-muted/40',
          )}>
          <span className="flex items-start justify-between gap-2">
            <span className="text-sm font-semibold leading-5">{area.title}</span>
            {active && (
              <span aria-hidden="true" className="ae-chip shrink-0 border-primary/30 bg-primary/10 text-primary">
                <Check className="h-3 w-3" />
                Selected
              </span>
            )}
          </span>
          <span className="text-xs leading-5 text-muted-foreground">{area.description}</span>
        </button>;
      })}
    </div>
    {section === 'rdi' ? <RdiResearchStatus attempt={attempt} /> :
     section === 'reviews' ? <StudyReviewDesk attempt={attempt} /> :
      <Suspense fallback={<p role="status">Loading Racetrack research…</p>}><Racetrack /></Suspense>}
  </div>;
}
