import { describe, expect, it } from 'vitest';
import {
  alignNavSeries,
  downsampleLttb,
  joinNavMarkers,
  lastSessions,
  navFromReport,
  rebaseNav,
  type NavPoint,
  type NavTrade,
} from './nav-series';
import type { ReportRow } from './types';

const DAY_MS = 86_400_000;

function curve(values: number[], start = '2026-01-01'): NavPoint[] {
  const startTime = Date.parse(`${start}T00:00:00Z`);
  return values.map((value, index) => ({
    date: new Date(startTime + index * DAY_MS).toISOString().slice(0, 10),
    value,
  }));
}

describe('navFromReport', () => {
  it('uses settlement dates, drops unusable rows, sorts and keeps the last duplicate', () => {
    const report = [
      { date: '2026-01-05', account: 100 },
      { date: '2026-01-02', holding_end_date: '2026-01-03', account: 90 },
      { date: '2026-01-04', account: 0 },
      { date: '2026-01-06', account: Number.NaN },
      { date: '2026-01-03', account: 95 },
      { date: '2026-02-30', account: 120 },
    ] as ReportRow[];
    expect(navFromReport(report)).toEqual([
      { date: '2026-01-03', value: 95 },
      { date: '2026-01-05', value: 100 },
    ]);
  });

  it('returns no curve without valid observations', () => {
    expect(navFromReport([])).toEqual([]);
    expect(navFromReport([{ date: '2026-01-01', account: -1 }])).toEqual([]);
  });
});

describe('rebaseNav', () => {
  it('rebases to 1.0 at the first valid observation without interpolating', () => {
    expect(rebaseNav([
      { date: '2026-01-01', value: 2 },
      { date: '2026-01-02', value: 4 },
      { date: '2026-01-03', value: 1 },
    ])).toEqual([
      { date: '2026-01-01', value: 1 },
      { date: '2026-01-02', value: 2 },
      { date: '2026-01-03', value: 0.5 },
    ]);
  });

  it('drops invalid points and returns an empty curve when none remain', () => {
    expect(rebaseNav([
      { date: '2026-01-01', value: 0 },
      { date: '2026-01-02', value: 2 },
      { date: '2026-01-03', value: Number.NaN },
      { date: 'not-a-date', value: 3 },
    ])).toEqual([{ date: '2026-01-02', value: 1 }]);
    expect(rebaseNav([])).toEqual([]);
  });
});

describe('downsampleLttb', () => {
  it('returns a copy when the curve already fits', () => {
    const points = curve([1, 2, 3]);
    const result = downsampleLttb(points, 3);
    expect(result).toEqual(points);
    expect(result).not.toBe(points);
  });

  it('handles empty input and caps below three points safely', () => {
    expect(downsampleLttb([], 10)).toEqual([]);
    const points = curve([1, 2, 3, 4]);
    expect(downsampleLttb(points, 0)).toEqual([]);
    expect(downsampleLttb(points, 1)).toEqual([points[0]]);
    expect(downsampleLttb(points, 2)).toEqual([points[0], points[3]]);
  });

  it('preserves endpoints, bounds the count and keeps a spike', () => {
    const values = Array.from({ length: 100 }, () => 1);
    values[50] = 100;
    const points = curve(values);
    const result = downsampleLttb(points, 10);
    expect(result).toHaveLength(10);
    expect(result[0]).toEqual(points[0]);
    expect(result[result.length - 1]).toEqual(points[99]);
    expect(result.some(point => point.value === 100)).toBe(true);
  });

  it('is deterministic, including flat-line ties', () => {
    const points = curve(Array.from({ length: 10 }, () => 1));
    const first = downsampleLttb(points, 5);
    expect(downsampleLttb(points, 5)).toEqual(first);
    expect(first.map(point => point.date)).toEqual([
      points[0].date,
      points[1].date,
      points[3].date,
      points[6].date,
      points[9].date,
    ]);
  });

  it('keeps a monotonic curve monotonic', () => {
    const points = curve(Array.from({ length: 80 }, (_, index) => index + 1));
    const result = downsampleLttb(points, 12);
    for (let index = 1; index < result.length; index += 1) {
      expect(result[index].value).toBeGreaterThan(result[index - 1].value);
    }
  });
});

describe('alignNavSeries', () => {
  it('uses exact date intersection in ascending order', () => {
    const primary = [
      { date: '2026-01-03', value: 1.2 },
      { date: '2026-01-01', value: 1 },
      { date: '2026-01-02', value: 1.1 },
    ];
    const baseline = [
      { date: '2026-01-02', value: 10 },
      { date: '2026-01-04', value: 12 },
      { date: '2026-01-01', value: 9 },
    ];
    expect(alignNavSeries(primary, baseline)).toEqual([
      { date: '2026-01-01', primary: 1, baseline: 9 },
      { date: '2026-01-02', primary: 1.1, baseline: 10 },
    ]);
  });

  it('returns no aligned points when either curve is empty or disjoint', () => {
    expect(alignNavSeries([], [{ date: '2026-01-01', value: 1 }])).toEqual([]);
    expect(alignNavSeries(
      [{ date: '2026-01-01', value: 1 }],
      [{ date: '2026-01-02', value: 1 }],
    )).toEqual([]);
  });
});

describe('lastSessions', () => {
  const points = curve([1, 2, 3, 4, 5]);

  it('keeps the prior close plus the requested sessions', () => {
    expect(lastSessions(points, 2).map(point => point.value)).toEqual([3, 4, 5]);
    expect(lastSessions(points, 1).map(point => point.value)).toEqual([4, 5]);
  });

  it('returns all points when the curve is short and clamps invalid counts', () => {
    expect(lastSessions(points, 10).map(point => point.value)).toEqual([1, 2, 3, 4, 5]);
    expect(lastSessions(points, 0).map(point => point.value)).toEqual([4, 5]);
    expect(lastSessions(points, Number.NaN).map(point => point.value)).toEqual([4, 5]);
    expect(lastSessions([], 3)).toEqual([]);
  });
});

describe('joinNavMarkers', () => {
  const points = curve([1, 1, 1, 1], '2026-01-02');
  const trades: NavTrade[] = [
    { date: '2026-01-02', action: 'BUY', instrument: 'AAA', previous_weight: 0, target_weight: 0.1, reason: 'entry' },
    { date: '2026-01-02', action: 'INCREASE', instrument: 'AAA', previous_weight: 0.1, target_weight: 0.15, reason: 'add' },
    { date: '2026-01-02', action: 'SELL', instrument: 'BBB', previous_weight: 0.05, target_weight: 0, reason: 'exit' },
    { date: '2026-01-02', action: 'HOLD', instrument: 'CCC' },
    { date: '2026-01-03', action: 'DECREASE', instrument: 'AAA', previous_weight: 0.15, target_weight: 0.05, reason: 'trim' },
    { date: '2026-01-04', action: 'BUY', instrument: 'DDD', previous_weight: null, target_weight: 0.2 },
    { date: '2026-01-09', action: 'BUY', instrument: 'EEE', previous_weight: 0, target_weight: 0.1 },
  ];

  it('aggregates execution-date markers, filters HOLD and drops unknown dates', () => {
    const markers = joinNavMarkers(points, trades, 'trade-date');
    expect(markers.map(marker => marker.date)).toEqual(['2026-01-02', '2026-01-03', '2026-01-04']);
    expect(markers[0]).toMatchObject({
      side: 'mixed',
      count: 3,
      instruments: ['AAA', 'BBB'],
      reasons: ['entry', 'add', 'exit'],
    });
    expect(markers[0].netWeightDelta).toBeCloseTo(0.1);
    expect(markers[1]).toMatchObject({
      side: 'sell',
      count: 1,
      instruments: ['AAA'],
      reasons: ['trim'],
    });
    expect(markers[1].netWeightDelta).toBeCloseTo(-0.1);
    expect(markers[2]).toMatchObject({
      side: 'buy',
      count: 1,
      instruments: ['DDD'],
      netWeightDelta: null,
      reasons: [],
    });
  });

  it('joins holding-end markers with a trade-date fallback', () => {
    const markers = joinNavMarkers(points, [
      { date: '2026-01-02', holding_end_date: '2026-01-05', action: 'BUY', instrument: 'AAA' },
      { date: '2026-01-04', action: 'SELL', instrument: 'BBB' },
      { date: '2026-01-03', holding_end_date: '2026-01-09', action: 'BUY', instrument: 'CCC' },
    ], 'holding-end');
    expect(markers.map(marker => marker.date)).toEqual(['2026-01-04', '2026-01-05']);
    expect(markers.map(marker => marker.side)).toEqual(['sell', 'buy']);
  });

  it('ignores HOLD-only dates and accepts action casing', () => {
    expect(joinNavMarkers(points, [
      { date: '2026-01-03', action: 'HOLD', instrument: 'AAA' },
    ], 'trade-date')).toEqual([]);
    expect(joinNavMarkers(points, [
      { date: '2026-01-02', action: 'buy', instrument: 'AAA' },
    ], 'trade-date')).toMatchObject([{ date: '2026-01-02', side: 'buy', count: 1 }]);
  });

  it('counts all non-HOLD rows but cannot form a marker from unknown actions alone', () => {
    expect(joinNavMarkers(points, [
      { date: '2026-01-02', action: 'BUY', instrument: 'AAA' },
      { date: '2026-01-02', action: 'REBALANCE', instrument: 'BBB' },
    ], 'trade-date')).toMatchObject([{ side: 'buy', count: 2, instruments: ['AAA', 'BBB'] }]);
    expect(joinNavMarkers(points, [
      { date: '2026-01-02', action: 'REBALANCE', instrument: 'BBB' },
    ], 'trade-date')).toEqual([]);
  });
});
