import { describe, expect, it } from 'vitest';
import type { DerivedExcess } from './derived-excess';
import type { GovernedRunSummary } from './governed-run';
import {
  RANKING_INDEXES,
  formatDate,
  formatPrice,
  formatPriceChange,
  formatReturn,
  indexRowsFromBars,
  periodAlignedExcess,
  rankingCell,
  rankingExcessFromDerived,
  rankingWindowPeriod,
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
  it('declares the ordered governed index identities', () => {
    expect(RANKING_INDEXES).toEqual([
      { market: 'us', symbol: 'QQQ', title: 'QQQ' },
      { market: 'us', symbol: 'SPX', title: 'S&P 500' },
      { market: 'cn', symbol: '000300', title: 'CSI 300' },
    ]);
  });

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
    expect(row.maxDrawdownBasis).toContain('not the sorted horizon');
    expect(row.maxDrawdownBasis).toContain('Close-to-close');
  });

  it('keeps each governed index own title as its benchmark, never another market baseline', () => {
    const bars = [bar('2026-11-04', 100, 110), bar('2026-11-11', 119, 121)];
    const qqq = indexRowsFromBars('us', 'QQQ', 'QQQ', bars, '2026-11-11')[0];
    const spx = indexRowsFromBars('us', 'SPX', 'S&P 500', bars, '2026-11-11')[0];
    const csi = indexRowsFromBars('cn', '000300', 'CSI 300', bars, '2026-11-11')[0];
    expect(qqq.benchmark).toBe('QQQ');
    expect(spx.benchmark).toBe('S&P 500');
    expect(csi.benchmark).toBe('CSI 300');
    expect(spx.id).toBe('index:us:SPX');
    expect(spx.market).toBe('us');
    expect(spx.href).toBe('/securities/us/SPX');
    expect(spx.excess?.value).toBeNull();
    expect(spx.excess?.reason).toContain('excess is not computed');
    expect(spx.signal).toBeUndefined();
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
    expect(row.maxDrawdownBasis).toContain('Retained max-drawdown summary');
    expect(row.maxDrawdownBasis).toContain('not the sorted horizon');
  });
});

describe('declared benchmark wealth', () => {
  it('resolves the declared wealth column for the real run shapes', () => {
    const byd = strategyRowsFromNav(run({ benchmark: 'BYD v1.2' }), [
      { date: '2026-01-02', account: 100, bench_byd_v1_2: 10 },
      { date: '2026-11-11', account: 120, bench_byd_v1_2: 12 },
    ])[0];
    expect(byd.benchmarkField).toBe('bench_byd_v1_2');
    expect(byd.benchmarkNav).toEqual([
      { date: '2026-01-02', value: 10 },
      { date: '2026-11-11', value: 12 },
    ]);

    const qqqi = strategyRowsFromNav(run({ modelVersionId: 'qqqi', benchmark: 'QQQ' }), [
      { date: '2026-01-02', account: 100, bench: -0.0146, bench_qqq: 0.9854 },
      { date: '2026-11-11', account: 120, bench: 0.0312, bench_qqq: 1.021 },
    ])[0];
    expect(qqqi.benchmarkField).toBe('bench_qqq');
    expect(qqqi.benchmarkNav.map((point) => point.value)).toEqual([0.9854, 1.021]);

    const usX = strategyRowsFromNav(run({ benchmark: 'QQQ' }), [
      { date: '2026-01-02', account: 100, bench_qqq: 1.0115, bench_qqq_before: 0.99 },
      { date: '2026-11-11', account: 120, bench_qqq: 1.05, bench_qqq_before: 0.99 },
    ])[0];
    expect(usX.benchmarkField).toBe('bench_qqq');
    // The `_before` opening anchor is never a wealth observation.
    expect(usX.benchmarkNav.map((point) => point.value)).toEqual([1.0115, 1.05]);
  });

  it('exposes no benchmark wealth when the run retains only an account identity', () => {
    const row = strategyRowsFromNav(run({
      modelVersionId: 'cn_27_v1_3',
      market: 'cn',
      benchmark: '000300',
    }), [
      { date: '2026-01-02', account: 100, benchmark_account: 200 },
      { date: '2026-11-11', account: 120, benchmark_account: 210 },
    ])[0];
    expect(row.benchmarkField).toBeNull();
    expect(row.benchmarkNav).toEqual([]);
  });

  it('never treats the plain bench return column as wealth, even when it is positive', () => {
    const row = strategyRowsFromNav(run({ benchmark: 'QQQ' }), [
      { date: '2026-01-02', account: 100, bench: 0.01 },
      { date: '2026-11-11', account: 120, bench: 0.02 },
    ])[0];
    expect(row.benchmarkField).toBeNull();
    expect(row.benchmarkNav).toEqual([]);
  });
});

describe('period-aligned excess', () => {
  function rowFrom(points: Array<{ date: string; account?: number; bench_qqq?: number }>) {
    return strategyRowsFromNav(run(), points.map((point) => ({
      date: point.date,
      account: point.account ?? 0,
      ...(point.bench_qqq === undefined ? {} : { bench_qqq: point.bench_qqq }),
    })))[0];
  }

  it('matches (1 + strategy) / (1 + benchmark) - 1 over the exact common dates for 1M and 1Y', () => {
    const row = rowFrom([
      { date: '2025-11-11', account: 100, bench_qqq: 200 },
      { date: '2026-10-11', account: 130, bench_qqq: 250 },
      { date: '2026-11-11', account: 140, bench_qqq: 260 },
    ]);

    const oneMonth = periodAlignedExcess(row, '1m');
    expect(oneMonth.source).toBe('aligned');
    expect(oneMonth.label).toBe('aligned');
    expect(oneMonth.value).toBeCloseTo((140 / 130) / (260 / 250) - 1, 12);
    expect(oneMonth.window).toBe('2026-10-11 → 2026-11-11');
    expect(oneMonth.basis).toContain('1M aligned excess');
    expect(oneMonth.basis).toContain('bench_qqq');
    expect(oneMonth.basis).toContain('Browser-derived, not a sealed metric');

    const oneYear = periodAlignedExcess(row, '1y');
    expect(oneYear.value).toBeCloseTo((140 / 100) / (260 / 200) - 1, 12);
    expect(oneYear.window).toBe('2025-11-11 → 2026-11-11');
  });

  it('uses only exact common dates and never a synthetic window start', () => {
    const row = rowFrom([
      { date: '2026-09-11', account: 100, bench_qqq: 230 },
      { date: '2026-10-11', account: 120 },
      { date: '2026-10-20', account: 125, bench_qqq: 245 },
      { date: '2026-11-11', account: 150, bench_qqq: 270 },
    ]);
    const aligned = periodAlignedExcess(row, '1m');
    // The requested 1M start is 2026-10-11, but the benchmark has no
    // observation there; the measurement starts at the exact common date.
    expect(aligned.value).toBeCloseTo((150 / 125) / (270 / 245) - 1, 12);
    expect(aligned.window).toBe('2026-10-20 → 2026-11-11');
    expect(aligned.window).not.toContain('2026-10-11');
    expect(aligned.basis).not.toContain('2026-10-11');
  });

  it('shows no aligned excess when the horizon cell is not displayed', () => {
    const row = rowFrom([
      { date: '2026-11-11', account: 100, bench_qqq: 200 },
      { date: '2026-11-12', account: 101, bench_qqq: 201 },
    ]);
    expect(row.cells['1m'].display).toBe(false);
    const aligned = periodAlignedExcess(row, '1m');
    expect(aligned.value).toBeNull();
    expect(aligned.source).toBe('unavailable');
    expect(aligned.reason).toContain('not displayed');
  });

  it('names the missing benchmark wealth column instead of inventing an excess', () => {
    const row = strategyRowsFromNav(run({
      modelVersionId: 'cn_27_v1_3',
      market: 'cn',
      benchmark: '000300',
    }), [
      { date: '2023-09-01', account: 100 },
      { date: '2026-08-05', account: 136 },
      { date: '2026-09-04', account: 140 },
    ])[0];
    expect(row.cells['1m'].display).toBe(true);
    const aligned = periodAlignedExcess(row, '1m');
    expect(aligned.value).toBeNull();
    expect(aligned.reason).toContain('No retained benchmark wealth column is available for 000300');
  });

  it('reports a missing exact-date overlap rather than snapping the benchmark', () => {
    const row = rowFrom([
      { date: '2026-10-11', account: 100 },
      { date: '2026-10-20', bench_qqq: 210 },
      { date: '2026-10-25', account: 105 },
      { date: '2026-11-05', bench_qqq: 215 },
      { date: '2026-11-11', account: 120 },
    ]);
    expect(row.cells['1m'].display).toBe(true);
    const aligned = periodAlignedExcess(row, '1m');
    expect(aligned.value).toBeNull();
    expect(aligned.reason).toContain('fewer than two exact common dates');
  });

  it('never carries benchmark wealth or excess on governed index rows', () => {
    const index = indexRowsFromBars('us', 'QQQ', 'QQQ', [
      bar('2026-10-11', 100, 100),
      bar('2026-11-11', 100, 110),
    ], '2026-11-11')[0];
    expect(index.benchmarkNav).toEqual([]);
    expect(index.benchmarkField).toBeNull();
    expect(index.excess?.value).toBeNull();
    expect(index.excess?.source).toBe('unavailable');
    expect(periodAlignedExcess(index, '1m').value).toBeNull();
  });

  it('keeps the 1M trend window for metric sorts', () => {
    expect(rankingWindowPeriod('1m')).toBe('1m');
    expect(rankingWindowPeriod('3y')).toBe('3y');
    expect(rankingWindowPeriod('excess')).toBe('1m');
    expect(rankingWindowPeriod('maxDrawdown')).toBe('1m');
    expect(rankingWindowPeriod('signal')).toBe('1m');
    expect(rankingWindowPeriod('asOf')).toBe('1m');
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

  it('orders explicit metric sorts while leaving every displayed cell untouched', () => {
    const alpha = strategyRowsFromNav(run({ modelVersionId: 'alpha', title: 'Alpha' }), navRows([
      ['2026-10-11', 100], ['2026-11-11', 110],
    ]), { excess: { value: 0.2, source: 'retained', label: 'retained', basis: 'Alpha basis.' } })[0];
    const beta = {
      ...alpha,
      id: 'beta',
      modelVersionId: 'beta',
      title: 'Beta',
      asOf: '2026-10-11',
      excess: { value: 0.05, source: 'retained' as const, label: 'retained', basis: 'Beta basis.' },
      maxDrawdown: -0.02,
      signal: { label: 'Attention', direction: 'attention', note: 'Review', attention: true, isNew: false, isHold: false },
    };
    const cells = new Map([alpha, beta].map(row => [row.id, row.cells]));
    expect(sortRankingRows([beta, alpha], 'excess').map(row => row.id)).toEqual(['alpha', 'beta']);
    expect(sortRankingRows([alpha, beta], 'maxDrawdown').map(row => row.id)).toEqual(['beta', 'alpha']);
    expect(sortRankingRows([alpha, beta], 'signal').map(row => row.id)).toEqual(['beta', 'alpha']);
    expect(sortRankingRows([beta, alpha], 'asOf').map(row => row.id)).toEqual(['alpha', 'beta']);
    for (const row of [alpha, beta]) expect(row.cells).toBe(cells.get(row.id));
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

describe('row-kind ordering', () => {
  function strategyRow(id: string, market: 'us' | 'cn', points: Array<[string, number]>) {
    return strategyRowsFromNav(run({
      key: id,
      modelVersionId: id,
      title: id,
      market,
      evidenceCutoff: '2026-11-11',
    }), navRows(points))[0];
  }

  function indexRow(market: 'us' | 'cn', symbol: string, title: string, points: Array<[string, number]>) {
    return indexRowsFromBars(
      market,
      symbol,
      title,
      points.map(([time, close]) => bar(time, close, close)),
      '2026-11-11',
    )[0];
  }

  const rows = [
    // US strategies: beta leads on 1M, alpha leads on 3M.
    strategyRow('us_alpha', 'us', [['2026-08-11', 100], ['2026-10-11', 110], ['2026-11-11', 120]]),
    strategyRow('us_beta', 'us', [['2026-08-11', 100], ['2026-10-11', 100], ['2026-11-11', 110]]),
    // US indices: QQQ leads on 1M, S&P 500 leads on 3M.
    indexRow('us', 'QQQ', 'QQQ', [['2026-08-11', 110], ['2026-10-11', 100], ['2026-11-11', 120]]),
    indexRow('us', 'SPX', 'S&P 500', [['2026-08-11', 100], ['2026-10-11', 120], ['2026-11-11', 138]]),
    // China: the index outreturns the strategy on every horizon.
    strategyRow('cn_27', 'cn', [['2026-08-11', 100], ['2026-10-11', 100], ['2026-11-11', 103]]),
    indexRow('cn', '000300', 'CSI 300', [['2026-08-11', 100], ['2026-10-11', 100], ['2026-11-11', 112]]),
  ];

  const ids = (sorted: ReturnType<typeof sortRankingRows>) => sorted.map((row) => row.id);

  it('keeps the mixed order as the default, ranking strategies and indices together', () => {
    const expected = [
      'index:us:QQQ', 'index:us:SPX', 'us_beta', 'us_alpha',
      'index:cn:000300', 'cn_27',
    ];
    expect(ids(sortRankingRows(rows, '1m'))).toEqual(expected);
    expect(ids(sortRankingRows(rows, '1m', { kindOrder: 'mixed' }))).toEqual(expected);
    expect(ids(sortRankingRows(rows, '3m'))).toEqual([
      'index:us:SPX', 'us_alpha', 'us_beta', 'index:us:QQQ',
      'index:cn:000300', 'cn_27',
    ]);
  });

  it('places every strategy row before the index rows in both markets while keeping the horizon order', () => {
    expect(ids(sortRankingRows(rows, '1m', { kindOrder: 'strategies-first' }))).toEqual([
      'us_beta', 'us_alpha', 'index:us:QQQ', 'index:us:SPX',
      'cn_27', 'index:cn:000300',
    ]);
    // The same kind precedence with another horizon: strategies and then
    // indices each follow the 3M order rather than the 1M order.
    expect(ids(sortRankingRows(rows, '3m', { kindOrder: 'strategies-first' }))).toEqual([
      'us_alpha', 'us_beta', 'index:us:SPX', 'index:us:QQQ',
      'cn_27', 'index:cn:000300',
    ]);
  });

  it('is deterministic, leaves the input untouched and never computes index excess', () => {
    const ordered = sortRankingRows(rows, '1m', { kindOrder: 'strategies-first' });
    expect(ids(sortRankingRows(rows, '1m', { kindOrder: 'strategies-first' }))).toEqual(ids(ordered));
    expect(ids(rows)).toEqual([
      'us_alpha', 'us_beta', 'index:us:QQQ', 'index:us:SPX', 'cn_27', 'index:cn:000300',
    ]);
    for (const spy of ordered.filter((row) => row.kind === 'index' && row.symbol === 'SPX')) {
      expect(spy.title).toBe('S&P 500');
      expect(spy.excess?.value).toBeNull();
      expect(spy.excess?.reason).toContain('excess is not computed');
    }
    expect(ordered.filter((row) => row.kind === 'index').map((row) => row.symbol))
      .toContain('SPX');
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
