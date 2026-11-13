import { describe, expect, it } from 'vitest';
import {
  HORIZON_PERIODS,
  horizonCoverage,
  isPerformanceDate,
  latestPerformanceObservation,
  performancePeriodStart,
  periodStartIndex,
  strategyPeriodSummary,
} from './performancePeriods';

describe('observed performance windows', () => {
  it('uses the declared evidence cutoff for calendar eligibility, with leap/month/year boundaries', () => {
    expect(performancePeriodStart('2024-03-31', '1m')).toBe('2024-02-29');
    expect(performancePeriodStart('2026-03-31', '1m')).toBe('2026-02-28');
    expect(performancePeriodStart('2026-01-31', '3m')).toBe('2025-10-31');
    expect(performancePeriodStart('2026-01-01', 'ytd')).toBe('2026-01-01');
    expect(performancePeriodStart('2026-10-28', 'all')).toBeNull();
    expect(performancePeriodStart('2026-02-30', '1m')).toBeNull();
    expect(performancePeriodStart('', '1m')).toBeNull();
    expect(isPerformanceDate('2024-02-29')).toBe(true);
    expect(isPerformanceDate('2026-02-29')).toBe(false);
  });
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

describe('research horizons', () => {
  it('exposes exactly the decision horizons in order', () => {
    expect(HORIZON_PERIODS).toEqual(['1w', '1m', '3m', '1y', '2y', '3y']);
  });

  it('derives a calendar week lower bound across month, year and leap boundaries', () => {
    expect(performancePeriodStart('2026-03-31', '1w')).toBe('2026-03-24');
    expect(performancePeriodStart('2026-03-05', '1w')).toBe('2026-02-26');
    expect(performancePeriodStart('2026-01-03', '1w')).toBe('2025-12-27');
    expect(performancePeriodStart('2024-03-01', '1w')).toBe('2024-02-23');
    expect(performancePeriodStart('2026-02-30', '1w')).toBeNull();
  });

  it('derives a 24-month lower bound with month-end clamping', () => {
    expect(performancePeriodStart('2026-11-13', '2y')).toBe('2024-11-13');
    expect(performancePeriodStart('2026-02-28', '2y')).toBe('2024-02-28');
    expect(performancePeriodStart('2024-02-29', '2y')).toBe('2022-02-28');
    expect(performancePeriodStart('2026-01-31', '2y')).toBe('2024-01-31');
    expect(performancePeriodStart('', '2y')).toBeNull();
  });

  it('keeps period slicing consistent for the new horizons', () => {
    const rows = [
      { date: '2026-03-20', account: 1 },
      { date: '2026-03-23', account: 1.01 },
      { date: '2026-03-24', account: 1.02 },
      { date: '2026-03-31', account: 1.05 },
    ];
    expect(periodStartIndex(rows, '1w')).toBe(2);
    expect(strategyPeriodSummary(rows, '1w').return).toBeCloseTo(1.05 / 1.02 - 1);
    expect(periodStartIndex(rows, '2y')).toBe(0);
  });
});

describe('horizon coverage', () => {
  it('reports a fully covered window when the first observation is within a week of the request', () => {
    const coverage = horizonCoverage([
      { date: '2026-02-02', account: 1 },
      { date: '2026-03-02', account: 1.1 },
      { date: '2026-04-01', account: 1.2 },
      { date: '2026-05-01', account: 1.3 },
    ], '3m');
    expect(coverage).toEqual({
      state: 'full',
      asOf: '2026-05-01',
      requestedStart: '2026-02-01',
      firstObservation: '2026-02-02',
      observations: 4,
      missingDays: 1,
      cadenceDays: 30,
      reason: 'covered',
    });
  });

  it('keeps a three-year window full when history starts three days late', () => {
    const coverage = horizonCoverage([
      { date: '2023-09-07', account: 1 },
      { date: '2024-09-04', account: 1.1 },
      { date: '2025-09-04', account: 1.2 },
      { date: '2026-09-04', account: 1.3 },
    ], '3y');
    expect(coverage.state).toBe('full');
    expect(coverage.reason).toBe('covered');
    expect(coverage.asOf).toBe('2026-09-04');
    expect(coverage.requestedStart).toBe('2023-09-04');
    expect(coverage.firstObservation).toBe('2023-09-07');
    expect(coverage.missingDays).toBe(3);
    expect(coverage.observations).toBe(4);
  });

  it('refuses to present a short history as a full three-year window', () => {
    const coverage = horizonCoverage([
      { date: '2024-01-30', account: 1 },
      { date: '2025-01-30', account: 1.1 },
      { date: '2026-11-10', account: 1.2 },
    ], '3y');
    expect(coverage.state).toBe('none');
    expect(coverage.reason).toBe('truncated_window');
    expect(coverage.asOf).toBe('2026-11-10');
    expect(coverage.requestedStart).toBe('2023-11-10');
    expect(coverage.firstObservation).toBe('2024-01-30');
    expect(coverage.missingDays).toBe(81);
    expect(coverage.observations).toBe(3);
  });

  it('marks a coarse ten-session trace partial for a one-week horizon', () => {
    const coverage = horizonCoverage([
      { date: '2026-10-14', account: 1 },
      { date: '2026-10-28', account: 1.05 },
      { date: '2026-11-11', account: 1.1 },
    ], '1w');
    expect(coverage.state).toBe('partial');
    expect(coverage.reason).toBe('coarse_cadence');
    expect(coverage.requestedStart).toBe('2026-11-04');
    expect(coverage.observations).toBe(1);
    expect(coverage.cadenceDays).toBe(14);
  });

  it('marks a two-observation week partial because the prior close is missing', () => {
    const coverage = horizonCoverage([
      { date: '2026-10-23', account: 1 },
      { date: '2026-11-06', account: 1.02 },
      { date: '2026-11-11', account: 1.03 },
    ], '1w');
    expect(coverage.state).toBe('partial');
    expect(coverage.reason).toBe('insufficient_observations');
    expect(coverage.requestedStart).toBe('2026-11-04');
    expect(coverage.firstObservation).toBe('2026-11-06');
    expect(coverage.observations).toBe(2);
    expect(coverage.missingDays).toBe(2);
    expect(coverage.cadenceDays).toBe(5);
  });

  it('reports insufficient observations for non-weekly windows and all-history', () => {
    const single = [{ date: '2026-11-11', account: 1.2 }];
    expect(horizonCoverage(single, '1m')).toMatchObject({
      state: 'none',
      reason: 'insufficient_observations',
      observations: 1,
      asOf: '2026-11-11',
      requestedStart: '2026-10-11',
      firstObservation: '2026-11-11',
    });
    expect(horizonCoverage(single, 'all')).toMatchObject({
      state: 'none',
      reason: 'insufficient_observations',
      requestedStart: '2026-11-11',
      observations: 1,
      missingDays: 0,
    });
  });

  it('treats all-history as fully covered from its first observation', () => {
    const coverage = horizonCoverage([
      { date: '2025-01-02', account: 1 },
      { date: '2025-06-02', account: 1.1 },
      { date: '2026-01-02', account: 1.2 },
    ], 'all');
    expect(coverage).toMatchObject({
      state: 'full',
      reason: 'covered',
      requestedStart: '2025-01-02',
      firstObservation: '2025-01-02',
      observations: 3,
      missingDays: 0,
    });
  });

  it('sorts observations and keeps the last duplicate settlement', () => {
    const coverage = horizonCoverage([
      { date: '2026-03-02', account: 1.1 },
      { date: '2026-02-02', account: 1 },
      { date: '2026-03-02', account: 1.2 },
    ], '1m');
    expect(coverage.asOf).toBe('2026-03-02');
    expect(coverage.requestedStart).toBe('2026-02-02');
    expect(coverage.firstObservation).toBe('2026-02-02');
    expect(coverage.observations).toBe(2);
    expect(coverage.state).toBe('full');
  });

  it('never throws on malformed rows and reports invalid dates', () => {
    expect(horizonCoverage([], '3y')).toEqual({
      state: 'none',
      asOf: null,
      requestedStart: null,
      firstObservation: null,
      observations: 0,
      missingDays: null,
      cadenceDays: null,
      reason: 'invalid_dates',
    });
    expect(horizonCoverage([
      { date: '2026-02-30', account: 1 },
      { date: '', account: 1 },
    ], '1m')).toMatchObject({ state: 'none', reason: 'invalid_dates' });
    expect(horizonCoverage([{ date: '2026-01-02', account: 0 }], '1m')).toMatchObject({
      state: 'none',
      asOf: '2026-01-02',
      observations: 0,
      reason: 'insufficient_observations',
    });
    expect(horizonCoverage([{ date: '2026-01-02', account: Number.NaN }], '1w')).toMatchObject({
      state: 'none',
      asOf: '2026-01-02',
      observations: 0,
      reason: 'insufficient_observations',
    });
  });
});
