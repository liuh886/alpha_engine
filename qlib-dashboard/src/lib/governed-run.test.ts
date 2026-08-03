import { describe, expect, it } from 'vitest';
import type { ModelData } from './data-parser';
import type { FormalBacktestPackage } from './formal-backtest';
import { adaptFormalRuns, governedRunQuery, selectRunFromQuery } from './governed-run';

function formalPackage(modelId: string): FormalBacktestPackage {
  return {
    schema_version: '1.0.0',
    record_type: 'formal_model_backtest',
    backtest_id: `${modelId}_run`,
    model_id: modelId,
    display_name: modelId === 'qqqi_qqq_tqqq_v4_2' ? 'QQQ Rotation v4.2' : 'US x1.1',
    market: 'us',
    benchmark: 'QQQ',
    publication_status: 'accepted_formal_baseline',
    generated_at: '2026-08-03T00:00:00Z',
    evidence_cutoff: '2026-07-31',
    trace_frequency: 'daily',
    date_range: { start: '2024-01-01', end: '2026-07-31' },
    metrics: { 'Total Return': 0.1 },
    portfolio_contract: {},
    report: [{ date: '2024-01-01', account: 1 }],
    positions: [],
    trades: [],
    attribution: [],
    window_summary: [],
    evidence: {},
    evidence_completeness: { status: 'partial', missing: ['trade_ledger'] },
    interpretation_notes: [],
    research_only: true,
    trade_ready: false,
  };
}

describe('governed formal run adapter', () => {
  it('preserves formal channel identity and model-kind semantics', () => {
    const model = { id: 'qqqi_qqq_tqqq_v4_2', name: 'QQQ Rotation v4.2' } as ModelData;
    const [run] = adaptFormalRuns([formalPackage(model.id)], [model]);
    expect(run.channel).toBe('formal');
    expect(run.publicationStatus).toBe('accepted_formal_baseline');
    expect(run.modelKind).toBe('rules_based_allocation');
    expect(run.evidenceStatus).toBe('partial');
    expect(run.modelData).toBe(model);
  });

  it('round-trips the channel, family, version and run deep link', () => {
    const model = { id: 'us_x1_1', name: 'US x1.1' } as ModelData;
    const [run] = adaptFormalRuns([formalPackage(model.id)], [model]);
    const query = governedRunQuery(run);
    expect(selectRunFromQuery([run], `?${query}`)?.key).toBe(run.key);
    expect(selectRunFromQuery([run], '?channel=preview&family=x&version=y&run=z')).toBeNull();
  });
});
