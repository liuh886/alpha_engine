import { describe, expect, it } from 'vitest';
import { latestPerformanceObservation, periodStartIndex, strategyPeriodSummary } from './performancePeriods';

describe('observed performance windows', () => {
  it('explains the latest sparse or provisional change with actual boundaries', () => {
    const observation = latestPerformanceObservation([
      { date: '2026-09-01', holding_end_date: '2026-09-17', account_before: 1, account: 0.95 },
      { date: '2026-09-30', account: 0.9, provisional_mtm: true },
    ]);
    expect(observation?.previousDate).toBe('2026-09-17');
    expect(observation?.date).toBe('2026-09-30');
    expect(observation?.observedReturn).toBeCloseTo(0.9 / 0.95 - 1);
    expect(observation?.drawdown).toBeCloseTo(-0.1);
    expect(observation?.drawdownChange).toBeCloseTo(-0.05);
    expect(observation?.provisional).toBe(true);
  });
  it('does not invent risk or change from missing or misordered wealth evidence', () => {
    expect(latestPerformanceObservation([{ date: '2026-01-01', account: NaN }])).toBeNull();
    expect(latestPerformanceObservation([{ date: '2026-01-02', account: 1 }, { date: '2026-01-01', account: 2 }])).toBeNull();
    expect(latestPerformanceObservation([{ date: '2026-01-01', account: 1 }])?.observedReturn).toBeNull();
  });
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
