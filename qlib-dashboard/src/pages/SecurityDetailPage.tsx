import { useEffect, useMemo, useState } from 'react';
import { Link, useOutletContext, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Loader2 } from 'lucide-react';
import { SecurityHistoryChart } from '@/components/SecurityHistoryChart';
import { boundSecurityEvents, loadSecurityEvidence, securityBarsForPeriod, type SecurityEvidence, type SecurityEvent } from '@/lib/security-evidence';
import type { PerformancePeriod } from '@/lib/performancePeriods';
import type { RunWorkspaceContext } from '@/lib/run-workspace';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { cn } from '@/lib/utils';

const PERIODS: Array<{ key: PerformancePeriod; label: string }> = [
  { key: '1m', label: '1M' }, { key: '3m', label: '3M' }, { key: '6m', label: '6M' },
  { key: '1y', label: '1Y' }, { key: '3y', label: '3Y' }, { key: 'all', label: 'All' },
];
const weight = (value: number | null) => value === null ? '—' : `${(value * 100).toFixed(1)}%`;

function History({ evidence, runs }: { evidence: SecurityEvidence; runs: GovernedRunSummary[] }) {
  const [params, setParams] = useSearchParams();
  const range = PERIODS.find(period => period.key === params.get('range'))?.key ?? '1y';
  const [hidden, setHidden] = useState<string[]>([]);
  const [selected, setSelected] = useState<SecurityEvent[]>([]);
  const [completeLedger, setCompleteLedger] = useState(false);
  const [limit, setLimit] = useState(100);
  const models = runs.filter(run => run.market === evidence.market);
  const names = new Map(models.map(run => [run.modelVersionId, run.title]));
  const name = (id: string) => names.get(id) ?? id;
  const allEvents = useMemo(() => boundSecurityEvents(evidence, runs), [evidence, runs]);
  const events = allEvents.filter(event => !hidden.includes(event.model_id));
  const bars = useMemo(() => securityBarsForPeriod(evidence.bars, range), [evidence, range]);
  const first = bars[0];
  const last = bars[bars.length - 1];
  const visibleEvents = events.filter(event => first && last && event.time >= first.time && event.time <= last.time);
  const barDates = new Set(evidence.bars.map(bar => bar.time));
  const outsideCoverage = events.filter(event => !barDates.has(event.time)).length;
  const rows = [...(completeLedger ? events : visibleEvents)].sort((a, b) => b.time.localeCompare(a.time) || a.model_id.localeCompare(b.model_id));
  const activeSelection = selected.filter(event => visibleEvents.includes(event));
  const excludedModels = models.filter(run => !evidence.bindings.some(binding => binding.model_version_id === run.modelVersionId
    && binding.run_id === run.runId && binding.bundle_id === run.bundleId));
  return <>
    <section className="rounded-xl border bg-card p-4 sm:p-6" aria-label="Price and model events">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Price and model events</h2>
          <p data-testid="security-visible-dates" className="mt-1 text-xs text-muted-foreground">{first?.time} – {last?.time} · {bars.length} observed sessions</p>
        </div>
        <div className="flex flex-wrap rounded-lg border p-1" aria-label="Security chart period">
          {PERIODS.map(period => <button key={period.key} type="button" aria-pressed={range === period.key}
            className={cn('min-h-10 rounded-md px-3 text-xs', range === period.key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted')}
            onClick={() => { const next = new URLSearchParams(params); next.set('range', period.key); setParams(next, { replace: true }); }}>
            {period.label}</button>)}
        </div>
      </div>
      <div className="my-4 grid grid-cols-2 gap-3 border-y py-4 sm:grid-cols-4">
        <div><p className="text-xs text-muted-foreground">Last observed close</p><strong className="font-mono">{last?.close.toFixed(2) ?? '—'}</strong></div>
        <div><p className="text-xs text-muted-foreground">Price return in range</p><strong className="font-mono">{first && last ? `${((last.close / first.close - 1) * 100).toFixed(2)}%` : '—'}</strong></div>
        <div><p className="text-xs text-muted-foreground">Model events in range</p><strong data-testid="security-event-count" className="font-mono">{visibleEvents.length}</strong></div>
        <div><p className="text-xs text-muted-foreground">Price evidence through</p><strong className="font-mono">{evidence.cutoff}</strong></div>
      </div>
      <fieldset className="mb-4 flex flex-wrap gap-x-5 gap-y-1">
        <legend className="mb-1 text-xs font-semibold">Model markers</legend>
        {models.map(run => <label key={run.modelVersionId} className="flex min-h-10 cursor-pointer items-center gap-2 text-sm">
          <input type="checkbox" checked={!hidden.includes(run.modelVersionId)}
            onChange={() => setHidden(values => values.includes(run.modelVersionId) ? values.filter(id => id !== run.modelVersionId) : [...values, run.modelVersionId])} />
          {run.title}<span className="font-mono text-xs text-muted-foreground">{allEvents.filter(event => event.model_id === run.modelVersionId && first && last && event.time >= first.time && event.time <= last.time).length} in range</span>
        </label>)}
      </fieldset>
      <p className="mb-3 text-xs leading-relaxed text-muted-foreground">B = buy / increase · S = sell / decrease. Tap a marker for its model and reason. Markers use historical ledger dates and do not establish live fills.</p>
      {excludedModels.length > 0 && <p role="status" className="mb-3 rounded-lg border border-amber-500/30 p-3 text-sm">Model markers unavailable for {excludedModels.map(run => run.title).join(', ')}: price publication does not bind the current formal run. Price history remains readable.</p>}
      <SecurityHistoryChart bars={bars} events={visibleEvents} modelName={name} onSelect={setSelected} />
      {activeSelection.length > 0 && <div data-testid="security-selected-event" role="status" className="mt-4 space-y-2 rounded-lg border bg-muted/30 p-3 text-sm">
        {activeSelection.map((event, index) => <p key={index}><strong>{name(event.model_id)} · {event.time} · {event.action}</strong><br />
          Weight {weight(event.previous_weight)} → {weight(event.target_weight)} · {event.reason || 'No reason retained'}</p>)}
      </div>}
      {outsideCoverage > 0 && <p className="mt-3 text-xs text-muted-foreground">{outsideCoverage} historical events have no matching price bar and are not plotted. They remain available in the complete ledger below.</p>}
    </section>
    <section className="rounded-xl border bg-card p-4 sm:p-6" aria-label="Historical model event ledger">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold">Historical model event ledger</h2>
        <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" checked={completeLedger}
          onChange={event => { setCompleteLedger(event.target.checked); setLimit(100); }} />Show complete ledger</label>
      </div>
      <p className="mb-3 text-xs text-muted-foreground">{completeLedger ? 'Full retained ledger, including events outside price coverage.' : 'Selected chart interval.'} Weight changes describe historical model targets. The chart price is a governed reference, not the event execution price.</p>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-xs">
          <thead><tr className="border-b">{['Ledger date', 'Model', 'Action', 'Previous → target', 'Reason / evidence'].map(label => <th key={label} className="whitespace-nowrap px-2 py-3">{label}</th>)}</tr></thead>
          <tbody>{rows.slice(0, limit).map((event, index) => <tr key={`${event.model_id}:${event.time}:${index}`} className="border-b align-top">
            <td className="whitespace-nowrap px-2 py-3 font-mono">{event.time}</td>
            <td className="whitespace-nowrap px-2 py-3"><Link className="text-primary underline" to={`/strategies/${encodeURIComponent(event.model_id)}`}>{name(event.model_id)}</Link></td>
            <td className="px-2 py-3 font-semibold">{event.action}</td>
            <td className="whitespace-nowrap px-2 py-3 font-mono">{weight(event.previous_weight)} → {weight(event.target_weight)}</td>
            <td className="min-w-56 max-w-sm break-words px-2 py-3">{event.reason || 'No reason retained'}<span className="mt-1 block text-muted-foreground">{event.run_id}</span></td>
          </tr>)}</tbody>
        </table>
      </div>
      {!rows.length && <p className="py-6 text-sm text-muted-foreground">No retained model events for this instrument and selection.</p>}
      {rows.length > limit && <button type="button" className="mt-4 min-h-10 rounded border px-4 text-sm" onClick={() => setLimit(value => value + 100)}>Show more events ({limit} of {rows.length})</button>}
    </section>
    <details className="rounded-xl border p-4 text-xs text-muted-foreground">
      <summary className="cursor-pointer font-medium">Price and event provenance</summary>
      <p className="mt-3 break-all">Published price source SHA-256: {evidence.source_sha256}</p>
      <p className="mt-2 break-all">Provider manifest SHA-256: {evidence.provider_manifest_sha256}</p>
      <p className="mt-2">OHLCV is retained governed provider evidence. Adjustment and execution semantics remain those of the source contracts; price return is not strategy return. Only exact active formal model/run/bundle identities qualify for markers.</p>
    </details>
  </>;
}

export function SecurityDetailPage() {
  const { market, symbol } = useParams();
  const [params] = useSearchParams();
  const workspace = useOutletContext<RunWorkspaceContext>();
  const key = `${market}:${symbol}`;
  const [state, setState] = useState<{ key: string; evidence?: SecurityEvidence; error?: string } | null>(null);
  const [retry, setRetry] = useState(0);
  const current = state?.key === key ? state : null;
  const parent = workspace.runs.find(run => run.modelVersionId === params.get('model'));
  useEffect(() => {
    let active = true;
    if (market !== 'us' && market !== 'cn' || !symbol) return;
    void loadSecurityEvidence(market, symbol).then(evidence => { if (active) setState({ key, evidence }); })
      .catch(error => { if (active) setState({ key, error: error instanceof Error ? error.message : String(error) }); });
    return () => { active = false; };
  }, [key, market, retry, symbol]);
  const valid = market === 'us' || market === 'cn';
  return <div className="mx-auto max-w-[1500px] space-y-5 pb-16">
    <Link to={parent ? `/strategies/${encodeURIComponent(parent.modelVersionId)}` : '/app'} className="inline-flex min-h-10 items-center gap-2 text-sm text-primary"><ArrowLeft className="h-4 w-4" />{parent ? parent.title : 'Overview'}</Link>
    <header><p className="text-xs uppercase tracking-wide text-muted-foreground">{market?.toUpperCase()} · Historical research evidence</p>
      <h1 className="mt-2 text-2xl font-bold">{current?.evidence ? `${current.evidence.name} · ${current.evidence.symbol}` : symbol}</h1>
      <p className="mt-2 text-sm text-muted-foreground">Instrument price history and model buy/sell events.</p></header>
    {!valid || current?.error ? <div className="rounded-xl border p-6" role="alert"><h2 className="font-semibold">Security history unavailable</h2><p className="mt-2 text-sm text-muted-foreground">{current?.error || 'Unsupported market.'}</p>
      {valid && <button type="button" className="mt-4 min-h-10 rounded border px-4" onClick={() => { setState(null); setRetry(value => value + 1); }}>Retry price evidence</button>}</div>
      : current?.evidence ? <History key={`${key}:${current.evidence.source_sha256}`} evidence={current.evidence} runs={workspace.runs} />
        : <p className="flex items-center gap-2 p-6 text-sm"><Loader2 className="h-4 w-4 animate-spin" />Loading verified price history…</p>}
  </div>;
}
