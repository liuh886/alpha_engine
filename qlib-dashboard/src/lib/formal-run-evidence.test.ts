import { describe, expect, it, vi } from 'vitest';
import { attachRetainedTradeEvidence, loadFormalRunEvidence, metricById } from './formal-run-evidence';
import { parseCanonicalMetricV2 } from './model-run-bundle-v2';
import { loadRunSection, type GovernedRunSummary } from './governed-run';
import { declaredBenchmarkDescriptor, discoverBenchmarkOptions } from './performanceBenchmarks';

vi.mock('./governed-run', () => ({ loadRunSection: vi.fn() }));

describe('formal run evidence helpers', () => {
  it('keeps the declared BYD strategy benchmark while retaining a separate optional stock baseline', async () => {
    const report = [
      { date: '2026-01-01', account: 1, bench_byd_v1_2: 1 },
      { date: '2026-01-02', account: 1.2, bench_byd_v1_2: 1.1 },
    ];
    const sections = {
      performance: { research_only: true, trade_ready: false, benchmark: 'BYD v1.2',
        date_range: { start: '2026-01-01', end: '2026-01-02' }, report },
      portfolio: { research_only: true, trade_ready: false, positions: [
        { date: '2026-01-01', instrument: 'BYD', price: 100, weight: 1 },
        { date: '2026-01-02', instrument: 'BYD', price: 200, weight: 1 },
      ] },
    };
    vi.mocked(loadRunSection).mockImplementation(async (_run, key) => sections[key as keyof typeof sections]);
    const run = { channel: 'formal', modelFamilyId: 'byd_allocation', benchmark: 'BYD v1.2',
      summary: { research_only: true, trade_ready: false, metrics: [] },
      manifest: { comparability_key: { trace_frequency: 'daily' }, sections: Object.keys(sections).map(section_id => ({ section_id, availability_status: 'available' })) },
    } as unknown as GovernedRunSummary;
    const evidence = await loadFormalRunEvidence(run);
    const descriptor = declaredBenchmarkDescriptor(evidence.performance.report, evidence.performance.benchmark);
    expect(descriptor?.field).toBe('bench_byd_v1_2');
    expect(evidence.performance.report[0].benchmark_id).toBe('BYD v1.2');
    const options = discoverBenchmarkOptions(evidence.performance.report, evidence.performance.benchmark);
    expect(options.find(option => option.field === 'bench_byd_v1_2')?.series[1]).toBeCloseTo(.1);
    expect(options.find(option => option.field === 'bench_byd')?.series[1]).toBe(1);
    expect(report[0]).not.toHaveProperty('benchmark_id');
    expect(report[0]).not.toHaveProperty('account_before');
  });
  it('keeps unavailable canonical metrics explicit', () => {
    const metric = parseCanonicalMetricV2({
      metric_id: 'sharpe_ratio',
      value: null,
      unit: 'decimal',
      direction: 'higher_is_better',
      estimator: null,
      annualization: null,
      sample_count: null,
      scope: 'accepted_formal_window',
      availability_status: 'not_retained',
      unavailable_reason: 'The source package did not retain Sharpe ratio.',
    });
    expect(metricById([metric], 'sharpe_ratio')).toEqual(metric);
    expect(metric.value).toBeNull();
    expect(metric.unavailable_reason).toContain('did not retain');
  });

  it('does not invent undeclared metrics', () => {
    expect(metricById([], 'annualized_return')).toBeNull();
  });

  it('joins retained trade costs and actions by exact date and instrument', () => {
    const positions = attachRetainedTradeEvidence(
      [
        { date: '2026-08-12', instrument: 'A', weight: 0.6 },
        { date: '2026-08-12', instrument: 'B', weight: 0.4 },
      ],
      [
        { date: '2026-08-12', instrument: 'A', action: 'buy', transaction_cost: 0.001 },
        { date: '2026-08-12', instrument: 'A', action: 'buy', transaction_cost: 0.002 },
        { date: '2026-08-11', instrument: 'B', action: 'sell', transaction_cost: 0.5 },
      ],
    );

    expect(positions).toEqual([
      expect.objectContaining({
        instrument: 'A',
        trade_status: 'trade',
        trade_action: 'buy',
        transaction_cost: 0.003,
      }),
      expect.objectContaining({ instrument: 'B', trade_status: 'no_trade' }),
    ]);
    expect(positions[1]).not.toHaveProperty('transaction_cost');
  });

  it('keeps a trade explicit when its retained cost is incomplete', () => {
    const [position] = attachRetainedTradeEvidence(
      [{ date: '2026-08-12', instrument: 'A', weight: 1 }],
      [{ date: '2026-08-12', instrument: 'A', action: 'buy', transaction_cost: null }],
    );

    expect(position).toEqual(expect.objectContaining({ trade_status: 'trade', trade_action: 'buy' }));
    expect(position).not.toHaveProperty('transaction_cost');
  });
});
