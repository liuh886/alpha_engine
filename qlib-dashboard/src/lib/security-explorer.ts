import { format, parseISO, subMonths, subYears } from 'date-fns';

import type { FormalModelEvent, MarketBar } from './market-evidence';

export type SecurityChartRange = '6m' | '1y' | '3y' | 'all';

export interface SecurityRangeSummary {
  firstTime: string;
  lastTime: string;
  returnPct: number;
  high: number;
  low: number;
  latestVolume: number;
  barCount: number;
  eventCount: number;
}

export function validSecurityChartRange(value: string | null | undefined): SecurityChartRange {
  return value === '6m' || value === '1y' || value === '3y' || value === 'all' ? value : '1y';
}

function rangeCutoff(latestTime: string, range: SecurityChartRange): string | null {
  if (range === 'all') return null;
  const latest = parseISO(latestTime);
  const cutoff = range === '6m'
    ? subMonths(latest, 6)
    : range === '1y'
      ? subYears(latest, 1)
      : subYears(latest, 3);
  return format(cutoff, 'yyyy-MM-dd');
}

export function barsForSecurityRange(bars: MarketBar[], range: SecurityChartRange): MarketBar[] {
  if (bars.length === 0 || range === 'all') return bars;
  const cutoff = rangeCutoff(bars[bars.length - 1].time, range);
  if (!cutoff) return bars;
  const filtered = bars.filter((bar) => bar.time >= cutoff);
  return filtered.length > 0 ? filtered : [bars[bars.length - 1]];
}

export function summarizeSecurityRange(
  bars: MarketBar[],
  events: FormalModelEvent[],
  range: SecurityChartRange,
): SecurityRangeSummary | null {
  const visible = barsForSecurityRange(bars, range);
  if (visible.length === 0) return null;
  const first = visible[0];
  const last = visible[visible.length - 1];
  const eventCount = events.filter((event) => event.time >= first.time && event.time <= last.time).length;
  return {
    firstTime: first.time,
    lastTime: last.time,
    returnPct: last.close / first.close - 1,
    high: Math.max(...visible.map((bar) => bar.high)),
    low: Math.min(...visible.map((bar) => bar.low)),
    latestVolume: last.volume,
    barCount: visible.length,
    eventCount,
  };
}
