import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { fetchRdiResearch, type RdiResearchBriefing } from '@/lib/rdi-research';
import { RdiHistoricalComparison } from './RdiHistoricalComparison';
import { RdiEvidenceSources } from './RdiEvidenceSources';

export function RdiResearchStatus({ attempt }: { attempt: number }) {
  const [retryAttempt, setRetryAttempt] = useState(0);
  const [result, setResult] = useState<{
    attempt: number; retryAttempt: number; briefing: RdiResearchBriefing | null;
  } | null>(null);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      active = false;
      controller.abort();
      setResult({ attempt, retryAttempt, briefing: null });
    }, 10_000);
    void fetchRdiResearch(controller.signal).then(briefing => {
      if (active) setResult({ attempt, retryAttempt, briefing });
    }).catch(() => {
      if (active) setResult({ attempt, retryAttempt, briefing: null });
    }).finally(() => window.clearTimeout(timeout));
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [attempt, retryAttempt]);
  const current = result?.attempt === attempt && result.retryAttempt === retryAttempt ? result : null;
  const briefing = current?.briefing;
  const retry = () => setRetryAttempt(value => value + 1);

  return <section className="min-w-0 overflow-hidden rounded-xl border bg-card" aria-labelledby="rdi-title" aria-busy={!current}>
    <header className="border-b p-4 sm:px-6 sm:py-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">A-share risk research</p><h2 id="rdi-title" tabIndex={-1} className="mt-1 scroll-mt-4 text-xl font-semibold tracking-tight">Risk density · RDI</h2></div>
        <span className="rounded-full border bg-muted/40 px-3 py-1 text-xs text-muted-foreground">Not validated</span>
      </div>
      <p className="mt-2 max-w-3xl text-sm text-muted-foreground">Understand what known events could explain about risk over 7, 14 and 28 trading sessions.</p>
    </header>
    {!current ? <div role="status" className="min-h-48 p-6 text-sm text-muted-foreground">Reading reviewed evidence…</div>
      : !briefing ? <div className="space-y-4 p-4 sm:p-6">
        <div role="alert"><h3 className="font-semibold">Reviewed evidence unavailable</h3><p className="mt-2 text-sm text-muted-foreground">RDI reviewed evidence could not be verified. No earlier statistics are shown. Other strategy observations remain independent.</p></div>
        <Button variant="outline" onClick={retry}>Retry RDI</Button>
      </div> : <>
        <div className="grid gap-6 p-4 sm:p-6 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.4fr)]">
          <div className="min-w-0 space-y-5">
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-amber-800 dark:text-amber-300">Current assessment</p>
              <h3 className="mt-2 text-lg font-semibold tracking-tight">Risk assessment unavailable</h3>
              <p className="mt-2 text-sm text-muted-foreground">Event coverage and predictive usefulness need separate validation. Missing events cannot mean zero risk. No RDI score or forecast is published.</p>
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-5 text-sm">
              <div><dt className="text-xs text-muted-foreground">Reviewed price cutoff</dt><dd className="mt-1 font-semibold tabular-nums">{briefing.reviewed_price_cutoff}</dd><dd className="mt-1 text-xs text-muted-foreground">CSI300 index · {briefing.reviewed_price_rows.toLocaleString('en-US')} post-inception rows</dd></div>
              <div><dt className="text-xs text-muted-foreground">Evidence review date</dt><dd className="mt-1 font-semibold tabular-nums">{briefing.reviewed_at}</dd><dd className="mt-1 text-xs text-muted-foreground">Dated review, not a live update</dd></div>
              <div><dt className="text-xs text-muted-foreground">Historical source certification</dt><dd className="mt-1 font-semibold">{briefing.event_families.filter(row => row.historical_pit_verified).length} / {briefing.event_families.length} families</dd><dd className="mt-1 text-xs text-muted-foreground">Inventory only; not a daily audit</dd></div>
              <div><dt className="text-xs text-muted-foreground">Sector ETF admission</dt><dd className="mt-1 font-semibold">None admitted</dd><dd className="mt-1 text-xs text-muted-foreground">{briefing.sector_candidates.length} unapproved candidates</dd></div>
            </dl>
            <div className="border-t pt-4">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Next evidence needed</h3>
              <p className="mt-2 text-sm">Certify a narrow event history, verify prices and exchange sessions through the study period, then test across independent market episodes.</p>
            </div>
          </div>
          {briefing.status === 'evidence_mismatch' ? <div className="min-w-0 rounded-lg border bg-muted/20 p-5">
            <h3 className="font-semibold">Historical comparison withheld</h3>
            <p role="alert" className="mt-2 text-sm text-muted-foreground">Source evidence has changed or is inconsistent. Historical statistics are hidden until the review is renewed.</p>
            <Button variant="outline" className="mt-4" onClick={retry}>Retry RDI</Button>
          </div> : <RdiHistoricalComparison rows={briefing.historical_comparison} priceCutoff={briefing.reviewed_price_cutoff} />}
        </div>
        <div className="border-t px-4 sm:px-6"><RdiEvidenceSources briefing={briefing} /></div>
      </>}
  </section>;
}
