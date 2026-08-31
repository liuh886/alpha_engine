import { describe, expect, it } from 'vitest';
import { attachRetainedTradeEvidence, metricById } from './formal-run-evidence';
import { parseCanonicalMetricV2 } from './model-run-bundle-v2';

describe('formal run evidence helpers', () => {
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
