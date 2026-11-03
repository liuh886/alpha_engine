import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { StudyReviewDesk } from './StudyReviewDesk';
import * as studyReviewLib from '@/lib/study-review';

const mockFeed: studyReviewLib.StudyReviewFeed = {
  schema_version: '1.0.0',
  research_only: true,
  trade_ready: false,
  reviews: [
    {
      schema_version: '1.0',
      review_id: 'rev_us87_low_vol_v1',
      title: 'US87 Low-Volatility Defense Hypothesis',
      lifecycle_state: 'observing',
      created_at: '2026-11-03T00:00:00Z',
      updated_at: '2026-11-03T00:00:00Z',
      hypothesis: {
        statement: 'Lowest volatility quintile dampens drawdown.',
        economic_rationale: 'Variance drag reduction.',
        expected_edge: 'Lower drawdown by at least 5%.',
        falsification_criteria: ['MaxDD > pool MaxDD'],
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
          cumulative_return: 0.033,
          annualized_return: 0.021,
          sharpe_ratio: 0.52,
          max_drawdown: -0.177,
          persistence_score: 0.314,
          vs_benchmark_returns: { us87_ew_pool_runner_v1: -0.204, QQQ: -0.052 },
          rebalances_count: 35,
          cash_drag_ratio: 0.05,
        },
      },
      counter_evidence: [
        {
          evidence_id: 'CE-001',
          session: '2024-11-01',
          category: 'beta_drag',
          severity: 'info',
          observation: 'Lagged US87 Equal-Weight Pool Index during rally.',
          metrics_impact: {},
        },
      ],
      conclusion: {
        verdict: 'Hypothesis supported in downside protection',
        verdict_session: '2026-11-02',
        summary: 'Max drawdown is -17.7% vs -28.0% pool.',
        supported_points: ['Downside protection verified'],
        unresolved_risks: ['Beta lag during rallies'],
        recommendation: 'continue_observing',
      },
      scheduled_review: {
        next_review_session: '2026-12-01',
        cadence: 'monthly',
        review_triggers: ['max_drawdown_below_-0.25'],
      },
      lineage_fingerprint: 'abc1234567890',
      research_only: true,
      trade_ready: false,
    },
  ],
};

describe('StudyReviewDesk Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders loading indicator initially then displays review cards', async () => {
    vi.spyOn(studyReviewLib, 'fetchStudyReviews').mockResolvedValue(mockFeed);

    render(<StudyReviewDesk />);
    expect(screen.getByRole('status')).toHaveTextContent(/Loading study reviews/i);

    await waitFor(() => {
      expect(screen.getByText('US87 Low-Volatility Defense Hypothesis')).toBeInTheDocument();
    });

    expect(screen.getByText('Observing')).toBeInTheDocument();
    expect(screen.getByText('us87_low_vol_challenger_v1')).toBeInTheDocument();
    expect(screen.getByText(/2026-12-01/)).toBeInTheDocument();
  });

  it('opens and closes review detail modal', async () => {
    vi.spyOn(studyReviewLib, 'fetchStudyReviews').mockResolvedValue(mockFeed);

    render(<StudyReviewDesk />);
    await waitFor(() => {
      expect(screen.getByText('US87 Low-Volatility Defense Hypothesis')).toBeInTheDocument();
    });

    // Click inspect full review button
    const inspectBtn = screen.getByRole('button', { name: /Inspect Full Review/i });
    fireEvent.click(inspectBtn);

    // Modal should be open
    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText(/1\. Hypothesis Formulation/i)).toBeInTheDocument();
    expect(screen.getByText(/2\. Frozen Conditions/i)).toBeInTheDocument();
    expect(screen.getByText(/3\. Performance Observations/i)).toBeInTheDocument();
    expect(screen.getByText(/4\. Counter-Evidence Collection/i)).toBeInTheDocument();
    expect(screen.getByText(/5\. Review Conclusion/i)).toBeInTheDocument();
    expect(screen.getByText(/6\. Scheduled Review & Watchpoints/i)).toBeInTheDocument();

    // Close modal
    const closeBtn = screen.getByRole('button', { name: /Close dialog/i });
    fireEvent.click(closeBtn);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('filters reviews by state', async () => {
    vi.spyOn(studyReviewLib, 'fetchStudyReviews').mockResolvedValue(mockFeed);

    render(<StudyReviewDesk />);
    await waitFor(() => {
      expect(screen.getByText('US87 Low-Volatility Defense Hypothesis')).toBeInTheDocument();
    });

    // Click 'refuted' filter
    const refutedFilter = screen.getByRole('button', { name: 'refuted' });
    fireEvent.click(refutedFilter);

    expect(screen.getByText(/No investment hypotheses currently in refuted state/i)).toBeInTheDocument();
  });

  it('renders alert when fetch fails', async () => {
    vi.spyOn(studyReviewLib, 'fetchStudyReviews').mockRejectedValue(new Error('Network failure'));

    render(<StudyReviewDesk />);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
    expect(screen.getByText(/Network failure/i)).toBeInTheDocument();
  });
});
