import { describe, expect, it } from 'vitest';
import type { SecurityBar, SecurityEvent } from './security-evidence';
import {
  toLightweightCandleData,
  toLightweightVolumeData,
  toLightweightMarkers,
  assertLightweightParity,
} from './lightweight-chart-adapter';
import { securityMarkers } from '../components/SecurityHistoryChart';

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

  it('maps SecurityBar to TradingView HistogramData for volume with bullish/bearish color encoding', () => {
    const volume = toLightweightVolumeData(mockBars);
    expect(volume).toHaveLength(3);
    // 2026-07-29: close (484.0) >= open (480.5) -> bullish (greenish)
    expect(volume[0].color).toContain('150, 105');
    expect(volume[0].value).toBe(15200000);
    // 2026-07-30: close (482.5) < open (483.8) -> bearish (reddish)
    expect(volume[1].color).toContain('225, 29, 72');
    expect(volume[1].value).toBe(14100000);
  });

  it('maps security markers to TradingView series markers with shape, color, and positions', () => {
    const markers = securityMarkers(mockBars, mockEvents);
    const lcMarkers = toLightweightMarkers(markers);
    expect(lcMarkers).toHaveLength(2);

    // Buy marker
    const buy = lcMarkers.find(m => m.time === '2026-07-29')!;
    expect(buy.position).toBe('belowBar');
    expect(buy.shape).toBe('arrowUp');
    expect(buy.color).toBe('#059669');
    expect(buy.text).toBe('B');

    // Sell marker
    const sell = lcMarkers.find(m => m.time === '2026-07-31')!;
    expect(sell.position).toBe('aboveBar');
    expect(sell.shape).toBe('arrowDown');
    expect(sell.color).toBe('#e11d48');
    expect(sell.text).toBe('S');
  });

  it('proves parity between Recharts data representation and TradingView adapter', () => {
    const rechartsData = mockBars.map(bar => ({ ...bar, priceRange: [bar.low, bar.high] as [number, number] }));
    const markers = securityMarkers(mockBars, mockEvents);

    const parity = assertLightweightParity(mockBars, rechartsData, markers);
    expect(parity.barsMatch).toBe(true);
    expect(parity.barCount).toBe(3);
    expect(parity.eventCount).toBe(2);
    expect(parity.noMissingIntervals).toBe(true);
    expect(parity.noInventedBars).toBe(true);
    expect(parity.mismatches).toHaveLength(0);
  });

  it('detects and flags any time-order regression or invented bars', () => {
    const invalidBars: SecurityBar[] = [
      { time: '2026-07-30', open: 100, high: 101, low: 99, close: 100, volume: 1000 },
      { time: '2026-07-29', open: 100, high: 101, low: 99, close: 100, volume: 1000 }, // Out of order!
    ];
    const rechartsData = invalidBars.map(bar => ({ ...bar, priceRange: [bar.low, bar.high] as [number, number] }));
    const parity = assertLightweightParity(invalidBars, rechartsData, []);
    expect(parity.noMissingIntervals).toBe(false);
    expect(parity.mismatches).toContain('Non-chronological bar order at 2026-07-29');
  });
});
