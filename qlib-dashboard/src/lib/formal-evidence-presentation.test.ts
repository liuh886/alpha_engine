import { describe, expect, it } from 'vitest';
import { visibleWindowColumns } from './formal-evidence-presentation';

describe('visibleWindowColumns', () => {
  it('retains the complete CN ranker window summary', () => {
    const columns = visibleWindowColumns([{
      window: '2026H2_PARTIAL',
      rebalance_count: 3,
      total_return: -0.02,
      benchmark_return: -0.01,
      relative_excess: -0.01,
      max_drawdown: -0.03,
      risk_on_share: 1,
      all_period_hit_rate: 0.33,
      turnover: 2.1,
    }]);

    expect(columns).toEqual([
      'window',
      'rebalance_count',
      'total_return',
      'benchmark_return',
      'relative_excess',
      'max_drawdown',
      'risk_on_share',
      'all_period_hit_rate',
      'turnover',
    ]);
  });

  it('keeps model-specific scalar fields instead of silently dropping them', () => {
    const columns = visibleWindowColumns([{ window: 'stress', custom_tail_loss: -0.2 }]);
    expect(columns).toEqual(['window', 'custom_tail_loss']);
  });
});
