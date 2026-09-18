import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ModelOperationsPage } from './ModelOperationsPage';
import * as modelOps from '@/lib/model-operations';

describe('ModelOperationsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders loading state initially', () => {
    vi.spyOn(modelOps, 'fetchModelOperations').mockReturnValue(new Promise(() => {}));
    render(<ModelOperationsPage />);
    expect(screen.getByText(/Loading Model Operations read model/i)).toBeInTheDocument();
  });

  it('renders champion and gate status when data loaded', async () => {
    vi.spyOn(modelOps, 'fetchModelOperations').mockResolvedValue({
      schema_version: 'model_operations_v1',
      generated_at: '2026-09-17T00:00:00Z',
      research_only: true,
      trade_ready: false,
      digest: 'digest1',
      markets: [
        {
          market: 'us',
          champion: {
            model_version_id: 'qqqi_qqq_tqqq_v4_3',
            artifact_id: 'art_qqq',
            declared_at: '2026-09-09T00:00:00Z',
            declared_by: 'formal_catalog',
            snapshot_id: 'snap_us',
            metrics: {
              excess_return_with_cost: 0.185,
              annualized_return: 0.248,
              max_drawdown: -0.124,
              information_ratio: 1.45,
            },
            previous_champion_id: null,
            promotion_reason: 'Accepted formal baseline',
          },
          challenger: null,
          drift: {
            model_version_id: 'qqqi_qqq_tqqq_v4_3',
            overall_severity: 'ok',
            checked_at: '2026-09-17T00:00:00Z',
            checks: [
              {
                check_name: 'population_stability_index',
                measured_value: 0.042,
                baseline: 0.0,
                threshold: 0.25,
                severity: 'ok',
                evidence_window: 'latest_30_sessions',
                recommended_action: 'none',
              },
            ],
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
            gates: [
              {
                name: 'data_freshness',
                status: 'pass',
                detail: 'age=1.0d',
              },
            ],
            hard_blocks: [],
            recovery_conditions: [],
            challenger_created: false,
            champion_unchanged: true,
          },
          execution_plan: {
            plan_id: 'plan_1',
            asof_date: '2026-09-17',
            market: 'us',
            model_version_id: 'qqqi_qqq_tqqq_v4_3',
            target_weights: { AAPL: 0.35 },
            cash_weight: 0.05,
            gross_exposure: 0.95,
            net_exposure: 0.95,
            traded_notional_fraction: 0.95,
            one_sided_turnover: 0.475,
            expected_transaction_cost: 0.0019,
            decisions: [
              {
                instrument: 'AAPL',
                score: 0.95,
                sector: 'Technology',
                status: 'selected',
                weight: 0.35,
                reason_code: 'selected',
                detail: 'rank 1',
              },
            ],
            constraint_snapshot: {},
            reconciliation: {},
            warnings: [],
            advisory_only: true,
          },
          paper_ledger: {
            initial_cash: 1000000,
            cash_balance: 850000,
            current_nav: 1002000,
            unrealized_pnl: 2000,
            total_events: 4,
            hash_chain_verified: true,
            latest_digest: 'digest_hash',
            positions: { AAPL: 100 },
            recent_fills: [],
          },
          attribution: {
            total_return_arithmetic: 0.005,
            compounded_return: 0.005,
            benchmark_return_sum: 0.001,
            contributions: {
              stock_selection: 0.003,
              market_exposure: 0.002,
            },
            residual: 0,
            reconciliation: {
              within_tolerance: true,
              abs_residual: 0,
              components_sum_matches_total: true,
            },
          },
        },
      ],
    });

    render(<ModelOperationsPage />);

    await waitFor(() => {
      expect(screen.getByText('qqqi_qqq_tqqq_v4_3')).toBeInTheDocument();
    });

    expect(screen.getByText(/Approved Champion/i)).toBeInTheDocument();
    expect(screen.getByText(/Decision: continue/i)).toBeInTheDocument();
    expect(screen.getByText(/SHA-256 Chain Verified/i)).toBeInTheDocument();
  });
});
