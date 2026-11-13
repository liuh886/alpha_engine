import { alignNavSeries, type NavPoint } from './nav-series';
import { declaredBenchmarkDescriptor, effectivePerformanceDate } from './performanceBenchmarks';
import { isPerformanceDate } from './performancePeriods';
import type { ReportRow } from './types';

export type BaselineKind = 'declared' | 'market' | 'none';

export type BaselineMarket = 'us' | 'cn';

/** Where a selectable baseline's observations come from. `none` has no series. */
export type BaselineSource = 'formal_report' | 'market_bars';

export interface BaselineOption {
  key: string;
  label: string;
  kind: BaselineKind;
  market: BaselineMarket;
  /** Omitted for the `none` option, which selects no overlay. */
  source?: BaselineSource;
  /** Resolved wealth column for a declared option, for example `bench_qqq`. */
  field?: string;
  available: boolean;
  reason?: string;
}

/** The governed market baseline for each market. Never substitute another index. */
export const MARKET_BASELINES: Readonly<Record<BaselineMarket, { symbol: string; label: string }>> = {
  us: { symbol: 'QQQ', label: 'QQQ' },
  cn: { symbol: '000300', label: 'CSI 300 (000300.SH)' },
};

export interface MarketBar {
  time?: string;
  date?: string;
  open: number;
}

/** A governed run identity subset; pages pass their run's benchmark and market. */
export interface BaselineRunIdentity {
  benchmark?: string | null;
  market: BaselineMarket;
}

const DECLARED_UNAVAILABLE = 'Benchmark wealth series not retained';
const MARKET_UNAVAILABLE = 'Fewer than two retained market observations.';

function sortedUnique(points: NavPoint[]): NavPoint[] {
  // alignNavSeries already validates dates/values and keeps the last duplicate.
  return alignNavSeries(points, points).map(point => ({ date: point.date, value: point.primary }));
}

function isWealthField(field: string): boolean {
  // `bench` and `bench_<slug>` can be wealth levels. `bench_*_before` is an
  // opening anchor, and `benchmark_*` columns are source returns/account values.
  return field === 'bench' || (field.startsWith('bench_') && !field.endsWith('_before'));
}

function normalizeBenchmarkIdentity(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function retainedBenchmarkFields(rows: ReportRow[]): string[] {
  const fields: string[] = [];
  for (const row of rows) {
    if (!row) continue;
    for (const key of Object.keys(row)) {
      if (isWealthField(key) && !fields.includes(key)) fields.push(key);
    }
  }
  return fields;
}

/**
 * A benchmark column is only usable as wealth when every retained observation
 * is a finite positive level on at least two dates. Per-row return columns
 * (for example a `bench` column whose first value is negative) fail this check
 * rather than being cumulated or treated as levels.
 */
function isPositiveWealthField(rows: ReportRow[], field: string): boolean {
  const dates = new Set<string>();
  for (const row of rows) {
    if (!row) continue;
    const date = effectivePerformanceDate(row);
    if (!isPerformanceDate(date)) continue;
    const raw = row[field];
    if (raw === null || raw === undefined || raw === '') continue;
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0) return false;
    dates.add(date);
  }
  return dates.size >= 2;
}

/**
 * Pick the retained wealth column for a declared benchmark. The declared
 * identity is normalized first (so `BYD v1.2` prefers `bench_byd_v1_2`), then
 * a known alias/canonical field from the existing benchmark descriptor, and
 * only then the plain `bench` column when it passes the wealth check.
 */
function selectDeclaredWealthField(rows: ReportRow[], benchmark: string): string | null {
  const normalized = normalizeBenchmarkIdentity(benchmark);
  const fields = retainedBenchmarkFields(rows);
  const candidates = new Set<string>();

  if (normalized) {
    const exact = fields.find(field => field.startsWith('bench_')
      && normalizeBenchmarkIdentity(field.slice('bench_'.length)) === normalized);
    if (exact) candidates.add(exact);
  }
  const descriptor = declaredBenchmarkDescriptor(rows, benchmark);
  if (descriptor && fields.includes(descriptor.field)) candidates.add(descriptor.field);
  if (fields.includes('bench')) candidates.add('bench');

  for (const field of candidates) {
    if (isPositiveWealthField(rows, field)) return field;
  }
  return null;
}

/**
 * Extract a declared benchmark's retained wealth observations.
 *
 * Accepts only `bench`/`bench_<slug>` wealth fields and requires at least two
 * valid positive observations. Missing cells (`null`, `undefined`, `''`) are
 * skipped, but the function fails closed: if any present value for the field is
 * non-finite or not greater than zero, the whole curve is rejected with `[]`
 * rather than silently shortened. Rows use the effective performance date,
 * require a valid ISO date, keep the last duplicate date, and return ascending
 * observations. No value is forward-filled or interpolated.
 *
 * Caution: a plain `bench` column is a per-row return in some reports. Pages
 * should use `discoverBaselineOptions`, which only selects a column that
 * passes the positive-wealth check.
 */
export function navFromBenchmarkField(rows: ReportRow[], field: string): NavPoint[] {
  if (!Array.isArray(rows) || !isWealthField(field)) return [];
  const points: NavPoint[] = [];
  for (const row of rows) {
    if (!row) continue;
    const date = effectivePerformanceDate(row);
    if (!isPerformanceDate(date)) continue;
    const raw = row[field];
    if (raw === null || raw === undefined || raw === '') continue;
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0) return [];
    points.push({ date, value });
  }
  const observations = sortedUnique(points);
  return observations.length >= 2 ? observations : [];
}

/**
 * Extract a market baseline from governed bars as an open-to-open level series.
 *
 * The raw open is retained as the wealth observation; this is not a total-return
 * index (dividends and corporate actions are not applied). `time` is preferred
 * over `date`, invalid dates and non-positive/non-finite opens are skipped, the
 * last duplicate date wins, and observations are returned ascending.
 */
export function marketNavFromBars(bars: readonly MarketBar[]): NavPoint[] {
  if (!Array.isArray(bars)) return [];
  const points: NavPoint[] = [];
  for (const bar of bars) {
    if (!bar || typeof bar.open !== 'number' || !Number.isFinite(bar.open) || bar.open <= 0) continue;
    const date = isPerformanceDate(bar.time) ? bar.time : isPerformanceDate(bar.date) ? bar.date : null;
    if (date === null) continue;
    points.push({ date, value: bar.open });
  }
  return sortedUnique(points);
}

/**
 * Describe the baseline choices a page may offer for one run.
 *
 * - `declared` reuses the run's declared benchmark identity and a retained
 *   `bench`/`bench_<slug>` wealth column. A declared benchmark can itself be a
 *   strategy version (for example BYD v1.2), so the option label always comes
 *   from `run.benchmark`, never from the discovered field name. When no
 *   positive wealth column is retained (for example CN 000300 without a
 *   benchmark column), the option stays visible and unavailable with a reason.
 * - `market` is offered only when governed bars for the run's market are
 *   supplied (US QQQ, CN 000300). No other index is invented.
 * - `none` is always available.
 */
export function discoverBaselineOptions(
  run: BaselineRunIdentity,
  rows: ReportRow[],
  marketBars?: Partial<Record<BaselineMarket, readonly MarketBar[]>>,
): BaselineOption[] {
  const options: BaselineOption[] = [];
  const market = run.market;
  const benchmark = typeof run.benchmark === 'string' ? run.benchmark.trim() : '';

  if (benchmark) {
    const field = selectDeclaredWealthField(rows, benchmark);
    const available = field !== null && navFromBenchmarkField(rows, field).length >= 2;
    options.push({
      key: field === null ? `declared:${normalizeBenchmarkIdentity(benchmark) || 'unresolved'}` : `declared:${field}`,
      label: benchmark,
      kind: 'declared',
      market,
      source: 'formal_report',
      ...(field === null ? {} : { field }),
      available,
      ...(available ? {} : { reason: DECLARED_UNAVAILABLE }),
    });
  }

  const bars = marketBars?.[market];
  if (Array.isArray(bars) && bars.length > 0) {
    const identity = MARKET_BASELINES[market];
    const available = marketNavFromBars(bars).length >= 2;
    options.push({
      key: `market:${identity.symbol}`,
      label: identity.label,
      kind: 'market',
      market,
      source: 'market_bars',
      available,
      ...(available ? {} : { reason: MARKET_UNAVAILABLE }),
    });
  }

  options.push({ key: 'none', label: 'No baseline', kind: 'none', market, available: true });
  return options;
}
