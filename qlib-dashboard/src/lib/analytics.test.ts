import { describe, expect, it } from 'vitest';
import { buildPagePath, GA_MEASUREMENT_ID } from './analytics';

describe('AlphaEngine GA4 contract', () => {
  it('uses the production measurement ID', () => {
    expect(GA_MEASUREMENT_ID).toBe('G-18RES38PZ5');
  });

  it('preserves HashRouter views in page paths', () => {
    expect(buildPagePath({
      pathname: '/alpha_engine/',
      search: '?source=github',
      hash: '#/backtests?run=us-x1.1',
    })).toBe('/alpha_engine/?source=github#/backtests?run=us-x1.1');
  });
});
