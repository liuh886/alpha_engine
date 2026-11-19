import { describe, expect, it } from 'vitest';
import type { SecurityBar } from './security-evidence';
import {
  VIX_PANE_LABEL,
  VIX_SMA_LABEL,
  VIX_SMA_ID,
  VIX_SERIES_ID,
  vixPoints,
  vixSmaPoints,
  vixUnavailableReason,
} from './vix-context';
import { INDICATOR_REGISTRY } from './indicators';

function makeBars(count: number, close: (index: number) => number = index => 12 + index): SecurityBar[] {
  return Array.from({ length: count }, (_, index) => {
    const time = new Date(Date.UTC(2025, 0, 1 + index)).toISOString().slice(0, 10);
    const value = close(index);
    return { time, open: value, high: value + 1, low: value - 1, close: value, volume: 0 };
  });
}

describe('US VIX context', () => {
  it('uses exact observed closes inside the chart window, never filled dates', () => {
    const bars = makeBars(10);
    const points = vixPoints(bars, '2025-01-03', '2025-01-06');
    expect(points).toEqual([
      { time: '2025-01-03', value: 14 },
      { time: '2025-01-04', value: 15 },
      { time: '2025-01-05', value: 16 },
      { time: '2025-01-06', value: 17 },
    ]);
    expect(points.every(point => bars.some(bar => bar.time === point.time && bar.close === point.value))).toBe(true);
  });

  it('returns no points outside the window or without a valid close', () => {
    const bars = makeBars(3).map((bar, index) => (index === 1 ? { ...bar, close: Number.NaN } : bar));
    expect(vixPoints(bars, '2030-01-01', '2030-01-31')).toEqual([]);
    expect(vixPoints([], '2025-01-01', '2025-01-31')).toEqual([]);
    expect(vixPoints(bars, null, '2025-01-03')).toEqual([]);
    expect(vixPoints(bars, '2025-01-01', '2025-01-03').map(point => point.time)).toEqual([
      '2025-01-01',
      '2025-01-03',
    ]);
  });

  it('computes the governed VIX SMA 20 from full-history warm-up and clips to the window', () => {
    const entry = INDICATOR_REGISTRY.find(candidate => candidate.indicator_id === VIX_SMA_ID);
    expect(entry).toBeDefined();
    expect(entry?.inputs.series_id).toBe(VIX_SERIES_ID);
    expect(VIX_SMA_LABEL).toBe('VIX SMA 20');
    expect(VIX_PANE_LABEL).toBe('VIX · US market context');

    const bars = makeBars(30);
    const result = vixSmaPoints(bars, '2025-01-25', '2025-01-30');
    expect(result.available).toBe(true);
    expect(result.points.length).toBe(6);
    expect(result.points[0].time).toBe('2025-01-25');
    expect(result.points[0].value).toBeCloseTo(
      bars.slice(5, 25).reduce((total, bar) => total + bar.close, 0) / 20,
      8,
    );
    // Every emitted date is an exact observed VIX date, never a synthetic one.
    expect(result.points.every(point => bars.some(bar => bar.time === point.time))).toBe(true);
  });

  it('reports insufficient history and an absent governed series explicitly', () => {
    const short = vixSmaPoints(makeBars(5), '2025-01-01', '2025-01-10');
    expect(short.available).toBe(false);
    expect(short.points).toEqual([]);
    expect(short.reason).toContain('20 observations');

    const unavailable = vixUnavailableReason(new Error('Security history unavailable (404).'));
    expect(unavailable).toContain('(404)');
    expect(unavailable).toContain('No substitute series is shown');
  });
});
