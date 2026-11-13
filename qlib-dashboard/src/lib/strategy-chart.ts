import {
  MARKET_BASELINES,
  discoverBaselineOptions,
  type BaselineKind,
  type BaselineMarket,
  type BaselineOption,
  type BaselineRunIdentity,
} from './baseline';
import { alignNavSeries, type NavPoint, type NavTrade } from './nav-series';
import { effectivePerformanceDate } from './performanceBenchmarks';
import {
  isPerformanceDate,
  type HorizonCoverage,
  type HorizonCoverageReason,
  type PerformancePeriod,
} from './performancePeriods';
import type { ReportRow } from './types';

export interface ChartHorizon {
  period: PerformancePeriod;
  label: string;
}

/** Exactly the decision horizons exposed by the strategy chart, ALL included. */
export const CHART_HORIZONS: readonly ChartHorizon[] = [
  { period: '1w', label: '1W' },
  { period: '1m', label: '1M' },
  { period: '3m', label: '3M' },
  { period: '1y', label: '1Y' },
  { period: '2y', label: '2Y' },
  { period: '3y', label: '3Y' },
  { period: 'all', label: 'ALL' },
];

export const DEFAULT_CHART_HORIZON: PerformancePeriod = '1y';

/** `evidenceCutoff - asOf` above this many calendar days marks a stale window. */
export const STALE_AFTER_DAYS = 14;

/** A short-history partial window is still readable within one week of the request. */
export const MAX_DISPLAYABLE_SHORTFALL_DAYS = 7;

const DAY_MS = 86_400_000;

const RETURN_FORMAT = new Intl.NumberFormat('en-US', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: 'exceptZero',
});

/** One-decimal signed return, or an em dash. Never `0.0%` for a missing value. */
export function formatReturn(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  // Round to the displayed precision first so tiny negatives cannot surface as -0.0%.
  const rounded = Math.round(value * 1000) / 1000;
  return RETURN_FORMAT.format(rounded === 0 ? 0 : rounded);
}

/** Foundation semantic token for a signed value; zero stays neutral. */
export function returnTone(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) return '';
  return value > 0 ? 'text-positive' : 'text-negative';
}

function normalized(points: NavPoint[]): NavPoint[] {
  // alignNavSeries already validates dates/positive values and keeps the last duplicate.
  return alignNavSeries(points, points).map(point => ({ date: point.date, value: point.primary }));
}

/** Exact-date slice of a baseline into the primary window, with no interpolation. */
export function navBetween(points: NavPoint[], startDate: string | null, endDate: string | null): NavPoint[] {
  if (!startDate || !endDate) return [];
  return normalized(points).filter(point => point.date >= startDate && point.date <= endDate);
}

export interface WindowReturnSet {
  strategy: number | null;
  baseline: number | null;
  excess: number | null;
  /** First and last dates used for the displayed numbers. */
  startDate: string | null;
  endDate: string | null;
  alignedObservations: number;
  aligned: boolean;
}

/**
 * Window returns. When a baseline is selected, strategy, baseline and excess are
 * all read from the exact-date intersection, so they describe one common window.
 * Excess is `(1 + strategy) / (1 + baseline) - 1`.
 */
export function windowReturns(primary: NavPoint[], baseline?: NavPoint[] | null): WindowReturnSet {
  const points = normalized(primary);
  if (points.length === 0) {
    return {
      strategy: null,
      baseline: null,
      excess: null,
      startDate: null,
      endDate: null,
      alignedObservations: 0,
      aligned: false,
    };
  }

  const aligned = Array.isArray(baseline) && baseline.length > 0 ? alignNavSeries(points, baseline) : [];
  if (aligned.length >= 2) {
    const first = aligned[0];
    const last = aligned[aligned.length - 1];
    const strategy = last.primary / first.primary - 1;
    const baselineReturn = last.baseline / first.baseline - 1;
    return {
      strategy,
      baseline: baselineReturn,
      excess: (1 + strategy) / (1 + baselineReturn) - 1,
      startDate: first.date,
      endDate: last.date,
      alignedObservations: aligned.length,
      aligned: true,
    };
  }

  const first = points[0];
  const last = points[points.length - 1];
  return {
    strategy: points.length >= 2 ? last.value / first.value - 1 : null,
    baseline: null,
    excess: null,
    startDate: first.date,
    endDate: last.date,
    alignedObservations: aligned.length,
    aligned: false,
  };
}

/** Equity/peak − 1 over the retained window. Null below two observations. */
export function maximumDrawdown(points: NavPoint[]): number | null {
  const valid = normalized(points);
  if (valid.length < 2) return null;
  let peak = valid[0].value;
  let drawdown = 0;
  for (const point of valid) {
    peak = Math.max(peak, point.value);
    drawdown = Math.min(drawdown, point.value / peak - 1);
  }
  return drawdown;
}

const COVERAGE_TEXT: Record<HorizonCoverageReason, string> = {
  covered: 'The requested window is fully covered.',
  short_history: 'Retained history starts after the requested window.',
  truncated_window: 'Retained history does not reach the requested window.',
  coarse_cadence: 'Observation cadence is coarser than a weekly window.',
  insufficient_observations: 'Too few observations fall inside this window.',
  invalid_dates: 'No valid observation dates are retained.',
};

/** Plain-language reason for a coverage state, safe to show in a metric tile. */
export function coverageReasonText(coverage: HorizonCoverage): string {
  if (coverage.reason === 'short_history' && coverage.firstObservation) {
    return `History starts ${coverage.firstObservation}, after the requested window start.`;
  }
  if (coverage.reason === 'coarse_cadence' && coverage.cadenceDays !== null) {
    return `Observed cadence of ${coverage.cadenceDays} calendar days is too coarse for a weekly window.`;
  }
  if (coverage.reason === 'insufficient_observations') {
    return `Only ${coverage.observations} valid observation${coverage.observations === 1 ? '' : 's'} in this window.`;
  }
  return COVERAGE_TEXT[coverage.reason] ?? COVERAGE_TEXT.invalid_dates;
}

export interface ChartMetricDisplay {
  text: string;
  visible: boolean;
  reason: string | null;
  firstObservation: string | null;
}

/**
 * Coverage-aware metric display. Full windows and short-history partials within
 * one week show a number; coarse or too-short windows show `—` with a reason.
 */
export function metricDisplay(coverage: HorizonCoverage, value: number | null): ChartMetricDisplay {
  const firstObservation = coverage.firstObservation;
  if (value === null || !Number.isFinite(value)) {
    return { text: '—', visible: false, reason: coverageReasonText(coverage), firstObservation };
  }
  if (coverage.state === 'full') {
    return { text: formatReturn(value), visible: true, reason: null, firstObservation };
  }
  if (
    coverage.state === 'partial'
    && coverage.reason === 'short_history'
    && coverage.missingDays !== null
    && coverage.missingDays <= MAX_DISPLAYABLE_SHORTFALL_DAYS
  ) {
    return { text: formatReturn(value), visible: true, reason: null, firstObservation };
  }
  return { text: '—', visible: false, reason: coverageReasonText(coverage), firstObservation };
}

/**
 * Declared + market + none options for one run. The market option describes the
 * run's own market only and stays available until its governed bars are actually
 * requested, so it can be selected lazily from the chart.
 */
export function strategyBaselineOptions(run: BaselineRunIdentity, rows: ReportRow[]): BaselineOption[] {
  const discovered = discoverBaselineOptions(run, Array.isArray(rows) ? rows : []);
  const identity = MARKET_BASELINES[run.market];
  const marketOption: BaselineOption = {
    key: `market:${identity.symbol}`,
    label: identity.label,
    kind: 'market',
    market: run.market,
    source: 'market_bars',
    available: true,
  };
  const noneIndex = discovered.findIndex(option => option.kind === 'none');
  if (noneIndex < 0) return [...discovered, marketOption];
  return [...discovered.slice(0, noneIndex), marketOption, ...discovered.slice(noneIndex)];
}

/** Persisted preference when usable, otherwise declared when usable, else none. */
export function defaultBaselineKind(options: BaselineOption[], preferred: BaselineKind): BaselineKind {
  const usable = (kind: BaselineKind) => options.some(option => option.kind === kind && option.available);
  if (usable(preferred)) return preferred;
  if (usable('declared')) return 'declared';
  return 'none';
}

/** Stable cache key and evidence identity for the one governed market baseline. */
export function marketBaselineKey(market: BaselineMarket): string {
  return `${market}:${MARKET_BASELINES[market].symbol}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function optionalText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

function optionalNumber(value: unknown): number | null {
  const numeric = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : Number.NaN;
  return Number.isFinite(numeric) ? numeric : null;
}

/**
 * Defensive trade-ledger parsing for both retained shapes (`records` or a bare
 * array). Malformed rows are ignored rather than failing the whole chart.
 */
export function parseNavTrades(payload: unknown): NavTrade[] {
  const rows = Array.isArray(payload)
    ? payload
    : isRecord(payload) && Array.isArray(payload.records)
      ? payload.records
      : [];
  const trades: NavTrade[] = [];
  for (const item of rows) {
    if (!isRecord(item)) continue;
    const action = typeof item.action === 'string' ? item.action.trim() : '';
    if (!action) continue;
    const date = isPerformanceDate(item.date) ? item.date : null;
    const holdingEnd = isPerformanceDate(item.holding_end_date) ? item.holding_end_date : null;
    if (date === null && holdingEnd === null) continue;
    trades.push({
      date: date ?? holdingEnd ?? '',
      ...(holdingEnd === null ? {} : { holding_end_date: holdingEnd }),
      action,
      previous_weight: optionalNumber(item.previous_weight),
      target_weight: optionalNumber(item.target_weight),
      instrument: optionalText(item.instrument),
      reason: optionalText(item.reason),
    });
  }
  return trades;
}

export type NavMarkerMode = 'trade-date' | 'holding-end';

/** Holding-end markers only when the NAV projection itself carries settlement dates. */
export function navMarkerMode(rows: ReportRow[]): NavMarkerMode {
  return Array.isArray(rows) && rows.some(row => isPerformanceDate(row.holding_end_date))
    ? 'holding-end'
    : 'trade-date';
}

/** Calendar days between the evidence cutoff and the last observation. */
export function staleDays(evidenceCutoff: string, asOf: string | null): number | null {
  if (!isPerformanceDate(evidenceCutoff) || !isPerformanceDate(asOf)) return null;
  return Math.round(
    (Date.parse(`${evidenceCutoff}T00:00:00Z`) - Date.parse(`${asOf}T00:00:00Z`)) / DAY_MS,
  );
}

export function isStale(evidenceCutoff: string, asOf: string | null): boolean {
  const days = staleDays(evidenceCutoff, asOf);
  return days !== null && days > STALE_AFTER_DAYS;
}

/** Provisional marks inside the displayed exact-date window, never elsewhere. */
export function provisionalObservationCount(
  rows: ReportRow[],
  startDate: string | null,
  endDate: string | null,
): number {
  if (!Array.isArray(rows) || !startDate || !endDate) return 0;
  return rows.filter(row => {
    const date = effectivePerformanceDate(row);
    return date >= startDate
      && date <= endDate
      && (row.provisional_mtm === true || row.settlement_status === 'provisional_mtm');
  }).length;
}
