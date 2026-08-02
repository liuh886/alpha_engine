import type { ModelData } from '@/lib/data-parser';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';

interface ModelSelectorProps {
  models: ModelData[];
  selectedModelId: string;
  onSelect: (id: string) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
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
      <DialogContent className="max-h-[82vh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Select formal baseline</DialogTitle>
          <p className="text-sm text-muted-foreground">
            Only accepted named model backtests are available. Exploratory experiments and rejected candidates are excluded by the publication catalog.
          </p>
        </DialogHeader>

        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[220px]">Formal model</TableHead>
                <TableHead className="min-w-[150px]">Scope</TableHead>
                <TableHead className="min-w-[190px]">Performance</TableHead>
                <TableHead className="min-w-[220px]">Backtest contract</TableHead>
                <TableHead className="text-right">Selection</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {models.map((model) => {
                const isSelected = model.id === selectedModelId;
                const annualizedReturn = model.backtest.metrics['Annualized Return'] ?? model.backtest.metrics.CAGR ?? null;
                const relativeExcess = model.backtest.metrics['Compounded Relative Excess Return'] ?? model.backtest.metrics['Excess Return'] ?? null;
                const sharpe = model.backtest.metrics['Sharpe Ratio'] ?? null;
                const params = model.params || {};
                const formal = (params.formal_backtest || {}) as Record<string, unknown>;
                const contract = (formal.portfolio_contract || {}) as Record<string, unknown>;
                const topk = contract.topk as number | undefined;
                const costsBps = (contract.cost_bps ?? contract.transaction_cost_bps) as number | undefined;
                const rebalanceSessions = contract.rebalance_sessions as number | undefined;
                const traceFrequency = String(formal.trace_frequency || 'not declared').split('_').join(' ');
                const completeness = (formal.evidence_completeness || {}) as Record<string, unknown>;

                return (
                  <TableRow
                    key={model.id}
                    className={`cursor-pointer transition-colors hover:bg-muted/50 ${isSelected ? 'bg-muted' : ''}`}
                    tabIndex={0}
                    aria-selected={isSelected}
                    onClick={() => {
                      onSelect(model.id);
                      onOpenChange(false);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onSelect(model.id);
                        onOpenChange(false);
                      }
                    }}
                  >
                    <TableCell>
                      <div className="font-semibold text-foreground">{model.name || 'Untitled record'}</div>
                      <div className="mt-1 max-w-[260px] truncate font-mono text-[10px] text-muted-foreground" title={model.id}>{model.id}</div>
                      <Badge variant="secondary" className="mt-2 text-[9px]">Formal baseline</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="uppercase">{model.market}</Badge>
                      <div className="mt-2 text-xs text-muted-foreground">
                        <div>{model.backtest.meta.start || 'Start not declared'}</div>
                        <div>{model.backtest.meta.end || 'End not declared'}</div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className={`font-mono text-sm font-semibold ${annualizedReturn !== null && annualizedReturn > 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-foreground'}`}>
                        {annualizedReturn !== null ? `${(annualizedReturn * 100).toFixed(1)}% annualized` : 'Annualized return unavailable'}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        Relative excess {relativeExcess !== null ? `${(relativeExcess * 100).toFixed(1)}%` : '—'} · Sharpe {sharpe !== null ? sharpe.toFixed(2) : '—'}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="space-y-1 text-xs text-muted-foreground">
                        <div>Trace: {traceFrequency}</div>
                        <div>Rebalance: {rebalanceSessions !== undefined ? `${rebalanceSessions} sessions` : 'state / source defined'}</div>
                        <div>Top-K: {topk !== undefined ? topk : 'not applicable'}</div>
                        <div>Costs: {costsBps !== undefined ? `${costsBps} bps` : 'not declared'}</div>
                        <div>Evidence: {String(completeness.status || 'not declared')}</div>
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      {isSelected ? <Badge>Active</Badge> : <span className="text-xs text-muted-foreground">Select</span>}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </DialogContent>
    </Dialog>
  );
}
