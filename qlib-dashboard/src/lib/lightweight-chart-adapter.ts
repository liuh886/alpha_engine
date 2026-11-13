import type { NavPoint } from './nav-series';
import type { SecurityBar } from './security-evidence';
import type { SecurityMarker } from './security-markers';

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

/** A point on the indexed (100 = start) instrument/baseline line. */
export interface LightweightLineData {
  time: string;
  value: number;
}

export interface LightweightMarkerData {
  time: string;
  position: 'belowBar' | 'aboveBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown';
  id: string;
  size: number;
  events: SecurityMarker['events'];
}

export interface VolumeColors {
  up: string;
  down: string;
}

export interface MarkerColors {
  buy: string;
  sell: string;
}

export function toLightweightCandleData(bars: readonly SecurityBar[]): LightweightCandleData[] {
  return bars.map(bar => ({
    time: bar.time,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
  }));
}

export function toLightweightVolumeData(
  bars: readonly SecurityBar[],
  colors: VolumeColors,
): LightweightVolumeData[] {
  return bars.map(bar => ({
    time: bar.time,
    value: bar.volume,
    color: bar.close >= bar.open ? colors.up : colors.down,
  }));
}

export function toLightweightLineData(points: readonly NavPoint[]): LightweightLineData[] {
  return points
    .filter(point => typeof point.date === 'string' && Number.isFinite(point.value))
    .map(point => ({ time: point.date, value: point.value }));
}

/**
 * Buy/increase is an upward triangle below the bar; sell/decrease is a downward
 * triangle above it. One marker per exact date/side, with a stable id and the
 * library default size of 1. Colors come from the caller's theme tokens.
 */
export function toLightweightMarkers(
  markers: readonly SecurityMarker[],
  colors: MarkerColors,
): LightweightMarkerData[] {
  return markers
    .slice()
    .sort((left, right) => left.time.localeCompare(right.time))
    .map(marker => ({
      time: marker.time,
      position: marker.positive ? ('belowBar' as const) : ('aboveBar' as const),
      color: marker.positive ? colors.buy : colors.sell,
      shape: marker.positive ? ('arrowUp' as const) : ('arrowDown' as const),
      id: `${marker.time}:${marker.positive ? 'buy' : 'sell'}`,
      size: 1,
      events: marker.events,
    }));
}
