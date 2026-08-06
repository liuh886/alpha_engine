import { describe, expect, it, vi } from 'vitest';
import {
  classifyFormalFreshness,
  fetchFormalFreshness,
  parseFormalFreshnessPolicy,
} from './formal-freshness';

const policy = {
  schema_version: '1.0.0',
  cutoff_policy: 'latest_completed_trading_session',
  markets: { cn: '2026-08-03', us: '2026-07-31' },
  next_session_close_utc: {
    cn: '2026-08-04T07:00:00Z',
    us: '2026-08-03T20:00:00Z',
  },
  research_only: true,
  trade_ready: false,
} as const;

describe('formal freshness', () => {
  it('classifies the policy as current before the next declared close', () => {
    const snapshot = classifyFormalFreshness(
      parseFormalFreshnessPolicy(policy),
      new Date('2026-08-03T19:00:00Z'),
    );
    expect(snapshot.status).toBe('current');
    expect(snapshot.staleMarkets).toEqual([]);
  });

  it('classifies each passed market close as stale', () => {
    const snapshot = classifyFormalFreshness(
      parseFormalFreshnessPolicy(policy),
      new Date('2026-08-06T00:00:00Z'),
    );
    expect(snapshot.status).toBe('stale');
    expect(snapshot.staleMarkets).toEqual(['cn', 'us']);
  });

  it('blocks malformed policy data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...policy, research_only: false }),
    }));
    const snapshot = await fetchFormalFreshness(new Date('2026-08-06T00:00:00Z'));
    expect(snapshot.status).toBe('blocked');
    vi.unstubAllGlobals();
  });

  it('reports missing policy data as unknown', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    const snapshot = await fetchFormalFreshness(new Date('2026-08-06T00:00:00Z'));
    expect(snapshot.status).toBe('unknown');
    vi.unstubAllGlobals();
  });
});
