import { ClipboardList, GitBranch, ShieldBan } from 'lucide-react';
import type { ModelData } from '@/lib/data-parser';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { numericMetric } from '@/lib/artifact-data';

function resultSummary(model: ModelData): string {
  const sharpe = numericMetric(model, ['Sharpe Ratio', 'sharpe_ratio', 'sharpe']);
  const excess = numericMetric(model, ['Excess Return', 'excess_return']);
  const parts = [];
  if (sharpe !== null) parts.push(`Sharpe ${sharpe.toFixed(2)}`);
  if (excess !== null) parts.push(`excess ${(excess * 100).toFixed(1)}%`);
  return parts.join(' · ') || 'No headline economics exported';
}

export function EvidenceExperimentsPage({ models }: { models: ModelData[] }) {
  const ordered = [...models].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));

  return (
    <div className="research-page space-y-6">
      <header className="research-page-header">
        <div><p className="research-kicker">Evidence / Experiments</p><h1>Immutable research record</h1><p>Each model artifact is treated as an observed experiment result. Parameters and evidence already seen are not presented as permission for another retrospective search.</p></div>
        <Badge variant="outline" className="h-7 gap-1.5"><ShieldBan className="h-3.5 w-3.5" /> No automatic promotion</Badge>
      </header>

      {ordered.length === 0 ? (
        <div className="research-empty-state"><ClipboardList className="h-8 w-8 text-muted-foreground" /><h1 className="mt-3 text-xl font-semibold">No experiments are indexed</h1><p className="mt-2 text-sm text-muted-foreground">The active bundle does not expose model or experiment records.</p></div>
      ) : (
        <div className="relative space-y-4 before:absolute before:bottom-4 before:left-[18px] before:top-4 before:w-px before:bg-border">
          {ordered.map((model, index) => {
            const params = model.params as Record<string, unknown> | undefined;
            const stopRule = String(params?.stop_rule ?? params?.research_stop_rule ?? 'Use the declared experiment contract; no post-result tuning is authorized.');
            return <div key={model.id} className="relative pl-12"><div className="absolute left-[10px] top-5 flex h-4 w-4 items-center justify-center rounded-full border-2 border-primary bg-background"><div className="h-1.5 w-1.5 rounded-full bg-primary" /></div><Card className="research-surface"><CardContent className="pt-5"><div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-[10px] text-muted-foreground">EXP-{String(ordered.length - index).padStart(3, '0')}</span><Badge variant="outline" className="text-[9px] uppercase">{model.market || 'unknown'}</Badge><Badge variant="secondary" className="text-[9px] uppercase">{model.stage || 'candidate'}</Badge></div><h2 className="mt-2 truncate text-base font-semibold">{model.name || model.tag || model.id}</h2><p className="mt-1 font-mono text-[10px] text-muted-foreground">{model.id} · run {model.run_id || 'not declared'}</p><p className="mt-3 text-sm text-muted-foreground">{model.description || 'No hypothesis narrative was exported with this model artifact.'}</p></div><div className="shrink-0 text-left lg:text-right"><p className="text-sm font-semibold">{resultSummary(model)}</p><p className="mt-1 text-xs text-muted-foreground">{model.created_at ? new Date(model.created_at).toLocaleString() : 'Date not declared'}</p></div></div><div className="mt-4 grid gap-3 border-t pt-4 md:grid-cols-3"><div className="research-stat"><dt>Model family</dt><dd>{model.model_type || 'Not declared'}</dd></div><div className="research-stat"><dt>Snapshot</dt><dd className="truncate" title={model.snapshot_id}>{model.snapshot_id || 'Not declared'}</dd></div><div className="research-stat"><dt>Benchmark</dt><dd>{model.backtest?.meta?.benchmark || 'Not declared'}</dd></div></div><div className="mt-3 flex gap-2 rounded-lg bg-muted/45 p-3 text-xs text-muted-foreground"><GitBranch className="h-4 w-4 shrink-0 text-primary" /><span><strong className="text-foreground">Stop rule:</strong> {stopRule}</span></div></CardContent></Card></div>;
          })}
        </div>
      )}
    </div>
  );
}
