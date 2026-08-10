import { describe, expect, it } from 'vitest';

import type { FormalModelEvent, MarketBar } from './market-evidence';
import { barsForSecurityRange, summarizeSecurityRange, validSecurityChartRange } from './security-explorer';

const bars: MarketBar[] = [
  { time: '2024-01-02', open: 90, high: 101, low: 89, close: 100, volume: 1_000 },
  { time: '2025-01-02', open: 100, high: 112, low: 98, close: 110, volume: 2_000 },
  { time: '2026-01-02', open: 110, high: 125, low: 108, close: 120, volume: 3_000 },
  { time: '2026-08-03', open: 120, high: 151, low: 119, close: 150, volume: 4_000 },
];

const events: FormalModelEvent[] = [
  {
    time: '2025-01-02',
    instrument_id: 'us:TEST',
    source_instrument: 'TEST',
    model_id: 'old',
    model_name: 'Old model',
    run_id: 'run-old',
    action: 'BUY',
    previous_weight: 0,
    target_weight: 0.1,
    weight_delta: 0.1,
    reason: 'old',
    research_only: true,
    trade_ready: false,
  },
  {
    time: '2026-08-03',
    instrument_id: 'us:TEST',
    source_instrument: 'TEST',
    model_id: 'current',
    model_name: 'Current model',
    run_id: 'run-current',
    action: 'INCREASE',
    previous_weight: 0.1,
    target_weight: 0.2,
    weight_delta: 0.1,
    reason: 'current',
    research_only: true,
    trade_ready: false,
  },
];

describe('Security Explorer range utilities', () => {
  it('defaults unknown ranges to one year', () => {
    expect(validSecurityChartRange(null)).toBe('1y');
    expect(validSecurityChartRange('unexpected')).toBe('1y');
  });

  it('selects bars inside the requested range', () => {
    expect(barsForSecurityRange(bars, '1y').map((bar) => bar.time)).toEqual(['2026-01-02', '2026-08-03']);
    expect(barsForSecurityRange(bars, 'all')).toHaveLength(4);
  });

  it('summarizes visible price, volume and formal-event evidence', () => {
    const summary = summarizeSecurityRange(bars, events, '1y');
    expect(summary).not.toBeNull();
    expect(summary?.returnPct).toBeCloseTo(0.25, 10);
    expect(summary?.high).toBe(151);
    expect(summary?.low).toBe(108);
    expect(summary?.latestVolume).toBe(4_000);
    expect(summary?.barCount).toBe(2);
    expect(summary?.eventCount).toBe(1);
  });
});
