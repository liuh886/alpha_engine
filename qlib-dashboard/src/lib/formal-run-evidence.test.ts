import { describe, expect, it } from 'vitest';
import { metricById } from './formal-run-evidence';
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
});
