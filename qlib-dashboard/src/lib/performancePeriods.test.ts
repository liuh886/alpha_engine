import { describe, expect, it } from 'vitest';
import { periodStartIndex, strategyPeriodSummary } from './performancePeriods';

describe('observed performance windows', () => {
  it('includes the first settled loss when initial capital is declared', () => {
    const result = strategyPeriodSummary([
      { date: '2026-01-01', account_before: 1, account: 0.95 },
      { date: '2026-02-01', account: 1.1 },
    ], 'all');
    expect(result.return).toBeCloseTo(0.1);
    expect(result.drawdown).toBeCloseTo(-0.05);
  });
  it('rejects an invalid declared initial capital instead of hiding its first period', () => {
    expect(strategyPeriodSummary([{ date: '2026-01-01', account_before: 0, account: 1 }], 'all').return).toBeNull();
  });
  it('clamps month-end subtraction and uses settled performance dates', () => {
    const rows = [
      { date: '2026-02-01', holding_end_date: '2026-02-28', account: 1 },
      { date: '2026-03-01', holding_end_date: '2026-03-31', account: 1.2 },
    ];
    expect(periodStartIndex(rows, '1m')).toBe(0);
    expect(strategyPeriodSummary(rows, '1m').return).toBeCloseTo(0.2);
  });
  it('does not substitute all history for an unavailable interval', () => {
    expect(periodStartIndex([{ date: '', account: 1 }], '1y')).toBe(-1);
    expect(strategyPeriodSummary([], '1m').return).toBeNull();
  });
});
