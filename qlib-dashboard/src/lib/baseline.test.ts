import { describe, expect, it } from 'vitest';
import {
  MARKET_BASELINES,
  discoverBaselineOptions,
  marketNavFromBars,
  navFromBenchmarkField,
  type MarketBar,
} from './baseline';
import type { ReportRow } from './types';

describe('navFromBenchmarkField', () => {
  it('uses effective dates, skips missing cells, sorts and keeps the last duplicate', () => {
    const rows: ReportRow[] = [
      { date: '2026-01-05', account: 1, bench: 101 },
      { date: '2026-01-02', holding_end_date: '2026-01-03', account: 1, bench: 99 },
      { date: '2026-01-04', account: 1 },
      { date: '2026-01-06', account: 1 },
      { date: '2026-01-03', account: 1, bench: 95 },
      { date: '2026-02-30', account: 1, bench: 120 },
    ];
    expect(navFromBenchmarkField(rows, 'bench')).toEqual([
      { date: '2026-01-03', value: 95 },
      { date: '2026-01-05', value: 101 },
    ]);
  });

  it('fails closed when a present observation is zero or non-finite', () => {
    const valid: ReportRow[] = [
      { date: '2026-01-01', account: 1, bench: 100 },
      { date: '2026-01-02', account: 1, bench: 101 },
    ];
    expect(navFromBenchmarkField([
      ...valid,
      { date: '2026-01-03', account: 1, bench: 0 },
    ], 'bench')).toEqual([]);
    expect(navFromBenchmarkField([
      ...valid,
      { date: '2026-01-03', account: 1, bench: Number.NaN },
    ], 'bench')).toEqual([]);
    expect(navFromBenchmarkField([
      { date: '2026-01-01', account: 1, bench: -1 },
      { date: '2026-01-02', account: 1, bench: 101 },
    ], 'bench')).toEqual([]);
  });

  it('accepts bench_<slug> wealth fields', () => {
    const rows: ReportRow[] = [
      { date: '2026-01-02', account: 1, bench_byd_v1_2: 102 },
      { date: '2026-01-01', account: 1, bench_byd_v1_2: 100 },
    ];
    expect(navFromBenchmarkField(rows, 'bench_byd_v1_2')).toEqual([
      { date: '2026-01-01', value: 100 },
      { date: '2026-01-02', value: 102 },
    ]);
  });

  it('rejects non-wealth and opening-anchor fields', () => {
    const rows: ReportRow[] = [
      { date: '2026-01-01', account: 100, benchmark_return: 0.01, benchmark_account: 100, bench_qqq_before: 99 },
    ];
    for (const field of ['account', 'benchmark_return', 'benchmark_account', 'bench_qqq_before', 'value']) {
      expect(navFromBenchmarkField(rows, field)).toEqual([]);
    }
  });

  it('returns no curve without at least two valid observations', () => {
    expect(navFromBenchmarkField([], 'bench')).toEqual([]);
    expect(navFromBenchmarkField([{ date: '2026-01-01', account: 1, bench: 100 }], 'bench')).toEqual([]);
    expect(navFromBenchmarkField([{ date: '2026-01-01', account: 1, bench: -2 }], 'bench')).toEqual([]);
  });
});

describe('marketNavFromBars', () => {
  it('normalizes time/date, keeps raw opens, sorts and keeps the last duplicate', () => {
    const bars: MarketBar[] = [
      { time: '2026-01-05', open: 400 },
      { date: '2026-01-02', open: 390 },
      { time: '2026-01-03', open: 0 },
      { time: '2026-01-04', open: Number.NaN },
      { time: '2026-01-03', open: 395 },
      { date: '2026-02-30', open: 410 },
      { time: 'not-a-date', date: '2026-01-06', open: 405 },
    ];
    expect(marketNavFromBars(bars)).toEqual([
      { date: '2026-01-02', value: 390 },
      { date: '2026-01-03', value: 395 },
      { date: '2026-01-05', value: 400 },
      { date: '2026-01-06', value: 405 },
    ]);
  });

  it('prefers time over date and keeps open-to-open levels unrebased', () => {
    expect(marketNavFromBars([
      { time: '2026-01-02', date: '2026-01-01', open: 10 },
      { date: '2026-01-03', open: 20 },
    ])).toEqual([
      { date: '2026-01-02', value: 10 },
      { date: '2026-01-03', value: 20 },
    ]);
  });

  it('returns no curve without usable bars', () => {
    expect(marketNavFromBars([])).toEqual([]);
    expect(marketNavFromBars([{ open: 10 }])).toEqual([]);
    expect(marketNavFromBars([{ time: '2026-01-01', open: -1 }])).toEqual([]);
  });
});

describe('discoverBaselineOptions', () => {
  const report: ReportRow[] = [
    { date: '2026-01-01', account: 1, bench_byd_v1_2: 100 },
    { date: '2026-01-02', account: 1, bench_byd_v1_2: 102 },
  ];
  const usBars: MarketBar[] = [
    { time: '2026-01-01', open: 400 },
    { time: '2026-01-02', open: 402 },
  ];
  const cnBars: MarketBar[] = [
    { time: '2026-01-01', open: 3900 },
    { time: '2026-01-02', open: 3920 },
  ];

  it('labels the declared benchmark with the run identity and discovers its wealth field', () => {
    const options = discoverBaselineOptions({ benchmark: 'BYD v1.2', market: 'us' }, report, { us: usBars });
    expect(options[0]).toMatchObject({
      key: 'declared:bench_byd_v1_2',
      label: 'BYD v1.2',
      kind: 'declared',
      market: 'us',
      source: 'formal_report',
      available: true,
    });
  });

  it('keeps the raw manifest identity in the key but shows a readable label', () => {
    const options = discoverBaselineOptions({ benchmark: 'byd_v1.2', market: 'us' }, report, { us: usBars });
    expect(options[0]).toMatchObject({ key: 'declared:bench_byd_v1_2', label: 'BYD v1.2' });
    const unresolved = discoverBaselineOptions({ benchmark: 'qqq', market: 'us' }, report, { us: usBars });
    expect(unresolved[0]).toMatchObject({ key: 'declared:qqq', label: 'QQQ', available: false });
  });

  it('offers only the governed market baseline with its real symbol', () => {
    const us = discoverBaselineOptions({ benchmark: 'BYD v1.2', market: 'us' }, report, { us: usBars, cn: cnBars });
    expect(us.find(option => option.kind === 'market')).toMatchObject({
      key: 'market:QQQ',
      label: 'QQQ',
      source: 'market_bars',
      available: true,
    });
    expect(us.some(option => option.label.includes('CSI 300'))).toBe(false);

    const cnReport: ReportRow[] = [
      { date: '2026-01-01', account: 1, bench_hs300: 3900 },
      { date: '2026-01-02', account: 1, bench_hs300: 3920 },
    ];
    const cn = discoverBaselineOptions({ benchmark: '000300', market: 'cn' }, cnReport, { cn: cnBars });
    expect(cn.find(option => option.kind === 'market')).toMatchObject({
      key: 'market:000300',
      label: 'CSI 300 (000300.SH)',
      source: 'market_bars',
      available: true,
    });
    expect(cn.some(option => option.label === 'QQQ')).toBe(false);
  });

  it('never invents an unrequested index', () => {
    const options = discoverBaselineOptions({ benchmark: 'BYD v1.2', market: 'us' }, report, { us: usBars });
    const labels = options.map(option => option.label);
    expect(labels).toEqual(['BYD v1.2', 'QQQ', 'No baseline']);
    expect(labels.some(label => /sp\s*500|s&p/i.test(label))).toBe(false);
    expect(MARKET_BASELINES.us.symbol).toBe('QQQ');
    expect(MARKET_BASELINES.cn.symbol).toBe('000300');
  });

  it('keeps an unavailable declared benchmark visible with a reason', () => {
    const options = discoverBaselineOptions(
      { benchmark: 'BYD v1.2', market: 'us' },
      [{ date: '2026-01-01', account: 1, bench_byd_v1_2: 100 }],
    );
    expect(options[0]).toMatchObject({ kind: 'declared', available: false });
    expect(options[0].reason).toBeTruthy();
  });

  it('omits the market option when that market has no governed bars', () => {
    const options = discoverBaselineOptions({ benchmark: 'BYD v1.2', market: 'us' }, report, { cn: cnBars });
    expect(options.some(option => option.kind === 'market')).toBe(false);
  });

  it('marks the market baseline unavailable when its bars are not usable', () => {
    const options = discoverBaselineOptions({ benchmark: 'BYD v1.2', market: 'us' }, report, {
      us: [{ time: '2026-01-01', open: 400 }],
    });
    const market = options.find(option => option.kind === 'market');
    expect(market).toMatchObject({ kind: 'market', available: false });
    expect(market?.reason).toBeTruthy();
  });

  it('omits the declared option when the run declares no benchmark and always offers none', () => {
    const options = discoverBaselineOptions({ benchmark: null, market: 'cn' }, []);
    expect(options.map(option => option.kind)).toEqual(['none']);
    expect(options[0]).toMatchObject({ label: 'No baseline', available: true, market: 'cn' });
  });

  it('selects bench_qqq wealth for a QQQ run and never treats a per-row bench return as wealth', () => {
    // Real qqqi shape: `bench` is a daily return (starts negative), `bench_qqq`
    // is the retained wealth level.
    const qqqi: ReportRow[] = [
      { date: '2026-01-01', account: 1, bench: -0.0146, bench_qqq: 0.9854 },
      { date: '2026-01-02', account: 1, bench: 0.0312, bench_qqq: 1.021 },
      { date: '2026-01-03', account: 1, bench: 0.0219, bench_qqq: 1.6323 },
    ];
    const options = discoverBaselineOptions({ benchmark: 'QQQ', market: 'us' }, qqqi);
    expect(options[0]).toMatchObject({
      key: 'declared:bench_qqq',
      label: 'QQQ',
      available: true,
      source: 'formal_report',
      field: 'bench_qqq',
    });

    const returnsOnly: ReportRow[] = [
      { date: '2026-01-01', account: 1, bench: -0.0146 },
      { date: '2026-01-02', account: 1, bench: 0.0312 },
      { date: '2026-01-03', account: 1, bench: 0.0219 },
    ];
    const unavailable = discoverBaselineOptions({ benchmark: 'QQQ', market: 'us' }, returnsOnly, { us: usBars });
    expect(unavailable[0]).toMatchObject({ kind: 'declared', available: false });
    expect(unavailable[0].reason).toBe('Benchmark wealth series not retained');
    expect(unavailable[0].field).toBeUndefined();
    // The market baseline remains independently available.
    expect(unavailable.find(option => option.kind === 'market')).toMatchObject({ label: 'QQQ', available: true });
  });

  it('keeps the declared benchmark unavailable when CN 000300 has no benchmark column', () => {
    const cn27: ReportRow[] = [
      { date: '2026-01-01', account: 1 },
      { date: '2026-01-02', account: 1.01 },
    ];
    const options = discoverBaselineOptions({ benchmark: '000300', market: 'cn' }, cn27, { cn: cnBars });
    expect(options[0]).toMatchObject({
      label: '000300',
      kind: 'declared',
      available: false,
      reason: 'Benchmark wealth series not retained',
    });
    expect(options.find(option => option.kind === 'market')).toMatchObject({
      label: 'CSI 300 (000300.SH)',
      available: true,
    });
  });

  it('resolves the BYD strategy-version slug and labels it from the run identity', () => {
    const byd: ReportRow[] = [
      { date: '2026-01-01', account: 1, bench_byd_v1_2: 1000 },
      { date: '2026-01-02', account: 1, bench_byd_v1_2: 1010 },
    ];
    const options = discoverBaselineOptions({ benchmark: 'BYD v1.2', market: 'us' }, byd);
    expect(options[0]).toMatchObject({
      key: 'declared:bench_byd_v1_2',
      label: 'BYD v1.2',
      available: true,
      field: 'bench_byd_v1_2',
    });
    expect(navFromBenchmarkField(byd, 'bench_byd_v1_2')).toEqual([
      { date: '2026-01-01', value: 1000 },
      { date: '2026-01-02', value: 1010 },
    ]);
  });

  it('ignores the bench_qqq_before opening anchor', () => {
    const usx: ReportRow[] = [
      { date: '2026-01-01', account: 1, bench_qqq: 0.9854, bench_qqq_before: 0.99 },
      { date: '2026-01-02', account: 1, bench_qqq: 1.02, bench_qqq_before: 0.99 },
    ];
    const options = discoverBaselineOptions({ benchmark: 'QQQ', market: 'us' }, usx);
    expect(options[0]).toMatchObject({ key: 'declared:bench_qqq', available: true });
    expect(navFromBenchmarkField(usx, 'bench_qqq_before')).toEqual([]);
  });

  it('rejects a wealth-named column that contains a non-positive observation', () => {
    const corrupt: ReportRow[] = [
      { date: '2026-01-01', account: 1, bench_byd_v1_2: 1000 },
      { date: '2026-01-02', account: 1, bench_byd_v1_2: 0 },
      { date: '2026-01-03', account: 1, bench_byd_v1_2: 1020 },
    ];
    const options = discoverBaselineOptions({ benchmark: 'BYD v1.2', market: 'us' }, corrupt);
    expect(options[0]).toMatchObject({ kind: 'declared', available: false });
    expect(options[0].reason).toBe('Benchmark wealth series not retained');
  });
});
