import { describe, expect, it } from 'vitest';
import {
  buildPagePath,
  CLOUDFLARE_WEB_ANALYTICS_SRC,
  GA_MEASUREMENT_ID,
  viewFromHash,
} from './analytics';

describe('AlphaEngine dual analytics contract', () => {
  it('keeps the production GA4 property', () => {
    expect(GA_MEASUREMENT_ID).toBe('G-18RES38PZ5');
  });

  it('keeps the Cloudflare Web Analytics beacon', () => {
    expect(CLOUDFLARE_WEB_ANALYTICS_SRC).toBe('https://static.cloudflareinsights.com/beacon.min.js');
  });

  it('preserves HashRouter views in page paths', () => {
    expect(buildPagePath({
      pathname: '/alpha_engine/',
      search: '?source=github',
      hash: '#/backtests?run=us-x1.1',
    })).toBe('/alpha_engine/?source=github#/backtests?run=us-x1.1');
  });

  it('reduces product events to non-sensitive route families', () => {
    expect(viewFromHash('#/backtests?run=us-x1.1')).toBe('backtests');
    expect(viewFromHash('#/strategies/qqq-v4.2')).toBe('strategies');
    expect(viewFromHash('#/')).toBe('landing');
  });
});
