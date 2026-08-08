import { useEffect, useMemo, useState } from 'react';
import { Activity, CandlestickChart, Search, ShieldCheck } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';

import { SecurityEvidenceChart, type SecurityLowerStudy } from '@/components/SecurityEvidenceChart';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  loadMarketEvidenceCatalog,
  loadSecurityMarketEvidence,
  type MarketEvidenceCatalog,
  type MarketEvidenceMarket,
  type SecurityMarketEvidence,
} from '@/lib/market-evidence';
import { cn } from '@/lib/utils';

const MARKETS: Array<{ id: MarketEvidenceMarket; label: string; baseline: string }> = [
  { id: 'us', label: 'US', baseline: 'QQQ' },
  { id: 'cn', label: 'CN', baseline: 'CSI 300' },
];

function shortHash(value: string): string {
  return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : 'unavailable';
}

function formatWeight(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function defaultSymbol(catalog: MarketEvidenceCatalog): string {
  const traded = [...catalog.symbols].sort((left, right) => right.formal_event_count - left.formal_event_count)[0];
  if (traded && traded.formal_event_count > 0) return traded.symbol;
  const benchmark = catalog.symbols.find((row) => row.symbol === catalog.benchmark);
  return benchmark?.symbol ?? catalog.symbols[0]?.symbol ?? '';
}

function validStudy(value: string): SecurityLowerStudy {
  if (value === 'none' || value === 'macd' || value === 'rsi' || value.startsWith('factor:')) return value as SecurityLowerStudy;
  return 'macd';
}

export function SecurityExplorerPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [catalogs, setCatalogs] = useState<Partial<Record<MarketEvidenceMarket, MarketEvidenceCatalog>>>({});
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<SecurityMarketEvidence | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [visibleModelIds, setVisibleModelIds] = useState<Set<string>>(new Set());

  const market: MarketEvidenceMarket = searchParams.get('market') === 'cn' ? 'cn' : 'us';
  const catalog = catalogs[market];
  const requestedSymbol = searchParams.get('symbol')?.toUpperCase() ?? '';
  const showBoll = searchParams.get('boll') === '1';
  const lowerStudy = validStudy(searchParams.get('study') ?? 'macd');

  const updateParams = (changes: Record<string, string | null>, replace = false) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(changes).forEach(([key, value]) => {
      if (value === null) next.delete(key);
      else next.set(key, value);
    });
    setSearchParams(next, { replace });
  };

  useEffect(() => {
    let active = true;
    setCatalogError(null);
    Promise.allSettled(MARKETS.map(async ({ id }) => [id, await loadMarketEvidenceCatalog(id)] as const))
      .then((results) => {
        if (!active) return;
        const next: Partial<Record<MarketEvidenceMarket, MarketEvidenceCatalog>> = {};
        const failures: string[] = [];
        results.forEach((result, index) => {
          const id = MARKETS[index].id;
          if (result.status === 'fulfilled') next[id] = result.value[1];
          else failures.push(`${id.toUpperCase()}: ${result.reason instanceof Error ? result.reason.message : String(result.reason)}`);
        });
        setCatalogs(next);
        if (Object.keys(next).length === 0) setCatalogError(failures.join(' · ') || 'Market evidence is not published yet.');
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!catalog || catalog.symbols.some((row) => row.symbol === requestedSymbol)) return;
    const symbol = defaultSymbol(catalog);
    if (!symbol) return;
    const next = new URLSearchParams(searchParams);
    next.set('market', market);
    next.set('symbol', symbol);
    if (!next.has('study')) next.set('study', 'macd');
    setSearchParams(next, { replace: true });
  }, [catalog, market, requestedSymbol, searchParams, setSearchParams]);

  useEffect(() => {
    if (!catalog || !requestedSymbol || !catalog.symbols.some((row) => row.symbol === requestedSymbol)) return;
    let active = true;
    setEvidence(null);
    setEvidenceError(null);
    loadSecurityMarketEvidence(catalog, requestedSymbol)
      .then((payload) => {
        if (!active) return;
        setEvidence(payload);
        setVisibleModelIds(new Set(payload.formal_model_events.map((event) => event.model_id)));
      })
      .catch((error) => {
        if (active) setEvidenceError(error instanceof Error ? error.message : String(error));
      });
    return () => { active = false; };
  }, [catalog, requestedSymbol]);

  const filteredSymbols = useMemo(() => {
    if (!catalog) return [];
    const needle = query.trim().toUpperCase();
    const rows = needle
      ? catalog.symbols.filter((row) => row.symbol.includes(needle) || row.name.toUpperCase().includes(needle))
      : catalog.symbols;
    return [...rows].sort((left, right) => right.formal_event_count - left.formal_event_count || left.symbol.localeCompare(right.symbol));
  }, [catalog, query]);

  const modelRows = useMemo(() => {
    if (!evidence) return [];
    const rows = new Map<string, { id: string; name: string; count: number }>();
    evidence.formal_model_events.forEach((event) => {
      const row = rows.get(event.model_id) ?? { id: event.model_id, name: event.model_name, count: 0 };
      row.count += 1;
      rows.set(event.model_id, row);
    });
    return [...rows.values()].sort((left, right) => left.name.localeCompare(right.name));
  }, [evidence]);

  const factorIds = evidence ? Object.keys(evidence.factor_series).sort() : [];
  const latest = evidence && evidence.bars.length ? evidence.bars[evidence.bars.length - 1] : undefined;
  const previous = evidence && evidence.bars.length > 1 ? evidence.bars[evidence.bars.length - 2] : undefined;
  const dailyChange = latest && previous ? latest.close / previous.close - 1 : null;

  if (catalogError) {
    return (
      <div className="mx-auto max-w-4xl p-4 md:p-8">
        <Card><CardHeader><CardTitle className="text-base">Security Explorer</CardTitle></CardHeader><CardContent className="space-y-2 text-sm text-muted-foreground"><p>Governed market evidence is not available yet. The chart intentionally stays empty instead of fetching a market provider from the browser.</p><p className="font-mono text-xs">{catalogError}</p></CardContent></Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1600px] space-y-4 p-3 md:p-6">
      <header className="flex flex-col gap-3 border-b pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div><div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground"><CandlestickChart className="h-4 w-4" /> Market Evidence</div><h1 className="text-2xl font-semibold tracking-tight">Security Explorer</h1><p className="mt-1 max-w-3xl text-sm text-muted-foreground">Inspect one security against immutable OHLCV, formal model actions, chart studies and retained canonical factor series.</p></div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground"><ShieldCheck className="h-4 w-4" /> Static evidence · research only</div>
      </header>

      <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="space-y-3">
          <div className="grid grid-cols-2 rounded-lg border p-1">{MARKETS.map((row) => <button key={row.id} type="button" className={cn('rounded-md px-3 py-2 text-xs font-medium transition-colors', market === row.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted')} onClick={() => updateParams({ market: row.id, symbol: catalogs[row.id] ? defaultSymbol(catalogs[row.id]!) : null })}>{row.label}</button>)}</div>
          <div className="relative"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search ticker or name" className="h-9 w-full rounded-md border bg-background pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-ring" aria-label="Search securities" /></div>
          <div className="max-h-[620px] overflow-y-auto rounded-lg border">{filteredSymbols.slice(0, 180).map((row) => <button key={row.symbol} type="button" onClick={() => updateParams({ symbol: row.symbol })} className={cn('flex w-full items-center justify-between gap-3 border-b px-3 py-2.5 text-left last:border-b-0 hover:bg-muted/60', requestedSymbol === row.symbol && 'bg-muted')}><span className="min-w-0"><span className="block font-mono text-xs font-semibold">{row.symbol}</span><span className="block truncate text-[11px] text-muted-foreground">{row.name}</span></span>{row.formal_event_count > 0 && <span className="rounded-full border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{row.formal_event_count}</span>}</button>)}</div>
        </aside>

        <main className="min-w-0 space-y-4">
          {catalog && <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4"><Metric label="Market cutoff" value={catalog.cutoff} /><Metric label="Default baseline" value={market === 'us' ? 'QQQ' : 'CSI 300'} /><Metric label="Pool" value={catalog.pool_id} /><Metric label="Provider evidence" value={shortHash(catalog.provider_manifest_sha256)} /></div>}
          {evidenceError && <Card><CardContent className="p-4 text-sm text-destructive">{evidenceError}</CardContent></Card>}
          {!evidence && !evidenceError && <Card><CardContent className="flex h-[420px] items-center justify-center text-sm text-muted-foreground">Loading governed security evidence…</CardContent></Card>}

          {evidence && <>
            <Card>
              <CardHeader className="space-y-3 border-b pb-3">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div><CardTitle className="flex items-baseline gap-2 text-lg"><span className="font-mono">{evidence.symbol}</span><span className="text-sm font-normal text-muted-foreground">{evidence.name}</span></CardTitle><div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted-foreground"><span>{evidence.start} → {evidence.cutoff}</span>{latest && <span className="font-mono">Close {latest.close.toFixed(2)}</span>}{dailyChange !== null && <span className={cn('font-mono', dailyChange >= 0 ? 'text-green-600' : 'text-red-600')}>{dailyChange >= 0 ? '+' : ''}{(dailyChange * 100).toFixed(2)}%</span>}</div></div>
                  <div className="flex flex-wrap items-center gap-2"><label className="flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs"><input type="checkbox" checked={showBoll} onChange={(event) => updateParams({ boll: event.target.checked ? '1' : null })} />BOLL 20,2</label><select value={lowerStudy} onChange={(event) => updateParams({ study: event.target.value })} className="h-8 rounded-md border bg-background px-2 text-xs" aria-label="Lower chart study"><option value="none">No lower pane</option><option value="macd">MACD 12,26,9</option><option value="rsi">RSI 14</option>{factorIds.map((factorId) => <option key={factorId} value={`factor:${factorId}`}>{factorId}</option>)}</select></div>
                </div>
                {modelRows.length > 0 ? <div className="flex flex-wrap gap-2">{modelRows.map((model) => { const active = visibleModelIds.has(model.id); return <button key={model.id} type="button" onClick={() => setVisibleModelIds((current) => { const next = new Set(current); if (active) next.delete(model.id); else next.add(model.id); return next; })} className={cn('rounded-full border px-2.5 py-1 text-[11px]', active ? 'bg-foreground text-background' : 'text-muted-foreground')}>{model.name} · {model.count}</button>; })}</div> : <div className="text-xs text-muted-foreground">No accepted formal model has a retained trade event for this security yet.</div>}
              </CardHeader>
              <CardContent className="p-0 md:p-2"><SecurityEvidenceChart evidence={evidence} showBoll={showBoll} lowerStudy={lowerStudy} visibleModelIds={visibleModelIds} /></CardContent>
            </Card>

            <div className="grid gap-4 lg:grid-cols-[1.1fr_.9fr]">
              <Card><CardHeader className="pb-3"><CardTitle className="text-sm">Formal model events</CardTitle></CardHeader><CardContent className="overflow-x-auto p-0">{evidence.formal_model_events.length ? <table className="w-full text-xs"><thead className="border-y bg-muted/40 text-left text-[10px] uppercase tracking-wide text-muted-foreground"><tr><th className="px-3 py-2">Date</th><th className="px-3 py-2">Model</th><th className="px-3 py-2">Action</th><th className="px-3 py-2">Weight</th><th className="px-3 py-2">Reason</th></tr></thead><tbody>{[...evidence.formal_model_events].reverse().slice(0, 20).map((event, index) => <tr key={`${event.time}-${event.model_id}-${index}`} className="border-b last:border-b-0"><td className="px-3 py-2 font-mono">{event.time}</td><td className="px-3 py-2">{event.model_name}</td><td className={cn('px-3 py-2 font-semibold', event.action === 'BUY' || event.action === 'INCREASE' ? 'text-green-600' : 'text-red-600')}>{event.action}</td><td className="px-3 py-2 font-mono">{formatWeight(event.previous_weight)} → {formatWeight(event.target_weight)}</td><td className="max-w-[300px] truncate px-3 py-2 text-muted-foreground" title={event.reason}>{event.reason || 'retained formal trade event'}</td></tr>)}</tbody></table> : <div className="p-4 text-sm text-muted-foreground">No formal model events for this security.</div>}</CardContent></Card>
              <Card><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-sm"><Activity className="h-4 w-4" /> Evidence boundary</CardTitle></CardHeader><CardContent className="space-y-2 text-xs text-muted-foreground"><EvidenceLine label="OHLCV SHA" value={shortHash(evidence.source_csv_sha256)} /><EvidenceLine label="Provider manifest" value={shortHash(evidence.provider_manifest_sha256)} /><EvidenceLine label="Canonical factor series" value={factorIds.length ? `${factorIds.length} retained` : 'not materialized for this symbol'} /><p className="pt-2 leading-relaxed">Chart studies are deterministic diagnostics from the same adjusted OHLCV. Canonical factor panes are published only when materialized by the backend; the browser does not recreate model factors.</p></CardContent></Card>
            </div>
          </>}
        </main>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <Card><CardContent className="p-3"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div><div className="mt-1 truncate font-mono text-sm">{value}</div></CardContent></Card>;
}

function EvidenceLine({ label, value }: { label: string; value: string }) {
  return <div className="flex justify-between gap-3"><span>{label}</span><span className="font-mono">{value}</span></div>;
}
