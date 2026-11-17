/**
 * Typed extension point for task C (indicator overlays). The security chart
 * renderer stays `lightweight-charts`; callers add browser-derived line or
 * histogram series on the price pane, the volume pane, or a dedicated
 * indicator pane. No indicator is computed or enabled here.
 */
export interface SecurityChartOverlayPoint {
  time: string;
  value: number;
  /** Histogram point color; defaults to the series color. */
  color?: string;
}

export interface SecurityChartOverlayPriceFormat {
  type: 'price' | 'volume' | 'custom';
  precision?: number;
  minMove?: number;
  formatter?: (value: number) => string;
}

/**
 * Theme-resolved categorical roles. The renderer maps these to concrete canvas
 * colors from `chart-theme`, so a dark-mode switch repaints the overlays without
 * the caller re-reading CSS custom properties. `positive`/`negative` are
 * reserved polarity cues, and `muted` is annotation ink for the volume moving
 * average. `primary`/`baseline` are the instrument and market-baseline lines;
 * `model-*` reuse the fixed model identity order and `entity-*` the validated
 * instrument comparison order, so compare overlays follow the active theme.
 */
export type OverlayColorRole =
  | 'indicator-1'
  | 'indicator-2'
  | 'indicator-3'
  | 'indicator-4'
  | 'positive'
  | 'negative'
  | 'muted'
  | 'primary'
  | 'baseline'
  | 'model-1'
  | 'model-2'
  | 'model-3'
  | 'model-4'
  | 'model-5'
  | 'entity-1'
  | 'entity-2'
  | 'entity-3'
  | 'entity-4';

export interface SecurityChartOverlay {
  /** Stable identity; the chart updates this series in place. */
  id: string;
  label: string;
  kind: 'line' | 'histogram';
  data: readonly SecurityChartOverlayPoint[];
  /**
   * `price` shares the candle's right scale, `volume` shares the zero-based
   * volume overlay scale, and `indicator` creates a dedicated lower pane.
   */
  pane?: 'price' | 'volume' | 'indicator';
  /** Distinguishes multiple indicator panes; ignored for price/volume. */
  paneId?: string;
  /** Concrete canvas color (CSS custom properties cannot resolve in canvas). */
  color?: string;
  /** Theme-resolved role; takes precedence over `color` when provided. */
  colorRole?: OverlayColorRole;
  lineWidth?: 1 | 2 | 3 | 4;
  lineStyle?: 'solid' | 'dashed';
  priceFormat?: SecurityChartOverlayPriceFormat;
  scaleMargins?: { top: number; bottom: number };
  visible?: boolean;
}

/** Stable pane key used to create and reuse indicator panes. */
export function overlayPaneKey(overlay: Pick<SecurityChartOverlay, 'pane' | 'paneId'>): string {
  if (overlay.pane !== 'indicator') return '__main__';
  return overlay.paneId && overlay.paneId.trim() !== '' ? overlay.paneId : 'indicator';
}

/** Exact observations only; invalid times/values are skipped, never filled. */
export function toLightweightOverlayData(
  overlay: Pick<SecurityChartOverlay, 'data'>,
): Array<{ time: string; value: number; color?: string }> {
  if (!Array.isArray(overlay.data)) return [];
  return overlay.data
    .filter(point => typeof point.time === 'string' && point.time !== ''
      && Number.isFinite(point.value))
    .map(point => ({
      time: point.time,
      value: point.value,
      ...(point.color ? { color: point.color } : {}),
    }));
}
