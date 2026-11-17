/**
 * Any-entity comparison for the security chart. One global exact common window
 * is the intersection of every displayed entity's observed dates; each series
 * is rebased to 100 at that single start. Nothing is interpolated, forward
 * filled or snapped, and no series is rebased on a different window.
 */
import type { NavPoint } from './nav-series';
import { isPerformanceDate, positiveNumber } from './performancePeriods';
import type { SecuritySymbol } from './security-evidence';

/** Hard cap for entity overlays beside the page's own instrument. */
export const MAX_COMPARE_OVERLAYS = 4;

export type CompareEntityKind = 'instrument' | 'model';

export interface EntitySeriesInput {
  id: string;
  label: string;
  points: readonly NavPoint[];
}

export interface RebasedEntitySeries {
  id: string;
  label: string;
  points: NavPoint[];
}

export interface RebasedEntityWindow {
  /** First exact observation shared by every displayed series. */
  startDate: string;
  endDate: string;
  observations: number;
  series: RebasedEntitySeries[];
}

export interface CompareEntityOption {
  id: string;
  kind: CompareEntityKind;
  label: string;
  detail: string;
  available: boolean;
  reason?: string;
}

export interface CompareEntitySelection {
  id: string;
  kind: CompareEntityKind;
  label: string;
  /**
   * Fixed palette slot (0-3) for instruments, assigned on add and never
   * reassigned while the entity stays selected, so removing a neighbour never
   * repaints the survivors. Models carry no slot and use model identity tokens.
   */
  colorSlot?: number;
}

export function instrumentEntityId(market: string, symbol: string): string {
  return `instrument:${market}:${symbol.trim().toUpperCase()}`;
}

export function modelEntityId(market: string, modelVersionId: string): string {
  return `model:${market}:${modelVersionId}`;
}

/**
 * One valid observation per date; the last duplicate wins. Invalid dates,
 * non-finite and non-positive values are dropped rather than filled.
 */
export function entityPointMap(points: readonly NavPoint[]): Map<string, number> {
  const byDate = new Map<string, number>();
  if (!Array.isArray(points)) return byDate;
  for (const point of points) {
    if (!point || !isPerformanceDate(point.date)) continue;
    const value = positiveNumber(point.value);
    if (value === null) continue;
    byDate.set(point.date, value);
  }
  return byDate;
}

/**
 * Exact observed dates present in every series, ascending. A single series
 * returns its own valid dates. An empty or invalid series yields no window.
 */
export function commonExactDates(inputs: readonly EntitySeriesInput[]): string[] {
  if (inputs.length === 0) return [];
  const maps = inputs.map(input => entityPointMap(input.points));
  if (maps.some(map => map.size === 0)) return [];
  const [first, ...rest] = maps;
  return [...first.keys()].filter(date => rest.every(map => map.has(date))).sort();
}

/**
 * Rebase every displayed series to 100 at the global exact common start. Only
 * exact shared observations are emitted, so all series share one window and
 * one indexed axis. Returns null when the window has fewer than two dates.
 */
export function rebaseEntityWindow(
  inputs: readonly EntitySeriesInput[],
): RebasedEntityWindow | null {
  const dates = commonExactDates(inputs);
  if (dates.length < 2) return null;
  const maps = inputs.map(input => entityPointMap(input.points));
  const startDate = dates[0];
  const series = inputs.map((input, index) => {
    const base = maps[index].get(startDate) as number;
    return {
      id: input.id,
      label: input.label,
      points: dates.map(date => ({
        date,
        value: ((maps[index].get(date) as number) / base) * 100,
      })),
    };
  });
  return {
    startDate,
    endDate: dates[dates.length - 1],
    observations: dates.length,
    series,
  };
}

/**
 * Whether an entity can join the current displayed set without collapsing the
 * window. A series with fewer than two exact dates in common with the base is
 * reported unavailable instead of blanking every other line.
 */
export function entityOverlapsWindow(
  basePoints: readonly NavPoint[],
  points: readonly NavPoint[],
): boolean {
  return commonExactDates([
    { id: 'base', label: 'base', points: basePoints },
    { id: 'overlay', label: 'overlay', points },
  ]).length >= 2;
}

/** First unused fixed palette slot, or null when all four are taken. */
export function firstFreeEntitySlot(used: readonly number[]): number | null {
  for (let slot = 0; slot < MAX_COMPARE_OVERLAYS; slot += 1) {
    if (!used.includes(slot)) return slot;
  }
  return null;
}

/** Case-insensitive symbol/name search used by the compare picker. */
export function filterEntityOptions(
  options: readonly CompareEntityOption[],
  query: string,
): CompareEntityOption[] {
  const needle = query.trim().toLowerCase();
  if (needle === '') return [...options];
  return options.filter(option => (
    option.label.toLowerCase().includes(needle)
    || option.detail.toLowerCase().includes(needle)
  ));
}

/**
 * Same-market instrument options from the market evidence catalog. The base
 * instrument is never offered, and no symbol from another market can enter.
 */
export function instrumentEntityOptions(
  market: string,
  symbols: readonly SecuritySymbol[],
  baseSymbol: string,
): CompareEntityOption[] {
  const base = baseSymbol.trim().toUpperCase();
  return symbols
    .filter(symbol => symbol.symbol.toUpperCase() !== base)
    .map(symbol => ({
      id: instrumentEntityId(market, symbol.symbol),
      kind: 'instrument' as const,
      label: symbol.symbol,
      detail: symbol.name,
      available: true,
    }))
    .sort((left, right) => left.label.localeCompare(right.label));
}
