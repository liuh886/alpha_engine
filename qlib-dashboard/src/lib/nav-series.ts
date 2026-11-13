import { effectivePerformanceDate } from './performanceBenchmarks';
import { isPerformanceDate, positiveNumber } from './performancePeriods';
import type { ReportRow } from './types';

export interface NavPoint {
  date: string;
  value: number;
}

export interface AlignedNavPoint {
  date: string;
  primary: number;
  baseline: number;
}

export interface NavTrade {
  date: string;
  holding_end_date?: string | null;
  action: string;
  previous_weight?: number | null;
  target_weight?: number | null;
  instrument?: string | null;
  reason?: string | null;
}

export interface NavMarker {
  date: string;
  side: 'buy' | 'sell' | 'mixed';
  count: number;
  instruments: string[];
  netWeightDelta: number | null;
  reasons: string[];
}

type MarkerMode = 'trade-date' | 'holding-end';

function isValidNavPoint(point: NavPoint | null | undefined): point is NavPoint {
  return point !== null && point !== undefined
    && isPerformanceDate(point.date)
    && Number.isFinite(point.value)
    && point.value > 0;
}

function validPointMap(points: NavPoint[]): Map<string, number> {
  const values = new Map<string, number>();
  if (!Array.isArray(points)) return values;
  for (const point of points) {
    if (isValidNavPoint(point)) values.set(point.date, point.value);
  }
  return values;
}

/**
 * Extract the observed NAV curve. Rows without a usable settlement date or
 * positive account are dropped rather than forward-filled; duplicate effective
 * dates keep the last observation.
 */
export function navFromReport(report: ReportRow[]): NavPoint[] {
  if (!Array.isArray(report)) return [];
  const byDate = new Map<string, number>();
  for (const row of report) {
    if (!row) continue;
    const date = effectivePerformanceDate(row);
    if (!isPerformanceDate(date)) continue;
    const value = positiveNumber(row.account);
    if (value === null) continue;
    byDate.set(date, value);
  }
  return [...byDate.entries()]
    .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
    .map(([date, value]) => ({ date, value }));
}

/** Rebase a curve to 1.0 at its first valid observation, without interpolation. */
export function rebaseNav(points: NavPoint[]): NavPoint[] {
  if (!Array.isArray(points)) return [];
  const valid = points.filter(isValidNavPoint);
  if (valid.length === 0) return [];
  const base = valid[0].value;
  return valid.map(point => ({ date: point.date, value: point.value / base }));
}

/**
 * Deterministic Largest-Triangle-Three-Buckets downsampling. The first and last
 * points are always preserved, and ties keep the earliest candidate in a bucket.
 */
export function downsampleLttb(points: NavPoint[], maxPoints: number): NavPoint[] {
  if (!Array.isArray(points) || points.length === 0) return [];
  if (!Number.isFinite(maxPoints)) return points.slice();
  const limit = Math.floor(maxPoints);
  if (points.length <= limit) return points.slice();
  if (limit <= 0) return [];
  if (limit === 1) return [points[0]];
  if (limit === 2) return [points[0], points[points.length - 1]];

  const sampled: NavPoint[] = [points[0]];
  const bucketWidth = (points.length - 2) / (limit - 2);
  let anchorIndex = 0;

  for (let bucket = 0; bucket < limit - 2; bucket += 1) {
    const nextStart = Math.floor((bucket + 1) * bucketWidth) + 1;
    const nextEnd = Math.min(Math.floor((bucket + 2) * bucketWidth) + 1, points.length);
    let averageX = 0;
    let averageY = 0;
    for (let index = nextStart; index < nextEnd; index += 1) {
      averageX += index;
      averageY += points[index].value;
    }
    const nextCount = nextEnd - nextStart;
    if (nextCount > 0) {
      averageX /= nextCount;
      averageY /= nextCount;
    } else {
      averageX = points.length - 1;
      averageY = points[points.length - 1].value;
    }

    const rangeStart = Math.floor(bucket * bucketWidth) + 1;
    const rangeEnd = Math.floor((bucket + 1) * bucketWidth) + 1;
    const anchorX = anchorIndex;
    const anchorY = points[anchorIndex].value;
    let selectedIndex = rangeStart;
    let maxArea = -1;
    for (let index = rangeStart; index < rangeEnd; index += 1) {
      const area = Math.abs(
        (anchorX - averageX) * (points[index].value - anchorY)
        - (anchorX - index) * (averageY - anchorY),
      );
      if (area > maxArea) {
        maxArea = area;
        selectedIndex = index;
      }
    }
    anchorIndex = selectedIndex;
    sampled.push(points[selectedIndex]);
  }

  sampled.push(points[points.length - 1]);
  return sampled;
}

/** Exact-date intersection of two curves, ascending; no interpolation or snapping. */
export function alignNavSeries(primary: NavPoint[], baseline: NavPoint[]): AlignedNavPoint[] {
  const primaryValues = validPointMap(primary);
  const baselineValues = validPointMap(baseline);
  return [...primaryValues.keys()]
    .filter(date => baselineValues.has(date))
    .sort()
    .map(date => ({
      date,
      primary: primaryValues.get(date) as number,
      baseline: baselineValues.get(date) as number,
    }));
}

/** The last `count + 1` observations, so a week curve includes the prior close. */
export function lastSessions(points: NavPoint[], count: number): NavPoint[] {
  if (!Array.isArray(points) || points.length === 0) return [];
  const sessions = Number.isFinite(count) ? Math.max(1, Math.floor(count)) : 1;
  return points.slice(-(sessions + 1));
}

function markerDate(trade: NavTrade, mode: MarkerMode): string | null {
  if (mode === 'holding-end' && isPerformanceDate(trade.holding_end_date)) {
    return trade.holding_end_date;
  }
  return isPerformanceDate(trade.date) ? trade.date : null;
}

function tradeSide(action: string): 'buy' | 'sell' | null {
  const normalized = action.trim().toUpperCase();
  if (normalized === 'BUY' || normalized === 'INCREASE') return 'buy';
  if (normalized === 'SELL' || normalized === 'DECREASE') return 'sell';
  return null;
}

function finiteWeight(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function nonEmptyText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

interface MarkerAggregate {
  sawBuy: boolean;
  sawSell: boolean;
  count: number;
  instruments: Set<string>;
  reasons: Set<string>;
  netWeightDelta: number | null;
}

/**
 * Join trades to observed NAV dates. `trade-date` marks execution decisions;
 * `holding-end` marks the settlement date when the trade carries one, falling
 * back to the trade date. HOLD rows and dates absent from the curve are ignored.
 */
export function joinNavMarkers(
  points: NavPoint[],
  trades: NavTrade[],
  mode: MarkerMode,
): NavMarker[] {
  if (!Array.isArray(points) || !Array.isArray(trades)) return [];
  const pointDates = new Set(validPointMap(points).keys());
  const markerMode: MarkerMode = mode === 'holding-end' ? 'holding-end' : 'trade-date';
  const aggregates = new Map<string, MarkerAggregate>();

  for (const trade of trades) {
    if (!trade || typeof trade.action !== 'string') continue;
    if (trade.action.trim().toUpperCase() === 'HOLD') continue;
    const date = markerDate(trade, markerMode);
    if (date === null || !pointDates.has(date)) continue;

    let aggregate = aggregates.get(date);
    if (!aggregate) {
      aggregate = {
        sawBuy: false,
        sawSell: false,
        count: 0,
        instruments: new Set<string>(),
        reasons: new Set<string>(),
        netWeightDelta: null,
      };
      aggregates.set(date, aggregate);
    }

    const side = tradeSide(trade.action);
    if (side === 'buy') aggregate.sawBuy = true;
    if (side === 'sell') aggregate.sawSell = true;
    aggregate.count += 1;

    const instrument = nonEmptyText(trade.instrument);
    if (instrument !== null) aggregate.instruments.add(instrument);
    const reason = nonEmptyText(trade.reason);
    if (reason !== null) aggregate.reasons.add(reason);

    const previous = finiteWeight(trade.previous_weight);
    const target = finiteWeight(trade.target_weight);
    if (previous !== null && target !== null) {
      aggregate.netWeightDelta = (aggregate.netWeightDelta ?? 0) + (target - previous);
    }
  }

  return [...aggregates.entries()]
    .filter(([, aggregate]) => aggregate.sawBuy || aggregate.sawSell)
    .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
    .map(([date, aggregate]) => ({
      date,
      side: aggregate.sawBuy && aggregate.sawSell ? 'mixed' : aggregate.sawBuy ? 'buy' : 'sell',
      count: aggregate.count,
      instruments: [...aggregate.instruments],
      netWeightDelta: aggregate.netWeightDelta,
      reasons: [...aggregate.reasons],
    }));
}
