import { describe, expect, it } from 'vitest';
import { metricById } from './formal-run-evidence';

describe('formal evidence helpers', () => {
  it('selects canonical metrics by stable identifier', () => {
    const metrics = [
      {
        metric_id: 'annualized_return',
        label: 'Annualized return',
        value: 0.12,
        unit: 'ratio',
        direction: 'higher_is_better',
        comparability_status: 'comparable',
      },
    ] as const;

    expect(metricById([...metrics], 'annualized_return')?.value).toBe(0.12);
    expect(metricById([...metrics], 'missing')).toBeNull();
  });
});
