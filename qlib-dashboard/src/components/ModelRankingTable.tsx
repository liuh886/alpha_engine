import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowDown,
  ArrowRight,
  ChevronDown,
  CircleSlash2,
  Info,
  PauseCircle,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { Sparkline } from '@/components/charts/Sparkline';
import type { ModelRankingIssue } from '@/hooks/useModelRanking';
import {
  RANKING_MARKET_LABELS,
  RANKING_METRIC_SORTS,
  formatDate,
  formatPeriodLabel,
  formatPrice,
  formatReturn,
  isHorizonSort,
  sortRankingRows,
  type ModelRankingRow,
  type RankingCell,
  type RankingMarket,
  type RankingSignal,
  type RankingSort,
} from '@/lib/model-ranking';
import { HORIZON_PERIODS } from '@/lib/performancePeriods';
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

/** Narrow screens get a card layout instead of a squeezed multi-column table. */
function useNarrowViewport(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia('(max-width: 767px)');
    const update = () => setNarrow(query.matches);
    update();
    query.addEventListener?.('change', update);
    return () => query.removeEventListener?.('change', update);
  }, []);
  return narrow;
}

function sparklineTone(cell: RankingCell | undefined): 'positive' | 'negative' | 'neutral' {
  if (!cell || !cell.display || cell.value === null || cell.value === 0) return 'neutral';
  return cell.value > 0 ? 'positive' : 'negative';
}

/**
 * One consistent missing-value pattern: a visible dash plus an info
 * disclosure whose summary is keyboard- and touch-reachable. Opening it shows
 * the full reason; assistive technology gets the same text from the summary's
 * accessible name.
 */
function MissingCell({ testId, reason, shortLabel }: { testId?: string; reason: string; shortLabel?: string }) {
  return (
    <details className="inline-block max-w-full text-right">
      <summary
        data-testid={testId}
        title={reason}
        aria-label={`${shortLabel ?? 'Unavailable'}: ${reason}`}
        className="inline-flex cursor-pointer list-none items-center justify-end gap-1 rounded text-muted-foreground [&::-webkit-details-marker]:hidden"
      >
        <span aria-hidden="true">—</span>
        {shortLabel && <span aria-hidden="true" className="text-[9px]">{shortLabel}</span>}
        <Info className="h-3 w-3 shrink-0" aria-hidden="true" />
      </summary>
      <p className="mt-1 max-w-[220px] text-left text-[10px] leading-4 text-muted-foreground">{reason}</p>
    </details>
  );
}

/**
 * One disclosure pattern for a displayed value's basis. The summary is a real
 * keyboard- and touch-reachable control; nothing depends on hover.
 */
function BasisDisclosure({ summary, children, testId }: {
  summary: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <details className="inline-block max-w-full text-right">
      <summary
        data-testid={testId}
        className="inline-flex cursor-pointer list-none items-center justify-end gap-1 rounded [&::-webkit-details-marker]:hidden"
      >
        {summary}
        <Info className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden="true" />
      </summary>
      <p className="mt-1 max-w-[240px] text-left text-[10px] leading-4 text-muted-foreground">{children}</p>
    </details>
  );
}

function ReturnCell({ cell, testId }: { cell: RankingCell; testId: string }) {
  if (!cell.display || cell.value === null) {
    return <MissingCell testId={testId} reason={cell.reason ?? 'No measured return is available.'} />;
  }
  const value = <span className={cn('font-medium tabular-nums', signedTone(cell.value))}>{formatReturn(cell.value)}</span>;
  if (!cell.reason) return <span data-testid={testId}>{value}</span>;
  return (
    <BasisDisclosure testId={testId} summary={value}>
      {cell.reason}
    </BasisDisclosure>
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
  const chip = <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium', signalTone(signal.direction))}>
    <SignalIcon direction={signal.direction} />{signal.label}
  </span>;
  return (
    <span className="inline-flex flex-wrap items-center justify-end gap-1">
      {onInspectSignal ? (
        <button
          type="button"
          onClick={() => onInspectSignal(row)}
          aria-label={`Inspect signal for ${row.title}: ${signal.label}`}
          className={cn(
            'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors',
            signalTone(signal.direction),
          )}
        >
          <SignalIcon direction={signal.direction} />{signal.label}
        </button>
      ) : chip}
      {signal.note && (
        <BasisDisclosure summary={<span className="sr-only">Signal basis for {row.title}</span>}>
          {signal.note}
        </BasisDisclosure>
      )}
    </span>
  );
}

function sparklineTitle(row: ModelRankingRow): string {
  const start = row.nav[0];
  const end = row.nav[row.nav.length - 1];
  if (!start || !end) return `${row.title}: no retained observations.`;
  const change = start.value > 0 ? end.value / start.value - 1 : null;
  return `${row.title}: ${start.date} ${formatPrice(start.value)} → ${end.date} ${formatPrice(end.value)} (${formatReturn(change)}). Retained observations, not a forecast.`;
}

function RowDetails({ row }: { row: ModelRankingRow }) {
  const first = row.nav[0];
  const last = row.nav[row.nav.length - 1];
  return (
    <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
      <div><dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">Benchmark</dt><dd>{row.benchmark}</dd></div>
      {row.asOf === row.evidenceCutoff ? (
        <div><dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">As of · Evidence cutoff</dt><dd>{formatDate(row.asOf)}</dd></div>
      ) : (
        <>
          <div><dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">Evidence cutoff</dt><dd>{formatDate(row.evidenceCutoff)}</dd></div>
          <div><dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">As of</dt><dd>{formatDate(row.asOf)}</dd></div>
        </>
      )}
      <div><dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">Retained window</dt><dd>{first && last ? `${formatDate(first.date)} → ${formatDate(last.date)}` : 'No retained observations'}</dd></div>
      {row.signal?.note && <div className="sm:col-span-2"><dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">Signal note</dt><dd className="text-muted-foreground">{row.signal.note}</dd></div>}
      {row.excess?.basis && <div className="sm:col-span-2"><dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">Excess basis</dt><dd className="text-muted-foreground">{row.excess.basis}</dd></div>}
      {row.maxDrawdownBasis && <div className="sm:col-span-2"><dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">Max drawdown basis</dt><dd className="text-muted-foreground">{row.maxDrawdownBasis}</dd></div>}
    </dl>
  );
}

function Row({ row, density, selected, sort, expanded, onToggle, onInspectSignal }: {
  row: ModelRankingRow;
  density: 'compact' | 'full';
  selected: boolean;
  sort: RankingSort;
  expanded: boolean;
  onToggle: () => void;
  onInspectSignal?: (row: ModelRankingRow) => void;
}) {
  const evidenceLabel = row.kind === 'strategy' ? 'Inspect evidence' : 'Price history';
  const sparklinePeriod = isHorizonSort(sort) ? sort : '1m';
  const detailsId = `row-details-${row.id}`;
  return (<Fragment>
    <tr
      data-testid={rowTestId(row)}
      data-kind={row.kind}
      data-stale={row.stale ? 'true' : 'false'}
      className={cn(
        'h-12 border-b last:border-b-0 transition-colors hover:bg-muted/30 focus-within:bg-muted/30 md:h-10',
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
          <span aria-hidden="true">·</span>
          <button type="button" aria-expanded={expanded} aria-controls={detailsId} onClick={onToggle}
            className="inline-flex items-center gap-0.5 text-primary hover:underline">
            Row details<ChevronDown className={cn('h-3 w-3 transition-transform', expanded && 'rotate-180')} aria-hidden="true" />
          </button>
        </div>
      </th>
      {HORIZON_PERIODS.map((period) => (
        <td key={period} className="px-2 py-1.5 text-right align-middle">
          <ReturnCell cell={row.cells[period]} testId={`cell-${row.id}-${period}`} />
        </td>
      ))}
      <td className="px-2 py-1.5 text-right align-middle">
        <span title={sparklineTitle(row)}>
          <Sparkline nav={row.nav} width={72} height={24} showEndpoint tone={sparklineTone(row.cells[sparklinePeriod])} className="ml-auto" />
        </span>
      </td>
      {density === 'full' && (
        <td className="px-2 py-1.5 text-right align-middle">
          {row.excess && row.excess.value !== null ? (
            <BasisDisclosure summary={
              <span className="inline-flex flex-col items-end gap-0.5">
                <span className="inline-flex items-center gap-1">
                  <span className={cn('font-medium tabular-nums', signedTone(row.excess.value))}>
                    {formatReturn(row.excess.value)}
                  </span>
                  <span className="rounded border bg-muted/40 px-1 py-0.5 text-[9px] font-medium text-muted-foreground">
                    {row.excess.label}
                  </span>
                </span>
                <span className="text-[9px] text-muted-foreground">{row.excess.window ?? 'run window'}</span>
              </span>
            }>
              {row.excess.basis}
            </BasisDisclosure>
          ) : (
            <MissingCell
              testId={`excess-${row.id}`}
              reason={row.excess?.reason ?? 'Excess is unavailable for this row.'}
              shortLabel="Unavailable"
            />
          )}
        </td>
      )}
      {density === 'full' && (
        <td className="px-2 py-1.5 text-right align-middle">
          {row.maxDrawdown !== null && row.maxDrawdown !== undefined ? (
            <BasisDisclosure summary={
              <span className="inline-flex flex-col items-end gap-0.5">
                <span className={cn('font-medium tabular-nums', signedTone(row.maxDrawdown))}>
                  {formatReturn(row.maxDrawdown)}
                </span>
                <span className="text-[9px] text-muted-foreground">{row.kind === 'index' ? 'close window' : 'run window'}</span>
              </span>
            }>
              {row.maxDrawdownBasis ?? 'Run-window maximum drawdown from retained observations.'}
            </BasisDisclosure>
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
    {expanded && (
      <tr id={detailsId} className="border-b bg-muted/20 last:border-b-0">
        <td colSpan={1 + HORIZON_PERIODS.length + 1 + (density === 'full' ? 3 : 0)} className="px-3 py-3">
          <RowDetails row={row} />
        </td>
      </tr>
    )}
  </Fragment>);
}

/**
 * Narrow-screen row card. Every decision horizon stays visible with its own
 * label, and the sorted horizon is highlighted instead of losing columns.
 */
function RankingCard({ row, density, selected, sort, expanded, onToggle, onInspectSignal }: {
  row: ModelRankingRow;
  density: 'compact' | 'full';
  selected: boolean;
  sort: RankingSort;
  expanded: boolean;
  onToggle: () => void;
  onInspectSignal?: (row: ModelRankingRow) => void;
}) {
  const evidenceLabel = row.kind === 'strategy' ? 'Inspect evidence' : 'Price history';
  const detailsId = `card-details-${row.id}`;
  // Governed index rows have no signal and no strategy excess; keeping empty
  // metric wells would push the first strategy card below the handset fold.
  const showMetrics = density === 'full' && row.kind === 'strategy';
  return (
    <li
      data-testid={rowTestId(row)}
      data-kind={row.kind}
      data-stale={row.stale ? 'true' : 'false'}
      className={cn(
        'rounded-lg border bg-card p-3 shadow-card',
        row.stale && 'bg-warning/[0.04]',
        selected && 'border-primary/40 bg-primary/5',
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-2 gap-y-1">
        <div className="min-w-0">
          <Link to={row.href} className="text-sm font-semibold hover:text-primary">{row.title}</Link>
          <p className="mt-0.5 break-words text-[11px] text-muted-foreground">
            {RANKING_MARKET_LABELS[row.market]} · {row.benchmark} · As of {formatDate(row.asOf)}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Link to={row.href} className="inline-flex items-center gap-0.5 text-[11px] text-primary hover:underline">
            {evidenceLabel}<ArrowRight className="h-3 w-3" aria-hidden="true" />
          </Link>
          <button type="button" aria-expanded={expanded} aria-controls={detailsId} onClick={onToggle}
            className="inline-flex items-center gap-0.5 text-[11px] text-primary hover:underline">
            Row details<ChevronDown className={cn('h-3 w-3 transition-transform', expanded && 'rotate-180')} aria-hidden="true" />
          </button>
        </div>
      </div>
      {row.stale && (
        <span
          data-testid={`stale-${row.id}`}
          title={`Evidence cutoff ${row.evidenceCutoff} is ${row.staleDays} calendar days after the last observation ${formatDate(row.asOf)}.`}
          className="mt-1.5 inline-flex items-center gap-1 whitespace-nowrap rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-[10px] font-medium text-warning"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-warning" aria-hidden="true" />
          Stale · {row.staleDays}d behind cutoff
        </span>
      )}
      <dl className="mt-2 grid grid-cols-3 gap-1.5">
        {HORIZON_PERIODS.map(period => (
          <div key={period} className={cn('rounded border bg-background/60 px-2 py-1', sort === period && 'border-primary/40')}>
            <dt className="text-[9px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {formatPeriodLabel(period)}
            </dt>
            <dd className="mt-0.5 text-right text-[12px]">
              <ReturnCell cell={row.cells[period]} testId={`cell-${row.id}-${period}`} />
            </dd>
          </div>
        ))}
      </dl>
      {showMetrics && (
        <dl className="mt-1.5 grid grid-cols-2 gap-1.5">
          <div className="min-w-0 rounded border bg-background/60 px-2 py-1">
            <dt className="break-words text-[9px] uppercase tracking-[0.08em] text-muted-foreground">Excess · {row.excess?.window ?? 'run window'}</dt>
            <dd className="mt-0.5 text-right text-[12px]">
              {row.excess && row.excess.value !== null ? (
                <BasisDisclosure summary={
                  <span className={cn('font-medium tabular-nums', signedTone(row.excess.value))}>
                    {formatReturn(row.excess.value)}
                    <span className="ml-1 text-[9px] font-normal text-muted-foreground">{row.excess.label}</span>
                  </span>
                }>
                  {row.excess.basis}
                </BasisDisclosure>
              ) : (
                <MissingCell
                  testId={`excess-${row.id}`}
                  reason={row.excess?.reason ?? 'Excess is unavailable for this row.'}
                  shortLabel="Unavailable"
                />
              )}
            </dd>
          </div>
          <div className="min-w-0 rounded border bg-background/60 px-2 py-1">
            <dt className="break-words text-[9px] uppercase tracking-[0.08em] text-muted-foreground">
              Max DD · run window
            </dt>
            <dd className="mt-0.5 text-right text-[12px]">
              {row.maxDrawdown !== null && row.maxDrawdown !== undefined ? (
                <BasisDisclosure summary={
                  <span className={cn('font-medium tabular-nums', signedTone(row.maxDrawdown))}>
                    {formatReturn(row.maxDrawdown)}
                  </span>
                }>
                  {row.maxDrawdownBasis ?? 'Run-window maximum drawdown from retained observations.'}
                </BasisDisclosure>
              ) : (
                <MissingCell reason={row.maxDrawdownReason ?? 'Max drawdown is unavailable for this row.'} />
              )}
            </dd>
          </div>
        </dl>
      )}
      {showMetrics && (
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Signal</span>
          <SignalCell row={row} onInspectSignal={onInspectSignal} />
        </div>
      )}
      {expanded && (
        <div id={detailsId} className="mt-2 rounded-lg border bg-muted/20 p-3">
          <RowDetails row={row} />
        </div>
      )}
    </li>
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
  const [sort, setSort] = useState<RankingSort>('1m');
  const [expandedIds, setExpandedIds] = useState<ReadonlySet<string>>(() => new Set());
  const narrow = useNarrowViewport();
  const sorted = useMemo(() => sortRankingRows(rows, sort), [rows, sort]);
  const columns = 1 + HORIZON_PERIODS.length + 1 + (density === 'full' ? 3 : 0);
  const markets: RankingMarket[] = ['us', 'cn'];
  const toggleRow = (id: string) => setExpandedIds(previous => {
    const next = new Set(previous);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const metricSorts = density === 'full' ? RANKING_METRIC_SORTS : (['asOf'] as const);
  const metricLabel = (key: string) => key === 'asOf' ? 'As of' : key === 'maxDrawdown' ? 'Max DD' : key === 'excess' ? 'Excess' : 'Signal';

  return (
    <div className="relative overflow-hidden rounded-xl border bg-card shadow-card" aria-busy={loading}>
      {sorted.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">
          {loading ? 'Reading governed NAV projections…' : emptyMessage}
        </p>
      ) : narrow ? (
        <div className="space-y-3 p-3">
          <div
            role="group"
            aria-label="Sort ranking by horizon"
            className="flex items-center gap-1.5 overflow-x-auto pb-1"
          >
            <span className="shrink-0 px-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              Sort
            </span>
            {HORIZON_PERIODS.map((period) => (
              <button
                key={period}
                type="button"
                onClick={() => setSort(period)}
                aria-pressed={sort === period}
                className={cn(
                  'min-h-11 min-w-11 shrink-0 rounded-lg border px-3 text-xs font-semibold uppercase tracking-[0.08em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  sort === period
                    ? 'border-primary/40 bg-primary/10 text-foreground'
                    : 'bg-card text-muted-foreground hover:text-foreground',
                )}
              >
                {formatPeriodLabel(period)}
              </button>
            ))}
            {metricSorts.map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setSort(key)}
                aria-pressed={sort === key}
                className={cn(
                  'min-h-11 min-w-11 shrink-0 rounded-lg border px-3 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  sort === key
                    ? 'border-primary/40 bg-primary/10 text-foreground'
                    : 'bg-card text-muted-foreground hover:text-foreground',
                )}
              >
                {metricLabel(key)}
              </button>
            ))}
          </div>
          {markets.map((market) => {
            const marketRows = sorted.filter((row) => row.market === market);
            if (!marketRows.length) return null;
            return (
              <section
                key={market}
                aria-label={RANKING_MARKET_LABELS[market]}
                data-testid={`ranking-group-${market}`}
              >
                <h3 className="px-1 pb-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
                  {RANKING_MARKET_LABELS[market]}
                </h3>
                <ul className="space-y-2">
                  {marketRows.map((row) => (
                    <RankingCard
                      key={row.id}
                      row={row}
                      density={density}
                      selected={selectedId === row.id}
                      sort={sort}
                      expanded={expandedIds.has(row.id)}
                      onToggle={() => toggleRow(row.id)}
                      onInspectSignal={onInspectSignal}
                    />
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      ) : (
        <div className="overflow-auto max-h-[70vh]">
          <table className={cn('w-full border-collapse text-sm', density === 'full' ? 'min-w-[1040px]' : 'min-w-[820px]')}>
            <caption className="sr-only">{caption}</caption>
            <thead className="sticky top-0 z-10 bg-card shadow-[0_1px_0_hsl(var(--border))]">
              <tr className="border-b bg-muted/20">
                <th scope="col" aria-sort={sort === 'asOf' ? 'descending' : 'none'} className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {/* The as-of control sits immediately after the Model label.
                      Stretching it to the far edge of this wide column read as a
                      separate, empty AS OF column at desktop widths. */}
                  <span className="flex items-center gap-2">
                    <span>Model</span>
                    <button
                      type="button"
                      onClick={() => setSort('asOf')}
                      aria-pressed={sort === 'asOf'}
                      aria-label="Sort by as-of freshness"
                      className={cn(
                        '-my-2 flex min-h-11 min-w-11 items-center gap-1 rounded px-1 text-[10px] font-semibold uppercase tracking-[0.12em] transition-colors',
                        sort === 'asOf'
                          ? 'text-foreground underline decoration-primary decoration-2 underline-offset-4'
                          : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground',
                      )}
                    >
                      As of
                      <ArrowDown className={cn('h-3 w-3 shrink-0', sort === 'asOf' ? 'opacity-100' : 'opacity-0')} aria-hidden="true" />
                    </button>
                  </span>
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
                        '-mx-2 -my-2 flex min-h-11 min-w-11 items-center justify-end gap-1 rounded px-2 text-[10px] font-semibold uppercase tracking-[0.12em] transition-colors',
                        sort === period
                          ? 'text-foreground underline decoration-primary decoration-2 underline-offset-4'
                          : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground',
                      )}
                    >
                      {formatPeriodLabel(period)}
                      <ArrowDown className={cn('h-3 w-3 shrink-0', sort === period ? 'opacity-100' : 'opacity-0')} aria-hidden="true" />
                    </button>
                  </th>
                ))}
                <th scope="col" className="px-2 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  Trend
                  <span className="block text-[9px] font-normal normal-case tracking-normal">retained history</span>
                </th>
                {density === 'full' && (
                  <>
                    {RANKING_METRIC_SORTS.filter(key => key !== 'asOf').map((key) => (
                      <th key={key} scope="col" aria-sort={sort === key ? 'descending' : 'none'}
                        title={key === 'excess'
                          ? 'Run-window excess, not aligned to the sorted horizon'
                          : key === 'maxDrawdown'
                            ? 'Run-window max drawdown, not aligned to the sorted horizon'
                            : 'Current verified signal state'}
                        className="px-2 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        <button
                          type="button"
                          onClick={() => setSort(key)}
                          aria-pressed={sort === key}
                          className={cn(
                            '-mx-2 -my-2 flex min-h-11 min-w-11 items-center justify-end gap-1 rounded px-2 text-[10px] font-semibold uppercase tracking-[0.12em] transition-colors',
                            sort === key
                              ? 'text-foreground underline decoration-primary decoration-2 underline-offset-4'
                              : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground',
                          )}
                        >
                          {metricLabel(key)}
                          <ArrowDown className={cn('h-3 w-3 shrink-0', sort === key ? 'opacity-100' : 'opacity-0')} aria-hidden="true" />
                        </button>
                      </th>
                    ))}
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
                        sort={sort}
                        expanded={expandedIds.has(row.id)}
                        onToggle={() => toggleRow(row.id)}
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
