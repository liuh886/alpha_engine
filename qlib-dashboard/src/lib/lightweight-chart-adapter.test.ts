import { describe, expect, it } from 'vitest';
import type { SecurityBar, SecurityEvent } from './security-evidence';
import {
  toLightweightCandleData,
  toLightweightLineData,
  toLightweightMarkers,
  toLightweightVolumeData,
} from './lightweight-chart-adapter';
import { securityMarkers } from './security-markers';

const mockBars: SecurityBar[] = [
  { time: '2026-07-29', open: 480.5, high: 485.2, low: 479.1, close: 484.0, volume: 15200000 },
  { time: '2026-07-30', open: 483.8, high: 486.0, low: 481.2, close: 482.5, volume: 14100000 },
  { time: '2026-07-31', open: 482.0, high: 488.5, low: 481.5, close: 487.3, volume: 18900000 },
];

const mockEvents: SecurityEvent[] = [
  {
    model_id: 'qqq_model',
    run_id: 'run_1',
    instrument_id: 'QQQ',
    time: '2026-07-29',
    action: 'BUY',
    previous_weight: 0,
    target_weight: 0.5,
    reason: 'Trend breakout confirmation',
  },
  {
    model_id: 'qqq_model',
    run_id: 'run_1',
    instrument_id: 'QQQ',
    time: '2026-07-31',
    action: 'SELL',
    previous_weight: 0.5,
    target_weight: 0,
    reason: 'Profit taking target reached',
  },
];

const markerColors = { buy: 'hsl(152, 62%, 28%)', sell: 'hsl(0, 68%, 43%)' };
const volumeColors = { up: 'hsla(152, 62%, 28%, 0.4)', down: 'hsla(0, 68%, 43%, 0.4)' };

describe('lightweight-chart-adapter', () => {
  it('maps SecurityBar to TradingView CandlestickData with exact timestamp and OHLC precision', () => {
    const candles = toLightweightCandleData(mockBars);
    expect(candles).toHaveLength(3);
    expect(candles[0]).toEqual({
      time: '2026-07-29',
      open: 480.5,
      high: 485.2,
      low: 479.1,
      close: 484.0,
    });
    expect(candles[2]).toEqual({
      time: '2026-07-31',
      open: 482.0,
      high: 488.5,
      low: 481.5,
      close: 487.3,
    });
  });

  it('maps SecurityBar to TradingView HistogramData with caller-supplied theme colors', () => {
    const volume = toLightweightVolumeData(mockBars, volumeColors);
    expect(volume).toHaveLength(3);
    expect(volume[0].color).toBe(volumeColors.up);
    expect(volume[0].value).toBe(15200000);
    expect(volume[1].color).toBe(volumeColors.down);
    expect(volume[1].value).toBe(14100000);
  });

  it('maps indexed NAV points to exact-date line data without interpolation', () => {
    const line = toLightweightLineData([
      { date: '2026-01-02', value: 100 },
      { date: '2026-01-05', value: 102.5 },
    ]);
    expect(line).toEqual([
      { time: '2026-01-02', value: 100 },
      { time: '2026-01-05', value: 102.5 },
    ]);
  });

  it('maps security markers to upward/downward triangles with stable ids and size', () => {
    const markers = securityMarkers(mockBars, mockEvents);
    const lcMarkers = toLightweightMarkers(markers, markerColors);
    expect(lcMarkers).toHaveLength(2);

    const buy = lcMarkers.find(marker => marker.time === '2026-07-29')!;
    expect(buy.position).toBe('belowBar');
    expect(buy.shape).toBe('arrowUp');
    expect(buy.color).toBe(markerColors.buy);
    expect(buy.id).toBe('2026-07-29:buy');
    expect(buy.size).toBe(1);

    const sell = lcMarkers.find(marker => marker.time === '2026-07-31')!;
    expect(sell.position).toBe('aboveBar');
    expect(sell.shape).toBe('arrowDown');
    expect(sell.color).toBe(markerColors.sell);
    expect(sell.id).toBe('2026-07-31:sell');
    expect(sell.size).toBe(1);
  });
});
