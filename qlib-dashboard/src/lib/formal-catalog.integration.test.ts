import { describe, expect, it } from 'vitest';
import { metricById } from './formal-run-evidence';

describe('formal evidence helpers', () => {
  it('returns null when a canonical metric is absent', () => {
    expect(metricById([], 'missing')).toBeNull();
  });
});
