import { Fragment, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  CircleSlash2,
  PauseCircle,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { Sparkline } from '@/components/charts/Sparkline';
import type { ModelRankingIssue } from '@/hooks/useModelRanking';
import {
  RANKING_MARKET_LABELS,
  formatDate,
  formatPeriodLabel,
  formatPrice,
  formatReturn,
  sortRankingRows,
  type ModelRankingRow,
  type RankingCell,
  type RankingMarket,
  type RankingSignal,
} from '@/lib/model-ranking';
import { HORIZON_PERIODS, type HorizonPeriod } from '@/lib/performancePeriods';
import { cn } from '@/lib/utils';

export interface ModelRankingTableProps {
  rows: ModelRankingRow[];
  density: 'compact' | 'full';
  loading?: boolean;
  issues?: ModelRankingIssue[];
  selectedId?: string | null;
  onInspectSignal?: (row: ModelRankingRow) => void;
  emptyMessage?: string;
  caption?: string;
}

function signedTone(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value === 0) return 'text-muted-foreground';
  return value > 0 ? 'text-positive' : 'text-negative';
}

function rowTestId(row: ModelRankingRow): string {
  return row.kind === 'strategy'
    ? `fleet-${row.modelVersionId}`
    : `ranking-index-${row.market}-${row.symbol}`;
}

function MissingCell({ testId, reason }: { testId?: string; reason: string }) {
  return (
    <span data-testid={testId} title={reason} className="inline-block">
      <span aria-hidden="true" className="text-muted-foreground">—</span>
      <span className="sr-only">{reason}</span>
    </span>
  );
}

function ReturnCell({ cell, testId }: { cell: RankingCell; testId: string }) {
  if (!cell.display || cell.value === null) {
    return <MissingCell testId={testId} reason={cell.reason ?? 'No measured return is available.'} />;
  }
  return (
    <span data-testid={testId} title={cell.reason} className={cn('font-medium tabular-nums', signedTone(cell.value))}>
      {formatReturn(cell.value)}
    </span>
  );
}

function SignalIcon({ direction }: { direction: string }) {
  switch (direction) {
    case 'increase':
      return <TrendingUp className="h-3.5 w-3.5" aria-hidden="true" />;
    case 'reduce':
      return <TrendingDown className="h-3.5 w-3.5" aria-hidden="true" />;
    case 'hold':
      return <PauseCircle className="h-3.5 w-3.5" aria-hidden="true" />;
    case 'attention':
      return <ShieldAlert className="h-3.5 w-3.5" aria-hidden="true" />;
    default:
      return <CircleSlash2 className="h-3.5 w-3.5" aria-hidden="true" />;
  }
}

function signalTone(direction: string): string {
  switch (direction) {
    case 'increase':
      return 'border-positive/30 bg-positive/10 text-positive hover:bg-positive/15';
    case 'reduce':
      return 'border-warning/30 bg-warning/10 text-warning hover:bg-warning/15';
    case 'hold':
      return 'border-primary/30 bg-primary/10 text-primary hover:bg-primary/15';
    case 'attention':
      return 'border-negative/30 bg-negative/10 text-negative hover:bg-negative/15';
    default:
      return 'border-border bg-muted/40 text-muted-foreground hover:bg-muted/60';
  }
}

function SignalCell({ row, onInspectSignal }: { row: ModelRankingRow; onInspectSignal?: (row: ModelRankingRow) => void }) {
  const signal: RankingSignal | undefined = row.signal;
  if (!signal) return <MissingCell reason="Current signal is unavailable for this row." />;
  if (!onInspectSignal) {
    return <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium', signalTone(signal.direction))}>
      <SignalIcon direction={signal.direction} />{signal.label}
    </span>;
  }
  return (
    <button
      type="button"
      onClick={() => onInspectSignal(row)}
      aria-label={`Inspect signal for ${row.title}: ${signal.label}`}
      title={signal.note}
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors',
        signalTone(signal.direction),
      )}
    >
      <SignalIcon direction={signal.direction} />{signal.label}
    </button>
  );
}

function sparklineTitle(row: ModelRankingRow): string {
  const start = row.nav[0];
  const end = row.nav[row.nav.length - 1];
  if (!start || !end) return `${row.title}: no retained observations.`;
  const change = start.value > 0 ? end.value / start.value - 1 : null;
  return `${row.title}: ${start.date} ${formatPrice(start.value)} → ${end.date} ${formatPrice(end.value)} (${formatReturn(change)}). Retained observations, not a forecast.`;
}

function Row({ row, density, selected, onInspectSignal }: {
  row: ModelRankingRow;
  density: 'compact' | 'full';
  selected: boolean;
  onInspectSignal?: (row: ModelRankingRow) => void;
}) {
  const evidenceLabel = row.kind === 'strategy' ? 'Inspect evidence' : 'Price history';
  return (
    <tr
      data-testid={rowTestId(row)}
      data-kind={row.kind}
      data-stale={row.stale ? 'true' : 'false'}
      className={cn(
        'h-12 border-b last:border-b-0 md:h-10',
        row.stale && 'bg-warning/[0.04]',
        selected && 'bg-primary/5',
      )}
    >
      <th scope="row" className={cn('min-w-[230px] px-3 py-1.5 text-left align-middle font-normal', selected && 'border-l-2 border-primary')}>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <Link to={row.href} className="text-sm font-semibold hover:text-primary">
            {row.title}
          </Link>
          {row.stale && (
            <span
              data-testid={`stale-${row.id}`}
              title={`Evidence cutoff ${row.evidenceCutoff} is ${row.staleDays} calendar days after the last observation ${formatDate(row.asOf)}.`}
              className="inline-flex items-center gap-1 whitespace-nowrap rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-[10px] font-medium text-warning"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-warning" aria-hidden="true" />
              Stale · {row.staleDays}d behind cutoff
            </span>
          )}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-muted-foreground">
          <span>{RANKING_MARKET_LABELS[row.market]}</span>
          <span aria-hidden="true">·</span>
          <span className="max-w-[170px] truncate" title={row.benchmark}>{row.benchmark}</span>
          <span aria-hidden="true">·</span>
          <span>As of {formatDate(row.asOf)}</span>
          <span aria-hidden="true">·</span>
          <Link to={row.href} className="inline-flex items-center gap-0.5 text-primary hover:underline">
            {evidenceLabel}<ArrowRight className="h-3 w-3" aria-hidden="true" />
          </Link>
        </div>
      </th>
      {HORIZON_PERIODS.map((period) => (
        <td key={period} className="px-2 py-1.5 text-right align-middle">
          <ReturnCell cell={row.cells[period]} testId={`cell-${row.id}-${period}`} />
        </td>
      ))}
      <td className="px-2 py-1.5 text-right align-middle">
        <span title={sparklineTitle(row)}>
          <Sparkline nav={row.nav} width={72} height={24} showEndpoint className="ml-auto" />
        </span>
      </td>
      {density === 'full' && (
        <td className="px-2 py-1.5 text-right align-middle">
          {row.excess && row.excess.value !== null ? (
            <span title={row.excess.basis} className="inline-flex items-center gap-1">
              <span className={cn('font-medium tabular-nums', signedTone(row.excess.value))}>
                {formatReturn(row.excess.value)}
              </span>
              <span className="rounded border bg-muted/40 px-1 py-0.5 text-[9px] font-medium text-muted-foreground">
                {row.excess.label}
              </span>
            </span>
          ) : (
            <span title={row.excess?.reason ?? 'Excess is unavailable for this row.'}>
              <span aria-hidden="true" className="text-muted-foreground">—</span>
              <span className="mt-0.5 block max-w-[190px] truncate text-[10px] text-muted-foreground">
                Excess unavailable: {row.excess?.reason ?? 'No retained or derived excess observation.'}
              </span>
            </span>
          )}
        </td>
      )}
      {density === 'full' && (
        <td className="px-2 py-1.5 text-right align-middle">
          {row.maxDrawdown !== null && row.maxDrawdown !== undefined ? (
            <span title={row.maxDrawdownBasis} className={cn('font-medium tabular-nums', signedTone(row.maxDrawdown))}>
              {formatReturn(row.maxDrawdown)}
            </span>
          ) : (
            <MissingCell reason={row.maxDrawdownReason ?? 'Max drawdown is unavailable for this row.'} />
          )}
        </td>
      )}
      {density === 'full' && (
        <td className="px-2 py-1.5 text-right align-middle">
          <SignalCell row={row} onInspectSignal={onInspectSignal} />
        </td>
      )}
    </tr>
  );
}

/**
 * Shared model-ranking table. Compact density keeps the same horizon matrix as
 * full density; full density adds excess, max drawdown and the current signal.
 * Sparklines are aria-hidden beside the numeric cells and never the only value.
 */
export function ModelRankingTable({
  rows,
  density,
  loading = false,
  issues = [],
  selectedId = null,
  onInspectSignal,
  emptyMessage = 'No model ranking rows are available.',
  caption = 'Model ranking by market and horizon',
}: ModelRankingTableProps) {
  const [sort, setSort] = useState<HorizonPeriod>('1m');
  const sorted = useMemo(() => sortRankingRows(rows, sort), [rows, sort]);
  const columns = 1 + HORIZON_PERIODS.length + 1 + (density === 'full' ? 3 : 0);
  const markets: RankingMarket[] = ['us', 'cn'];

  return (
    <div className="relative overflow-hidden rounded-xl border bg-card shadow-card" aria-busy={loading}>
      {sorted.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">
          {loading ? 'Reading governed NAV projections…' : emptyMessage}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className={cn('w-full border-collapse text-sm', density === 'full' ? 'min-w-[1040px]' : 'min-w-[820px]')}>
            <caption className="sr-only">{caption}</caption>
            <thead>
              <tr className="border-b bg-muted/20">
                <th scope="col" className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  Model
                </th>
                {HORIZON_PERIODS.map((period) => (
                  <th
                    key={period}
                    scope="col"
                    aria-sort={sort === period ? 'descending' : 'none'}
                    className="px-2 py-2 text-right"
                  >
                    <button
                      type="button"
                      onClick={() => setSort(period)}
                      aria-pressed={sort === period}
                      className={cn(
                        'rounded px-1 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] transition-colors',
                        sort === period ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
                      )}
                    >
                      {formatPeriodLabel(period)}
                    </button>
                  </th>
                ))}
                <th scope="col" className="px-2 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  Trend
                </th>
                {density === 'full' && (
                  <>
                    <th scope="col" className="px-2 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                      Excess
                    </th>
                    <th scope="col" className="px-2 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                      Max DD
                    </th>
                    <th scope="col" className="px-2 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                      Signal
                    </th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {markets.map((market) => {
                const marketRows = sorted.filter((row) => row.market === market);
                if (!marketRows.length) return null;
                return (
                  <Fragment key={market}>
                    <tr data-testid={`ranking-group-${market}`}>
                      <th
                        scope="colgroup"
                        colSpan={columns}
                        className="border-b bg-muted/25 px-3 py-1.5 text-left text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground"
                      >
                        {RANKING_MARKET_LABELS[market]}
                      </th>
                    </tr>
                    {marketRows.map((row) => (
                      <Row
                        key={row.id}
                        row={row}
                        density={density}
                        selected={selectedId === row.id}
                        onInspectSignal={onInspectSignal}
                      />
                    ))}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {issues.length > 0 && (
        <ul aria-label="Model ranking read issues" className="space-y-1 border-t bg-warning/[0.04] px-3 py-2 text-xs text-warning">
          {issues.map((issue) => <li key={issue.id}>{issue.message}</li>)}
        </ul>
      )}
    </div>
  );
}
