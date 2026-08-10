import { describe, expect, it } from 'vitest';

import {
  declaredBenchmarkDescriptor,
  discoverBenchmarkOptions,
} from './performanceBenchmarks';


describe('shared performance benchmark discovery', () => {
  it('discovers a new bench_* series without model-specific chart code', () => {
    const report = [
      { date: '2026-01-01', account: 1, bench_spy: 100 },
      { date: '2026-01-02', account: 1.02, bench_spy: 101 },
    ];

    const options = discoverBenchmarkOptions(report);

    expect(options).toHaveLength(1);
    expect(options[0].key).toBe('benchmark_spy');
    expect(options[0].label).toBe('SPY');
    expect(options[0].series[1]).toBeCloseTo(0.01, 10);
  });

  it('keeps generic bench evidence secondary to named baselines', () => {
    const report = [
      { date: '2026-01-01', account: 1, bench: 0, bench_qqq: 100 },
      { date: '2026-01-02', account: 1.02, bench: 0.01, bench_qqq: 101 },
    ];

    const options = discoverBenchmarkOptions(report);

    expect(options.map(option => option.key)).toEqual(['benchmark_qqq', 'benchmark']);
  });

  it('resolves declared CSI300 identity to retained hs300 evidence', () => {
    const report = [
      { date: '2026-01-01', account: 1, bench_qqq: 100, bench_hs300: 100 },
    ];

    expect(declaredBenchmarkDescriptor(report, '000300.SH')?.key).toBe('benchmark_hs300');
  });
});
