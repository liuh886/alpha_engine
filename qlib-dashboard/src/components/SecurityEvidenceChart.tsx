import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';

import type { SecurityMarketEvidence } from '@/lib/market-evidence';
import { barsForSecurityRange, type SecurityChartRange } from '@/lib/security-explorer';

export type SecurityLowerStudy = 'macd' | 'rsi' | `factor:${string}` | 'none';

interface SecurityEvidenceChartProps {
  evidence: SecurityMarketEvidence;
  showBoll: boolean;
  lowerStudy: SecurityLowerStudy;
  visibleModelIds: Set<string>;
  range: SecurityChartRange;
}

interface CursorSnapshot {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

function markerForEvent(
  event: SecurityMarketEvidence['formal_model_events'][number],
): SeriesMarker<Time> {
  const positive = event.action === 'BUY' || event.action === 'INCREASE';
  const modelLabel = event.model_name.replace(/^US |^CN /, '');
  return {
    time: event.time as Time,
    position: positive ? 'belowBar' : 'aboveBar',
    color: positive ? '#16a34a' : '#dc2626',
    shape: positive ? 'arrowUp' : 'arrowDown',
    text: `${modelLabel} ${event.action}`,
  };
}

function lineData(rows: Array<{ time: string; value: number }>) {
  return rows.map((row) => ({ time: row.time as Time, value: row.value }));
}

function timeKey(time: Time | undefined): string | null {
  if (time === undefined) return null;
  if (typeof time === 'string') return time;
  if (typeof time === 'number') return new Date(time * 1000).toISOString().slice(0, 10);
  return `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}`;
}

function formatVolume(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return Math.round(value).toLocaleString();
}

function activeStudyLabel(lowerStudy: SecurityLowerStudy): string | null {
  if (lowerStudy === 'none') return null;
  if (lowerStudy === 'macd') return 'MACD 12,26,9';
  if (lowerStudy === 'rsi') return 'RSI 14';
  return lowerStudy.slice('factor:'.length);
}

export function SecurityEvidenceChart({ evidence, showBoll, lowerStudy, visibleModelIds, range }: SecurityEvidenceChartProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [cursor, setCursor] = useState<CursorSnapshot | null>(null);

  const latest = evidence.bars[evidence.bars.length - 1];
  const displayPoint = cursor ?? latest;
  const layers = useMemo(() => [
    'Price',
    'Volume',
    showBoll ? 'BOLL 20,2' : null,
    activeStudyLabel(lowerStudy),
  ].filter((value): value is string => Boolean(value)), [lowerStudy, showBoll]);

  useEffect(() => setCursor(null), [evidence.symbol]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;

    const chart = createChart(host, {
      width: host.clientWidth,
      height: host.clientHeight || 620,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#94a3b8',
        panes: {
          separatorColor: 'rgba(148, 163, 184, 0.18)',
          separatorHoverColor: 'rgba(148, 163, 184, 0.34)',
          enableResize: true,
        },
      },
      grid: {
        vertLines: { color: 'rgba(148, 163, 184, 0.07)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.07)' },
      },
      crosshair: {
        vertLine: { labelBackgroundColor: '#334155' },
        horzLine: { labelBackgroundColor: '#334155' },
      },
      rightPriceScale: { borderColor: 'rgba(148, 163, 184, 0.18)' },
      timeScale: {
        borderColor: 'rgba(148, 163, 184, 0.18)',
        timeVisible: false,
        rightOffset: 6,
        fixLeftEdge: true,
      },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
    });
    chartRef.current = chart;

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: '#16a34a',
      downColor: '#dc2626',
      borderVisible: false,
      wickUpColor: '#16a34a',
      wickDownColor: '#dc2626',
      priceLineVisible: false,
    }, 0);
    candles.setData(evidence.bars.map((bar) => ({
      time: bar.time as Time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    })));
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.23 } });

    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: '',
      priceFormat: { type: 'volume' },
      priceLineVisible: false,
      lastValueVisible: false,
    }, 0);
    volume.setData(evidence.bars.map((bar) => ({
      time: bar.time as Time,
      value: bar.volume,
      color: bar.close >= bar.open ? 'rgba(22,163,74,0.28)' : 'rgba(220,38,38,0.28)',
    })));
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    const markers = evidence.formal_model_events
      .filter((event) => visibleModelIds.has(event.model_id))
      .map(markerForEvent);
    if (markers.length) createSeriesMarkers(candles, markers);

    if (showBoll) {
      const boll = evidence.chart_studies.boll20;
      const middle = chart.addSeries(LineSeries, {
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        color: '#64748b',
        priceLineVisible: false,
        lastValueVisible: false,
      }, 0);
      const upper = chart.addSeries(LineSeries, {
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        color: '#8b5cf6',
        priceLineVisible: false,
        lastValueVisible: false,
      }, 0);
      const lower = chart.addSeries(LineSeries, {
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        color: '#8b5cf6',
        priceLineVisible: false,
        lastValueVisible: false,
      }, 0);
      middle.setData(boll.map((row) => ({ time: row.time as Time, value: row.middle })));
      upper.setData(boll.map((row) => ({ time: row.time as Time, value: row.upper })));
      lower.setData(boll.map((row) => ({ time: row.time as Time, value: row.lower })));
    }

    if (lowerStudy === 'macd') {
      const pane = 1;
      const macd = evidence.chart_studies.macd_12_26_9;
      const macdLine = chart.addSeries(LineSeries, { color: '#2563eb', lineWidth: 1, priceLineVisible: false }, pane);
      const signalLine = chart.addSeries(LineSeries, { color: '#f59e0b', lineStyle: LineStyle.Dashed, lineWidth: 1, priceLineVisible: false }, pane);
      const histogram = chart.addSeries(HistogramSeries, { priceLineVisible: false, priceFormat: { type: 'price', precision: 4, minMove: 0.0001 } }, pane);
      macdLine.setData(macd.map((row) => ({ time: row.time as Time, value: row.macd })));
      signalLine.setData(macd.map((row) => ({ time: row.time as Time, value: row.signal })));
      histogram.setData(macd.map((row) => ({ time: row.time as Time, value: row.histogram, color: row.histogram >= 0 ? 'rgba(22,163,74,0.5)' : 'rgba(220,38,38,0.5)' })));
      macdLine.createPriceLine({ price: 0, color: 'rgba(148,163,184,0.3)', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: '' });
    } else if (lowerStudy === 'rsi') {
      const pane = 1;
      const rsi = chart.addSeries(LineSeries, { color: '#8b5cf6', lineWidth: 1, priceLineVisible: false }, pane);
      rsi.setData(lineData(evidence.chart_studies.rsi14));
      rsi.createPriceLine({ price: 70, color: 'rgba(220,38,38,0.35)', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '70' });
      rsi.createPriceLine({ price: 30, color: 'rgba(22,163,74,0.35)', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '30' });
    } else if (lowerStudy.startsWith('factor:')) {
      const factorId = lowerStudy.slice('factor:'.length);
      const rows = evidence.factor_series[factorId] ?? [];
      const factor = chart.addSeries(LineSeries, { color: '#0ea5e9', lineWidth: 1, priceLineVisible: false }, 1);
      factor.setData(lineData(rows));
    }

    const panes = chart.panes();
    if (panes.length > 1) {
      panes[0].setHeight(430);
      panes[1].setHeight(160);
    }

    const volumeByTime = new Map(evidence.bars.map((bar) => [bar.time, bar.volume]));
    chart.subscribeCrosshairMove((param) => {
      const key = timeKey(param.time);
      const raw = param.seriesData.get(candles);
      if (!key || !raw || typeof raw !== 'object' || !('open' in raw) || !('high' in raw) || !('low' in raw) || !('close' in raw)) {
        setCursor(null);
        return;
      }
      setCursor({
        time: key,
        open: Number(raw.open),
        high: Number(raw.high),
        low: Number(raw.low),
        close: Number(raw.close),
        volume: volumeByTime.get(key) ?? 0,
      });
    });

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      chart.applyOptions({ width: Math.floor(entry.contentRect.width), height: Math.max(420, Math.floor(entry.contentRect.height)) });
    });
    resizeObserver.observe(host);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [evidence, lowerStudy, showBoll, visibleModelIds]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || evidence.bars.length === 0) return;
    const visible = barsForSecurityRange(evidence.bars, range);
    if (range === 'all' || visible.length === 0) {
      chart.timeScale().fitContent();
      return;
    }
    chart.timeScale().setVisibleRange({
      from: visible[0].time as Time,
      to: visible[visible.length - 1].time as Time,
    });
  }, [evidence, lowerStudy, range, showBoll, visibleModelIds]);

  return (
    <div className="relative" data-testid="security-chart-workspace">
      {displayPoint && (
        <div className="pointer-events-none absolute left-2 top-2 z-10 flex max-w-[calc(100%-1rem)] flex-wrap items-center gap-x-3 gap-y-1 rounded-md border bg-background/90 px-2.5 py-1.5 font-mono text-[10px] shadow-sm backdrop-blur-sm sm:left-3 sm:top-3 sm:text-[11px]">
          <span className="text-muted-foreground">{displayPoint.time}</span>
          <span>O {displayPoint.open.toFixed(2)}</span>
          <span>H {displayPoint.high.toFixed(2)}</span>
          <span>L {displayPoint.low.toFixed(2)}</span>
          <span className="font-semibold">C {displayPoint.close.toFixed(2)}</span>
          <span className="text-muted-foreground">V {formatVolume(displayPoint.volume)}</span>
        </div>
      )}
      <div className="pointer-events-none absolute right-14 top-3 z-10 hidden items-center gap-2 rounded-md border bg-background/85 px-2 py-1 text-[10px] text-muted-foreground backdrop-blur-sm sm:flex">
        {layers.map((layer) => <span key={layer}>{layer}</span>)}
      </div>
      <div
        ref={hostRef}
        data-testid="security-evidence-chart"
        className="h-[520px] min-h-[420px] w-full touch-pan-y md:h-[680px]"
        role="img"
        aria-label={`${evidence.symbol} daily candlestick and volume chart with formal model events`}
      />
    </div>
  );
}
