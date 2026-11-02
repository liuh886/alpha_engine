import { useEffect, useRef, useState } from 'react';
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  createSeriesMarkers,
  ColorType,
  CrosshairMode,
  type IChartApi,
} from 'lightweight-charts';
import type { SecurityBar, SecurityEvent } from '@/lib/security-evidence';
import {
  toLightweightCandleData,
  toLightweightVolumeData,
  toLightweightMarkers,
} from '@/lib/lightweight-chart-adapter';
import { securityMarkers } from './SecurityHistoryChart';

export function SecurityLightweightChart({
  bars,
  events,
  modelName: _modelName,
  onSelect,
}: {
  bars: SecurityBar[];
  events: SecurityEvent[];
  modelName?: (id: string) => string;
  onSelect: (events: SecurityEvent[]) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<IChartApi | null>(null);
  const [canvasSupported, setCanvasSupported] = useState(true);

  useEffect(() => {
    if (!containerRef.current) return;

    // Guard against headless/jsdom environments without Canvas 2D
    const testCanvas = document.createElement('canvas');
    if (!testCanvas.getContext || !testCanvas.getContext('2d')) {
      setCanvasSupported(false);
      return;
    }
    setCanvasSupported(true);

    const isDark = document.documentElement.classList.contains('dark');
    const width = containerRef.current.clientWidth || 600;

    const chart = createChart(containerRef.current, {
      width,
      height: 440,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: isDark ? '#94a3b8' : '#64748b',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: isDark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.06)' },
        horzLines: { color: isDark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.06)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: isDark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.12)',
        scaleMargins: {
          top: 0.1,
          bottom: 0.25,
        },
      },
      timeScale: {
        borderColor: isDark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.12)',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    chartInstanceRef.current = chart;

    // 1. Candlestick series
    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#059669',
      downColor: '#e11d48',
      borderVisible: false,
      wickUpColor: '#059669',
      wickDownColor: '#e11d48',
    });
    candlestickSeries.setData(toLightweightCandleData(bars));

    // 2. Volume series
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: {
        type: 'volume',
      },
      priceScaleId: '', // Overlay on the main scale with custom margins
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.78, // Sits in bottom 22%
        bottom: 0,
      },
    });
    volumeSeries.setData(toLightweightVolumeData(bars));

    // 3. Trade markers
    const markers = securityMarkers(bars, events);
    const lcMarkers = toLightweightMarkers(markers);
    if (lcMarkers.length > 0) {
      createSeriesMarkers(
        candlestickSeries,
        lcMarkers.map(m => ({
          time: m.time,
          position: m.position,
          color: m.color,
          shape: m.shape,
          text: m.text,
          id: m.id,
        })),
      );
    }

    // 4. Click event subscription
    chart.subscribeClick((param) => {
      if (!param.time) return;
      let timeStr: string;
      if (typeof param.time === 'string') {
        timeStr = param.time;
      } else if (typeof param.time === 'object' && param.time !== null && 'year' in param.time) {
        const bd = param.time as { year: number; month: number; day: number };
        timeStr = `${bd.year}-${String(bd.month).padStart(2, '0')}-${String(bd.day).padStart(2, '0')}`;
      } else {
        return;
      }
      // Multiple model directions can share one session. A date click should
      // expose every matched historical model event rather than the first cluster.
      const sessionEvents = markers.filter(m => m.time === timeStr).flatMap(m => m.events);
      if (sessionEvents.length > 0) onSelect(sessionEvents);
    });

    // 5. Responsive resize
    const handleResize = () => {
      if (containerRef.current && chartInstanceRef.current) {
        chartInstanceRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartInstanceRef.current = null;
    };
  }, [bars, events, onSelect]);

  return (
    <div className="space-y-2">
      <div
        ref={containerRef}
        data-testid="security-lightweight-chart-container"
        className="w-full min-h-[440px] rounded-lg border bg-background/50 overflow-hidden"
      >
        {!canvasSupported && (
          <div className="flex h-[440px] items-center justify-center text-sm text-muted-foreground p-6">
            Canvas 2D rendering is not supported in this environment. Showing classic chart view.
          </div>
        )}
      </div>
      <p className="text-[11px] text-muted-foreground leading-relaxed">
        TradingView Lightweight Charts™ v5.2.1 · Apache License 2.0. Drag to pan, scroll to zoom, click any candle or trade marker to inspect model evidence.
      </p>
    </div>
  );
}
