import { describe, expect, it } from 'vitest';
import type { DerivedExcess } from './derived-excess';
import type { GovernedRunSummary } from './governed-run';
import {
  formatDate,
  formatPrice,
  formatPriceChange,
  formatReturn,
  indexRowsFromBars,
  rankingCell,
  rankingExcessFromDerived,
  retainedExcess,
  sortRankingRows,
  strategyRowsFromNav,
  STALE_AFTER_DAYS,
} from './model-ranking';
import type { SecurityBar } from './security-evidence';
import type { ReportRow } from './types';

function run(overrides: Partial<GovernedRunSummary> = {}): GovernedRunSummary {
  return {
    key: 'us_x1_3',
    modelFamilyId: 'us_x',
    modelVersionId: 'us_x1_3',
    runId: 'us_x1_3-formal',
    bundleId: 'b'.repeat(64),
    title: 'US x1.3',
    modelKind: 'cross_sectional_ranker',
    channel: 'formal',
    publicationStatus: 'accepted_formal_baseline',
    market: 'us',
    benchmark: 'QQQ',
    generatedAt: '2026-11-12',
    evidenceCutoff: '2026-11-11',
    evidenceStatus: 'complete',
    decisionStatus: 'supported',
    manifestPath: 'us_x/manifest.json',
    manifestSha256: 'a'.repeat(64),
    summary: { metrics: [] },
    manifest: null,
    loadWarnings: [],
    ...overrides,
  };
}

function navRows(points: Array<[string, number]>): ReportRow[] {
  return points.map(([date, account]) => ({ date, account }));
}

function bar(time: string, open: number, close: number): SecurityBar {
  return { time, open, high: Math.max(open, close), low: Math.min(open, close), close, volume: 1000 };
}

describe('model ranking cells', () => {
  it('renders a fully covered horizon from exact observation dates', () => {
    const rows = navRows([
      ['2026-11-05', 101],
      ['2026-11-10', 105],
      ['2026-11-11', 110],
    ]);
    const cell = rankingCell(rows.map((row) => ({ date: String(row.date), value: Number(row.account) })), '1w');
    expect(cell.display).toBe(true);
    expect(cell.value).toBeCloseTo(110 / 101 - 1, 12);
    expect(cell.coverage.state).toBe('full');
    expect(cell.coverage.firstObservation).toBe('2026-11-05');
  });

  it('treats a short 3Y start within seven days as full cn_27 history', () => {
    const row = strategyRowsFromNav(run({
      key: 'cn_27_v1_3',
      modelVersionId: 'cn_27_v1_3',
      title: 'CN_27 V1.3',
      market: 'cn',
      benchmark: '000300',
      evidenceCutoff: '2026-11-12',
    }), navRows([
      ['2023-09-01', 90],
      ['2023-09-05', 100],
      ['2026-09-04', 200],
    ]))[0];
    expect(row.cells['3y'].coverage.state).toBe('full');
    expect(row.cells['3y'].coverage.missingDays).toBe(1);
    expect(row.cells['3y'].display).toBe(true);
    expect(row.cells['3y'].value).toBeCloseTo(1, 12);
    expect(row.cells['3y'].reason).toBeUndefined();
  });

  it('hides a partial short-history window beyond seven days instead of zeroing it', () => {
    const row = strategyRowsFromNav(run(), navRows([
      ['2023-11-25', 100],
      ['2026-11-11', 150],
    ]))[0];
    const cell = row.cells['3y'];
    expect(cell.coverage.state).toBe('partial');
    expect(cell.coverage.reason).toBe('short_history');
    expect(cell.display).toBe(false);
    expect(cell.value).toBeNull();
    expect(cell.reason).toContain('2023-11-25');
    expect(cell.reason).toContain('14 calendar days');
    expect(formatReturn(cell.value)).toBe('—');
  });

  it('hides a one-week window whose observations are too coarse (us_x cadence)', () => {
    const row = strategyRowsFromNav(run(), navRows([
      ['2026-10-28', 100],
      ['2026-11-11', 120],
    ]))[0];
    const cell = row.cells['1w'];
    expect(cell.coverage.state).toBe('partial');
    expect(cell.coverage.reason).toBe('coarse_cadence');
    expect(cell.coverage.cadenceDays).toBe(14);
    expect(cell.display).toBe(false);
    expect(cell.reason).toContain('14 days apart');
    expect(formatReturn(cell.value)).toBe('—');
  });

  it('never turns a one-point window into a zero return', () => {
    const row = strategyRowsFromNav(run(), navRows([['2026-11-11', 100]]))[0];
    const cell = row.cells['1m'];
    expect(cell.coverage.state).toBe('none');
    expect(cell.coverage.reason).toBe('insufficient_observations');
    expect(cell.display).toBe(false);
    expect(cell.value).toBeNull();
    expect(formatReturn(cell.value)).toBe('—');
  });
});

describe('model ranking staleness', () => {
  it('keeps a 14-day lag fresh and marks 15 days stale', () => {
    const fresh = strategyRowsFromNav(run({ evidenceCutoff: '2026-11-14' }), navRows([
      ['2026-11-01', 100],
      ['2026-11-10', 110],
    ]))[0];
    expect(STALE_AFTER_DAYS).toBe(14);
    expect(fresh.staleDays).toBe(4);
    expect(fresh.stale).toBe(false);

    const boundary = strategyRowsFromNav(run({ evidenceCutoff: '2026-11-24' }), navRows([
      ['2026-11-01', 100],
      ['2026-11-10', 110],
    ]))[0];
    expect(boundary.staleDays).toBe(14);
    expect(boundary.stale).toBe(false);

    const stale = strategyRowsFromNav(run({ evidenceCutoff: '2026-11-25' }), navRows([
      ['2026-11-01', 100],
      ['2026-11-10', 110],
    ]))[0];
    expect(stale.staleDays).toBe(15);
    expect(stale.stale).toBe(true);
    expect(stale.asOf).toBe('2026-11-10');
  });

  it('uses each strategy own last NAV date as its as-of date', () => {
    const rows = strategyRowsFromNav(run({
      key: 'cn_27_v1_3',
      modelVersionId: 'cn_27_v1_3',
      title: 'CN_27 V1.3',
      market: 'cn',
      evidenceCutoff: '2026-11-12',
    }), navRows([
      ['2023-09-01', 100],
      ['2026-09-04', 140],
    ]))[0];
    expect(rows.asOf).toBe('2026-09-04');
    expect(rows.evidenceCutoff).toBe('2026-11-12');
    expect(rows.stale).toBe(true);
    expect(rows.staleDays).toBe(69);
  });
});

describe('index rows', () => {
  it('uses governed close levels rather than opens or a baseline overlay', () => {
    const row = indexRowsFromBars('us', 'QQQ', 'QQQ', [
      bar('2026-11-04', 100, 110),
      bar('2026-11-06', 112, 116),
      bar('2026-11-11', 119, 121),
    ], '2026-11-11')[0];
    expect(row.nav.map((point) => point.value)).toEqual([110, 116, 121]);
    expect(row.cells['1w'].display).toBe(true);
    expect(row.cells['1w'].value).toBeCloseTo(121 / 110 - 1, 12);
    expect(row.href).toBe('/securities/us/QQQ');
    expect(row.excess?.value).toBeNull();
    expect(row.excess?.source).toBe('unavailable');
    expect(row.maxDrawdownBasis).toContain('not total return');
  });

  it('keeps an index drawdown on close-to-close price levels', () => {
    const row = indexRowsFromBars('cn', '000300', 'CSI 300', [
      bar('2026-11-02', 1, 100),
      bar('2026-11-03', 1, 80),
      bar('2026-11-04', 1, 120),
    ], '2026-11-04')[0];
    expect(row.maxDrawdown).toBeCloseTo(-0.2, 12);
    expect(row.href).toBe('/securities/cn/000300');
  });
});

describe('model ranking excess', () => {
  it('uses the retained excess metric only when it is available', () => {
    const retained = retainedExcess(run({ summary: { metrics: [
      { metric_id: 'excess_return', value: 0.25, availability_status: 'available', scope: 'full_history' },
    ] } }));
    expect(retained).toMatchObject({ value: 0.25, source: 'retained', label: 'retained' });
    expect(retained.basis).toContain('full_history');

    const unavailable = retainedExcess(run({ summary: { metrics: [
      { metric_id: 'excess_return', value: null, availability_status: 'not_retained', unavailable_reason: 'Not retained.' },
    ] } }));
    expect(unavailable.value).toBeNull();
    expect(unavailable.source).toBe('unavailable');
    expect(unavailable.reason).toBe('Not retained.');
  });

  it('labels a sealed derived excess as derived', () => {
    const excess = rankingExcessFromDerived({
      result: { excess_return: 0.16979, strategy_cumulative_return: 1, benchmark_cumulative_return: 1 },
      window: { observed_start: '2024-01-30', observed_end: '2026-11-10', observation_count: 699 },
      benchmark: { declared_identity: 'QQQ' },
      label: 'Derived · vs QQQ · 2024-01-30 → 2026-11-10 · 699 observations',
    } as DerivedExcess);
    expect(excess.value).toBeCloseTo(0.16979, 12);
    expect(excess.source).toBe('derived');
    expect(excess.label).toBe('derived');
    expect(excess.basis).toContain('699 observations');
  });

  it('attaches excess only when one is supplied', () => {
    const without = strategyRowsFromNav(run(), navRows([['2026-11-10', 100], ['2026-11-11', 110]]))[0];
    expect(without.excess).toBeUndefined();
    const withExcess = strategyRowsFromNav(run(), navRows([['2026-11-10', 100], ['2026-11-11', 110]]), {
      excess: { value: 0.1, source: 'retained', label: 'retained', basis: 'Retained.' },
    })[0];
    expect(withExcess.excess?.value).toBe(0.1);
  });

  it('carries retained max drawdown with its basis', () => {
    const row = strategyRowsFromNav(run({ summary: { metrics: [
      { metric_id: 'max_drawdown', value: -0.25, availability_status: 'available' },
    ] } }), navRows([['2026-11-10', 100], ['2026-11-11', 110]]))[0];
    expect(row.maxDrawdown).toBe(-0.25);
    expect(row.maxDrawdownBasis).toContain('Retained formal');
  });
});

describe('deterministic ordering', () => {
  function ranked(id: string, title: string, market: 'us' | 'cn', returnValue: number, last: string, cutoff: string) {
    const start = last === '2026-11-11' ? '2026-10-11' : '2026-08-01';
    return strategyRowsFromNav(run({
      key: id,
      modelVersionId: id,
      title,
      market,
      evidenceCutoff: cutoff,
    }), navRows([[start, 100], [last, 100 * (1 + returnValue)]]))[0];
  }

  it('groups by market, keeps fresh before stale, then sorts the horizon descending', () => {
    const rows = [
      ranked('cn_27', 'China strong', 'cn', 0.5, '2026-11-11', '2026-11-11'),
      ranked('us_stale', 'Stale high', 'us', 0.2, '2026-09-01', '2026-11-11'),
      ranked('us_beta', 'Beta', 'us', 0.1, '2026-11-11', '2026-11-11'),
      ranked('us_alpha', 'Alpha', 'us', 0.05, '2026-11-11', '2026-11-11'),
    ];
    expect(sortRankingRows(rows, '1m').map((row) => row.id)).toEqual([
      'us_beta', 'us_alpha', 'us_stale', 'cn_27',
    ]);
  });

  it('places missing horizon cells after measured cells and breaks ties by title', () => {
    const missing = strategyRowsFromNav(run({ modelVersionId: 'missing', title: 'Missing' }), navRows([
      ['2026-11-11', 100],
    ]))[0];
    const alpha = strategyRowsFromNav(run({ modelVersionId: 'alpha', title: 'Alpha' }), navRows([
      ['2026-10-11', 100], ['2026-11-11', 110],
    ]))[0];
    const beta = strategyRowsFromNav(run({ modelVersionId: 'beta', title: 'Beta' }), navRows([
      ['2026-10-11', 100], ['2026-11-11', 110],
    ]))[0];
    expect(sortRankingRows([missing, beta, alpha], '1m').map((row) => row.id)).toEqual([
      'alpha', 'beta', 'missing',
    ]);
  });
});

describe('formatting', () => {
  it('formats percentages with one decimal and an explicit sign', () => {
    expect(formatReturn(0.1234)).toBe('+12.3%');
    expect(formatReturn(-0.0456)).toBe('-4.6%');
    expect(formatReturn(0)).toBe('0.0%');
    expect(formatReturn(-0.00001)).toBe('0.0%');
    expect(formatReturn(null)).toBe('—');
  });

  it('formats prices with grouping and two decimals', () => {
    expect(formatPrice(1234.5)).toBe('1,234.50');
    expect(formatPrice(-2)).toBe('-2.00');
    expect(formatPrice(undefined)).toBe('—');
    expect(formatPriceChange(1.2)).toBe('+1.20');
    expect(formatPriceChange(-0.001)).toBe('0.00');
  });

  it('keeps dates as ISO strings and rejects invalid dates', () => {
    expect(formatDate('2026-11-11')).toBe('2026-11-11');
    expect(formatDate('2026-02-30')).toBe('—');
    expect(formatDate(null)).toBe('—');
  });
});
