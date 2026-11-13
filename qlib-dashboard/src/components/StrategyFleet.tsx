import { useMemo, useState } from 'react';
import { ModelRankingTable } from '@/components/ModelRankingTable';
import { StrategySignalDrawer } from '@/components/StrategySignalDrawer';
import { useModelRanking } from '@/hooks/useModelRanking';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { ModelRankingRow, RankingSignal } from '@/lib/model-ranking';
import {
  summarizeStrategySignal,
  type StrategyOperationsSnapshot,
} from '@/lib/strategy-operations';

type MarketFilter = 'all' | 'us' | 'cn';
type SignalFilter = 'all' | 'new' | 'attention';

function rankingSignal(snapshot?: StrategyOperationsSnapshot): RankingSignal {
  const summary = summarizeStrategySignal(snapshot);
  return {
    label: summary.badgeLabel,
    direction: summary.direction,
    note: summary.summaryNote,
    attention: summary.isAttention,
    isNew: summary.isNew,
    isHold: summary.isHold,
  };
}

/**
 * Strategies keeps one table. It reuses the shared ranking model at full
 * density and never downloads a run's full `performance.json` section.
 */
export function StrategyFleet({
  runs,
  snapshots,
}: {
  runs: GovernedRunSummary[];
  snapshots: Map<string, StrategyOperationsSnapshot>;
}) {
  const ranking = useModelRanking(runs, { includeIndices: true, includeExcess: true });
  const [marketFilter, setMarketFilter] = useState<MarketFilter>('all');
  const [signalFilter, setSignalFilter] = useState<SignalFilter>('all');
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const rows = useMemo(() => ranking.rows.map((row) => row.kind === 'strategy'
    ? { ...row, signal: rankingSignal(snapshots.get(row.modelVersionId)) }
    : row), [ranking.rows, snapshots]);

  const filteredRows = useMemo(() => rows.filter((row) => {
    if (marketFilter !== 'all' && row.market !== marketFilter) return false;
    // Governed index rows are market context, not strategies. A signal filter
    // narrows strategy rows only and must not erase the benchmark reference.
    if (row.kind === 'index') return true;
    if (signalFilter === 'new' && !row.signal?.isNew) return false;
    if (signalFilter === 'attention' && !row.signal?.attention) return false;
    return true;
  }), [rows, marketFilter, signalFilter]);

  const strategyCount = filteredRows.filter((row) => row.kind === 'strategy').length;
  const indexCount = filteredRows.filter((row) => row.kind === 'index').length;
  const selectedRun = selectedRunId
    ? runs.find((run) => run.modelVersionId === selectedRunId) ?? null
    : null;
  const selectedSnapshot = selectedRun
    ? snapshots.get(selectedRun.modelVersionId) ?? null
    : null;

  const handleInspectSignal = (row: ModelRankingRow) => {
    if (row.kind !== 'strategy') return;
    setSelectedRunId(row.modelVersionId);
    setDrawerOpen(true);
  };

  return (
    <section className="space-y-4" aria-label="Formal strategy fleet">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center">
          <select
            id="market"
            aria-label="Market"
            value={marketFilter}
            onChange={(event) => setMarketFilter(event.target.value as MarketFilter)}
            className="ae-select research-touch min-h-9 focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="all">All markets</option>
            <option value="us">US</option>
            <option value="cn">CN</option>
          </select>
          <select
            id="filter"
            aria-label="Signal filter"
            value={signalFilter}
            onChange={(event) => setSignalFilter(event.target.value as SignalFilter)}
            className="ae-select research-touch min-h-9 focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="all">All signals</option>
            <option value="new">New signals</option>
            <option value="attention">Needs attention</option>
          </select>
        </div>
        <p className="hidden text-[11px] leading-relaxed text-muted-foreground sm:block">
          Sort by any horizon. Each row keeps its own observed window and evidence cutoff.
        </p>
      </div>

      <details className="rounded-lg border border-border/70 bg-muted/15 px-3 py-2 text-xs text-muted-foreground" data-testid="strategy-method">
        <summary className="cursor-pointer font-medium text-foreground">How these numbers are built</summary>
        <p className="mt-2 leading-relaxed" role="note">
          Returns are browser-derived from each run's compact NAV projection. A horizon that is not fully
          covered shows — rather than an interpolated or one-point return. Current signals are read
          separately and are never inferred from a position delta.
        </p>
        <p className="mt-2 leading-relaxed" role="note">
          Excess and max drawdown describe each run's own retained or derived window; they are not aligned
          to the sorted horizon. Governed index rows use close-to-close price observations.
        </p>
      </details>

      {signalFilter !== 'all' && (
        <p data-testid="signal-filter-scope" className="text-xs leading-relaxed text-muted-foreground" role="note">
          Signal filters apply to strategies only; governed index rows remain visible for market context.
        </p>
      )}

      {!ranking.loading && strategyCount === 0 && (
        <p data-testid="strategy-filter-empty" className="text-xs leading-relaxed text-muted-foreground" role="status">
          No strategies match these filters. Governed index rows remain for market context.
        </p>
      )}

      <ModelRankingTable
        rows={filteredRows}
        density="full"
        loading={ranking.loading}
        issues={ranking.issues}
        selectedId={selectedRunId}
        onInspectSignal={(row) => handleInspectSignal(row)}
        emptyMessage="No strategies match these filters."
        caption="Formal strategy and governed index ranking by market and horizon"
      />

      <div className="flex flex-col gap-2 px-1 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span>{strategyCount} strategies · {indexCount} governed indices</span>
        <span>Model portfolio simulation · Returns are not an investment recommendation</span>
      </div>

      <StrategySignalDrawer
        run={selectedRun}
        snapshot={selectedSnapshot}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </section>
  );
}
