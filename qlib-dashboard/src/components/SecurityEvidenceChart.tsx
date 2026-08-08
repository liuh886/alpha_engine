import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';

import type { SecurityMarketEvidence } from '@/lib/market-evidence';

export type SecurityLowerStudy = 'macd' | 'rsi' | `factor:${string}` | 'none';

interface SecurityEvidenceChartProps {
  evidence: SecurityMarketEvidence;
  showBoll: boolean;
  lowerStudy: SecurityLowerStudy;
  visibleModelIds: Set<string>;
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

export function SecurityEvidenceChart({ evidence, showBoll, lowerStudy, visibleModelIds }: SecurityEvidenceChartProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;

    const chart = createChart(host, {
      width: host.clientWidth,
      height: host.clientHeight || 560,
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
        vertLines: { color: 'rgba(148, 163, 184, 0.08)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.08)' },
      },
      crosshair: {
        vertLine: { labelBackgroundColor: '#334155' },
        horzLine: { labelBackgroundColor: '#334155' },
      },
      rightPriceScale: { borderColor: 'rgba(148, 163, 184, 0.18)' },
      timeScale: {
        borderColor: 'rgba(148, 163, 184, 0.18)',
        timeVisible: false,
        rightOffset: 8,
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

    const markers = evidence.formal_model_events
      .filter((event) => visibleModelIds.has(event.model_id))
      .map(markerForEvent);
    if (markers.length) createSeriesMarkers(candles, markers);

    if (showBoll) {
      const boll = evidence.chart_studies.boll20;
      const middle = chart.addSeries(LineSeries, { lineWidth: 1, color: '#64748b', priceLineVisible: false, lastValueVisible: false }, 0);
      const upper = chart.addSeries(LineSeries, { lineWidth: 1, color: '#8b5cf6', priceLineVisible: false, lastValueVisible: false }, 0);
      const lower = chart.addSeries(LineSeries, { lineWidth: 1, color: '#8b5cf6', priceLineVisible: false, lastValueVisible: false }, 0);
      middle.setData(boll.map((row) => ({ time: row.time as Time, value: row.middle })));
      upper.setData(boll.map((row) => ({ time: row.time as Time, value: row.upper })));
      lower.setData(boll.map((row) => ({ time: row.time as Time, value: row.lower })));
    }

    if (lowerStudy === 'macd') {
      const pane = 1;
      const macd = evidence.chart_studies.macd_12_26_9;
      const macdLine = chart.addSeries(LineSeries, { color: '#2563eb', lineWidth: 1, priceLineVisible: false }, pane);
      const signalLine = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1, priceLineVisible: false }, pane);
      const histogram = chart.addSeries(HistogramSeries, { priceLineVisible: false, priceFormat: { type: 'price', precision: 4, minMove: 0.0001 } }, pane);
      macdLine.setData(macd.map((row) => ({ time: row.time as Time, value: row.macd })));
      signalLine.setData(macd.map((row) => ({ time: row.time as Time, value: row.signal })));
      histogram.setData(macd.map((row) => ({ time: row.time as Time, value: row.histogram, color: row.histogram >= 0 ? 'rgba(22,163,74,0.55)' : 'rgba(220,38,38,0.55)' })));
    } else if (lowerStudy === 'rsi') {
      const pane = 1;
      const rsi = chart.addSeries(LineSeries, { color: '#8b5cf6', lineWidth: 1, priceLineVisible: false }, pane);
      rsi.setData(lineData(evidence.chart_studies.rsi14));
      rsi.priceScale().applyOptions({ autoScale: false, scaleMargins: { top: 0.1, bottom: 0.1 } });
    } else if (lowerStudy.startsWith('factor:')) {
      const factorId = lowerStudy.slice('factor:'.length);
      const rows = evidence.factor_series[factorId] ?? [];
      const factor = chart.addSeries(LineSeries, { color: '#0ea5e9', lineWidth: 1, priceLineVisible: false }, 1);
      factor.setData(lineData(rows));
    }

    const panes = chart.panes();
    if (panes.length > 1) {
      panes[0].setHeight(390);
      panes[1].setHeight(150);
    }
    chart.timeScale().fitContent();

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

  return (
    <div
      ref={hostRef}
      data-testid="security-evidence-chart"
      className="h-[560px] min-h-[420px] w-full touch-pan-y md:h-[620px]"
      role="img"
      aria-label={`${evidence.symbol} daily candlestick chart with formal model events`}
    />
  );
}
