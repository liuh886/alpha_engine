import { useEffect, useMemo, useState } from 'react';
import { BarChart3, Braces, Database, ShieldQuestion } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { ModelData } from '@/lib/data-parser';
import {
  loadFactorDiagnostics,
  loadMarketEvidenceCatalog,
  type FactorDiagnosticsEvidence,
  type FactorDistributionRow,
  type MarketEvidenceMarket,
} from '@/lib/market-evidence';
import { cn } from '@/lib/utils';

interface ImportanceRow {
  name: string;
  models: number;
  meanImportance: number;
  maxImportance: number;
}

function formatNumber(value: number | undefined, digits = 4): string {
  return value === undefined || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function missingRate(row: FactorDistributionRow): number | null {
  const total = row.sample_count + row.missing_count;
  return total > 0 ? row.missing_count / total : null;
}

export function EvidenceFactorsPage({ models }: { models: ModelData[] }) {
  const [market, setMarket] = useState<MarketEvidenceMarket>('us');
  const [diagnostics, setDiagnostics] = useState<Partial<Record<MarketEvidenceMarket, FactorDiagnosticsEvidence>>>({});
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);
  const [selectedFactorId, setSelectedFactorId] = useState('');

  const importanceRows = useMemo<ImportanceRow[]>(() => {
    const values = new Map<string, number[]>();
    for (const model of models) {
      const importance = model.backtest?.featureImportance ?? {};
      for (const [name, raw] of Object.entries(importance)) {
        const value = Number(raw);
        if (!Number.isFinite(value)) continue;
        values.set(name, [...(values.get(name) ?? []), value]);
      }
    }
    return Array.from(values.entries()).map(([name, rows]) => ({
      name,
      models: rows.length,
      meanImportance: rows.reduce((sum, value) => sum + value, 0) / rows.length,
      maxImportance: Math.max(...rows),
    })).sort((left, right) => right.meanImportance - left.meanImportance);
  }, [models]);

  useEffect(() => {
    let active = true;
    setDiagnosticsError(null);
    Promise.allSettled((['us', 'cn'] as MarketEvidenceMarket[]).map(async (marketId) => {
      const catalog = await loadMarketEvidenceCatalog(marketId);
      return [marketId, await loadFactorDiagnostics(catalog)] as const;
    })).then((results) => {
      if (!active) return;
      const next: Partial<Record<MarketEvidenceMarket, FactorDiagnosticsEvidence>> = {};
      const failures: string[] = [];
      results.forEach((result, index) => {
        const marketId = (['us', 'cn'] as MarketEvidenceMarket[])[index];
        if (result.status === 'fulfilled') next[marketId] = result.value[1];
        else failures.push(`${marketId.toUpperCase()}: ${result.reason instanceof Error ? result.reason.message : String(result.reason)}`);
      });
      setDiagnostics(next);
      if (Object.keys(next).length === 0) setDiagnosticsError(failures.join(' · ') || 'Historical factor diagnostics are not published yet.');
    });
    return () => { active = false; };
  }, []);

  const marketDiagnostics = diagnostics[market];
  const availableFactors = useMemo(() => {
    return [...(marketDiagnostics?.factors ?? [])].sort((left, right) => left.information_family.localeCompare(right.information_family) || left.display_name.localeCompare(right.display_name));
  }, [marketDiagnostics]);

  useEffect(() => {
    if (!availableFactors.length) {
      setSelectedFactorId('');
      return;
    }
    if (!availableFactors.some((row) => row.factor_id === selectedFactorId)) setSelectedFactorId(availableFactors[0].factor_id);
  }, [availableFactors, selectedFactorId]);

  const selected = availableFactors.find((row) => row.factor_id === selectedFactorId) ?? null;
  const histogram = selected?.histogram?.map((bin) => ({
    label: `${bin.lower.toPrecision(3)}…${bin.upper.toPrecision(3)}`,
    midpoint: (bin.lower + bin.upper) / 2,
    count: bin.count,
  })) ?? [];
  const selectedMissingRate = selected ? missingRate(selected) : null;

  return (
    <div className="research-page space-y-6">
      <header className="research-page-header">
        <div>
          <p className="research-kicker">Evidence / Factors</p>
          <h1>Factor diagnostics and model explainability</h1>
          <p>Separate the statistical behavior of a canonical factor from model-specific importance and current-signal contribution. None of these is presented as causal evidence.</p>
        </div>
        <Badge variant="outline" className="h-7 gap-1.5"><ShieldQuestion className="h-3.5 w-3.5" /> Research evidence only</Badge>
      </header>

      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Historical factor distribution</h2>
            <p className="text-sm text-muted-foreground">Computed by the backend from the governed selected-pool provider and canonical factor implementation.</p>
          </div>
          <div className="flex rounded-lg border p-1">
            {(['us', 'cn'] as MarketEvidenceMarket[]).map((marketId) => (
              <button
                key={marketId}
                type="button"
                onClick={() => setMarket(marketId)}
                className={cn('rounded-md px-3 py-1.5 text-xs font-semibold uppercase', market === marketId ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted')}
              >{marketId}</button>
            ))}
          </div>
        </div>

        {diagnosticsError && !marketDiagnostics ? (
          <Card className="research-surface"><CardContent className="flex min-h-44 flex-col items-center justify-center text-center"><Database className="h-8 w-8 text-muted-foreground" /><h3 className="mt-3 font-semibold">Historical distribution evidence is not published yet</h3><p className="mt-2 max-w-2xl text-sm text-muted-foreground">The frontend does not estimate factor distributions from model importance or fetch raw market data directly. The next governed Market Evidence publication will populate this section.</p><p className="mt-2 font-mono text-[10px] text-muted-foreground">{diagnosticsError}</p></CardContent></Card>
        ) : marketDiagnostics && selected ? (
          <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
            <Card className="research-surface">
              <CardHeader className="pb-3"><CardTitle className="text-sm">Canonical factors · {market.toUpperCase()}</CardTitle></CardHeader>
              <CardContent className="p-0">
                <div className="max-h-[620px] overflow-y-auto">
                  {availableFactors.map((factor) => (
                    <button
                      key={factor.factor_id}
                      type="button"
                      onClick={() => setSelectedFactorId(factor.factor_id)}
                      className={cn('w-full border-t px-4 py-3 text-left first:border-t-0 hover:bg-muted/60', factor.factor_id === selected.factor_id && 'bg-muted')}
                    >
                      <span className="block truncate text-xs font-semibold">{factor.display_name}</span>
                      <span className="mt-0.5 block truncate font-mono text-[10px] text-muted-foreground">{factor.factor_id}</span>
                      <span className="mt-1 block text-[10px] text-muted-foreground">{factor.information_family}</span>
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card className="research-surface">
                <CardHeader className="border-b pb-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div><CardTitle className="text-base">{selected.display_name}</CardTitle><p className="mt-1 font-mono text-[10px] text-muted-foreground">{selected.factor_id}</p></div>
                    <div className="text-right text-[10px] text-muted-foreground"><div>{marketDiagnostics.pool_id}</div><div>{marketDiagnostics.start} → {marketDiagnostics.cutoff}</div></div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-5 pt-4">
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                    <div className="rounded-md border p-3"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Samples</div><div className="mt-1 font-mono text-lg">{selected.sample_count.toLocaleString()}</div></div>
                    <div className="rounded-md border p-3"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Missing</div><div className="mt-1 font-mono text-lg">{selectedMissingRate === null ? '—' : `${(selectedMissingRate * 100).toFixed(2)}%`}</div></div>
                    <div className="rounded-md border p-3"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Mean</div><div className="mt-1 font-mono text-lg">{formatNumber(selected.mean)}</div></div>
                    <div className="rounded-md border p-3"><div className="text-[10px] uppercase tracking-wide text-muted-foreground">Std</div><div className="mt-1 font-mono text-lg">{formatNumber(selected.std)}</div></div>
                  </div>

                  <div className="h-[300px]">
                    {histogram.length ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={histogram} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
                          <CartesianGrid vertical={false} strokeOpacity={0.12} />
                          <XAxis dataKey="midpoint" tickFormatter={(value) => Number(value).toPrecision(2)} minTickGap={24} tick={{ fontSize: 10 }} />
                          <YAxis tick={{ fontSize: 10 }} width={48} />
                          <Tooltip formatter={(value) => [Number(value).toLocaleString(), 'Observations']} labelFormatter={(value) => `Factor value ${Number(value).toPrecision(5)}`} />
                          <Bar dataKey="count" fill="hsl(var(--primary))" radius={[2, 2, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Distribution is unavailable for this factor.</div>}
                  </div>

                  <div className="grid grid-cols-3 gap-2 text-center sm:grid-cols-7">
                    {[
                      ['1%', selected.q01], ['5%', selected.q05], ['25%', selected.q25], ['Median', selected.median], ['75%', selected.q75], ['95%', selected.q95], ['99%', selected.q99],
                    ].map(([label, value]) => (
                      <div key={String(label)} className="rounded-md border px-2 py-2"><div className="text-[9px] uppercase text-muted-foreground">{label}</div><div className="mt-1 font-mono text-xs">{formatNumber(value as number | undefined, 3)}</div></div>
                    ))}
                  </div>

                  <div className="rounded-md bg-muted/40 p-3 text-xs leading-relaxed text-muted-foreground">
                    Histogram display is clipped to the 1st–99th percentile to keep the main distribution readable. Tail observations are retained in the summary: {selected.below_histogram_clip ?? 0} below and {selected.above_histogram_clip ?? 0} above the displayed range. This is descriptive distribution evidence, not IC or feature importance.
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        ) : null}
      </section>

      <section className="space-y-4 border-t pt-6">
        <div><h2 className="text-lg font-semibold">Model-specific feature importance</h2><p className="text-sm text-muted-foreground">A separate diagnostic layer. Importance magnitude cannot be compared directly with factor distribution, IC or causal effect.</p></div>
        <div className="grid gap-4 md:grid-cols-3">
          <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Models inspected</p><p className="mt-2 font-mono text-2xl font-semibold">{models.length}</p></CardContent></Card>
          <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Exported features</p><p className="mt-2 font-mono text-2xl font-semibold">{importanceRows.length}</p></CardContent></Card>
          <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Evidence type</p><p className="mt-2 text-lg font-semibold">Model importance</p></CardContent></Card>
        </div>

        {importanceRows.length === 0 ? (
          <Card className="research-surface"><CardContent className="flex min-h-56 flex-col items-center justify-center text-center"><Braces className="h-8 w-8 text-muted-foreground" /><h3 className="mt-3 text-lg font-semibold">No feature importance is exported</h3><p className="mt-2 max-w-xl text-sm text-muted-foreground">The active model records do not contain a feature-importance mapping. The frontend does not infer importance from returns.</p></CardContent></Card>
        ) : (
          <div className="grid gap-5 xl:grid-cols-[0.8fr_1.2fr]">
            <Card className="research-surface"><CardHeader><CardTitle className="flex items-center gap-2 text-sm"><BarChart3 className="h-4 w-4 text-primary" /> Leading diagnostic features</CardTitle></CardHeader><CardContent className="space-y-3">{importanceRows.slice(0, 12).map((factor) => <div key={factor.name}><div className="mb-1 flex items-center justify-between gap-3 text-xs"><span className="truncate font-medium">{factor.name}</span><span className="font-mono">{factor.meanImportance.toFixed(4)}</span></div><div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(2, (factor.meanImportance / importanceRows[0].meanImportance) * 100)}%` }} /></div></div>)}</CardContent></Card>
            <Card className="research-surface overflow-hidden"><CardHeader><CardTitle className="text-sm">Feature importance table</CardTitle></CardHeader><CardContent className="p-0"><div className="max-h-[560px] overflow-auto"><Table><TableHeader className="sticky top-0 bg-card"><TableRow><TableHead>Feature</TableHead><TableHead>Models</TableHead><TableHead>Mean importance</TableHead><TableHead>Maximum</TableHead><TableHead>Status</TableHead></TableRow></TableHeader><TableBody>{importanceRows.map((factor) => <TableRow key={factor.name}><TableCell className="font-mono text-xs">{factor.name}</TableCell><TableCell>{factor.models}</TableCell><TableCell className="font-mono">{factor.meanImportance.toFixed(5)}</TableCell><TableCell className="font-mono">{factor.maxImportance.toFixed(5)}</TableCell><TableCell><Badge variant="outline" className="text-[9px]">diagnostic only</Badge></TableCell></TableRow>)}</TableBody></Table></div></CardContent></Card>
          </div>
        )}
      </section>
    </div>
  );
}
