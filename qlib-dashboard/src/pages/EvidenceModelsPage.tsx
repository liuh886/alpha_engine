import { useMemo, useState } from 'react';
import { BarChart3, CheckCircle2, Cpu, GitCompareArrows, ShieldAlert } from 'lucide-react';
import type { ModelData } from '@/lib/data-parser';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  modelKindLabel,
  projectFormalEvidence,
  projectFormalMetric,
} from '@/lib/formal-evidence';

function metric(model: ModelData, aliases: string[], percent = false): { text: string; reason: string } {
  const projected = projectFormalMetric(model, aliases);
  if (projected.value === null) return { text: 'Unavailable', reason: projected.reason };
  return {
    text: percent ? `${(projected.value * 100).toFixed(1)}%` : projected.value.toFixed(2),
    reason: '',
  };
}

export function EvidenceModelsPage({ models }: { models: ModelData[] }) {
  const [selectedIds, setSelectedIds] = useState<string[]>(() => models.slice(0, 2).map((model) => model.id));
  const selected = useMemo(() => models.filter((model) => selectedIds.includes(model.id)), [models, selectedIds]);
  const focus = selected[0] ?? models[0];
  const focusProjection = focus ? projectFormalEvidence(focus) : null;
  const ledger = focusProjection?.trades.slice(-100).reverse() ?? [];

  const toggle = (id: string) => {
    setSelectedIds((current) => current.includes(id)
      ? current.filter((row) => row !== id)
      : [...current.slice(-2), id]);
  };

  if (models.length === 0) {
    return <div className="research-empty-state"><Cpu className="h-8 w-8 text-muted-foreground" /><h1 className="mt-3 text-xl font-semibold">No model evidence is declared</h1><p className="mt-2 text-sm text-muted-foreground">The active bundle does not contain a model index.</p></div>;
  }

  return (
    <div className="research-page space-y-6">
      <header className="research-page-header">
        <div><p className="research-kicker">Evidence / Models</p><h1>Model contracts and observed results</h1><p>Compare accepted evidence using the retained benchmark, cost and evidence boundary. Selecting a model never promotes it.</p></div>
        <Badge variant="outline" className="h-7 gap-1.5"><ShieldAlert className="h-3.5 w-3.5" /> No model is trade ready</Badge>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {models.slice(0, 12).map((model) => {
          const active = selectedIds.includes(model.id);
          const projection = projectFormalEvidence(model);
          const sharpe = metric(model, ['Sharpe Ratio', 'sharpe_ratio', 'sharpe']);
          const annualized = metric(model, ['Annualized Return', 'CAGR', 'annual_return', 'annualized_return'], true);
          return <button key={model.id} type="button" onClick={() => toggle(model.id)} className={`rounded-xl border bg-card p-4 text-left transition-colors ${active ? 'border-primary ring-1 ring-primary/25' : 'hover:border-primary/40'}`}>
            <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="truncate text-sm font-semibold">{model.name || model.tag || model.id}</p><p className="mt-1 font-mono text-[10px] text-muted-foreground">{model.id}</p></div>{active && <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />}</div>
            <div className="mt-4 grid grid-cols-2 gap-2 text-xs"><div><span className="text-muted-foreground">Sharpe</span><p className="mt-0.5 font-mono font-semibold" title={sharpe.reason}>{sharpe.text}</p></div><div><span className="text-muted-foreground">Ann. return</span><p className="mt-0.5 font-mono font-semibold" title={annualized.reason}>{annualized.text}</p></div></div>
            <div className="mt-3 flex flex-wrap gap-1.5"><Badge variant="outline" className="text-[9px] uppercase">{model.market || 'unknown'}</Badge><Badge variant="secondary" className="text-[9px]">{modelKindLabel(projection.modelKind)}</Badge></div>
          </button>;
        })}
      </section>

      <Card className="research-surface overflow-hidden">
        <CardHeader className="flex flex-row items-center justify-between"><CardTitle className="flex items-center gap-2 text-sm"><GitCompareArrows className="h-4 w-4 text-primary" /> Formal evidence comparison</CardTitle><span className="text-xs text-muted-foreground">Select up to three records above</span></CardHeader>
        <CardContent className="p-0"><div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Metric</TableHead>{selected.map((model) => <TableHead key={model.id}>{model.name || model.id}</TableHead>)}</TableRow></TableHeader><TableBody>
          {[
            ['Total return', ['Total Return', 'total_return'], true],
            ['Annualized return', ['Annualized Return', 'CAGR', 'annual_return', 'annualized_return'], true],
            ['Benchmark return', ['Benchmark Return', 'benchmark_return'], true],
            ['Excess return', ['Compounded Relative Excess Return', 'Excess Return', 'excess_return'], true],
            ['Sharpe ratio', ['Sharpe Ratio', 'sharpe_ratio', 'sharpe'], false],
            ['Max drawdown', ['Max Drawdown', 'max_drawdown', 'mdd'], true],
            ['IC', ['IC', 'ic'], false],
            ['Rank IC', ['Rank IC', 'rank_ic', 'ric'], false],
            ['ICIR', ['ICIR', 'ic_ir'], false],
          ].map(([label, aliases, percent]) => <TableRow key={String(label)}><TableCell className="font-medium">{String(label)}</TableCell>{selected.map((model) => {
            const value = metric(model, aliases as string[], Boolean(percent));
            return <TableCell key={model.id} className="font-mono" title={value.reason}>{value.text}</TableCell>;
          })}</TableRow>)}
          <TableRow><TableCell className="font-medium">Declared costs</TableCell>{selected.map((model) => {
            const projection = projectFormalEvidence(model);
            return <TableCell key={model.id} className="font-mono" title={projection.costAvailability}>{projection.costBps === null ? 'Unavailable' : `${projection.costBps} bps`}</TableCell>;
          })}</TableRow>
        </TableBody></Table></div></CardContent>
      </Card>

      <Card className="research-surface overflow-hidden">
        <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><BarChart3 className="h-4 w-4 text-primary" /> Formal transaction evidence · {focus?.name || focus?.id}</CardTitle><p className="text-xs text-muted-foreground">This view reads the same retained formal transaction ledger used by Backtests. It does not infer trades from positions.</p></CardHeader>
        <CardContent className="p-0">
          {ledger.length === 0 ? <div className="border-t p-6 text-sm text-muted-foreground">{focusProjection?.tradeAvailability || 'Formal transaction evidence is unavailable.'}</div> : <div className="max-h-[420px] overflow-auto"><Table><TableHeader className="sticky top-0 bg-card"><TableRow><TableHead>Date</TableHead><TableHead>Instrument</TableHead><TableHead>Action</TableHead><TableHead>Target</TableHead><TableHead>Reason / window</TableHead></TableRow></TableHeader><TableBody>{ledger.map((row, index) => <TableRow key={`${row.instrument}-${row.date}-${index}`}><TableCell className="font-mono text-xs">{row.date}</TableCell><TableCell>{row.instrument}</TableCell><TableCell>{row.action}</TableCell><TableCell className="font-mono">{typeof row.target_weight === 'number' ? `${(row.target_weight * 100).toFixed(1)}%` : 'Unavailable'}</TableCell><TableCell className="max-w-[280px] truncate text-xs text-muted-foreground" title={String(row.reason ?? row.window ?? '')}>{String(row.reason ?? row.window ?? '—')}</TableCell></TableRow>)}</TableBody></Table></div>}
        </CardContent>
      </Card>
    </div>
  );
}
