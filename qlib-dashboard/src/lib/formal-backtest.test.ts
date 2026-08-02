import { describe, expect, it } from 'vitest';
import {
  attachFormalBacktests,
  parseFormalBacktestCatalog,
  parseFormalBacktestPackage,
  type FormalBacktestPackage,
} from './formal-backtest';

const formalPackage: FormalBacktestPackage = {
  schema_version: '1.0.0',
  record_type: 'formal_model_backtest',
  backtest_id: 'us_x1_1-formal-test',
  model_id: 'us_x1_1',
  display_name: 'US x1.1',
  market: 'us',
  benchmark: 'QQQ',
  publication_status: 'accepted_formal_baseline',
  generated_at: '2026-08-02T00:00:00Z',
  evidence_cutoff: '2025-12-31',
  trace_frequency: 'non_overlapping_10_session',
  date_range: { start: '2024-01-02', end: '2025-12-31' },
  metrics: { 'Total Return': 1.1 },
  portfolio_contract: { topk: 15 },
  report: [
    { date: '2024-01-02', account: 1, bench_qqq: 1 },
    { date: '2024-01-16', account: 1.1, bench_qqq: 1.05 },
  ],
  positions: [{ date: '2024-01-02', instrument: 'AAPL', weight: 1 / 15 }],
  trades: [{ date: '2024-01-02', instrument: 'AAPL', action: 'BUY', target_weight: 1 / 15 }],
  attribution: [{ instrument: 'AAPL', name: 'AAPL', value: 0.01 }],
  window_summary: [{ window: '2024H1', total_return: 0.1 }],
  evidence: { workflow_run_id: 1, artifact_id: 2, artifact_digest: 'sha256:test' },
  evidence_completeness: { status: 'complete', missing: [] },
  interpretation_notes: ['Formal baseline only.'],
  research_only: true,
  trade_ready: false,
};

const catalog = {
  schema_version: '1.0.0',
  published_at: '2026-08-02T00:00:00Z',
  publication_policy: 'formal_named_baselines_only',
  excluded_record_classes: ['exploratory_experiment'],
  records: [
    {
      model_id: 'us_x1_1',
      display_name: 'US x1.1',
      display_order: 1,
      path: 'us_x1_1.json',
      sha256: 'a'.repeat(64),
      publication_status: 'accepted_formal_baseline',
    },
  ],
  research_only: true,
  trade_ready: false,
};

describe('formal backtest publication contract', () => {
  it('accepts a named formal baseline and preserves complete ledgers', () => {
    const parsed = parseFormalBacktestPackage(formalPackage, 'us_x1_1');
    expect(parsed.report).toHaveLength(2);
    expect(parsed.positions).toHaveLength(1);
    expect(parsed.trades).toHaveLength(1);
    expect(parsed.evidence_completeness.status).toBe('complete');
  });

  it('rejects exploratory or weakened records', () => {
    expect(() => parseFormalBacktestPackage({ ...formalPackage, publication_status: 'exploratory_experiment' })).toThrow(/not publishable/);
    expect(() => parseFormalBacktestPackage({ ...formalPackage, research_only: false })).toThrow(/boundary/);
    expect(() => parseFormalBacktestPackage({ ...formalPackage, trade_ready: true })).toThrow(/boundary/);
  });

  it('validates the formal allow-list and rejects unsafe paths', () => {
    expect(parseFormalBacktestCatalog(catalog).records[0].model_id).toBe('us_x1_1');
    const unsafe = structuredClone(catalog);
    unsafe.records[0].path = '../experiment.json';
    expect(() => parseFormalBacktestCatalog(unsafe)).toThrow(/Unsafe/);
  });

  it('returns only catalog-provided formal models', () => {
    const models = attachFormalBacktests(
      [
        { id: 'us_x1_1', name: 'US x1.1' },
        { id: 'experiment_009', name: 'Exploratory experiment' },
      ],
      [formalPackage],
    );
    expect(models.map((model) => model.id)).toEqual(['us_x1_1']);
    expect(models[0].stage).toBe('FORMAL_BASELINE');
    expect(models[0].backtest.formalBacktest.record_type).toBe('formal_model_backtest');
  });
});
