import { useMemo, useState } from 'react';
import { BarChart3, CheckCircle2, Cpu, GitCompareArrows, ShieldAlert } from 'lucide-react';
import type { ModelData } from '@/lib/data-parser';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { extractSignalExecutionRows, numericMetric } from '@/lib/artifact-data';

function metric(model: ModelData, aliases: string[], percent = false): string {
  const value = numericMetric(model, aliases);
  if (value === null) return 'N/A';
  return percent ? `${(value * 100).toFixed(1)}%` : value.toFixed(2);
}

export function EvidenceModelsPage({ models }: { models: ModelData[] }) {
  const [selectedIds, setSelectedIds] = useState<string[]>(() => models.slice(0, 2).map((model) => model.id));
  const selected = useMemo(() => models.filter((model) => selectedIds.includes(model.id)), [models, selectedIds]);
  const focus = selected[0] ?? models[0];
  const ledger = focus ? extractSignalExecutionRows(focus).slice(-100).reverse() : [];

  const toggle = (id: string) => {
    setSelectedIds((current) => current.includes(id) ? current.filter((row) => row !== id) : [...current.slice(-2), id]);
  };

  if (models.length === 0) {
    return <div className="research-empty-state"><Cpu className="h-8 w-8 text-muted-foreground" /><h1 className="mt-3 text-xl font-semibold">No model evidence is declared</h1><p className="mt-2 text-sm text-muted-foreground">The active bundle does not contain a model index.</p></div>;
  }

  return (
    <div className="research-page space-y-6">
      <header className="research-page-header">
        <div><p className="research-kicker">Evidence / Models</p><h1>Model contracts and observed results</h1><p>Compare candidates using the same benchmark, cost and evidence boundary. Selecting a model never promotes it.</p></div>
        <Badge variant="outline" className="h-7 gap-1.5"><ShieldAlert className="h-3.5 w-3.5" /> No model is trade ready</Badge>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {models.slice(0, 12).map((model) => {
          const active = selectedIds.includes(model.id);
          return <button key={model.id} type="button" onClick={() => toggle(model.id)} className={`rounded-xl border bg-card p-4 text-left transition-colors ${active ? 'border-primary ring-1 ring-primary/25' : 'hover:border-primary/40'}`}>
            <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="truncate text-sm font-semibold">{model.name || model.tag || model.id}</p><p className="mt-1 font-mono text-[10px] text-muted-foreground">{model.id}</p></div>{active && <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />}</div>
            <div className="mt-4 grid grid-cols-2 gap-2 text-xs"><div><span className="text-muted-foreground">Sharpe</span><p className="mt-0.5 font-mono font-semibold">{metric(model, ['Sharpe Ratio', 'sharpe_ratio', 'sharpe'])}</p></div><div><span className="text-muted-foreground">Ann. return</span><p className="mt-0.5 font-mono font-semibold">{metric(model, ['Annualized Return', 'annual_return', 'annualized_return'], true)}</p></div></div>
            <div className="mt-3 flex gap-1.5"><Badge variant="outline" className="text-[9px] uppercase">{model.market || 'unknown'}</Badge><Badge variant="secondary" className="text-[9px] uppercase">{model.stage || 'candidate'}</Badge></div>
          </button>;
        })}
      </section>

      <Card className="research-surface overflow-hidden">
        <CardHeader className="flex flex-row items-center justify-between"><CardTitle className="flex items-center gap-2 text-sm"><GitCompareArrows className="h-4 w-4 text-primary" /> Candidate comparison</CardTitle><span className="text-xs text-muted-foreground">Select up to three records above</span></CardHeader>
        <CardContent className="p-0"><div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Metric</TableHead>{selected.map((model) => <TableHead key={model.id}>{model.name || model.id}</TableHead>)}</TableRow></TableHeader><TableBody>
          {[
            ['Total return', ['Total Return', 'total_return'], true],
            ['Annualized return', ['Annualized Return', 'annual_return', 'annualized_return'], true],
            ['Benchmark return', ['Benchmark Return', 'benchmark_return'], true],
            ['Excess return', ['Excess Return', 'excess_return'], true],
            ['Sharpe ratio', ['Sharpe Ratio', 'sharpe_ratio', 'sharpe'], false],
            ['Max drawdown', ['Max Drawdown', 'max_drawdown', 'mdd'], true],
            ['IC', ['IC', 'ic'], false],
            ['Rank IC', ['Rank IC', 'rank_ic', 'ric'], false],
            ['ICIR', ['ICIR', 'ic_ir'], false],
          ].map(([label, aliases, percent]) => <TableRow key={String(label)}><TableCell className="font-medium">{String(label)}</TableCell>{selected.map((model) => <TableCell key={model.id} className="font-mono">{metric(model, aliases as string[], Boolean(percent))}</TableCell>)}</TableRow>)}
        </TableBody></Table></div></CardContent>
      </Card>

      <Card className="research-surface overflow-hidden">
        <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><BarChart3 className="h-4 w-4 text-primary" /> Signal and execution evidence · {focus?.name || focus?.id}</CardTitle><p className="text-xs text-muted-foreground">Signals are derived at a declared close. Executions occur on a separate date, typically the next market open.</p></CardHeader>
        <CardContent className="p-0">
          {ledger.length === 0 ? <div className="border-t p-6 text-sm text-muted-foreground">This model index does not export a signal/execution ledger. The view does not infer dates from returns or positions.</div> : <div className="max-h-[420px] overflow-auto"><Table><TableHeader className="sticky top-0 bg-card"><TableRow><TableHead>Symbol</TableHead><TableHead>Signal date</TableHead><TableHead>Execution date</TableHead><TableHead>Action</TableHead><TableHead>Weight</TableHead></TableRow></TableHeader><TableBody>{ledger.map((row, index) => <TableRow key={`${row.symbol}-${row.executionDate}-${index}`}><TableCell>{row.symbol}</TableCell><TableCell className="font-mono text-xs text-blue-700 dark:text-blue-300">{row.signalDate}</TableCell><TableCell className="font-mono text-xs text-emerald-700 dark:text-emerald-300">{row.executionDate}</TableCell><TableCell>{row.action}</TableCell><TableCell className="font-mono">{row.weight === undefined ? 'N/A' : `${(row.weight * 100).toFixed(1)}%`}</TableCell></TableRow>)}</TableBody></Table></div>}
        </CardContent>
      </Card>
    </div>
  );
}
