import { describe, expect, it } from 'vitest';
import { parseSystemHealth } from './system-health';

const sample = {
  schema_version: '1.0.0',
  generated_at: '2026-08-13T09:30:00Z',
  state: 'delayed',
  markets: [{
    market: 'us',
    state: 'delayed',
    market_expected_cutoff: '2026-08-12',
    market_expected_cutoff_source: 'max_governed_active_watermark',
    provider_cutoff: '2026-08-10',
    provider_cutoff_source: 'provider_resolved_common_session',
    provider_lag_sessions: null,
    provider_lag_exact: false,
    provider_formal_consistency: 'current',
  }],
  strategies: [{
    strategy_id: 'us_x',
    model_version_id: 'us_x1_3',
    market: 'us',
    state: 'delayed',
    market_expected_cutoff: '2026-08-12',
    provider_cutoff: '2026-08-10',
    formal_cutoff: '2026-08-12',
    model_data_cutoff: '2026-08-12',
    factor_cutoff: '2026-08-12',
    last_signal_evaluation: null,
    last_signal_change: null,
    delivery_state: 'not_applicable',
    delivery_status: null,
    stages: {
      provider: 'delayed',
      formal: 'current',
      model_data: 'current',
      factor: 'current',
      signal: 'current',
      delivery: 'not_applicable',
    },
    formal_bundle_id: 'a'.repeat(64),
    formal_run_id: 'us_x1_3-through-2026_08_12',
  }],
  deployment: {
    state: 'not_applicable',
    expected_commit_sha: 'b'.repeat(40),
    workflow_run_id: '123',
    live_acceptance: 'verified_after_deployment',
    receipt: 'deployment.json',
  },
  model_data: {
    state: 'current',
    evidence_cutoff: '2026-08-12',
    bundle_id: 'c'.repeat(64),
  },
  research_only: true,
  trade_ready: false,
};

describe('system health contract', () => {
  it('keeps provider lag separate from formal consistency', () => {
    const parsed = parseSystemHealth(sample);
    expect(parsed.state).toBe('delayed');
    expect(parsed.markets[0].state).toBe('delayed');
    expect(parsed.markets[0].provider_formal_consistency).toBe('current');
    expect(parsed.strategies[0].stages.formal).toBe('current');
  });

  it('fails closed on unsupported stage states', () => {
    expect(() => parseSystemHealth({
      ...sample,
      strategies: [{ ...sample.strategies[0], stages: { ...sample.strategies[0].stages, signal: 'maybe' } }],
    })).toThrow(/Invalid system-health state/);
  });
});
