import { useState } from 'react';
import { rdiEvidenceUrl, type RdiResearchBriefing } from '@/lib/rdi-research';

const label = (value: string) => value.replace(/_/g, ' ');
const readinessLabel: Record<string, string> = { partial: 'Partially integrated', calendar_known_only: 'Calendar only', not_integrated: 'Not integrated' };

export function RdiEvidenceSources({ briefing }: { briefing: RdiResearchBriefing }) {
  const [needsIntegration, setNeedsIntegration] = useState(false);
  const sources = briefing.event_families.filter(row => !needsIntegration || row.readiness === 'not_integrated');
  return <>
    <details>
      <summary className="min-h-12 cursor-pointer py-4 text-sm font-medium">Data coverage and sources<span className="ml-2 text-xs font-normal text-muted-foreground">{briefing.event_families.length} families</span></summary>
      <div className="pb-5">
        <div role="group" aria-label="Source inventory filter" className="flex flex-wrap gap-2">
          <button type="button" aria-pressed={!needsIntegration} onClick={() => setNeedsIntegration(false)} className={'min-h-10 rounded-md border px-3 text-xs font-medium ' + (!needsIntegration ? 'border-primary/40 bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted')}>All sources</button>
          <button type="button" aria-pressed={needsIntegration} onClick={() => setNeedsIntegration(true)} className={'min-h-10 rounded-md border px-3 text-xs font-medium ' + (needsIntegration ? 'border-primary/40 bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted')}>Needs integration</button>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">Integration describes adapter availability. It does not certify historical completeness or first-time availability.</p>
        <p role="status" className="mt-3 text-xs text-muted-foreground">Showing {sources.length} of {briefing.event_families.length} source families</p>
        {sources.length ? <ul className="mt-1 divide-y text-sm">{sources.map(row => <li key={row.id} className="py-3">
          <div className="flex flex-wrap justify-between gap-2"><span className="font-medium capitalize">{label(row.id)}</span><span className="text-xs text-muted-foreground">{readinessLabel[row.readiness] || label(row.readiness)}</span></div>
          <p className="mt-1 text-xs text-muted-foreground">{row.source}</p>
          <p className="mt-1 text-xs">{row.historical_pit_verified ? 'Archive certified in inventory' : 'Historical coverage unverified'}</p>
        </li>)}</ul> : <p className="mt-3 rounded-md border bg-muted/20 p-3 text-sm">No sources in this inventory are marked as needing integration. Historical certification is still a separate requirement.</p>}
        <p className="mt-3 border-t pt-3 text-xs text-muted-foreground">Unapproved sector candidates: {briefing.sector_candidates.map(row => `${label(row.sector)} (${row.symbol})`).join(' · ')}.</p>
      </div>
    </details>
    <details className="border-t">
      <summary className="min-h-12 cursor-pointer py-4 text-sm font-medium">Evidence provenance</summary>
      <div className="pb-5">
        <a className="inline-block min-h-10 py-2 text-sm text-primary underline" href={rdiEvidenceUrl(briefing.protocol_path, briefing.repository_commit)} target="_blank" rel="noreferrer">Research protocol and limitations</a>
        <p className="mt-2 break-all text-xs text-muted-foreground"><a className="text-primary underline" href={rdiEvidenceUrl('data/csv_source/000300.csv', briefing.repository_commit)} target="_blank" rel="noreferrer">Price source at this build</a> · Git blob {briefing.price_source_git_blob_sha1}</p>
        <ul className="mt-4 space-y-3">{briefing.evidence.map(row => <li key={row.path} className="min-w-0 text-xs">
          <a className="break-all text-primary underline" href={rdiEvidenceUrl(row.path, briefing.repository_commit)} target="_blank" rel="noreferrer">{row.path}</a>
          <p className="mt-1 break-all font-mono text-muted-foreground">SHA-256 {row.sha256}</p>
        </li>)}</ul>
      </div>
    </details>
  </>;
}
