import { describe, expect, it } from 'vitest';
import type { SecurityBar } from './security-evidence';
import {
  formatIndexedReturn,
  formatSecurityPercent,
  formatSecurityPrice,
  visibleCloseSummary,
} from './security-format';

const bar = (time: string, close: number): SecurityBar => ({
  time, open: close, high: close, low: close, close, volume: 1,
});

describe('security formatting', () => {
  it('formats prices and returns without false precision or a fake zero', () => {
    expect(formatSecurityPrice(761.2)).toBe('761.20');
    expect(formatSecurityPrice(null)).toBe('—');
    expect(formatSecurityPercent(0.1234)).toBe('+12.3%');
    expect(formatSecurityPercent(-0.004)).toBe('-0.4%');
    expect(formatSecurityPercent(0)).toBe('0.0%');
    expect(formatSecurityPercent(null)).toBe('—');
    expect(formatIndexedReturn(100)).toBe('0.0%');
    expect(formatIndexedReturn(112.34)).toBe('+12.3%');
    expect(formatIndexedReturn(Number.NaN)).toBe('—');
  });

  it('uses the last six visible closes for the one-week change', () => {
    const summary = visibleCloseSummary([
      bar('2026-01-01', 90),
      bar('2026-01-02', 100),
      bar('2026-01-05', 100),
      bar('2026-01-06', 100),
      bar('2026-01-07', 100),
      bar('2026-01-08', 100),
      bar('2026-01-09', 110),
    ]);
    expect(summary.lastClose).toBe(110);
    expect(summary.asOf).toBe('2026-01-09');
    expect(summary.oneWeekChange).toBeCloseTo(0.1, 10);
    expect(summary.oneWeekReason).toBeNull();
  });

  it('falls back to the range start when fewer than six closes are visible', () => {
    const summary = visibleCloseSummary([
      bar('2026-01-02', 100),
      bar('2026-01-05', 105),
    ]);
    expect(summary.oneWeekChange).toBeCloseTo(0.05, 10);
    expect(summary.oneWeekReason).toBeNull();
  });

  it('returns a dash and a reason instead of 0.0% when the window is unavailable', () => {
    expect(visibleCloseSummary([])).toEqual({
      lastClose: null,
      oneWeekChange: null,
      oneWeekReason: 'No observed closes in this range.',
      asOf: null,
    });
    expect(visibleCloseSummary([bar('2026-01-02', 100)])).toEqual({
      lastClose: 100,
      oneWeekChange: null,
      oneWeekReason: 'Insufficient observed closes for a one-week change.',
      asOf: '2026-01-02',
    });
  });
});
