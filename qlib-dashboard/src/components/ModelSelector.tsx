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
          <DialogTitle>Select evidence record</DialogTitle>
          <p className="text-sm text-muted-foreground">
            Change the active model or backtest record used by the comparison views. The underlying bundle remains read-only.
          </p>
        </DialogHeader>

        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[220px]">Record</TableHead>
                <TableHead className="min-w-[150px]">Scope</TableHead>
                <TableHead className="min-w-[190px]">Performance</TableHead>
                <TableHead className="min-w-[190px]">Research contract</TableHead>
                <TableHead className="text-right">Selection</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {models.map((model) => {
                const isSelected = model.id === selectedModelId;
                const annualizedReturn = model.backtest.metrics['Annualized Return'] ?? null;
                const informationRatio = model.backtest.metrics['Information Ratio'] ?? null;
                const sharpe = model.backtest.metrics['Sharpe Ratio'] ?? null;
                const params = model.params || {};
                const meta = (params.meta || {}) as Record<string, unknown>;
                const strategyProfile = (meta.strategy_profile || {}) as Record<string, unknown>;
                const strategy = (strategyProfile.strategy || {}) as Record<string, unknown>;
                const positionRule = (strategy.position_rule || {}) as Record<string, unknown>;

                const rebalance = strategy.rebalance_frequency as string | undefined;
                const minHoldDays = strategy.min_hold_days as number | undefined;
                const topk = positionRule.topk as number | undefined;
                const costsBps = strategy.costs_bps as number | undefined;

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
                      <div className="mt-1 max-w-[260px] truncate font-mono text-[10px] text-muted-foreground" title={model.id}>
                        {model.id}
                      </div>
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
                        {annualizedReturn !== null ? `${(annualizedReturn * 100).toFixed(1)}% annualized` : 'Return unavailable'}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        IR {informationRatio !== null ? informationRatio.toFixed(2) : '—'} · Sharpe {sharpe !== null ? sharpe.toFixed(2) : '—'}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="space-y-1 text-xs text-muted-foreground">
                        <div>Rebalance: {rebalance || 'not declared'}</div>
                        <div>Minimum hold: {minHoldDays !== undefined ? `${minHoldDays}d` : 'not declared'}</div>
                        <div>Top-K: {topk !== undefined ? topk : 'not declared'}</div>
                        <div>Costs: {costsBps !== undefined ? `${costsBps} bps` : 'not declared'}</div>
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
