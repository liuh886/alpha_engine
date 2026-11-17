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
  /** Model identity retained so the legend and detail can attribute the mark. */
  modelId?: string;
}

export interface VolumeColors {
  up: string;
  down: string;
}

/** Resolve a marker color by model identity, with an ink fallback. */
export interface MarkerColorResolver {
  modelColor: (modelId: string) => string;
  fallbackColor: string;
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
 * triangle above it. Multiple models on the same session and direction each get
 * their own marker (the chart stacks same-time markers) colored by model
 * identity, so they are never collapsed into one unnamed mark. Direction stays
 * in the shape and position, not in color.
 */
export function toLightweightMarkers(
  markers: readonly SecurityMarker[],
  colors: MarkerColorResolver,
): LightweightMarkerData[] {
  const output: LightweightMarkerData[] = [];
  for (const marker of markers) {
    const direction = marker.positive ? 'buy' : 'sell';
    if (marker.models.length === 0) {
      output.push({
        time: marker.time,
        position: marker.positive ? ('belowBar' as const) : ('aboveBar' as const),
        color: colors.fallbackColor,
        shape: marker.positive ? ('arrowUp' as const) : ('arrowDown' as const),
        id: `${marker.time}:${direction}:unattributed`,
        size: 1,
        events: marker.events,
      });
      continue;
    }
    for (const model of marker.models) {
      output.push({
        time: marker.time,
        position: marker.positive ? ('belowBar' as const) : ('aboveBar' as const),
        color: colors.modelColor(model.modelId),
        shape: marker.positive ? ('arrowUp' as const) : ('arrowDown' as const),
        id: `${marker.time}:${direction}:${model.modelId}`,
        size: 1,
        events: model.events,
        modelId: model.modelId,
      });
    }
  }
  return output.sort((left, right) =>
    left.time.localeCompare(right.time)
    || Number(left.position === 'aboveBar') - Number(right.position === 'aboveBar')
    || (left.modelId ?? '').localeCompare(right.modelId ?? ''),
  );
}
