import { MARKET_BASELINES, type BaselineMarket } from './baseline';
import type { DerivedExcess } from './derived-excess';
import type { GovernedRunSummary } from './governed-run';
import { STALE_AFTER_DAYS, calendarDaysBetween } from './metrics';
import { alignNavSeries, navFromReport, type NavPoint } from './nav-series';
import {
  HORIZON_PERIODS,
  isPerformanceDate,
  type HorizonCoverage,
  type HorizonPeriod,
} from './performancePeriods';
import { navHorizonCoverage, navReturn } from './nav-returns';
import type { SecurityBar } from './security-evidence';
import type { ReportRow } from './types';

/**
 * Shared, fetch-free ranking model for Today's compact table and the full
 * Strategies table. Every number is derived in the browser from the governed
 * NAV projection or governed market-evidence closes; nothing here is published
 * as a new server-side metric.
 */

export type RankingMarket = BaselineMarket;

/** Display policy for one horizon. `value` is null whenever it must not render. */
export interface RankingCell {
  value: number | null;
  coverage: HorizonCoverage;
  display: boolean;
  reason?: string;
}

export type RankingExcessSource = 'derived' | 'retained' | 'unavailable';

/** One excess observation, with the provenance its label must disclose. */
export interface RankingExcess {
  value: number | null;
  source: RankingExcessSource;
  /** Short in-row badge: `derived`, `retained`, or `Excess unavailable`. */
  label: string;
  /** Tooltip/basis shown beside a displayed value. */
  basis: string;
  /** Window actually measured, when the artifact records one. */
  window?: string;
  reason?: string;
}

/** Current-operations metadata rendered in full density; never used for ranking math. */
export interface RankingSignal {
  label: string;
  direction: string;
  note: string;
  attention: boolean;
  isNew: boolean;
  isHold: boolean;
}

interface RankingRowBase {
  id: string;
  title: string;
  market: RankingMarket;
  /** Declared benchmark identity for strategies; governed index label for indices. */
  benchmark: string;
  /** Full retained observation curve used only for the compact sparkline. */
  nav: NavPoint[];
  href: string;
  /** Last retained NAV/close observation; always the row's own date. */
  asOf: string;
  evidenceCutoff: string;
  stale: boolean;
  staleDays: number;
  cells: Record<HorizonPeriod, RankingCell>;
  excess?: RankingExcess;
  maxDrawdown?: number | null;
  maxDrawdownReason?: string;
  maxDrawdownBasis?: string;
  signal?: RankingSignal;
}

export interface StrategyRankingRow extends RankingRowBase {
  kind: 'strategy';
  modelVersionId: string;
}

export interface IndexRankingRow extends RankingRowBase {
  kind: 'index';
  symbol: string;
}

export type ModelRankingRow = StrategyRankingRow | IndexRankingRow;

export interface StrategyRankingOptions {
  /** A retained or derived excess observation prepared by the caller. */
  excess?: RankingExcess | null;
}

export {
  STALE_AFTER_DAYS,
  calendarDaysBetween,
  formatDate,
  formatPrice,
  formatPriceChange,
  formatReturn,
} from './metrics';

export const RANKING_MARKET_LABELS: Readonly<Record<RankingMarket, string>> = {
  us: 'US',
  cn: 'China',
};

/** One governed index identity: its market, canonical symbol and display title. */
export interface RankingIndexIdentity {
  market: RankingMarket;
  symbol: string;
  title: string;
}

/**
 * Ordered governed index identities. Each one is read from its own published
 * market evidence; a missing series is reported as unpublished, never replaced
 * by another index, ETF, synthetic or interpolated series.
 */
export const RANKING_INDEXES: readonly RankingIndexIdentity[] = [
  { market: 'us', symbol: MARKET_BASELINES.us.symbol, title: 'QQQ' },
  { market: 'us', symbol: 'SPX', title: 'S&P 500' },
  { market: 'cn', symbol: MARKET_BASELINES.cn.symbol, title: 'CSI 300' },
];

export function formatPeriodLabel(period: HorizonPeriod): string {
  return period.toUpperCase();
}

function coverageReason(period: HorizonPeriod, coverage: HorizonCoverage): string {
  const label = formatPeriodLabel(period);
  switch (coverage.reason) {
    case 'short_history':
      return `History begins ${coverage.firstObservation ?? 'after the requested start'}; the ${label} window is missing its first ${coverage.missingDays ?? 'several'} calendar days.`;
    case 'coarse_cadence':
      return `Observations are ${coverage.cadenceDays ?? 'sparsely'} days apart; a ${label} return needs a denser series.`;
    case 'insufficient_observations':
      return `Only ${coverage.observations} observation${coverage.observations === 1 ? '' : 's'} in the ${label} window; no measured return is shown.`;
    case 'truncated_window':
      return `History begins ${coverage.firstObservation ?? 'after the requested start'}, ${coverage.missingDays ?? 'many'} days after the ${label} window starts; the return is not shown.`;
    case 'invalid_dates':
      return 'Observation dates could not be verified; no return is shown.';
    case 'covered':
    default:
      return `The ${label} window is not fully covered by retained observations.`;
  }
}

/**
 * The horizon display policy. A full window renders its measured return; a
 * short-history window missing at most seven calendar days renders with a
 * disclosure of its actual first observation; every other partial or missing
 * window renders as missing rather than a zero from a one-point window.
 */
export function rankingCell(nav: NavPoint[], period: HorizonPeriod): RankingCell {
  const coverage = navHorizonCoverage(nav, period);
  const observed = navReturn(nav, period);
  if (coverage.state === 'full' && observed !== null && Number.isFinite(observed)) {
    return { value: observed, coverage, display: true };
  }
  if (coverage.state === 'partial'
      && coverage.reason === 'short_history'
      && coverage.missingDays !== null
      && coverage.missingDays <= 7
      && coverage.observations >= 2
      && observed !== null
      && Number.isFinite(observed)) {
    return {
      value: observed,
      coverage,
      display: true,
      reason: `First retained observation ${coverage.firstObservation}; the requested window starts ${coverage.requestedStart}.`,
    };
  }
  return { value: null, coverage, display: false, reason: coverageReason(period, coverage) };
}

function cellsFor(nav: NavPoint[]): Record<HorizonPeriod, RankingCell> {
  return Object.fromEntries(
    HORIZON_PERIODS.map((period) => [period, rankingCell(nav, period)]),
  ) as Record<HorizonPeriod, RankingCell>;
}

interface SummaryMetricLike {
  metric_id?: unknown;
  value?: unknown;
  availability_status?: unknown;
  unavailable_reason?: unknown;
  scope?: unknown;
}

function summaryMetric(run: GovernedRunSummary, metricId: string): SummaryMetricLike | null {
  const metrics = Array.isArray(run.summary.metrics) ? run.summary.metrics : [];
  return (metrics as SummaryMetricLike[]).find((metric) => metric?.metric_id === metricId) ?? null;
}

function availableNumber(metric: SummaryMetricLike | null): number | null {
  return metric?.availability_status === 'available'
    && typeof metric.value === 'number'
    && Number.isFinite(metric.value)
    ? metric.value
    : null;
}

function unavailableReason(metric: SummaryMetricLike | null, fallback: string): string {
  return typeof metric?.unavailable_reason === 'string' && metric.unavailable_reason.trim() !== ''
    ? metric.unavailable_reason
    : fallback;
}

/**
 * The retained formal excess metric. This is the authority for runs whose
 * summary carries an available value; it is never recomputed from `bench`.
 */
export function retainedExcess(run: GovernedRunSummary): RankingExcess {
  const metric = summaryMetric(run, 'excess_return');
  const value = availableNumber(metric);
  if (value !== null) {
    const scope = typeof metric?.scope === 'string' && metric.scope.trim() !== ''
      ? metric.scope.trim()
      : null;
    return {
      value,
      source: 'retained',
      label: 'retained',
      // The raw metric scope stays in the disclosure; the visible window label
      // is a short, human-readable run-window description.
      basis: `Retained run-summary excess vs ${run.benchmark} over the run's own retained window${scope ? ` (recorded scope: ${scope})` : ''}; not the sorted horizon.`,
      window: 'run window',
    };
  }
  return {
    value: null,
    source: 'unavailable',
    label: 'Excess unavailable',
    basis: '',
    reason: unavailableReason(
      metric,
      'The governed formal source does not retain a finite excess-return metric.',
    ),
  };
}

/** Sealed derived excess, labelled distinct from a retained summary metric. */
export function rankingExcessFromDerived(excess: DerivedExcess): RankingExcess {
  const start = excess.window?.observed_start;
  const end = excess.window?.observed_end;
  return {
    value: excess.result.excess_return,
    source: 'derived',
    label: 'derived',
    basis: `${excess.label}. Compounded relative excess${start && end ? ` over ${start} → ${end}` : ''}; not the sorted horizon. Descriptive historical metric, not a live signal.`,
    window: start && end ? `${start} → ${end}` : undefined,
  };
}

function maxDrawdownFromNav(nav: NavPoint[]): number | null {
  if (nav.length < 2) return null;
  let peak = nav[0].value;
  let drawdown = 0;
  for (const point of nav) {
    peak = Math.max(peak, point.value);
    if (peak > 0) drawdown = Math.min(drawdown, point.value / peak - 1);
  }
  return drawdown;
}

function marketOf(run: GovernedRunSummary): RankingMarket {
  return String(run.market).toLowerCase() === 'cn' ? 'cn' : 'us';
}

/**
 * Build the strategy row from the compact `nav.json` projection. The full
 * retained curve drives the sparkline; excess is accepted only when the caller
 * has prepared a retained or derived observation.
 */
export function strategyRowsFromNav(
  run: GovernedRunSummary,
  navRows: ReportRow[],
  options: StrategyRankingOptions = {},
): StrategyRankingRow[] {
  const nav = navFromReport(navRows);
  const last = nav[nav.length - 1];
  const asOf = last?.date ?? '';
  const staleDays = last ? Math.max(0, calendarDaysBetween(last.date, run.evidenceCutoff)) : 0;
  const drawdownMetric = summaryMetric(run, 'max_drawdown');
  const maxDrawdown = availableNumber(drawdownMetric);
  const row: StrategyRankingRow = {
    id: run.modelVersionId,
    kind: 'strategy',
    modelVersionId: run.modelVersionId,
    title: run.title,
    market: marketOf(run),
    benchmark: run.benchmark,
    nav,
    href: `/strategies/${encodeURIComponent(run.modelVersionId)}`,
    asOf,
    evidenceCutoff: run.evidenceCutoff,
    stale: Boolean(last) && staleDays > STALE_AFTER_DAYS,
    staleDays,
    cells: cellsFor(nav),
    maxDrawdown,
    maxDrawdownReason: maxDrawdown === null
      ? unavailableReason(drawdownMetric, 'The formal summary does not retain a max-drawdown metric.')
      : undefined,
    maxDrawdownBasis: maxDrawdown === null ? undefined : 'Retained max-drawdown summary over the run\'s own window; not the sorted horizon.',
  };
  if (options.excess) row.excess = options.excess;
  return [row];
}

function closeNav(bars: readonly SecurityBar[]): NavPoint[] {
  const points: NavPoint[] = (Array.isArray(bars) ? bars : [])
    .filter((bar) => bar && typeof bar.time === 'string' && Number.isFinite(bar.close) && bar.close > 0)
    .map((bar) => ({ date: bar.time, value: bar.close }));
  return alignNavSeries(points, points).map((point) => ({ date: point.date, value: point.primary }));
}

/**
 * Build an index row from governed market-evidence closes. This is a
 * close-to-close price measure, not a total-return or baseline overlay, and its
 * excess is never combined with a strategy's wealth return. The row's declared
 * benchmark is its own governed title (QQQ, S&P 500 or CSI 300), never another
 * market's baseline label.
 */
export function indexRowsFromBars(
  market: RankingMarket,
  symbol: string,
  name: string,
  bars: readonly SecurityBar[],
  evidenceCutoff?: string,
): IndexRankingRow[] {
  const nav = closeNav(bars);
  const last = nav[nav.length - 1];
  const asOf = last?.date ?? '';
  const cutoff = isPerformanceDate(evidenceCutoff) ? evidenceCutoff : asOf;
  const staleDays = last && cutoff ? Math.max(0, calendarDaysBetween(last.date, cutoff)) : 0;
  const maxDrawdown = maxDrawdownFromNav(nav);
  return [{
    id: `index:${market}:${symbol}`,
    kind: 'index',
    symbol,
    title: name,
    market,
    benchmark: name,
    nav,
    href: `/securities/${market}/${encodeURIComponent(symbol)}`,
    asOf,
    evidenceCutoff: cutoff,
    stale: Boolean(last) && staleDays > STALE_AFTER_DAYS,
    staleDays,
    cells: cellsFor(nav),
    excess: {
      value: null,
      source: 'unavailable',
      label: 'Excess unavailable',
      basis: '',
      reason: 'Index rows are close-to-close price returns; excess is not computed.',
    },
    maxDrawdown,
    maxDrawdownReason: maxDrawdown === null ? 'Fewer than two governed close observations.' : undefined,
    maxDrawdownBasis: maxDrawdown === null ? undefined : 'Close-to-close price drawdown over the governed index history; not the sorted horizon.',
  }];
}

const MARKET_ORDER: Readonly<Record<RankingMarket, number>> = { us: 0, cn: 1 };

export type RankingSort = HorizonPeriod | 'excess' | 'maxDrawdown' | 'signal' | 'asOf';

/**
 * Row-kind precedence inside each market group. `'mixed'` leaves strategies and
 * governed indices interleaved by the selected sort; `'strategies-first'`
 * places every strategy row before the index rows and then applies the same
 * sort within each kind.
 */
export type RankingKindOrder = 'mixed' | 'strategies-first';

export interface RankingSortOptions {
  /** Defaults to `'mixed'`, which is the Today ranking's existing order. */
  kindOrder?: RankingKindOrder;
}

export const RANKING_METRIC_SORTS = ['asOf', 'excess', 'maxDrawdown', 'signal'] as const;

export function isHorizonSort(sort: RankingSort): sort is HorizonPeriod {
  return (HORIZON_PERIODS as readonly string[]).includes(sort);
}

const SIGNAL_ORDER: Readonly<Record<string, number>> = {
  attention: 4, increase: 3, reduce: 2, hold: 1,
};

function rankValue(row: ModelRankingRow, period: HorizonPeriod): number {
  const cell = row.cells[period];
  return cell.display && cell.value !== null && Number.isFinite(cell.value)
    ? cell.value
    : Number.NEGATIVE_INFINITY;
}

/** Higher values sort first; unavailable observations always sort last. */
function metricValue(row: ModelRankingRow, sort: RankingSort): number {
  if (isHorizonSort(sort)) return rankValue(row, sort);
  switch (sort) {
    case 'excess':
      return row.excess?.value !== null && row.excess?.value !== undefined
        && Number.isFinite(row.excess.value)
        ? row.excess.value
        : Number.NEGATIVE_INFINITY;
    case 'maxDrawdown':
      return typeof row.maxDrawdown === 'number' && Number.isFinite(row.maxDrawdown)
        ? row.maxDrawdown
        : Number.NEGATIVE_INFINITY;
    case 'signal':
      return row.signal ? SIGNAL_ORDER[row.signal.direction] ?? 0 : Number.NEGATIVE_INFINITY;
    case 'asOf': {
      const timestamp = Date.parse(`${row.asOf}T00:00:00Z`);
      return Number.isFinite(timestamp) ? timestamp : Number.NEGATIVE_INFINITY;
    }
  }
}

/**
 * Deterministic ordering: US before China, optionally every strategy row
 * before the governed index rows, fresh before stale, the selected metric
 * descending with missing values last, then title and row identity. Sort keys
 * never change a displayed value; they only reorder existing rows.
 */
export function sortRankingRows(
  rows: readonly ModelRankingRow[],
  sort: RankingSort,
  options: RankingSortOptions = {},
): ModelRankingRow[] {
  const strategiesFirst = (options.kindOrder ?? 'mixed') === 'strategies-first';
  return [...rows].sort((left, right) => {
    const marketOrder = MARKET_ORDER[left.market] - MARKET_ORDER[right.market];
    if (marketOrder !== 0) return marketOrder;
    if (strategiesFirst) {
      const kindOrder = Number(left.kind === 'index') - Number(right.kind === 'index');
      if (kindOrder !== 0) return kindOrder;
    }
    const freshness = Number(left.stale) - Number(right.stale);
    if (freshness !== 0) return freshness;
    const leftValue = metricValue(left, sort);
    const rightValue = metricValue(right, sort);
    if (leftValue !== rightValue) {
      if (leftValue === Number.NEGATIVE_INFINITY) return 1;
      if (rightValue === Number.NEGATIVE_INFINITY) return -1;
      return rightValue - leftValue;
    }
    if (left.title !== right.title) return left.title < right.title ? -1 : 1;
    if (left.id === right.id) return 0;
    return left.id < right.id ? -1 : 1;
  });
}
