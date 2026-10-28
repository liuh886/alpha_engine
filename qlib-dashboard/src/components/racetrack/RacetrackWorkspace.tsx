import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, BarChart3, RefreshCw } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { ProjectionClient, displayWindow, leaderboardForWindow, windowReturn, type RaceMarket, type RaceProjection, type RaceWindow } from '@/lib/racetrack-projection';
import { RunnerDetail, percent } from './RunnerDetail';

const Chart = lazy(() => import('./RacetrackChart').then(m => ({ default: m.RacetrackChart })));
const WINDOWS: { value: RaceWindow; label: string }[] = [{ value: 1, label: '1M' }, { value: 3, label: '3M' }, { value: 6, label: '6M' }, { value: 12, label: '1Y' }];

export function RacetrackWorkspace() {
  const [params, setParams] = useSearchParams();
  const market: RaceMarket = params.get('raceMarket') === 'cn' ? 'cn' : 'us';
  const requestedWindow = Number(params.get('raceWindow'));
  const window = (WINDOWS.some(item => item.value === requestedWindow) ? requestedWindow : 3) as RaceWindow;
  const [attempt, setAttempt] = useState(0);
  const selected = params.get('raceRunner');
  const detailOpen = params.get('raceDetail') === '1';
  const updateParams = useCallback((values: Record<string, string | null>) => setParams(previous => {
    const updated = new URLSearchParams(previous);
    for (const [key, value] of Object.entries(values)) {
      if (value === null) updated.delete(key);
      else updated.set(key, value);
    }
    return updated;
  }), [setParams]);
  const [result, setResult] = useState<{ market: RaceMarket; projection?: RaceProjection; error?: string } | null>(null);
  const [client] = useState(() => new ProjectionClient());
  const table = useRef<HTMLTableElement>(null);
  useEffect(() => {
    const controller = new AbortController(); setResult(null);
    if (!['localhost', '127.0.0.1', '[::1]'].includes(globalThis.location.hostname)) {
      setResult({ market, error: 'Open this Dashboard on localhost to read local research projections. Hosted Console pages do not publish this evidence.' });
      return () => controller.abort();
    }
    void client.load(market, controller.signal).then(
      projection => { if (!controller.signal.aborted) setResult({ market, projection }); },
      error => { if (!controller.signal.aborted) setResult({ market, error: error instanceof Error ? error.message : 'Projection unavailable.' }); },
    );
    return () => controller.abort();
  }, [market, attempt, client]);
  useEffect(() => () => client.clear(), [client]);
  const current = result?.market === market ? result : null;
  const projection = current?.projection;
  const phase = projection?.scoreboard.first_season;
  const display = useMemo(() => projection ? displayWindow(projection.scoreboard, window) : null, [projection, window]);
  const rows = useMemo(() => projection ? leaderboardForWindow(projection.scoreboard, window) : [], [projection, window]);
  const points = (value: number) => phase ? value.toFixed(2) : String(value);
  const hover = useCallback((id: string | null) => {
    table.current?.querySelectorAll<HTMLElement>('[data-runner]').forEach(row => {
      row.dataset.hover = row.dataset.runner === id ? 'true' : 'false';
    });
  }, []);
  const select = useCallback((id: string) => updateParams({ raceRunner: id, raceDetail: '1' }), [updateParams]);
  const entry = projection?.scoreboard.entries.find(row => row.runner_id === selected);

  return <section aria-label="Racetrack research" className="space-y-4">
    <div className="flex flex-wrap items-end justify-between gap-4 rounded-xl border bg-card px-5 py-4">
      <div><p className="text-[10px] font-semibold uppercase tracking-[.22em] text-muted-foreground">Racetrack · research only</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">{phase ? 'The first season.' : 'The long race.'}</h2>
        <p className="mt-2 text-sm text-muted-foreground">Compare published NAV, consistency and risk. Keep the thesis in view.</p>
        {projection && <p className="mt-2 max-w-3xl break-words text-[11px] text-muted-foreground">Qualification: {projection.manifest.data_qualification.replace(/_/g, ' ')}.</p>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-muted-foreground">Market
          <select aria-label="Racetrack market" value={market} onChange={e => updateParams({ raceMarket: e.target.value, raceRunner: null, raceDetail: null })} className="min-h-10 rounded-md border bg-background px-3 text-sm text-foreground">
            <option value="us">US · US87 / QQQ</option><option value="cn">CN · CN130 / CSI 300</option>
          </select>
        </label>
        <button className="flex min-h-10 items-center gap-2 rounded-md border px-3 text-xs disabled:opacity-50" disabled={!current} onClick={() => setAttempt(n => n + 1)}><RefreshCw className="h-3.5 w-3.5" />{current?.error ? 'Retry projection' : 'Refresh projection'}</button>
      </div>
    </div>
    {!current && <div role="status" className="rounded-xl border bg-card p-10 text-center text-sm text-muted-foreground">Reading and verifying the local projection…</div>}
    {current?.error && <div className="rounded-xl border bg-card p-8"><h3 className="font-semibold">Research projection unavailable</h3><p role="alert" className="mt-3 max-w-2xl text-sm text-muted-foreground">{current.error}</p><p className="mt-3 text-xs text-muted-foreground">The four-strategy monitor remains independent. Reading this view never trains, replays or downloads market data.</p></div>}
    {projection && display && <>
      <div className="grid gap-3 sm:grid-cols-3">
        <Fact label="Evidence through" value={projection.manifest.as_of_session} note={`Publication cutoff ${projection.manifest.as_of_cutoff}`} />
        <Fact label="Published competitors" value={String(projection.manifest.runner_count)} note={phase ? 'Pool index also races · QQQ is reference only' : projection.scoreboard.status === 'diagnostic_baseline_only' ? 'Baseline only · no runners admitted' : 'Ranked by published cumulative points'} />
        <Fact label="Season · provisional" value={projection.manifest.season_id.replace(/^season_/, '')} note={`${(projection.manifest.engine_config.friction_rate * 10000).toFixed(1)} bps friction · ${phase ? 'current month not reviewed' : 'partial months included'}`} />
      </div>
      {phase && <aside aria-label="First season rules" className="space-y-2 rounded-xl border bg-card px-5 py-4 text-xs leading-relaxed text-muted-foreground">
        <p className="font-medium text-foreground">Monthly return-points · +3.2% = 3.2 points; -1.5% = -1.5 points. The pool index earns them too.</p>
        <p>Totals sum monthly points arithmetically; they are not compounded NAV returns. Window ranks award no extra points. Calendar completeness is not settlement: every month remains provisional and not reviewed.</p>
        <p>Daily Brief explains the four formal strategies. This Racetrack compares separately admitted research runners; its window Top 10 does not replace the Brief.</p>
      </aside>}
      {!!phase?.source_gaps.length && <aside aria-label="Research data limitations" className="rounded-xl border border-amber-500/40 bg-amber-500/5 px-5 py-4 text-xs leading-relaxed">
        <p className="font-medium">Unresolved price / lifecycle gaps: {phase.source_gaps.slice(0, 8).map(gap => `${gap.symbol} (${gap.missing_sessions} ${gap.missing_sessions === 1 ? 'session' : 'sessions'})`).join(', ')}{phase.source_gaps.length > 8 ? ` and ${phase.source_gaps.length - 8} more` : ''}.</p>
        <p className="mt-1 text-muted-foreground">The replay retains the declared last-known valuation and rebalance cash-slot policy. Missing observations are not freshly tradable prices or certified halts. No candidate is silently dropped.</p>
      </aside>}
      <div className="rounded-xl border bg-card p-4 sm:p-5">
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3"><h3 className="flex items-center gap-2 font-semibold"><BarChart3 className="h-4 w-4 text-indigo-500" />NAV comparison</h3>
          <div className="flex gap-1 rounded-lg bg-muted p-1" aria-label="Chart window">{WINDOWS.map(w => <button key={w.value} aria-pressed={window === w.value} onClick={() => updateParams({ raceWindow: String(w.value) })} className={`min-h-9 rounded-md px-3 text-xs ${window === w.value ? 'bg-background font-semibold shadow-sm' : 'text-muted-foreground'}`}>{w.label}</button>)}</div>
        </header>
        <Suspense fallback={<div className="h-[370px] animate-pulse rounded-lg bg-muted" role="status">Loading chart…</div>}><Chart data={display} selected={selected} onSelect={select} onHover={hover} /></Suspense>
        <p className="mt-4 border-t pt-3 text-[11px] leading-relaxed text-muted-foreground">{phase ? 'Published trailing returns use the prior-close anchor and actual event friction. A short-history selection shows available benchmark history, without a window rank.' : 'Chart rebasing is for display only; published returns include inception costs and may differ from the rebased curve. Windows include partial calendar months.'} The x-axis uses trading sessions; weekends and exchange holidays are omitted. Gaps remain gaps. Points are provisional until complete-window review.</p>
      </div>
      <div className="grid min-w-0 gap-4">
        <section className="min-w-0 overflow-hidden rounded-xl border bg-card" aria-label="Published Top 10">
          <header className="border-b px-5 py-4"><h3 className="font-semibold">Published Top 10</h3><p className="mt-1 text-xs text-muted-foreground">{phase ? `Published ${WINDOWS.find(w => w.value === window)?.label} net-return ranks. Short-history entries remain unranked; the browser does not calculate ranks or points.` : 'Cumulative ranking from this vintage. Changing the chart window does not re-rank runners.'}</p></header>
          {!projection.scoreboard.entries.length ? <p className="px-5 py-10 text-sm text-muted-foreground">No registered runners. These benchmark curves are a diagnostic baseline, not a race or a strategy recommendation.</p> : <div className="overflow-x-auto"><table ref={table} className="w-full text-left text-xs tabular-nums">
            <thead className="bg-muted/30 text-muted-foreground"><tr><th className="px-4 py-3">Rank</th><th className="px-3">Runner</th><th className="px-3">Season pts</th><th className="px-3">{phase ? 'Sum of monthly pts' : 'Total pts'}</th><th className="px-3">{WINDOWS.find(w => w.value === window)?.label} return</th><th className="whitespace-nowrap px-4">Full-history drawdown</th></tr></thead>
            <tbody>{rows.map(({ entry: row, rank }) => <tr key={row.runner_id} data-runner={row.runner_id} className={`border-t data-[hover=true]:bg-indigo-500/10 ${selected === row.runner_id ? 'bg-indigo-500/10' : ''}`}>
              <td className="px-4 py-3 font-medium text-muted-foreground">{rank === null ? '—' : rank.toString().padStart(2, '0')}</td>
              <td className="px-3"><button aria-label={row.runner_id} aria-pressed={selected === row.runner_id} onClick={() => select(row.runner_id)} className="flex min-h-10 items-center gap-2 text-left font-medium focus-visible:ring-2"><span className="max-w-56 break-all">{phase?.pool_runner_id === row.runner_id ? 'US87 EW Pool Index' : row.runner_id}</span><ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /></button><p className="pb-2 text-[10px] text-muted-foreground">v{row.runner_version}{phase?.pool_runner_id === row.runner_id ? ' · Internal benchmark, also racing' : ''}{rank === null ? ' · Short history · not ranked' : ''}</p></td>
              <td className="px-3">{points(row.season_points)}</td><td className="px-3 font-semibold">{points(row.cumulative_points)}</td>
              <td className="whitespace-nowrap px-3">{windowReturn(row, window) === null ? 'Insufficient history' : percent(windowReturn(row, window))}</td>
              <td className="px-4">{percent(row.max_drawdown)}</td>
            </tr>)}</tbody>
          </table></div>}
        </section>
        {entry && detailOpen && <RunnerDetail projection={projection} entry={entry} client={client} onClose={() => updateParams({ raceDetail: null })} />}
      </div>
      <footer className="space-y-2 rounded-xl border bg-muted/20 px-5 py-4 text-[11px] leading-relaxed text-muted-foreground">
        <p className="break-all">Vintage {projection.manifest.release_id} · recorded timestamp {projection.manifest.generated_at_utc} · {projection.manifest.pool_id}</p>
        <p>Qualification: {projection.manifest.data_qualification}. Source availability is not full historical PIT certification. These are precomputed research projections, not live prices, account positions or trading instructions. Past NAV does not predict future NAV.</p>
        <p><a href="https://www.tradingview.com/" target="_blank" rel="noreferrer" className="underline">TradingView Lightweight Charts™</a> · Copyright (с) 2025 TradingView, Inc. · <a href="./licenses/racetrack-charts.txt" target="_blank" rel="noreferrer" className="underline">Licences</a></p>
      </footer>
    </>}
  </section>;
}

function Fact({ label, value, note }: { label: string; value: string; note: string }) {
  return <div className="min-w-0 rounded-xl border bg-card px-5 py-4"><p className="text-[10px] uppercase tracking-[.16em] text-muted-foreground">{label}</p><p className="mt-2 break-all text-xl font-semibold tabular-nums">{value}</p><p className="mt-2 text-[11px] text-muted-foreground">{note}</p></div>;
}
