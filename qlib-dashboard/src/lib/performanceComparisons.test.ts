import { describe, expect, it } from 'vitest';
import type { MarketEvidenceCatalog } from '@/lib/market-evidence';
import type { BenchmarkOption } from '@/lib/performanceBenchmarks';
import {
  alignMarketBarsToPerformanceDates,
  buildPerformanceComparisonOptions,
} from './performanceComparisons';

function catalog(): MarketEvidenceCatalog {
  return {
    schema_version: '1.1',
    evidence_type: 'market_evidence_catalog',
    market: 'us',
    pool_id: 'us_selected_equities_v2',
    candidate_count: 1,
    benchmark: 'QQQ',
    auxiliary_symbols: ['TQQQ'],
    start: '2026-01-01',
    cutoff: '2026-01-31',
    provider_identity_sha256: 'a'.repeat(64),
    provider_manifest_sha256: 'b'.repeat(64),
    factor_diagnostics_path: 'factor-diagnostics.json',
    factor_diagnostics_sha256: 'c'.repeat(64),
    factor_library_sha256: 'd'.repeat(64),
    series_factor_group: 'momentum_volatility_volume',
    symbol_count: 3,
    symbols: [
      {
        instrument_id: 'us:QQQ', provider_symbol: 'QQQ', symbol: 'QQQ', source_instruments: [], roles: ['benchmark'], name: 'QQQ',
        path: 'symbols/QQQ.json', sha256: 'e'.repeat(64), start: '2026-01-01', cutoff: '2026-01-31', formal_event_count: 0, factor_series_available: true,
      },
      {
        instrument_id: 'us:TQQQ', provider_symbol: 'TQQQ', symbol: 'TQQQ', source_instruments: [], roles: ['formal_auxiliary'], name: 'TQQQ',
        path: 'symbols/TQQQ.json', sha256: 'f'.repeat(64), start: '2026-01-01', cutoff: '2026-01-31', formal_event_count: 0, factor_series_available: true,
      },
      {
        instrument_id: 'us:AAPL', provider_symbol: 'AAPL', symbol: 'AAPL', source_instruments: [], roles: ['selected_pool_candidate'], name: 'Apple Inc.',
        path: 'symbols/AAPL.json', sha256: '1'.repeat(64), start: '2026-01-01', cutoff: '2026-01-31', formal_event_count: 0, factor_series_available: true,
      },
    ],
    research_only: true,
    trade_ready: false,
  };
}

describe('performance comparisons', () => {
  it('prefers the retained formal benchmark and adds governed reference and pool assets', () => {
    const retained: BenchmarkOption[] = [{
      key: 'benchmark_qqq',
      field: 'bench_qqq',
      label: 'QQQ',
      series: [0, 0.01],
    }];
    const options = buildPerformanceComparisonOptions(retained, catalog());

    expect(options.filter(option => option.label === 'QQQ')).toHaveLength(1);
    expect(options.find(option => option.label === 'TQQQ')?.group).toBe('Benchmarks');
    expect(options.find(option => option.label === 'AAPL')).toMatchObject({ group: 'Stock pool', detail: 'Apple Inc.' });
  });

  it('aligns market closes to performance dates and rebases the selected asset', () => {
    const series = alignMarketBarsToPerformanceDates([
      { time: '2026-01-02', open: 99, high: 101, low: 98, close: 100, volume: 1 },
      { time: '2026-01-05', open: 104, high: 106, low: 103, close: 105, volume: 1 },
      { time: '2026-01-06', open: 108, high: 111, low: 107, close: 110, volume: 1 },
    ], ['2026-01-02', '2026-01-04', '2026-01-06']);

    expect(series?.[0]).toBe(0);
    expect(series?.[1]).toBe(0);
    expect(series?.[2]).toBeCloseTo(0.1, 10);
  });
});
