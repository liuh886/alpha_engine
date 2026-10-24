import { useEffect, useState } from 'react';
import { fetchRdiResearch, rdiEvidenceUrl, type RdiResearchBriefing } from '@/lib/rdi-research';

const percent = (value: number) => (value * 100).toFixed(1) + '%';
const label = (value: string) => value.replace(/_/g, ' ');

export function RdiResearchStatus({ attempt }: { attempt: number }) {
  const [result, setResult] = useState<{ attempt: number; briefing: RdiResearchBriefing | null } | null>(null);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      active = false;
      controller.abort();
      setResult({ attempt, briefing: null });
    }, 10_000);
    void fetchRdiResearch(controller.signal).then(briefing => {
      if (active) setResult({ attempt, briefing });
    }).catch(() => {
      if (active) setResult({ attempt, briefing: null });
    }).finally(() => window.clearTimeout(timeout));
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [attempt]);
  const current = result?.attempt === attempt ? result : null;
  const briefing = current?.briefing;
  return <section className="rounded-xl border bg-card p-4 sm:p-6" aria-labelledby="rdi-title">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 id="rdi-title" className="font-semibold">A-share risk density · RDI</h2>
      <span className="rounded-full border px-2 py-1 text-xs text-muted-foreground">Research prototype</span>
    </div>
    <p className="mt-2 text-sm text-muted-foreground">Study whether known adverse events add information about downside over 7, 14 and 28 trading sessions.</p>
    {!current ? <p role="status" className="mt-4 text-sm">Reading reviewed evidence…</p>
      : !briefing ? <p role="alert" className="mt-4 text-sm">RDI reviewed evidence could not be verified. Use Refresh status to retry. Other strategy observations remain independent.</p>
        : <>
          <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
            <h3 className="text-sm font-semibold">Risk assessment unavailable</h3>
            <p className="mt-2 text-sm">Event coverage and predictive usefulness require separate validation. Missing events cannot be interpreted as zero risk. No RDI score or forecast is published.</p>
            {briefing.status === 'evidence_mismatch' && <p role="alert" className="mt-2 text-sm">Source evidence has changed or is inconsistent. Historical statistics are hidden until the review is renewed.</p>}
          </div>
          <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-3">
            <div><dt className="text-xs text-muted-foreground">Reviewed CSI300 price cutoff</dt><dd className="mt-1 font-semibold">{briefing.reviewed_price_cutoff}</dd><dd className="mt-1 text-xs text-muted-foreground">{briefing.reviewed_price_rows.toLocaleString('en-US')} post-inception rows · index, not ETF</dd></div>
            <div><dt className="text-xs text-muted-foreground">Historical event source certification</dt><dd className="mt-1 font-semibold">{briefing.event_families.filter(row => row.historical_pit_verified).length} / {briefing.event_families.length} families</dd><dd className="mt-1 text-xs text-muted-foreground">Inventory reviewed {briefing.reviewed_at}; not a daily coverage audit</dd></div>
            <div><dt className="text-xs text-muted-foreground">Sector ETF admission</dt><dd className="mt-1 font-semibold">None admitted</dd><dd className="mt-1 text-xs text-muted-foreground">{briefing.sector_candidates.length} candidates await verified history and eligibility</dd></div>
          </dl>
          <p className="mt-4 border-t pt-3 text-sm"><span className="font-semibold">Next evidence needed:</span> certify historical event availability and completeness, verify price sessions through the study period, then run frozen out-of-sample comparisons.</p>
          {!!briefing.historical_comparison.length && <details className="mt-4 border-t pt-3">
            <summary className="cursor-pointer text-sm font-medium">Historical price comparison · not an RDI forecast</summary>
            <p className="mt-3 text-sm text-muted-foreground">Historical frequency of a CSI300 close-to-close loss of at least 5%, grouped by whether the preceding 60-session drawdown was at least 10%. Prices end {briefing.reviewed_price_cutoff}.</p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">Descriptive price-only severe-loss frequencies and overlapping sample counts</caption>
                <thead><tr className="border-b text-xs text-muted-foreground"><th className="p-2">Horizon</th><th className="p-2">Drawdown ≥10%</th><th className="p-2">Other states</th></tr></thead>
                <tbody>{briefing.historical_comparison.map(row => <tr key={row.horizon_sessions} className="border-b last:border-0">
                  <th scope="row" className="p-2 font-medium">{row.horizon_sessions} sessions</th>
                  <td className="p-2 tabular-nums">{percent(row.drawdown_loss_frequency)}<span className="mt-1 block text-xs text-muted-foreground">n={row.drawdown_observations.toLocaleString('en-US')}</span></td>
                  <td className="p-2 tabular-nums">{percent(row.other_loss_frequency)}<span className="mt-1 block text-xs text-muted-foreground">n={row.other_observations.toLocaleString('en-US')}</span></td>
                </tr>)}</tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-muted-foreground">Overlapping observations are not independent samples. This single historical comparison has no out-of-sample significance or calibration evidence and does not test event density. It is not a current loss probability or tradable return.</p>
          </details>}
          <details className="mt-4 border-t pt-3">
            <summary className="cursor-pointer text-sm font-medium">Data coverage and sources</summary>
            <ul className="mt-3 divide-y text-sm">{briefing.event_families.map(row => <li key={row.id} className="py-3">
              <div className="flex flex-wrap justify-between gap-2"><span className="font-medium capitalize">{label(row.id)}</span><span className="text-xs text-muted-foreground">{row.historical_pit_verified ? 'Archive certified in inventory' : 'Historical coverage unverified'} · {label(row.readiness)}</span></div>
              <p className="mt-1 text-xs text-muted-foreground">{row.source}</p>
            </li>)}</ul>
            <p className="mt-3 text-xs text-muted-foreground">Unapproved sector candidates: {briefing.sector_candidates.map(row => `${label(row.sector)} (${row.symbol})`).join(' · ')}.</p>
            <a className="mt-4 inline-block text-sm text-primary underline" href={rdiEvidenceUrl(briefing.protocol_path, briefing.repository_commit)} target="_blank" rel="noreferrer">Research protocol and limitations</a>
            <p className="mt-3 break-all text-xs text-muted-foreground"><a className="text-primary underline" href={rdiEvidenceUrl('data/csv_source/000300.csv', briefing.repository_commit)} target="_blank" rel="noreferrer">Price source at this build</a> · Git blob {briefing.price_source_git_blob_sha1}</p>
            <ul className="mt-3 space-y-3">{briefing.evidence.map(row => <li key={row.path} className="min-w-0 text-xs">
              <a className="break-all text-primary underline" href={rdiEvidenceUrl(row.path, briefing.repository_commit)} target="_blank" rel="noreferrer">{row.path}</a>
              <p className="mt-1 break-all font-mono text-muted-foreground">SHA-256 {row.sha256}</p>
            </li>)}</ul>
          </details>
        </>}
  </section>;
}
