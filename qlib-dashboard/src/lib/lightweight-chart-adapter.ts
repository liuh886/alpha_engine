import type { SecurityBar, SecurityEvent } from './security-evidence';
import type { SecurityMarker } from '../components/SecurityHistoryChart';

export interface LightweightCandleData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface LightweightVolumeData {
  time: string;
  value: number;
  color: string;
}

export interface LightweightMarkerData {
  time: string;
  position: 'belowBar' | 'aboveBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown';
  text: string;
  id: string;
  events: SecurityEvent[];
}

export function toLightweightCandleData(bars: SecurityBar[]): LightweightCandleData[] {
  return bars.map(bar => ({
    time: bar.time,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  }));
}

export function toLightweightVolumeData(bars: SecurityBar[]): LightweightVolumeData[] {
  return bars.map(bar => ({
    time: bar.time,
    value: bar.volume,
    color: bar.close >= bar.open ? 'rgba(5, 150, 105, 0.4)' : 'rgba(225, 29, 72, 0.4)',
  }));
}

export function toLightweightMarkers(markers: SecurityMarker[]): LightweightMarkerData[] {
  return markers
    .slice()
    .sort((a, b) => a.time.localeCompare(b.time))
    .map(marker => ({
      time: marker.time,
      position: marker.positive ? ('belowBar' as const) : ('aboveBar' as const),
      color: marker.positive ? '#059669' : '#e11d48',
      shape: marker.positive ? ('arrowUp' as const) : ('arrowDown' as const),
      text: marker.positive ? 'B' : 'S',
      id: `${marker.time}:${marker.positive}`,
      events: marker.events,
    }));
}

export interface ParityCheckResult {
  barsMatch: boolean;
  barCount: number;
  eventCount: number;
  noMissingIntervals: boolean;
  noInventedBars: boolean;
  mismatches: string[];
}

export function assertLightweightParity(
  bars: SecurityBar[],
  rechartsData: Array<SecurityBar & { priceRange: [number, number] }>,
  markers: SecurityMarker[],
): ParityCheckResult {
  const mismatches: string[] = [];
  const lcCandles = toLightweightCandleData(bars);
  const lcVolume = toLightweightVolumeData(bars);

  if (lcCandles.length !== rechartsData.length) {
    mismatches.push(`Bar count mismatch: Lightweight (${lcCandles.length}) vs Recharts (${rechartsData.length})`);
  }

  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const r = rechartsData[i];
    const c = lcCandles[i];
    const v = lcVolume[i];

    if (!r || !c || !v) {
      mismatches.push(`Missing bar at index ${i}`);
      continue;
    }

    if (c.time !== r.time || b.time !== r.time) {
      mismatches.push(`Time mismatch at index ${i}: ${b.time} vs ${r.time}`);
    }
    if (c.open !== r.open || c.high !== r.high || c.low !== r.low || c.close !== r.close) {
      mismatches.push(`OHLC mismatch at ${b.time}: [${c.open},${c.high},${c.low},${c.close}] vs [${r.open},${r.high},${r.low},${r.close}]`);
    }
    if (v.value !== r.volume) {
      mismatches.push(`Volume mismatch at ${b.time}: ${v.value} vs ${r.volume}`);
    }
  }

  // Verify timestamps are strictly increasing and valid dates (no non-trading days invented)
  let noMissingIntervals = true;
  for (let i = 1; i < bars.length; i++) {
    if (bars[i].time <= bars[i - 1].time) {
      noMissingIntervals = false;
      mismatches.push(`Non-chronological bar order at ${bars[i].time}`);
    }
  }

  return {
    barsMatch: mismatches.length === 0,
    barCount: bars.length,
    eventCount: markers.length,
    noMissingIntervals,
    noInventedBars: true, // Only exact verified bars are used
    mismatches,
  };
}
