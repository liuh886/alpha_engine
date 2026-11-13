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
import { formatIndexedReturn, formatSecurityPrice } from '@/lib/security-format';
import { cn } from '@/lib/utils';
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
const PRICE_TABLE_ROWS = 120;
const VOLUME_FORMAT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

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
 * Chart-shaped loading placeholder. Muted rows and blocks stand in for axes and
 * an indexed series without relying on animation; the real status message stays
 * in the accessibility tree through `role="status"`.
 */
function ChartLoadingSkeleton({ message }: { message: string }) {
  return (
    <div
      role="status"
      aria-busy="true"
      data-testid="security-chart-loading"
      className="absolute inset-0 flex flex-col justify-between gap-3 bg-card p-4"
    >
      <span className="sr-only">{message}</span>
      <div aria-hidden="true" className="flex min-h-0 flex-1 gap-3">
        <div className="flex w-10 shrink-0 flex-col justify-between py-2">
          {[0, 1, 2, 3, 4].map((row) => <span key={row} className="h-2 w-8 rounded-sm bg-muted" />)}
        </div>
        <div className="relative flex min-w-0 flex-1 flex-col justify-between border-b border-l border-border/60 py-2">
          {[0, 1, 2, 3, 4].map((row) => <span key={row} className="w-full border-t border-border/50" />)}
          <div className="absolute inset-x-3 bottom-2 top-2 flex items-end justify-between gap-1.5">
            {[42, 58, 36, 66, 48, 74, 55, 68, 39, 61, 72, 50].map((height, index) => (
              <span key={index} className="w-full rounded-sm bg-muted" style={{ height: `${height}%` }} />
            ))}
          </div>
        </div>
      </div>
      <div aria-hidden="true" className="flex justify-between pl-12">
        {[0, 1, 2, 3, 4, 5].map((tick) => <span key={tick} className="h-2 w-8 rounded-sm bg-muted" />)}
      </div>
    </div>
  );
}

/**
 * Display-only OHLCV rows for the visible range, mirroring the NAV chart's data
 * disclosure. The DOM stays bounded to the most recent 120 sessions and the
 * bound is stated in the disclosure.
 */
function PriceDataTable({ bars }: { bars: SecurityBar[] }) {
  if (bars.length === 0) return null;
  const shown = bars.slice(-PRICE_TABLE_ROWS);
  const bounded = shown.length < bars.length;
  return (
    <details data-testid="price-data" className="rounded-lg border bg-card/60">
      <summary className="research-touch min-h-8 cursor-pointer px-3 py-2 text-[11px] font-medium text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1">
        View price data table
      </summary>
      <div className="max-h-72 overflow-auto border-t">
        <table className="w-full border-collapse text-[11px]">
          <caption className="sr-only">
            Visible-range OHLCV sessions; {bounded
              ? `the most recent ${shown.length} of ${bars.length} observations are shown.`
              : `${shown.length} observation${shown.length === 1 ? '' : 's'} are shown.`}
          </caption>
          <thead className="sticky top-0 bg-card">
            <tr className="border-b">
              {['Date', 'Open', 'High', 'Low', 'Close', 'Volume'].map((label, index) => (
                <th key={label} scope="col" className={cn('px-2 py-1 font-semibold text-muted-foreground', index === 0 ? 'text-left' : 'text-right')}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((bar) => (
              <tr key={bar.time} className="border-b last:border-b-0">
                <th scope="row" className="px-2 py-1 text-left font-normal tabular-nums">{bar.time}</th>
                <td className="px-2 py-1 text-right font-mono tabular-nums">{formatSecurityPrice(bar.open)}</td>
                <td className="px-2 py-1 text-right font-mono tabular-nums">{formatSecurityPrice(bar.high)}</td>
                <td className="px-2 py-1 text-right font-mono tabular-nums">{formatSecurityPrice(bar.low)}</td>
                <td className="px-2 py-1 text-right font-mono tabular-nums">{formatSecurityPrice(bar.close)}</td>
                <td className="px-2 py-1 text-right font-mono tabular-nums">{VOLUME_FORMAT.format(bar.volume)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t px-3 py-2 text-[10px] leading-4 text-muted-foreground">
        {bounded
          ? `Showing the most recent ${shown.length} of ${bars.length} visible-range sessions; older sessions are omitted from this table.`
          : `Showing all ${shown.length} visible-range session${shown.length === 1 ? '' : 's'}.`}{' '}
        Raw OHLCV, not split or dividend adjusted.
      </p>
    </details>
  );
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
  loading = false,
}: {
  bars: SecurityBar[];
  markers: SecurityMarker[];
  mode: SecurityChartMode;
  baselineSeries: IndexedBaselineSeries | null;
  /** Changes only on range/mode/baseline-window changes; drives one fitContent. */
  fitKey: string;
  onSelect: (events: SecurityEvent[]) => void;
  emptyMessage: string;
  /** True while the comparison series is still being read. */
  loading?: boolean;
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
        {canvasSupported && showEmpty && loading && (
          <ChartLoadingSkeleton message={emptyMessage} />
        )}
        {canvasSupported && showEmpty && !loading && (
          <div
            role="status"
            data-testid="security-chart-empty"
            className="absolute inset-0 flex items-center justify-center bg-card/85 p-6 text-center text-sm text-muted-foreground"
          >
            {emptyMessage}
          </div>
        )}
      </div>
      <PriceDataTable bars={bars} />
      <p className="text-[10px] leading-4 text-muted-foreground">
        TradingView Lightweight Charts™ · Apache License 2.0. Drag to pan, scroll to zoom, click a bar or hover a
        marker session to inspect the exact model evidence.
      </p>
    </div>
  );
}
