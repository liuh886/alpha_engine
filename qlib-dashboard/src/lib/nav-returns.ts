import { alignNavSeries, rebaseNav, type NavPoint } from './nav-series';
import {
  horizonCoverage,
  performancePeriodStart,
  type HorizonCoverage,
  type PerformancePeriod,
} from './performancePeriods';
import type { ReportRow } from './types';

/**
 * Normalize to the same observation contract used by the NAV builders: valid
 * ISO dates, finite positive observations, last duplicate date wins, ascending.
 * `alignNavSeries` already implements exactly that validation.
 */
function normalizedNav(nav: NavPoint[]): NavPoint[] {
  if (!Array.isArray(nav)) return [];
  return alignNavSeries(nav, nav).map(point => ({ date: point.date, value: point.primary }));
}

/**
 * Index of the first observation at or after the requested window start.
 * The as-of date is the series' own last observation, never the wall clock.
 */
function windowStartIndex(points: NavPoint[], period: PerformancePeriod): number {
  if (points.length === 0) return -1;
  if (period === 'all') return 0;
  const requestedStart = performancePeriodStart(points[points.length - 1].date, period);
  if (requestedStart === null) return -1;
  return points.findIndex(point => point.date >= requestedStart);
}

/**
 * Period return from the first observation at or after the window start to the
 * last observation, matching `strategyPeriodSummary`/`horizonCoverage`. Missing
 * settlements are never interpolated. A window containing only its end
 * observation yields 0, exactly like `strategyPeriodSummary`; callers should
 * surface `navHorizonCoverage` when the window is not fully covered.
 */
export function navReturn(nav: NavPoint[], period: PerformancePeriod): number | null {
  const points = normalizedNav(nav);
  if (points.length < 2) return null;
  const startIndex = windowStartIndex(points, period);
  if (startIndex < 0) return null;
  const start = points[startIndex];
  const end = points[points.length - 1];
  if (start.value <= 0) return null;
  return end.value / start.value - 1;
}

/**
 * Coverage for a NAV curve, delegated to the existing `horizonCoverage` report
 * contract so cadence and window rules cannot drift between the two surfaces.
 */
export function navHorizonCoverage(nav: NavPoint[], period: PerformancePeriod): HorizonCoverage {
  const rows: ReportRow[] = normalizedNav(nav).map(point => ({ date: point.date, account: point.value }));
  return horizonCoverage(rows, period);
}

/**
 * Window observations rebased to 100 at the first retained observation. The
 * first point keeps its actual observed date; no synthetic start is inserted.
 */
export function navSeriesForPeriod(nav: NavPoint[], period: PerformancePeriod): NavPoint[] {
  const points = normalizedNav(nav);
  if (points.length === 0) return [];
  const startIndex = windowStartIndex(points, period);
  if (startIndex < 0) return [];
  return rebaseNav(points.slice(startIndex)).map(point => ({ date: point.date, value: point.value * 100 }));
}
