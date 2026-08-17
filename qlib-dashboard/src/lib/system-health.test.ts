import { describe, expect, it } from 'vitest';
import { parseSystemHealth } from './system-health';

const sample = {
  schema_version: '1.0.0',
  generated_at: '2026-08-14T09:30:00Z',
  state: 'delayed',
  markets: [{
    market: 'us',
    state: 'delayed',
    market_expected_cutoff: '2026-08-14',
    market_expected_cutoff_source: 'max_governed_active_watermark',
    provider_cutoff: '2026-08-14',
    provider_cutoff_source: 'governed_benchmark_market_session',
    provider_lag_sessions: 0,
    provider_lag_exact: true,
    provider_formal_consistency: 'current',
  }],
  strategies: [{
    strategy_id: 'us_x',
    model_version_id: 'us_x1_3',
    market: 'us',
    state: 'delayed',
    market_expected_cutoff: '2026-08-14',
    provider_cutoff: '2026-08-14',
    formal_cutoff: '2026-08-12',
    model_data_cutoff: '2026-08-12',
    factor_cutoff: '2026-08-13',
    last_signal_evaluation: '2026-08-13',
    last_signal_change: '2026-08-13',
    delivery_state: 'current',
    delivery_status: 'sent',
    stages: {
      provider: 'current',
      formal: 'delayed',
      model_data: 'delayed',
      factor: 'current',
      signal: 'current',
      delivery: 'current',
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
  it('keeps data, formal, signal and delivery watermarks separate', () => {
    const parsed = parseSystemHealth(sample);
    const strategy = parsed.strategies[0];
    expect(parsed.markets[0].provider_cutoff_source).toBe('governed_benchmark_market_session');
    expect(strategy.provider_cutoff).toBe('2026-08-14');
    expect(strategy.formal_cutoff).toBe('2026-08-12');
    expect(strategy.last_signal_evaluation).toBe('2026-08-13');
    expect(strategy.delivery_state).toBe('current');
    expect(strategy.delivery_status).toBe('sent');
  });

  it('fails closed on unsupported delivery states', () => {
    expect(() => parseSystemHealth({
      ...sample,
      strategies: [{ ...sample.strategies[0], delivery_state: 'maybe' }],
    })).toThrow(/Invalid system-health state/);
  });
});
