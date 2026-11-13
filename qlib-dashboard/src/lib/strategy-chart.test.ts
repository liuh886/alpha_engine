import { describe, expect, it } from 'vitest';
import type { NavPoint } from '@/lib/nav-series';
import type { HorizonCoverage } from '@/lib/performancePeriods';
import type { ReportRow } from '@/lib/types';
import {
  CHART_HORIZONS,
  DEFAULT_CHART_HORIZON,
  MAX_DISPLAYABLE_SHORTFALL_DAYS,
  STALE_AFTER_DAYS,
  coverageReasonText,
  defaultBaselineKind,
  formatReturn,
  isStale,
  marketBaselineKey,
  maximumDrawdown,
  metricDisplay,
  navBetween,
  navMarkerMode,
  parseNavTrades,
  provisionalObservationCount,
  returnTone,
  staleDays,
  strategyBaselineOptions,
  windowReturns,
} from './strategy-chart';

const strategy: NavPoint[] = [
  { date: '2026-01-01', value: 100 },
  { date: '2026-01-02', value: 110 },
  { date: '2026-01-03', value: 121 },
];
const baseline: NavPoint[] = [
  { date: '2026-01-02', value: 200 },
  { date: '2026-01-03', value: 210 },
];

function coverage(overrides: Partial<HorizonCoverage> = {}): HorizonCoverage {
  return {
    state: 'full',
    asOf: '2026-01-03',
    requestedStart: '2025-01-03',
    firstObservation: '2026-01-01',
    observations: 3,
    missingDays: 0,
    cadenceDays: 1,
    reason: 'covered',
    ...overrides,
  };
}

describe('chart horizons and formatting', () => {
  it('exposes exactly the decision horizons with 1Y as the default', () => {
    expect(CHART_HORIZONS.map(horizon => horizon.label)).toEqual(['1W', '1M', '3M', '1Y', '2Y', '3Y', 'ALL']);
    expect(CHART_HORIZONS.map(horizon => horizon.period)).toEqual(['1w', '1m', '3m', '1y', '2y', '3y', 'all']);
    expect(DEFAULT_CHART_HORIZON).toBe('1y');
    expect(STALE_AFTER_DAYS).toBe(14);
    expect(MAX_DISPLAYABLE_SHORTFALL_DAYS).toBe(7);
  });

  it('formats signed one-decimal returns and never invents a zero', () => {
    expect(formatReturn(0.1234)).toBe('+12.3%');
    expect(formatReturn(-0.056)).toBe('-5.6%');
    expect(formatReturn(0)).toBe('0.0%');
    expect(formatReturn(-0.00004)).toBe('0.0%');
    expect(formatReturn(-1e-9)).toBe('0.0%');
    expect(formatReturn(-0.00004)).not.toContain('-0.0');
    expect(formatReturn(null)).toBe('—');
    expect(formatReturn(Number.NaN)).toBe('—');
    expect(returnTone(0.01)).toBe('text-positive');
    expect(returnTone(-0.01)).toBe('text-negative');
    expect(returnTone(0)).toBe('');
    expect(returnTone(null)).toBe('');
  });
});

describe('window returns and drawdown', () => {
  it('uses exact aligned dates for strategy, baseline and browser-derived excess', () => {
    const returns = windowReturns(strategy, baseline);
    expect(returns.aligned).toBe(true);
    expect(returns.alignedObservations).toBe(2);
    expect(returns.startDate).toBe('2026-01-02');
    expect(returns.endDate).toBe('2026-01-03');
    expect(returns.strategy).toBeCloseTo(0.1, 12);
    expect(returns.baseline).toBeCloseTo(0.05, 12);
    expect(returns.excess).toBeCloseTo(1.1 / 1.05 - 1, 12);
  });

  it('falls back to the primary window without inventing a baseline overlap', () => {
    const returns = windowReturns(strategy, [{ date: '2025-01-01', value: 100 }]);
    expect(returns.aligned).toBe(false);
    expect(returns.startDate).toBe('2026-01-01');
    expect(returns.strategy).toBeCloseTo(0.21, 12);
    expect(returns.baseline).toBeNull();
    expect(returns.excess).toBeNull();
  });

  it('never returns a return for a single observation', () => {
    const returns = windowReturns([{ date: '2026-01-01', value: 100 }]);
    expect(returns.strategy).toBeNull();
    expect(windowReturns([]).startDate).toBeNull();
  });

  it('computes maximum drawdown from retained wealth marks only', () => {
    expect(maximumDrawdown([
      { date: '2026-01-01', value: 100 },
      { date: '2026-01-02', value: 120 },
      { date: '2026-01-03', value: 90 },
      { date: '2026-01-04', value: 110 },
    ])).toBeCloseTo(-0.25, 12);
    expect(maximumDrawdown([{ date: '2026-01-01', value: 100 }])).toBeNull();
    expect(maximumDrawdown([
      { date: '2026-01-01', value: 100 },
      { date: '2026-01-02', value: 101 },
    ])).toBe(0);
  });

  it('slices baselines to exact dates without forward filling', () => {
    expect(navBetween(baseline, '2026-01-02', '2026-01-02')).toEqual([{ date: '2026-01-02', value: 200 }]);
    expect(navBetween(baseline, null, '2026-01-03')).toEqual([]);
    expect(navBetween(baseline, '2026-01-01', '2026-01-10')).toEqual(baseline);
  });
});

describe('coverage-aware metric display', () => {
  it('shows full-window values', () => {
    const display = metricDisplay(coverage(), 0.1234);
    expect(display).toEqual({ text: '+12.3%', visible: true, reason: null, firstObservation: '2026-01-01' });
  });

  it('shows a short-history partial only within the one-week allowance', () => {
    const within = metricDisplay(coverage({ state: 'partial', reason: 'short_history', missingDays: 7 }), 0.05);
    expect(within.visible).toBe(true);
    expect(within.text).toBe('+5.0%');

    const beyond = metricDisplay(coverage({ state: 'partial', reason: 'short_history', missingDays: 8 }), 0.05);
    expect(beyond.visible).toBe(false);
    expect(beyond.text).toBe('—');
    expect(beyond.reason).toContain('History starts 2026-01-01');
  });

  it('hides coarse, insufficient and truncated windows with a reason', () => {
    for (const reason of ['coarse_cadence', 'insufficient_observations', 'truncated_window'] as const) {
      const display = metricDisplay(coverage({ state: 'partial', reason, observations: 1 }), -0.02);
      expect(display.text).toBe('—');
      expect(display.visible).toBe(false);
      expect(display.reason).toBeTruthy();
    }
  });

  it('never renders 0.0% for a missing one-point value', () => {
    const display = metricDisplay(
      coverage({ state: 'none', reason: 'insufficient_observations', observations: 1, firstObservation: '2026-01-03' }),
      null,
    );
    expect(display.text).toBe('—');
    expect(display.text).not.toContain('0.0%');
    expect(display.reason).toBe('Only 1 valid observation in this window.');
  });

  it('provides plain-language coverage reasons', () => {
    expect(coverageReasonText(coverage())).toBe('The requested window is fully covered.');
    expect(coverageReasonText(coverage({ state: 'partial', reason: 'coarse_cadence', cadenceDays: 10 })))
      .toBe('Observed cadence of 10 calendar days is too coarse for a weekly window.');
    expect(coverageReasonText(coverage({ state: 'none', reason: 'invalid_dates' })))
      .toBe('No valid observation dates are retained.');
  });
});

describe('baseline options', () => {
  const declaredRows: ReportRow[] = strategy.map((point, index) => ({
    date: point.date,
    account: point.value,
    bench_qqq: 200 + index * 5,
  }));
  const declaredRun = { market: 'us' as const, benchmark: 'QQQ' };

  it('offers declared, own-market and none for a retained declared benchmark', () => {
    const options = strategyBaselineOptions(declaredRun, declaredRows);
    expect(options.map(option => option.kind)).toEqual(['declared', 'market', 'none']);
    const declared = options[0];
    expect(declared.available).toBe(true);
    expect(declared.field).toBe('bench_qqq');
    expect(declared.source).toBe('formal_report');
    const market = options[1];
    expect(market).toMatchObject({
      key: 'market:QQQ',
      label: 'QQQ',
      kind: 'market',
      market: 'us',
      source: 'market_bars',
      available: true,
    });
    expect(options[2].available).toBe(true);
  });

  it('keeps an unavailable declared option visible and defaults to none', () => {
    const rows: ReportRow[] = strategy.map((point, index) => ({
      date: point.date,
      account: point.value,
      benchmark_account: 100 + index,
    }));
    const options = strategyBaselineOptions({ market: 'cn', benchmark: '000300' }, rows);
    const declared = options.find(option => option.kind === 'declared');
    expect(declared?.available).toBe(false);
    expect(declared?.reason).toBeTruthy();
    const market = options.find(option => option.kind === 'market');
    expect(market?.key).toBe('market:000300');
    expect(market?.market).toBe('cn');
    expect(defaultBaselineKind(options, 'declared')).toBe('none');
  });

  it('honors a persisted market preference but never another market', () => {
    const options = strategyBaselineOptions(declaredRun, declaredRows);
    expect(defaultBaselineKind(options, 'market')).toBe('market');
    expect(defaultBaselineKind(options, 'none')).toBe('none');
    expect(defaultBaselineKind([], 'declared')).toBe('none');
    expect(marketBaselineKey('us')).toBe('us:QQQ');
    expect(marketBaselineKey('cn')).toBe('cn:000300');
  });
});

describe('trades, marker mode and staleness', () => {
  it('parses both retained trade shapes and drops malformed rows', () => {
    const payload = {
      records: [
        { date: '2026-01-02', action: 'BUY', instrument: 'AAPL', previous_weight: 0, target_weight: 0.1, reason: 'signal' },
        { date: '2026-02-30', action: 'SELL', instrument: 'MSFT' },
        { holding_end_date: '2026-01-03', action: 'SELL', instrument: 'MSFT' },
        { date: '2026-01-04', action: '' },
        'not-a-row',
      ],
    };
    const trades = parseNavTrades(payload);
    expect(trades).toHaveLength(2);
    expect(trades[0]).toMatchObject({ date: '2026-01-02', action: 'BUY', instrument: 'AAPL' });
    expect(trades[1]).toMatchObject({ date: '2026-01-03', action: 'SELL', holding_end_date: '2026-01-03' });
    expect(parseNavTrades([])).toEqual([]);
    expect(parseNavTrades(null)).toEqual([]);
  });

  it('uses holding-end markers only when the NAV projection carries them', () => {
    expect(navMarkerMode([{ date: '2026-01-01', account: 100 }])).toBe('trade-date');
    expect(navMarkerMode([{ date: '2026-01-01', account: 100, holding_end_date: '2026-01-02' }])).toBe('holding-end');
    expect(navMarkerMode([{ date: '2026-01-01', account: 100, holding_end_date: 'not-a-date' }])).toBe('trade-date');
  });

  it('marks stale only beyond 14 calendar days', () => {
    expect(staleDays('2026-11-12', '2026-10-29')).toBe(14);
    expect(isStale('2026-11-12', '2026-10-29')).toBe(false);
    expect(staleDays('2026-11-12', '2026-10-28')).toBe(15);
    expect(isStale('2026-11-12', '2026-10-28')).toBe(true);
    expect(isStale('not-a-date', '2026-10-28')).toBe(false);
    expect(staleDays('2026-11-12', null)).toBeNull();
  });

  it('counts provisional observations only inside the displayed window', () => {
    const rows: ReportRow[] = [
      { date: '2026-01-01', account: 100, provisional_mtm: true },
      { date: '2026-01-02', account: 101, settlement_status: 'provisional_mtm' },
      { date: '2026-01-03', account: 102, settlement_status: 'settled' },
      { date: '2026-01-04', account: 103, provisional_mtm: true },
    ];
    expect(provisionalObservationCount(rows, '2026-01-01', '2026-01-03')).toBe(2);
    expect(provisionalObservationCount(rows, '2026-01-04', '2026-01-04')).toBe(1);
    expect(provisionalObservationCount(rows, null, '2026-01-04')).toBe(0);
  });
});
