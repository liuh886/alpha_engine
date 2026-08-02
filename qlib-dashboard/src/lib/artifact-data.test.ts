import { describe, expect, it } from 'vitest';
import type { ModelData } from './data-parser';
import {
  extractSignalExecutionRows,
  formatBytes,
  groupArtifacts,
  numericMetric,
  parseDataReadinessEvidence,
} from './artifact-data';

describe('artifact evidence helpers', () => {
  it('groups manifest artifacts without losing required counts', () => {
    const groups = groupArtifacts([
      { artifact_id: 'a', kind: 'report', path: 'reports/a.md', media_type: 'text/markdown', byte_size: 100, sha256: '0'.repeat(64), required: false },
      { artifact_id: 'b', kind: 'report', path: 'reports/b.md', media_type: 'text/markdown', byte_size: 200, sha256: '1'.repeat(64), required: true },
      { artifact_id: 'c', kind: 'model_index', path: 'data/models.json', media_type: 'application/json', byte_size: 50, sha256: '2'.repeat(64), required: true },
    ]);
    expect(groups.find((group) => group.kind === 'report')).toEqual({ kind: 'report', count: 2, bytes: 300, required: 1 });
    expect(groups.find((group) => group.kind === 'model_index')?.required).toBe(1);
  });

  it('keeps signal and execution dates as distinct fields', () => {
    const model = {
      id: 'run-1',
      params: {
        signal_execution_ledger: [
          { symbol: 'QQQ', signal_date: '2026-07-30', execution_date: '2026-07-31', action: 'buy', weight: 1 },
        ],
      },
      metrics: { 'Sharpe Ratio': 1.23 },
      backtest: { metrics: {}, positions: [] },
    } as unknown as ModelData;
    const rows = extractSignalExecutionRows(model);
    expect(rows).toHaveLength(1);
    expect(rows[0].signalDate).toBe('2026-07-30');
    expect(rows[0].executionDate).toBe('2026-07-31');
    expect(rows[0].signalDate).not.toBe(rows[0].executionDate);
    expect(numericMetric(model, ['Sharpe Ratio'])).toBe(1.23);
  });

  it('parses the exact data readiness boundary used by training', () => {
    const evidence = parseDataReadinessEvidence(
      {
        schema_version: '1.0',
        bundle_id: 'bundle-1',
        built_at: '2026-08-02T00:00:00Z',
        evidence_cutoff: '2026-07-31',
        research_only: true,
        trade_ready: false,
        summary: {
          component_count: 2,
          ready_component_count: 1,
          partial_component_count: 1,
          blocked_component_count: 0,
          ready_training_profiles: ['price-only'],
          blocked_training_profiles: ['fundamental-model'],
        },
      },
      [
        {
          component_id: 'prices.us',
          component_kind: 'selected_pool_prices',
          status: 'ready',
          market: 'us',
          pool_id: 'us_selected_equities_v2',
          evidence_cutoff: '2026-06-18',
          first_date: '2021-01-04',
          last_date: '2026-06-18',
          expected_symbol_count: 87,
          ready_symbol_count: 87,
          coverage_ratio: 1,
          missing_symbols: [],
          invalid_symbols: [],
          quarantined_symbols: [],
          providers: ['tiingo'],
          professional_source_ready: true,
          research_only: true,
          trade_ready: false,
        },
        {
          component_id: 'fundamentals.us',
          component_kind: 'fundamental_coverage',
          status: 'partial',
          market: 'us',
          pool_id: 'us_selected_equities_v2',
          evidence_cutoff: '2026-06-18',
          first_date: null,
          last_date: '2026-06-18',
          expected_symbol_count: 87,
          ready_symbol_count: 70,
          coverage_ratio: 70 / 87,
          missing_symbols: ['XYZ'],
          invalid_symbols: [],
          quarantined_symbols: [],
          providers: ['sec'],
          professional_source_ready: null,
          research_only: true,
          trade_ready: false,
        },
      ],
      [
        {
          profile_id: 'price-only',
          market: 'us',
          candidate_pool_id: 'us_selected_equities_v2',
          candidate_count: 87,
          references: ['QQQ'],
          status: 'ready',
          failed_gates: [],
          research_only: true,
          trade_ready: false,
        },
        {
          profile_id: 'fundamental-model',
          market: 'us',
          candidate_pool_id: 'us_selected_equities_v2',
          candidate_count: 87,
          references: ['QQQ'],
          status: 'blocked',
          failed_gates: ['coverage below minimum'],
          research_only: true,
          trade_ready: false,
        },
      ],
    );

    expect(evidence.readiness.summary.ready_training_profiles).toEqual(['price-only']);
    expect(evidence.components[0].coverage_ratio).toBe(1);
    expect(evidence.components[1].missing_symbols).toEqual(['XYZ']);
    expect(evidence.profiles[1].failed_gates).toEqual(['coverage below minimum']);
  });

  it('rejects unsupported data readiness states', () => {
    expect(() => parseDataReadinessEvidence(
      {
        schema_version: '1.0',
        bundle_id: 'bundle-1',
        built_at: '2026-08-02T00:00:00Z',
        evidence_cutoff: '2026-07-31',
        research_only: true,
        trade_ready: false,
        summary: {},
      },
      [{
        component_id: 'bad', component_kind: 'prices', status: 'unknown', market: 'us', pool_id: '',
        expected_symbol_count: 0, ready_symbol_count: 0, coverage_ratio: 0, research_only: true, trade_ready: false,
      }],
      [],
    )).toThrow('Unsupported data component status');
  });

  it('formats artifact byte sizes', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(2 * 1024 * 1024)).toBe('2.0 MB');
  });
});
