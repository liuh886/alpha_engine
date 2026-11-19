/**
 * US strategy-chart VIX context.
 *
 * The pane reads the already published `us:VIX` market evidence through the
 * shared market-evidence cache. It owns no provider, no fallback series and no
 * indicator math: raw values are the exact observed closes inside the chart
 * window, and the optional average comes from the governed indicator registry
 * (`market_us_vix_sma_20`). CN charts are never offered or read.
 */

import {
  INDICATOR_REGISTRY,
  computeIndicator,
  type IndicatorEntry,
  type IndicatorPoint,
} from './indicators';
import type { SecurityBar } from './security-evidence';

export const VIX_PANE_LABEL = 'VIX · US market context';
export const VIX_SERIES_ID = 'us:VIX';
export const VIX_SMA_ID = 'market_us_vix_sma_20';
export const VIX_SMA_LABEL = 'VIX SMA 20';
export const VIX_DISCLOSURE =
  'Exact observed US VIX closes inside this chart window; browser-derived market context, not a signal.';

const VIX_SMA_ENTRY: IndicatorEntry | undefined = INDICATOR_REGISTRY.find(
  entry => entry.indicator_id === VIX_SMA_ID,
);

function inWindow(time: string, start: string, end: string): boolean {
  return time >= start && time <= end;
}

/** Exact observed VIX closes; nothing is filled, snapped or interpolated. */
export function vixPoints(
  bars: readonly SecurityBar[],
  start: string | null,
  end: string | null,
): IndicatorPoint[] {
  if (!start || !end || !Array.isArray(bars)) return [];
  return bars
    .filter(bar => bar && typeof bar.time === 'string'
      && inWindow(bar.time, start, end)
      && Number.isFinite(bar.close) && bar.close > 0)
    .map(bar => ({ time: bar.time, value: bar.close }));
}

export interface VixSmaResult {
  points: IndicatorPoint[];
  available: boolean;
  reason?: string;
}

/**
 * Governed 20-session SMA of the exact observed VIX closes. Warm-up uses the
 * full published series; the emitted values are clipped to the chart window.
 */
export function vixSmaPoints(
  bars: readonly SecurityBar[],
  start: string | null,
  end: string | null,
): VixSmaResult {
  if (!VIX_SMA_ENTRY) {
    return { points: [], available: false, reason: 'The governed VIX SMA 20 indicator is not registered.' };
  }
  if (!start || !end) {
    return { points: [], available: false, reason: 'No chart window is available yet.' };
  }
  const series = (Array.isArray(bars) ? bars : [])
    .filter(bar => bar && typeof bar.time === 'string' && Number.isFinite(bar.close) && bar.close > 0)
    .map(bar => ({ time: bar.time, value: bar.close }));
  if (series.length === 0) {
    return { points: [], available: false, reason: 'The governed us:VIX series has no published observations.' };
  }
  const computed = computeIndicator(VIX_SMA_ENTRY, {
    scope: 'market',
    market: 'us',
    series_id: VIX_SERIES_ID,
    series,
  });
  if (!computed.available) {
    return { points: [], available: false, reason: computed.detail };
  }
  const points = (computed.series.value ?? []).filter(point => inWindow(point.time, start, end));
  if (points.length === 0) {
    return { points: [], available: false, reason: 'No VIX SMA 20 value falls inside this window.' };
  }
  return { points, available: true };
}

/**
 * One explicit reason for an absent governed series. Route-404 publication
 * gaps keep their status; nothing is substituted or retried as another symbol.
 */
export function vixUnavailableReason(error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error);
  return `Governed US VIX series unavailable: ${detail} No substitute series is shown.`;
}
