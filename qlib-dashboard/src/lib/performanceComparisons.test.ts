import { expect, it } from 'vitest';
import type { BenchmarkOption } from './performanceBenchmarks';
import { buildPerformanceComparisonOptions } from './performanceComparisons';

it('keeps the retained benchmark preset order without changing its series or input order', () => {
  const labels = ['BYD', 'TQQQ', 'QQQ', 'CSI 300', 'CGDV'];
  const retained: BenchmarkOption[] = labels.map((label, index) => ({
    key: `benchmark_${index}`, field: `bench_${index}`, label, series: [0, 0.01 * index],
  }));
  const options = buildPerformanceComparisonOptions(retained);
  expect(options.map(option => option.label)).toEqual(['CSI 300', 'QQQ', 'TQQQ', 'CGDV', 'BYD']);
  expect(retained.map(option => option.label)).toEqual(labels);
  expect(options.find(option => option.label === 'QQQ')?.series).toBe(retained[2].series);
});
