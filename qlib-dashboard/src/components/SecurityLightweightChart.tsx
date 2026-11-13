import { useEffect, useRef, useState } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type AutoscaleInfo,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type Time,
} from 'lightweight-charts';
import type { SecurityBar, SecurityEvent } from '@/lib/security-evidence';
import type { SecurityMarker } from '@/lib/security-markers';
import type { IndexedBaselineSeries } from '@/lib/security-baseline';
import { chartTheme, type ChartTheme } from '@/lib/chart-theme';
import { formatIndexedReturn } from '@/lib/security-format';
import {
  toLightweightCandleData,
  toLightweightLineData,
  toLightweightMarkers,
  toLightweightVolumeData,
} from '@/lib/lightweight-chart-adapter';

export type SecurityChartMode = 'price' | 'baseline';

interface ChartHandles {
  chart: IChartApi;
  candle: ISeriesApi<'Candlestick'>;
  volume: ISeriesApi<'Histogram'>;
  instrument: ISeriesApi<'Line'>;
  baseline: ISeriesApi<'Line'>;
  candleMarkers: ISeriesMarkersPluginApi<Time>;
  lineMarkers: ISeriesMarkersPluginApi<Time>;
}

const PRICE_FORMAT = { type: 'price' as const, precision: 2, minMove: 0.01 };
const INDEXED_FORMAT = { type: 'custom' as const, formatter: formatIndexedReturn, minMove: 0.1 };

/**
 * Padded, data-driven price axis. Price and indexed lines keep their actual
 * range instead of snapping to zero; the volume histogram never uses this
 * provider and therefore always keeps a zero-based bar axis.
 */
function paddedPriceAutoscale(original: () => AutoscaleInfo | null): AutoscaleInfo | null {
  const info = original();
  if (!info?.priceRange) return info;
  const { minValue, maxValue } = info.priceRange;
  if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) return info;
  const span = maxValue - minValue;
  const pad = Math.max(span * 0.08, Math.abs(maxValue) * 0.002, 0.01);
  return { ...info, priceRange: { minValue: minValue - pad, maxValue: maxValue + pad } };
}

function markerTimeKey(time: Time | undefined): string | null {
  if (typeof time === 'string') return time;
  if (typeof time === 'number') return new Date(time * 1000).toISOString().slice(0, 10);
  if (time && typeof time === 'object' && 'year' in time) {
    const day = time as { year: number; month: number; day: number };
    return `${day.year}-${String(day.month).padStart(2, '0')}-${String(day.day).padStart(2, '0')}`;
  }
  return null;
}

function eventsBySession(markers: readonly SecurityMarker[]): Map<string, SecurityEvent[]> {
  const groups = new Map<string, SecurityEvent[]>();
  for (const marker of markers) {
    const events = groups.get(marker.time) ?? [];
    events.push(...marker.events);
    groups.set(marker.time, events);
  }
  return groups;
}

function isDarkTheme(): boolean {
  return typeof document !== 'undefined' && document.documentElement.classList.contains('dark');
}

/**
 * The single interactive chart instance for an instrument page.
 *
 * Lifecycle contract: the chart and its series/marker plugins are created once
 * per mount. Bars, markers, mode and baseline changes only call `setData` and
 * `setMarkers`; nothing here is rebuilt when the range, selection or callback
 * identity changes. `autoSize` owns width via ResizeObserver, and a
 * MutationObserver follows the document theme class.
 */
export function SecurityLightweightChart({
  bars,
  markers,
  mode,
  baselineSeries,
  fitKey,
  onSelect,
  emptyMessage,
}: {
  bars: SecurityBar[];
  markers: SecurityMarker[];
  mode: SecurityChartMode;
  baselineSeries: IndexedBaselineSeries | null;
  /** Changes only on range/mode/baseline-window changes; drives one fitContent. */
  fitKey: string;
  onSelect: (events: SecurityEvent[]) => void;
  emptyMessage: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const handlesRef = useRef<ChartHandles | null>(null);
  const themeRef = useRef<ChartTheme | null>(null);
  const barsRef = useRef<SecurityBar[]>(bars);
  const markersRef = useRef<SecurityMarker[]>(markers);
  const modeRef = useRef<SecurityChartMode>(mode);
  const onSelectRef = useRef(onSelect);
  const sessionEventsRef = useRef<Map<string, SecurityEvent[]>>(eventsBySession(markers));
  const [canvasSupported, setCanvasSupported] = useState(true);

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const theme = chartTheme(isDarkTheme());
    themeRef.current = theme;

    let chart: IChartApi;
    try {
      chart = createChart(container, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: theme.text,
          fontSize: 11,
          attributionLogo: false,
        },
        grid: {
          vertLines: { color: theme.grid },
          horzLines: { color: theme.grid },
        },
        crosshair: {
          mode: CrosshairMode.Normal,
          vertLine: { color: theme.crosshair, style: LineStyle.Dashed, width: 1 },
          horzLine: { color: theme.crosshair, style: LineStyle.Dashed, width: 1 },
        },
        rightPriceScale: {
          borderColor: theme.border,
          scaleMargins: { top: 0.1, bottom: 0.22 },
        },
        timeScale: {
          borderColor: theme.border,
          timeVisible: false,
          secondsVisible: false,
          rightOffset: 3,
        },
      });
    } catch {
      setCanvasSupported(false);
      return;
    }

    const candle = chart.addSeries(CandlestickSeries, {
      upColor: theme.candleUp,
      downColor: theme.candleDown,
      borderVisible: false,
      wickUpColor: theme.candleUp,
      wickDownColor: theme.candleDown,
      priceFormat: PRICE_FORMAT,
      autoscaleInfoProvider: paddedPriceAutoscale,
    });
    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: '',
      priceFormat: { type: 'volume' },
      lastValueVisible: false,
      priceLineVisible: false,
      visible: false,
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    const instrument = chart.addSeries(LineSeries, {
      color: theme.primary,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      visible: false,
      autoscaleInfoProvider: paddedPriceAutoscale,
    });
    const baseline = chart.addSeries(LineSeries, {
      color: theme.baseline,
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
      visible: false,
      autoscaleInfoProvider: paddedPriceAutoscale,
    });
    const candleMarkers = createSeriesMarkers(candle, []);
    const lineMarkers = createSeriesMarkers(instrument, []);
    const handles: ChartHandles = { chart, candle, volume, instrument, baseline, candleMarkers, lineMarkers };
    handlesRef.current = handles;

    let lastHoverSession: string | null = null;
    const selectSession = (time: Time | undefined) => {
      const key = markerTimeKey(time);
      if (!key) return;
      const events = sessionEventsRef.current.get(key);
      if (events && events.length > 0) onSelectRef.current(events);
    };
    const handleClick = (param: MouseEventParams) => selectSession(param.time);
    const handleCrosshair = (param: MouseEventParams) => {
      if (!param.point) {
        lastHoverSession = null;
        return;
      }
      const key = markerTimeKey(param.time);
      if (!key || key === lastHoverSession) return;
      lastHoverSession = key;
      selectSession(param.time);
    };
    chart.subscribeClick(handleClick);
    chart.subscribeCrosshairMove(handleCrosshair);

    const applyTheme = (next: ChartTheme) => {
      themeRef.current = next;
      chart.applyOptions({
        layout: { textColor: next.text },
        grid: { vertLines: { color: next.grid }, horzLines: { color: next.grid } },
        crosshair: {
          vertLine: { color: next.crosshair },
          horzLine: { color: next.crosshair },
        },
        rightPriceScale: { borderColor: next.border },
        timeScale: { borderColor: next.border },
      });
      candle.applyOptions({
        upColor: next.candleUp,
        downColor: next.candleDown,
        wickUpColor: next.candleUp,
        wickDownColor: next.candleDown,
      });
      instrument.applyOptions({ color: next.primary });
      baseline.applyOptions({ color: next.baseline });
      volume.setData(toLightweightVolumeData(barsRef.current, { up: next.volumeUp, down: next.volumeDown }));
      const markerData = toLightweightMarkers(markersRef.current, { buy: next.positive, sell: next.negative });
      if (modeRef.current === 'baseline') {
        lineMarkers.setMarkers(markerData);
        candleMarkers.setMarkers([]);
      } else {
        candleMarkers.setMarkers(markerData);
        lineMarkers.setMarkers([]);
      }
    };

    const observer = new MutationObserver(() => applyTheme(chartTheme(isDarkTheme())));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

    return () => {
      observer.disconnect();
      chart.unsubscribeClick(handleClick);
      chart.unsubscribeCrosshairMove(handleCrosshair);
      chart.remove();
      handlesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const handles = handlesRef.current;
    if (!handles) return;
    barsRef.current = bars;
    modeRef.current = mode;
    const theme = themeRef.current ?? chartTheme(isDarkTheme());
    if (mode === 'baseline') {
      handles.candle.applyOptions({ visible: false });
      handles.volume.applyOptions({ visible: false });
      // Clear the hidden price/volume data so only the indexed series drive
      // the shared right price scale.
      handles.candle.setData([]);
      handles.volume.setData([]);
      handles.instrument.applyOptions({ visible: true, priceFormat: INDEXED_FORMAT });
      handles.baseline.applyOptions({ visible: true, priceFormat: INDEXED_FORMAT });
      handles.instrument.setData(baselineSeries ? toLightweightLineData(baselineSeries.instrument) : []);
      handles.baseline.setData(baselineSeries ? toLightweightLineData(baselineSeries.baseline) : []);
      handles.chart.applyOptions({ rightPriceScale: { scaleMargins: { top: 0.12, bottom: 0.08 } } });
    } else {
      handles.instrument.applyOptions({ visible: false });
      handles.baseline.applyOptions({ visible: false });
      handles.instrument.setData([]);
      handles.baseline.setData([]);
      handles.candle.applyOptions({ visible: true, priceFormat: PRICE_FORMAT });
      handles.candle.setData(toLightweightCandleData(bars));
      handles.volume.applyOptions({ visible: true });
      handles.volume.setData(toLightweightVolumeData(bars, { up: theme.volumeUp, down: theme.volumeDown }));
      handles.chart.applyOptions({ rightPriceScale: { scaleMargins: { top: 0.1, bottom: 0.22 } } });
    }
  }, [bars, mode, baselineSeries]);

  useEffect(() => {
    const handles = handlesRef.current;
    if (!handles) return;
    markersRef.current = markers;
    sessionEventsRef.current = eventsBySession(markers);
    const theme = themeRef.current ?? chartTheme(isDarkTheme());
    const markerData = toLightweightMarkers(markers, { buy: theme.positive, sell: theme.negative });
    if (mode === 'baseline') {
      handles.lineMarkers.setMarkers(markerData);
      handles.candleMarkers.setMarkers([]);
    } else {
      handles.candleMarkers.setMarkers(markerData);
      handles.lineMarkers.setMarkers([]);
    }
  }, [markers, mode]);

  useEffect(() => {
    handlesRef.current?.chart.timeScale().fitContent();
  }, [fitKey]);

  const showEmpty = mode === 'baseline' ? !baselineSeries : bars.length === 0;

  return (
    <div className="space-y-1.5">
      <div className="relative w-full overflow-hidden rounded-lg border bg-card/40">
        <div
          ref={containerRef}
          data-testid="security-lightweight-chart-container"
          className="h-[300px] w-full sm:h-[380px] xl:h-[460px]"
        />
        {!canvasSupported && (
          <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-muted-foreground">
            Canvas 2D rendering is not supported in this environment. Price evidence remains available in the
            event ledger and provenance sections below.
          </div>
        )}
        {canvasSupported && mode === 'price' && !showEmpty && (
          <>
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 border-t border-border/70"
              style={{ bottom: '20%' }}
            />
            <span
              aria-hidden="true"
              className="pointer-events-none absolute bottom-6 left-2 text-[9px] font-semibold uppercase tracking-[0.08em] text-muted-foreground"
            >
              Volume · zero-based, lower 20%
            </span>
          </>
        )}
        {canvasSupported && showEmpty && (
          <div
            role="status"
            data-testid="security-chart-empty"
            className="absolute inset-0 flex items-center justify-center bg-card/85 p-6 text-center text-sm text-muted-foreground"
          >
            {emptyMessage}
          </div>
        )}
      </div>
      <p className="text-[10px] leading-4 text-muted-foreground">
        TradingView Lightweight Charts™ · Apache License 2.0. Drag to pan, scroll to zoom, click a bar or hover a
        marker session to inspect the exact model evidence.
      </p>
    </div>
  );
}
