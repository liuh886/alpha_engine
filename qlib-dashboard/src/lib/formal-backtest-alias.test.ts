import { describe, expect, it } from 'vitest';

import { attachFormalBacktests, type FormalBacktestPackage } from './formal-backtest';

function packageFixture(): FormalBacktestPackage {
  return {
    schema_version: '1.0.0',
    record_type: 'formal_model_backtest',
    backtest_id: 'byd-formal-test',
    model_id: 'byd_dividend_sleeve_v1_0',
    display_name: 'BYD Dividend Sleeve V1.0',
    market: 'cn',
    benchmark: 'BYD V1.0 cash sleeve',
    publication_status: 'accepted_formal_baseline',
    generated_at: '2026-08-05T00:00:00Z',
    evidence_cutoff: '2026-08-03',
    trace_frequency: 'daily_open_to_open',
    date_range: { start: '2026-08-01', end: '2026-08-03' },
    metrics: { CAGR: 0.35 },
    portfolio_contract: {},
    report: [{ date: '2026-08-01', account: 1 }],
    positions: [],
    trades: [],
    attribution: [],
    window_summary: [],
    evidence: {},
    evidence_completeness: { status: 'complete', missing: [] },
    interpretation_notes: [],
    research_only: true,
    trade_ready: false,
  };
}

describe('formal BYD public identity', () => {
  it('keeps the immutable technical ID while exposing BYD v1.1 everywhere', () => {
    const [model] = attachFormalBacktests([], [packageFixture()]);

    expect(model.id).toBe('byd_dividend_sleeve_v1_0');
    expect(model.name).toBe('BYD v1.1');
    expect(model.tag).toBe('BYD v1.1');
    expect(model.backtest.formalBacktest?.display_name).toBe('BYD v1.1');
  });
});
