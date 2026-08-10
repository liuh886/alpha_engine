import { describe, expect, it } from 'vitest';
import { discoverBenchmarkOptions } from './performanceBenchmarks';

describe('discoverBenchmarkOptions', () => {
  it('should discover correct options', () => {
    const report = [
      { date: '2026-01-01', account: 1, bench_000300: 1, bench_hs300: 1, bench_byd: 1, bench_bydv11: 1 },
      { date: '2026-01-02', account: 1.05, bench_000300: 1.01, bench_hs300: 1.01, bench_byd: 1.02, bench_bydv11: 1.01 },
      { date: '2026-01-03', account: 1.08, bench_000300: 1.02, bench_hs300: 1.02, bench_byd: 1.04, bench_bydv11: 1.02 },
    ];
    console.log(discoverBenchmarkOptions(report));
  });
});
