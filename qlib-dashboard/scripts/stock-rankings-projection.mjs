// Disposable per-market stock-ranking projection for the Today page.
//
// The browser owns the shared ranking display policy (`performancePeriods.ts`,
// `nav-returns.ts`, `model-ranking.ts`). Node cannot import those TypeScript
// modules, so this file replicates the exact window, coverage and display
// semantics in plain JavaScript. `stock-rankings-projection.test.mjs` pins the
// replication against the TypeScript primitives so the two cannot drift.
//
// Only `selected_pool_candidate` rows are projected. Every value is a
// close-to-close price return from exact observed dates; there is no
// interpolation, forward fill, total-return adjustment or model signal.

export const STOCK_RANKINGS_SCHEMA = 'stock_rankings_projection_v1';
export const STOCK_RANKINGS_VIEW = 'stock_rankings_v1';
export const STOCK_RANKING_PERIODS = Object.freeze(['1w', '1m', '3m', '1y']);
export const SELECTED_POOL_CANDIDATE_ROLE = 'selected_pool_candidate';

const DAY_MS = 86_400_000;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const SAFE_SYMBOL = /^[A-Za-z0-9._-]+$/;

/** Same contract as `isPerformanceDate` in `src/lib/performancePeriods.ts`. */
export function isPerformanceDate(value) {
  if (typeof value !== 'string' || !ISO_DATE.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

/**
 * Same definition as `performancePeriodStart` in `src/lib/performancePeriods.ts`
 * for the four supported horizons. Calendar windows end at the series' own last
 * observation; month subtraction clamps to the target month's last day.
 */
export function stockPeriodStart(asOf, period) {
  if (!isPerformanceDate(asOf)) return null;
  const end = new Date(`${asOf}T00:00:00Z`);
  if (period === '1w') {
    end.setUTCDate(end.getUTCDate() - 7);
  } else {
    const monthsBack = { '1m': 1, '3m': 3, '1y': 12 };
    const months = monthsBack[period];
    if (months === undefined) return null;
    const day = end.getUTCDate();
    end.setUTCDate(1);
    end.setUTCMonth(end.getUTCMonth() - months);
    const lastDay = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() + 1, 0)).getUTCDate();
    end.setUTCDate(Math.min(day, lastDay));
  }
  return end.toISOString().slice(0, 10);
}

/**
 * Normalize published OHLCV bars to the same observation contract as
 * `alignNavSeries`: valid ISO dates, finite positive closes, last duplicate
 * date wins, ascending. Invalid rows are dropped rather than repaired.
 */
export function normalizeCloses(bars) {
  if (!Array.isArray(bars)) return [];
  const byDate = new Map();
  for (const bar of bars) {
    if (!bar || !isPerformanceDate(bar.time)) continue;
    if (typeof bar.close !== 'number' || !Number.isFinite(bar.close) || bar.close <= 0) continue;
    byDate.set(bar.time, bar.close);
  }
  return [...byDate.entries()]
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
    .map(([date, value]) => ({ date, value }));
}

function calendarDaysBetween(from, to) {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS);
}

function median(values) {
  if (!values.length) return null;
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 === 0
    ? (ordered[middle - 1] + ordered[middle]) / 2
    : ordered[middle];
}

function medianCadenceDays(dates) {
  if (dates.length < 2) return null;
  const gaps = [];
  for (let index = 1; index < dates.length; index += 1) {
    gaps.push(calendarDaysBetween(dates[index - 1], dates[index]));
  }
  return median(gaps);
}

function invalidCoverage() {
  return {
    state: 'none',
    asOf: null,
    requestedStart: null,
    firstObservation: null,
    observations: 0,
    missingDays: null,
    cadenceDays: null,
    reason: 'invalid_dates',
  };
}

/**
 * Same coverage contract as `horizonCoverage` in
 * `src/lib/performancePeriods.ts`, with closes standing in for account values.
 */
export function stockHorizonCoverage(points, period) {
  const valid = Array.isArray(points) ? points : [];
  const observedDates = [...new Set(valid.map((point) => point.date))]
    .filter(isPerformanceDate)
    .sort();
  if (observedDates.length === 0) return invalidCoverage();

  const asOf = observedDates[observedDates.length - 1];
  const requestedStart = stockPeriodStart(asOf, period);
  if (requestedStart === null) return { ...invalidCoverage(), asOf };

  const windowDates = observedDates.filter((date) => date >= requestedStart);
  const observations = windowDates.length;
  const firstObservation = windowDates[0] ?? null;
  const missingDays = firstObservation === null
    ? null
    : calendarDaysBetween(requestedStart, firstObservation);
  const cadenceDays = medianCadenceDays(observations >= 2 ? windowDates : observedDates);
  const base = { asOf, requestedStart, firstObservation, observations, missingDays, cadenceDays };

  if (period === '1w') {
    if (cadenceDays !== null && cadenceDays > 7) {
      return { ...base, state: 'partial', reason: 'coarse_cadence' };
    }
    if (observations < 3) {
      return { ...base, state: 'partial', reason: 'insufficient_observations' };
    }
  } else if (observations < 2) {
    return { ...base, state: 'none', reason: 'insufficient_observations' };
  }

  if (missingDays !== null && missingDays > 31) return { ...base, state: 'none', reason: 'truncated_window' };
  if (missingDays !== null && missingDays > 7) return { ...base, state: 'partial', reason: 'short_history' };
  return { ...base, state: 'full', reason: 'covered' };
}

/**
 * Same return as `navReturn` in `src/lib/nav-returns.ts`: first observation at
 * or after the requested start through the series' own last close.
 */
export function stockNavReturn(points, period) {
  if (!Array.isArray(points) || points.length < 2) return null;
  const requestedStart = stockPeriodStart(points[points.length - 1].date, period);
  if (requestedStart === null) return null;
  const startIndex = points.findIndex((point) => point.date >= requestedStart);
  if (startIndex < 0) return null;
  const start = points[startIndex];
  const end = points[points.length - 1];
  if (!(start.value > 0)) return null;
  return end.value / start.value - 1;
}

export function formatPeriodLabel(period) {
  return period.toUpperCase();
}

/** Same human-readable reasons as `coverageReason` in `src/lib/model-ranking.ts`. */
function coverageReason(period, coverage) {
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
 * Same display policy as `rankingCell`: a fully covered window or a short
 * history missing at most seven days renders its observed return; everything
 * else renders `null` with the coverage reason. A one-point window is never a
 * zero return.
 */
export function stockReturnCell(points, period) {
  const coverage = stockHorizonCoverage(points, period);
  const observed = stockNavReturn(points, period);
  if (coverage.state === 'full' && observed !== null && Number.isFinite(observed)) {
    return { value: observed, reason: null };
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
      reason: `First observation ${coverage.firstObservation}; the requested window starts ${coverage.requestedStart}.`,
    };
  }
  return { value: null, reason: coverageReason(period, coverage) };
}

/**
 * Deterministic per-market projection. Input `symbols` are verified catalog
 * rows plus their parsed price payload. Rows sort by symbol so byte-for-byte
 * output depends only on the sealed source.
 */
export function buildStockRankingsProjection({ market, cutoff, symbols }) {
  if (market !== 'us' && market !== 'cn') {
    throw new Error('Stock ranking projection requires a US or China market.');
  }
  if (!isPerformanceDate(cutoff)) {
    throw new Error('Stock ranking projection requires a valid evidence cutoff.');
  }
  if (!Array.isArray(symbols)) {
    throw new Error('Stock ranking projection requires symbol evidence.');
  }

  const seen = new Set();
  const rows = [];
  for (const item of symbols) {
    if (!item || !Array.isArray(item.roles) || !item.roles.includes(SELECTED_POOL_CANDIDATE_ROLE)) continue;
    const symbol = String(item.symbol ?? '');
    if (!SAFE_SYMBOL.test(symbol)) {
      throw new Error(`Stock ranking projection has an unsafe symbol: ${symbol || '(empty)'}.`);
    }
    if (seen.has(symbol)) {
      throw new Error(`Stock ranking projection has a duplicate symbol: ${symbol}.`);
    }
    seen.add(symbol);
    const points = normalizeCloses(item.bars);
    if (points.length === 0) {
      throw new Error(`Stock ranking projection found no usable closes for ${market}:${symbol}.`);
    }
    const last = points[points.length - 1];
    const returns = {};
    for (const period of STOCK_RANKING_PERIODS) {
      returns[period] = stockReturnCell(points, period);
    }
    rows.push({
      symbol,
      name: typeof item.name === 'string' && item.name ? item.name : symbol,
      as_of: last.date,
      cutoff,
      returns,
    });
  }
  rows.sort((left, right) => (left.symbol < right.symbol ? -1 : left.symbol > right.symbol ? 1 : 0));

  return {
    schema_version: STOCK_RANKINGS_SCHEMA,
    view: STOCK_RANKINGS_VIEW,
    research_only: true,
    trade_ready: false,
    market,
    cutoff,
    periods: [...STOCK_RANKING_PERIODS],
    rows,
  };
}
