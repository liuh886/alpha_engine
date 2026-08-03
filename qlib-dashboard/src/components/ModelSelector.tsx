import type { ModelData } from '@/lib/data-parser';
import { CheckCircle2 } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { modelKindLabel, projectFormalEvidence, projectFormalMetric } from '@/lib/formal-evidence';

interface ModelSelectorProps {
  models: ModelData[];
  selectedModelId: string;
  onSelect: (id: string) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function percentMetric(model: ModelData, aliases: string[]): string {
  const metric = projectFormalMetric(model, aliases);
  return metric.value === null ? 'Unavailable' : `${(metric.value * 100).toFixed(1)}%`;
}

export function ModelSelector({
  models,
  selectedModelId,
  onSelect,
  open,
  onOpenChange,
}: ModelSelectorProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] w-[calc(100vw-1.5rem)] max-w-5xl overflow-y-auto p-4 sm:p-6">
        <DialogHeader>
          <DialogTitle>Select formal baseline</DialogTitle>
          <p className="text-sm text-muted-foreground">
            Only accepted named model backtests are available. Exploratory experiments and rejected candidates are excluded by the publication catalog.
          </p>
        </DialogHeader>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="formal-model-selector-cards">
          {models.map((model) => {
            const isSelected = model.id === selectedModelId;
            const projection = projectFormalEvidence(model);
            const formal = projection.formal;
            const rebalanceSessions = formal?.portfolio_contract.rebalance_sessions;
            const topk = formal?.portfolio_contract.topk;
            const traceFrequency = String(formal?.trace_frequency || 'not declared').split('_').join(' ');
            return (
              <button
                key={model.id}
                type="button"
                data-testid="formal-model-card"
                aria-pressed={isSelected}
                className={`min-w-0 rounded-xl border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${isSelected ? 'border-primary bg-primary/5 ring-1 ring-primary/25' : 'hover:border-primary/40 hover:bg-muted/30'}`}
                onClick={() => {
                  onSelect(model.id);
                  onOpenChange(false);
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-semibold text-foreground">{model.name || 'Untitled record'}</div>
                    <div className="mt-1 truncate font-mono text-[10px] text-muted-foreground" title={model.id}>{model.id}</div>
                  </div>
                  {isSelected && <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />}
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  <Badge variant="secondary" className="text-[9px]">Formal baseline</Badge>
                  <Badge variant="outline" className="text-[9px] uppercase">{model.market}</Badge>
                  <Badge variant="outline" className="text-[9px]">{modelKindLabel(projection.modelKind)}</Badge>
                </div>

                <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                  <div><dt className="text-muted-foreground">Annualized</dt><dd className="mt-0.5 font-mono font-semibold">{percentMetric(model, ['Annualized Return', 'CAGR'])}</dd></div>
                  <div><dt className="text-muted-foreground">Relative excess</dt><dd className="mt-0.5 font-mono font-semibold">{percentMetric(model, ['Compounded Relative Excess Return', 'Excess Return'])}</dd></div>
                  <div><dt className="text-muted-foreground">Start</dt><dd className="mt-0.5 font-mono text-[11px]">{model.backtest.meta.start || 'Not declared'}</dd></div>
                  <div><dt className="text-muted-foreground">End</dt><dd className="mt-0.5 font-mono text-[11px]">{model.backtest.meta.end || 'Not declared'}</dd></div>
                </dl>

                <div className="mt-4 space-y-1 border-t pt-3 text-[11px] text-muted-foreground">
                  <div>Trace: {traceFrequency}</div>
                  <div>Rebalance: {typeof rebalanceSessions === 'number' ? `${rebalanceSessions} sessions` : 'Source-defined state'}</div>
                  <div>Top-K: {typeof topk === 'number' ? topk : 'Not applicable'}</div>
                  <div title={projection.costAvailability}>Costs: {projection.costBps === null ? 'Unavailable' : `${projection.costBps} bps`}</div>
                  <div>Evidence: {formal?.evidence_completeness.status || 'Not declared'}</div>
                </div>
              </button>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
