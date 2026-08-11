import { describe, expect, it } from 'vitest';
import {
  evidenceAvailabilityLabel,
  formatCanonicalMetric,
  formatDeclaredValue,
} from './evidence-availability';
import type { CanonicalMetricV2 } from './model-run-bundle-v2';

function metric(overrides: Partial<CanonicalMetricV2>): CanonicalMetricV2 {
  return {
    metric_id: 'rank_ic',
    value: 0.04,
    unit: 'decimal',
    direction: 'higher_is_better',
    estimator: 'governed_test',
    annualization: null,
    sample_count: 10,
    scope: 'test',
    availability_status: 'available',
    unavailable_reason: null,
    ...overrides,
  };
}

describe('formal evidence availability rendering', () => {
  it('renders governed availability states instead of generic unavailable labels', () => {
    expect(evidenceAvailabilityLabel('not_applicable')).toBe('Not applicable');
    expect(evidenceAvailabilityLabel('not_computed')).toBe('Not computed');
    expect(evidenceAvailabilityLabel('not_retained')).toBe('Not retained');
    expect(evidenceAvailabilityLabel('blocked_by_source')).toBe('Blocked by source');
  });

  it('treats undeclared contract fields as violations', () => {
    expect(evidenceAvailabilityLabel(undefined)).toBe('Contract violation');
    expect(formatDeclaredValue(undefined)).toBe('Contract violation');
    expect(formatDeclaredValue(null)).toBe('Contract violation');
    expect(formatDeclaredValue('')).toBe('Contract violation');
    expect(formatDeclaredValue(0)).toBe('0');
    expect(formatDeclaredValue(false)).toBe('false');
  });

  it('never converts explicit metric states into Unavailable or Not declared', () => {
    const values = [
      formatCanonicalMetric(metric({ availability_status: 'available', value: 0.04 })),
      formatCanonicalMetric(metric({ availability_status: 'not_applicable', value: null, estimator: null, sample_count: null, unavailable_reason: 'Outside this model contract.' })),
      formatCanonicalMetric(metric({ availability_status: 'not_computed', value: null, estimator: null, sample_count: null, unavailable_reason: 'Not computed by the governed builder.' })),
      formatCanonicalMetric(metric({ availability_status: 'not_retained', value: null, estimator: null, sample_count: null, unavailable_reason: 'Historical source did not retain it.' })),
      formatCanonicalMetric(metric({ availability_status: 'blocked_by_source', value: null, estimator: null, sample_count: null, unavailable_reason: 'Source contract blocks it.' })),
    ];
    expect(values).not.toContain('Unavailable');
    expect(values).not.toContain('Not declared');
    expect(values).toEqual(['0.040', 'Not applicable', 'Not computed', 'Not retained', 'Blocked by source']);
  });
});
