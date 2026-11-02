import { describe, expect, it } from 'vitest';
import {
  evidenceAvailabilityLabel,
  formatCanonicalMetric,
  formatDeclaredValue,
  formatRefValue,
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

  it('formats turnover as percentage rather than raw float', () => {
    expect(formatCanonicalMetric(metric({ metric_id: 'turnover', availability_status: 'available', value: 0.25 }))).toBe('25.00%');
  });

  describe('formatRefValue numerical formatting', () => {
    it('formats zero and integers without decimals', () => {
      expect(formatRefValue(0)).toBe('0');
      expect(formatRefValue(5)).toBe('5');
      expect(formatRefValue(-10)).toBe('-10');
    });

    it('formats normal floats truncated to at most 4 decimal places without trailing zeros', () => {
      expect(formatRefValue(0.123456)).toBe('0.1235');
      expect(formatRefValue(0.25)).toBe('0.25');
      expect(formatRefValue(1.5)).toBe('1.5');
    });

    it('preserves very small non-zero reference values instead of rounding to 0', () => {
      expect(formatRefValue(0.00003456)).toBe('0.00003456');
      expect(formatRefValue(-0.000012)).toBe('-0.000012');
      expect(formatRefValue(0.0000999)).toBe('0.0000999');
      expect(formatRefValue(1e-7)).toBe('1e-7');
      expect(formatRefValue(0.000005)).toBe('0.000005');
    });

    it('passes non-number types through as strings', () => {
      expect(formatRefValue('custom')).toBe('custom');
      expect(formatRefValue(true)).toBe('true');
    });
  });
});
