import { describe, expect, it } from 'vitest';
import { parseStudyReviewFeed, type StudyReviewFeed } from './study-review';

describe('study-review parsing and validation', () => {
  it('parses valid study review feed with research_only and trade_ready flags', () => {
    const raw: StudyReviewFeed = {
      schema_version: '1.0.0',
      research_only: true,
      trade_ready: false,
      reviews: [
        {
          schema_version: '1.0',
          review_id: 'rev_001',
          title: 'Low Volatility Defense',
          lifecycle_state: 'observing',
          created_at: '2026-11-03T00:00:00Z',
          updated_at: '2026-11-03T00:00:00Z',
          hypothesis: {
            statement: 'Low vol protects in drawdowns.',
            economic_rationale: 'Variance drag reduction.',
            expected_edge: 'Lower drawdown.',
            falsification_criteria: ['MaxDD > benchmark'],
          },
          frozen_conditions: {
            frozen_at_cutoff: '2024-01-01',
            market: 'us',
            pool_id: 'us_selected_equities_v2',
            runner_id: 'us87_low_vol_challenger_v1',
            benchmarks: ['us87_ew_pool_runner_v1', 'QQQ'],
            cost_bps: 8,
            rebalance_cadence: 'monthly_first_session',
          },
          observations: {
            full_sample: {
              as_of_session: '2026-11-02',
              sample_kind: 'full_sample',
              cumulative_return: 0.05,
              annualized_return: 0.03,
              sharpe_ratio: 0.6,
              max_drawdown: -0.12,
              persistence_score: 0.4,
              vs_benchmark_returns: { QQQ: -0.05 },
              rebalances_count: 35,
              cash_drag_ratio: 0.05,
            },
          },
          counter_evidence: [
            {
              evidence_id: 'CE-001',
              session: '2025-01-02',
              category: 'beta_drag',
              severity: 'info',
              observation: 'Lagged pool during rally',
              metrics_impact: {},
            },
          ],
          conclusion: {
            verdict: 'Supported',
            verdict_session: '2026-11-02',
            summary: 'Thesis holds',
            supported_points: ['Low MaxDD'],
            unresolved_risks: ['Beta lag'],
            recommendation: 'continue_observing',
          },
          scheduled_review: {
            next_review_session: '2026-12-01',
            cadence: 'monthly',
            review_triggers: ['MaxDD < -0.25'],
          },
          lineage_fingerprint: 'abc1234',
          research_only: true,
          trade_ready: false,
        },
      ],
    };

    const parsed = parseStudyReviewFeed(raw);
    expect(parsed.reviews).toHaveLength(1);
    expect(parsed.reviews[0].review_id).toBe('rev_001');
    expect(parsed.reviews[0].lifecycle_state).toBe('observing');
    expect(parsed.research_only).toBe(true);
    expect(parsed.trade_ready).toBe(false);
  });

  it('rejects feed violating trade_ready or research_only', () => {
    expect(() => parseStudyReviewFeed({ research_only: false, trade_ready: false, reviews: [] })).toThrow();
    expect(() => parseStudyReviewFeed({ research_only: true, trade_ready: true, reviews: [] })).toThrow();
    expect(() => parseStudyReviewFeed(null)).toThrow();
  });
});
