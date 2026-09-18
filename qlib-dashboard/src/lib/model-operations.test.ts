import { describe, expect, it } from 'vitest';
import { parseModelOperations } from './model-operations';

describe('model-operations parser', () => {
  const validSnapshot = {
    schema_version: 'model_operations_v1',
    generated_at: '2026-09-17T00:00:00Z',
    research_only: true,
    trade_ready: false,
    digest: 'sample_digest',
    markets: [
      {
        market: 'us',
        champion: {
          model_version_id: 'qqqi_qqq_tqqq_v4_3',
          artifact_id: 'art_qqq',
          declared_at: '2026-09-09T00:00:00Z',
          declared_by: 'formal_catalog',
          snapshot_id: 'snap_us',
          metrics: { excess_return_with_cost: 0.185 },
          previous_champion_id: null,
          promotion_reason: 'Formal baseline',
        },
        challenger: null,
        drift: {
          model_version_id: 'qqqi_qqq_tqqq_v4_3',
          overall_severity: 'ok',
          checked_at: '2026-09-17T00:00:00Z',
          checks: [],
        },
        gate_decision: {
          record_id: 'rec_1',
          policy_version: 'ops_v1',
          decided_at: '2026-09-17T00:00:00Z',
          market: 'us',
          model_version_id: 'qqqi_qqq_tqqq_v4_3',
          champion_id: 'art_qqq',
          decision: 'continue',
          plan_eligible: true,
          gates: [],
          hard_blocks: [],
          recovery_conditions: [],
          challenger_created: false,
          champion_unchanged: true,
        },
        execution_plan: null,
        paper_ledger: {
          initial_cash: 1000000,
          cash_balance: 1000000,
          current_nav: 1000000,
          unrealized_pnl: 0,
          total_events: 1,
          hash_chain_verified: true,
          latest_digest: 'dig',
          positions: {},
          recent_fills: [],
        },
        attribution: {
          total_return_arithmetic: 0.005,
          compounded_return: 0.005,
          benchmark_return_sum: 0.001,
          contributions: {},
          residual: 0,
          reconciliation: {
            within_tolerance: true,
            abs_residual: 0,
            components_sum_matches_total: true,
          },
        },
      },
    ],
  };

  it('parses valid payload correctly', () => {
    const result = parseModelOperations(validSnapshot);
    expect(result.schema_version).toBe('model_operations_v1');
    expect(result.research_only).toBe(true);
    expect(result.trade_ready).toBe(false);
    expect(result.markets).toHaveLength(1);
    expect(result.markets[0].market).toBe('us');
  });

  it('fails closed when trade_ready is true', () => {
    expect(() =>
      parseModelOperations({ ...validSnapshot, trade_ready: true }),
    ).toThrow('trade_ready must be false');
  });

  it('fails closed when schema_version is unsupported', () => {
    expect(() =>
      parseModelOperations({ ...validSnapshot, schema_version: 'v2' }),
    ).toThrow('Unsupported schema_version');
  });
});
