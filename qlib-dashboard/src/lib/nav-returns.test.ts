import { describe, expect, it } from 'vitest';
import { navFromReport, type NavPoint } from './nav-series';
import { navHorizonCoverage, navReturn, navSeriesForPeriod } from './nav-returns';
import { HORIZON_PERIODS, horizonCoverage, type PerformancePeriod } from './performancePeriods';
import type { ReportRow } from './types';

const DAY_MS = 86_400_000;
const ALL_PERIODS: PerformancePeriod[] = [...HORIZON_PERIODS, '6m', 'ytd', 'all'];

function curve(values: number[], start = '2026-01-01'): NavPoint[] {
  const startTime = Date.parse(`${start}T00:00:00Z`);
  return values.map((value, index) => ({
    date: new Date(startTime + index * DAY_MS).toISOString().slice(0, 10),
    value,
  }));
}

function reportFrom(points: NavPoint[]): ReportRow[] {
  return points.map(point => ({ date: point.date, account: point.value }));
}

describe('navReturn', () => {
  it('starts at the first observation at or after the requested start', () => {
    const nav: NavPoint[] = [
      { date: '2026-01-20', value: 100 },
      { date: '2026-02-05', value: 110 },
      { date: '2026-03-01', value: 121 },
    ];
    // As-of is the last observation (2026-03-01); 1m starts 2026-02-01 and
    // snaps forward to the first retained observation, never backward.
    expect(navReturn(nav, '1m')).toBeCloseTo(121 / 110 - 1, 12);
  });

  it('uses the curve own last observation as the as-of date', () => {
    const nav: NavPoint[] = [
      { date: '2026-01-01', value: 100 },
      { date: '2026-01-20', value: 110 },
    ];
    expect(navReturn(nav, 'all')).toBeCloseTo(0.1, 12);
    // 1w starts 2026-01-13; only the last observation remains, matching
    // strategyPeriodSummary's zero-length window rather than inventing data.
    expect(navReturn(nav, '1w')).toBe(0);
  });

  it('keeps the last duplicate date and ignores invalid observations', () => {
    const nav: NavPoint[] = [
      { date: '2026-01-01', value: 100 },
      { date: '2026-01-01', value: 101 },
      { date: '2026-01-02', value: 110 },
      { date: '2026-02-30', value: 120 },
      { date: '2026-01-03', value: Number.NaN },
    ];
    expect(navReturn(nav, 'all')).toBeCloseTo(110 / 101 - 1, 12);
  });

  it('returns null without at least two valid observations', () => {
    expect(navReturn([], '1m')).toBeNull();
    expect(navReturn([{ date: '2026-01-01', value: 100 }], '1m')).toBeNull();
    expect(navReturn([
      { date: '2026-01-01', value: 0 },
      { date: '2026-01-02', value: Number.NaN },
    ], '1m')).toBeNull();
  });
});

describe('navHorizonCoverage', () => {
  it('matches horizonCoverage for the same dates and accounts', () => {
    const cases: NavPoint[][] = [
      curve(Array.from({ length: 40 }, (_, index) => 100 + index), '2026-01-01'),
      [
        { date: '2026-01-01', value: 100 },
        { date: '2026-01-08', value: 101 },
        { date: '2026-01-15', value: 102 },
        { date: '2026-01-22', value: 103 },
      ],
      [
        { date: '2025-12-25', value: 100 },
        { date: '2026-01-10', value: 101 },
        { date: '2026-01-20', value: 103 },
      ],
      [
        { date: '2025-11-15', value: 100 },
        { date: '2026-01-01', value: 105 },
      ],
    ];
    for (const points of cases) {
      const report = reportFrom(points);
      const nav = navFromReport(report);
      for (const period of ALL_PERIODS) {
        expect(navHorizonCoverage(nav, period)).toEqual(horizonCoverage(report, period));
      }
    }
  });

  it('requires three observations and weekly-or-finer cadence for a full 1w window', () => {
    const weekly: NavPoint[] = [
      { date: '2026-01-01', value: 100 },
      { date: '2026-01-08', value: 101 },
      { date: '2026-01-15', value: 102 },
      { date: '2026-01-22', value: 103 },
    ];
    expect(navHorizonCoverage(weekly, '1w')).toMatchObject({
      state: 'partial',
      reason: 'insufficient_observations',
      observations: 2,
      cadenceDays: 7,
    });

    const daily = curve(Array.from({ length: 10 }, (_, index) => 100 + index));
    expect(navHorizonCoverage(daily, '1w')).toMatchObject({ state: 'full', reason: 'covered' });

    const coarse: NavPoint[] = [
      { date: '2026-01-01', value: 100 },
      { date: '2026-01-20', value: 101 },
    ];
    expect(navHorizonCoverage(coarse, '1w')).toMatchObject({ state: 'partial', reason: 'coarse_cadence' });
  });

  it('does not interpolate missing settlement dates', () => {
    const nav: NavPoint[] = [
      { date: '2026-01-01', value: 100 },
      { date: '2026-02-01', value: 101 },
    ];
    const coverage = navHorizonCoverage(nav, '1w');
    expect(coverage.observations).toBe(1);
    expect(coverage.state).toBe('partial');
  });
});

describe('navSeriesForPeriod', () => {
  it('slices the window and rebases the first valid observation to 100', () => {
    const nav: NavPoint[] = [
      { date: '2026-01-20', value: 100 },
      { date: '2026-02-05', value: 110 },
      { date: '2026-03-01', value: 121 },
    ];
    const series = navSeriesForPeriod(nav, '1m');
    expect(series.map(point => point.date)).toEqual(['2026-02-05', '2026-03-01']);
    expect(series[0].value).toBe(100);
    expect(series[1].value).toBeCloseTo(110, 10);
  });

  it('keeps the actual start date and rebases all observations for `all`', () => {
    const nav: NavPoint[] = [
      { date: '2026-01-20', value: 50 },
      { date: '2026-02-05', value: 75 },
    ];
    expect(navSeriesForPeriod(nav, 'all')).toEqual([
      { date: '2026-01-20', value: 100 },
      { date: '2026-02-05', value: 150 },
    ]);
  });

  it('returns no series for empty or entirely invalid curves', () => {
    expect(navSeriesForPeriod([], '1m')).toEqual([]);
    expect(navSeriesForPeriod([{ date: '2026-01-01', value: Number.NaN }], 'all')).toEqual([]);
  });
});
