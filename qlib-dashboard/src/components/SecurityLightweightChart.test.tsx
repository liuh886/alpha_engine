import { act, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SecurityBar, SecurityEvent } from '@/lib/security-evidence';
import type { SecurityMarker } from '@/lib/security-markers';
import type { IndexedBaselineSeries } from '@/lib/security-baseline';

const harness = vi.hoisted(() => {
  interface MockSeries {
    setData: ReturnType<typeof vi.fn>;
    applyOptions: ReturnType<typeof vi.fn>;
    priceScale: () => { applyOptions: ReturnType<typeof vi.fn> };
  }
  interface MockChart {
    addSeries: ReturnType<typeof vi.fn>;
    applyOptions: ReturnType<typeof vi.fn>;
    subscribeClick: ReturnType<typeof vi.fn>;
    subscribeCrosshairMove: ReturnType<typeof vi.fn>;
    unsubscribeClick: ReturnType<typeof vi.fn>;
    unsubscribeCrosshairMove: ReturnType<typeof vi.fn>;
    remove: ReturnType<typeof vi.fn>;
    timeScale: () => { fitContent: ReturnType<typeof vi.fn> };
  }
  interface MockPlugin {
    setMarkers: ReturnType<typeof vi.fn>;
  }
  const charts: MockChart[] = [];
  const plugins: MockPlugin[] = [];
  const series: MockSeries[] = [];

  const makeSeries = (): MockSeries => {
    const item: MockSeries = {
      setData: vi.fn(),
      applyOptions: vi.fn(),
      priceScale: () => ({ applyOptions: vi.fn() }),
    };
    series.push(item);
    return item;
  };
  const createChart = vi.fn((_container: HTMLElement, _options: unknown): MockChart => {
    const timeScale = { fitContent: vi.fn() };
    const chart: MockChart = {
      addSeries: vi.fn(() => makeSeries()),
      applyOptions: vi.fn(),
      subscribeClick: vi.fn(),
      subscribeCrosshairMove: vi.fn(),
      unsubscribeClick: vi.fn(),
      unsubscribeCrosshairMove: vi.fn(),
      remove: vi.fn(),
      timeScale: () => timeScale,
    };
    charts.push(chart);
    return chart;
  });
  const createSeriesMarkers = vi.fn((): MockPlugin => {
    const plugin: MockPlugin = { setMarkers: vi.fn() };
    plugins.push(plugin);
    return plugin;
  });
  return { charts, plugins, series, createChart, createSeriesMarkers };
});

vi.mock('lightweight-charts', () => ({
  CandlestickSeries: 'CandlestickSeries',
  HistogramSeries: 'HistogramSeries',
  LineSeries: 'LineSeries',
  ColorType: { Solid: 'solid' },
  CrosshairMode: { Normal: 0 },
  LineStyle: { Dashed: 2 },
  createChart: harness.createChart,
  createSeriesMarkers: harness.createSeriesMarkers,
}));

import { SecurityLightweightChart } from './SecurityLightweightChart';

const bars: SecurityBar[] = [
  { time: '2026-01-05', open: 100, high: 102, low: 99, close: 101, volume: 1000 },
  { time: '2026-01-06', open: 101, high: 103, low: 100, close: 102, volume: 1200 },
];

const laterBars: SecurityBar[] = [
  ...bars,
  { time: '2026-01-07', open: 102, high: 104, low: 101, close: 103, volume: 900 },
];

const event: SecurityEvent = {
  time: '2026-01-05',
  model_id: 'model_a',
  run_id: 'run_1',
  instrument_id: 'us:QQQ',
  action: 'BUY',
  previous_weight: 0,
  target_weight: 0.5,
  reason: 'frozen rule',
};

const marker: SecurityMarker = { time: '2026-01-05', positive: true, events: [event] };

const baselineSeries: IndexedBaselineSeries = {
  startDate: '2026-01-05',
  endDate: '2026-01-06',
  observations: 2,
  instrument: [
    { date: '2026-01-05', value: 100 },
    { date: '2026-01-06', value: 102 },
  ],
  baseline: [
    { date: '2026-01-05', value: 100 },
    { date: '2026-01-06', value: 99 },
  ],
};

function renderChart(overrides: Partial<Parameters<typeof SecurityLightweightChart>[0]> = {}) {
  const props = {
    bars,
    markers: [marker],
    mode: 'price' as const,
    baselineSeries: null,
    fitKey: '1m:price',
    onSelect: vi.fn(),
    emptyMessage: 'No evidence in this range.',
    ...overrides,
  };
  const view = render(<SecurityLightweightChart {...props} />);
  return { ...view, props, chart: harness.charts[0], candle: harness.series[0], volume: harness.series[1], instrument: harness.series[2], baseline: harness.series[3] };
}

beforeEach(() => {
  harness.charts.length = 0;
  harness.plugins.length = 0;
  harness.series.length = 0;
  harness.createChart.mockClear();
  harness.createSeriesMarkers.mockClear();
  document.documentElement.classList.remove('dark');
});

afterEach(() => {
  document.documentElement.classList.remove('dark');
  vi.restoreAllMocks();
});

describe('SecurityLightweightChart lifecycle', () => {
  it('creates one chart, its series and marker plugins once per mount', () => {
    const first = vi.fn();
    const second = vi.fn();
    const { props, rerender } = renderChart({ onSelect: first });
    expect(harness.createChart).toHaveBeenCalledTimes(1);
    expect(harness.createChart.mock.calls[0][1]).toMatchObject({ autoSize: true });
    expect(harness.series).toHaveLength(4);
    expect(harness.plugins).toHaveLength(2);
    expect(harness.createSeriesMarkers).toHaveBeenCalledTimes(2);

    rerender(<SecurityLightweightChart {...props} bars={laterBars} markers={[]} mode="baseline" baselineSeries={baselineSeries} fitKey="3m:baseline" onSelect={second} />);

    expect(harness.createChart).toHaveBeenCalledTimes(1);
    expect(harness.series).toHaveLength(4);
    expect(harness.plugins).toHaveLength(2);
  });

  it('updates series data and visibility without rebuilding the chart', () => {
    const { props, rerender, candle, volume, instrument, baseline } = renderChart();
    expect(candle.setData).toHaveBeenCalledTimes(1);
    expect(candle.setData).toHaveBeenLastCalledWith([
      { time: '2026-01-05', open: 100, high: 102, low: 99, close: 101 },
      { time: '2026-01-06', open: 101, high: 103, low: 100, close: 102 },
    ]);
    expect(volume.setData).toHaveBeenCalledTimes(1);
    expect(instrument.setData).toHaveBeenLastCalledWith([]);

    rerender(<SecurityLightweightChart {...props} bars={laterBars} />);
    expect(harness.createChart).toHaveBeenCalledTimes(1);
    expect(candle.setData).toHaveBeenLastCalledWith(expect.arrayContaining([expect.objectContaining({ time: '2026-01-07', close: 103 })]));
    expect(volume.setData).toHaveBeenLastCalledWith(expect.arrayContaining([expect.objectContaining({ time: '2026-01-06', value: 1200 })]));

    rerender(<SecurityLightweightChart {...props} bars={laterBars} mode="baseline" baselineSeries={baselineSeries} />);
    expect(harness.createChart).toHaveBeenCalledTimes(1);
    expect(candle.applyOptions).toHaveBeenLastCalledWith({ visible: false });
    expect(volume.applyOptions).toHaveBeenLastCalledWith({ visible: false });
    expect(instrument.applyOptions).toHaveBeenCalledWith(expect.objectContaining({ visible: true }));
    expect(instrument.setData).toHaveBeenLastCalledWith([
      { time: '2026-01-05', value: 100 },
      { time: '2026-01-06', value: 102 },
    ]);
    expect(baseline.setData).toHaveBeenLastCalledWith([
      { time: '2026-01-05', value: 100 },
      { time: '2026-01-06', value: 99 },
    ]);

    rerender(<SecurityLightweightChart {...props} bars={laterBars} />);
    expect(instrument.setData).toHaveBeenLastCalledWith([]);
    expect(baseline.setData).toHaveBeenLastCalledWith([]);
    expect(candle.applyOptions).toHaveBeenLastCalledWith(expect.objectContaining({ visible: true }));
  });

  it('moves markers between the price and baseline plugins and clears the inactive one', () => {
    const { props, rerender } = renderChart();
    const [candleMarkers, lineMarkers] = harness.plugins;
    expect(candleMarkers.setMarkers).toHaveBeenLastCalledWith([
      expect.objectContaining({ time: '2026-01-05', position: 'belowBar', shape: 'arrowUp', id: '2026-01-05:buy', size: 1 }),
    ]);
    expect(lineMarkers.setMarkers).toHaveBeenLastCalledWith([]);

    rerender(<SecurityLightweightChart {...props} markers={[]} />);
    expect(candleMarkers.setMarkers).toHaveBeenLastCalledWith([]);
    expect(lineMarkers.setMarkers).toHaveBeenLastCalledWith([]);

    rerender(<SecurityLightweightChart {...props} markers={[marker]} mode="baseline" baselineSeries={baselineSeries} />);
    expect(lineMarkers.setMarkers).toHaveBeenLastCalledWith([
      expect.objectContaining({ time: '2026-01-05', id: '2026-01-05:buy' }),
    ]);
    expect(candleMarkers.setMarkers).toHaveBeenLastCalledWith([]);
  });

  it('routes click and hover selection through the latest callback and dedupes hover', () => {
    const first = vi.fn();
    const second = vi.fn();
    const { props, rerender, chart } = renderChart({ onSelect: first });
    rerender(<SecurityLightweightChart {...props} onSelect={second} />);

    const click = chart.subscribeClick.mock.calls[0][0] as (param: { time: string; point?: { x: number; y: number } }) => void;
    const hover = chart.subscribeCrosshairMove.mock.calls[0][0] as (param: { time: string; point?: { x: number; y: number } | null }) => void;

    act(() => click({ time: '2026-01-05', point: { x: 1, y: 1 } }));
    expect(second).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledWith([event]);
    expect(first).not.toHaveBeenCalled();

    act(() => hover({ time: '2026-01-05', point: { x: 1, y: 1 } }));
    expect(second).toHaveBeenCalledTimes(2);
    act(() => hover({ time: '2026-01-05', point: { x: 2, y: 2 } }));
    expect(second).toHaveBeenCalledTimes(2);

    act(() => hover({ time: '2026-01-05', point: null }));
    act(() => hover({ time: '2026-01-05', point: { x: 3, y: 3 } }));
    expect(second).toHaveBeenCalledTimes(3);

    act(() => click({ time: '2026-01-06', point: { x: 1, y: 1 } }));
    expect(second).toHaveBeenCalledTimes(3);

    act(() => click({ time: '2026-01-05', point: { x: 1, y: 1 } }));
    expect(second).toHaveBeenCalledTimes(4);
  });

  it('fits once per fit key and not on data-only updates', () => {
    const { props, rerender, chart } = renderChart();
    const fitContent = chart.timeScale().fitContent;
    expect(fitContent).toHaveBeenCalledTimes(1);

    rerender(<SecurityLightweightChart {...props} bars={laterBars} />);
    expect(fitContent).toHaveBeenCalledTimes(1);

    rerender(<SecurityLightweightChart {...props} bars={laterBars} fitKey="6m:price" />);
    expect(fitContent).toHaveBeenCalledTimes(2);
  });

  it('follows the document theme and removes the observer, handlers and chart on unmount', async () => {
    const disconnect = vi.spyOn(MutationObserver.prototype, 'disconnect');
    const { chart, unmount } = renderChart();

    act(() => document.documentElement.classList.add('dark'));
    await waitFor(() => {
      expect(chart.applyOptions).toHaveBeenCalledWith(expect.objectContaining({ layout: { textColor: '#94a3b8' } }));
    });

    unmount();
    expect(disconnect).toHaveBeenCalled();
    expect(chart.unsubscribeClick).toHaveBeenCalledTimes(1);
    expect(chart.unsubscribeCrosshairMove).toHaveBeenCalledTimes(1);
    expect(chart.remove).toHaveBeenCalledTimes(1);
    disconnect.mockRestore();
  });

  it('announces a chart-shaped skeleton while the comparison evidence loads', () => {
    renderChart({
      mode: 'baseline',
      baselineSeries: null,
      loading: true,
      emptyMessage: 'Loading QQQ baseline evidence…',
    });
    const status = screen.getByTestId('security-chart-loading');
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveAttribute('aria-busy', 'true');
    expect(status).toHaveTextContent('Loading QQQ baseline evidence…');
    expect(status.querySelectorAll('[aria-hidden="true"]').length).toBeGreaterThan(0);
    expect(screen.queryByTestId('security-chart-empty')).not.toBeInTheDocument();
  });

  it('bounds the price data table to the most recent 120 visible sessions and states the bound', () => {
    const many: SecurityBar[] = Array.from({ length: 130 }, (_, index) => {
      const time = new Date(Date.UTC(2025, 0, 1 + index)).toISOString().slice(0, 10);
      return {
        time,
        open: 100 + index,
        high: 102 + index,
        low: 99 + index,
        close: 101 + index,
        volume: 1000 + index,
      };
    });
    renderChart({ bars: many, markers: [] });
    const details = screen.getByTestId('price-data');
    expect(within(details).getByText('View price data table')).toBeInTheDocument();
    const rows = details.querySelectorAll('tbody tr');
    expect(rows).toHaveLength(120);
    expect(rows[0]).toHaveTextContent(many[10].time);
    expect(rows[119]).toHaveTextContent(many[129].time);
    expect(details).toHaveTextContent('Showing the most recent 120 of 130 visible-range sessions');
    expect(details).toHaveTextContent('Raw OHLCV, not split or dividend adjusted.');
  });
});
