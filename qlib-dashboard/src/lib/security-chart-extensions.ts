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
