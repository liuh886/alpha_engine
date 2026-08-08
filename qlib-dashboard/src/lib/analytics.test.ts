import { describe, expect, it } from 'vitest';
import { CLOUDFLARE_WEB_ANALYTICS_SRC } from './analytics';

describe('AlphaEngine web analytics contract', () => {
  it('uses the Cloudflare Web Analytics beacon', () => {
    expect(CLOUDFLARE_WEB_ANALYTICS_SRC).toBe('https://static.cloudflareinsights.com/beacon.min.js');
  });
});
