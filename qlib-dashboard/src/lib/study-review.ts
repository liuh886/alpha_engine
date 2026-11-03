export type ReviewLifecycleState =
  | 'formulated'
  | 'observing'
  | 'supported'
  | 'challenged'
  | 'refuted'
  | 'graduated';

export interface HypothesisSpec {
  statement: string;
  economic_rationale: string;
  expected_edge: string;
  falsification_criteria: string[];
}

export interface FrozenConditions {
  frozen_at_cutoff: string;
  market: string;
  pool_id: string;
  runner_id: string;
  benchmarks: string[];
  cost_bps: number;
  rebalance_cadence: string;
  contract_sha256?: string;
}

export interface ObservationMetrics {
  as_of_session: string;
  sample_kind: string;
  cumulative_return: number;
  annualized_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  persistence_score: number;
  vs_benchmark_returns: Record<string, number>;
  rebalances_count: number;
  cash_drag_ratio: number;
}

export interface CounterEvidenceItem {
  evidence_id: string;
  session: string;
  category: string;
  severity: 'info' | 'warning' | 'falsifying';
  observation: string;
  metrics_impact: Record<string, unknown>;
}

export interface ReviewConclusion {
  verdict: string;
  verdict_session: string;
  summary: string;
  supported_points: string[];
  unresolved_risks: string[];
  recommendation: string;
}

export interface ScheduledReview {
  next_review_session: string;
  cadence: string;
  review_triggers: string[];
}

export interface StudyReview {
  schema_version: string;
  review_id: string;
  title: string;
  lifecycle_state: ReviewLifecycleState;
  created_at: string;
  updated_at: string;
  hypothesis: HypothesisSpec;
  frozen_conditions: FrozenConditions;
  observations: Record<string, ObservationMetrics>;
  counter_evidence: CounterEvidenceItem[];
  conclusion: ReviewConclusion;
  scheduled_review: ScheduledReview;
  lineage_fingerprint: string;
  research_only: boolean;
  trade_ready: boolean;
}

export interface StudyReviewFeed {
  schema_version: string;
  research_only: boolean;
  trade_ready: boolean;
  reviews: StudyReview[];
}

function isObject(val: unknown): val is Record<string, unknown> {
  return val !== null && typeof val === 'object' && !Array.isArray(val);
}

export function parseStudyReviewFeed(raw: unknown): StudyReviewFeed {
  if (!isObject(raw)) {
    throw new Error('Study review feed root must be an object.');
  }
  if (raw.research_only !== true || raw.trade_ready !== false) {
    throw new Error('Study review feed must have research_only=true and trade_ready=false.');
  }
  if (!Array.isArray(raw.reviews)) {
    throw new Error('Study review feed must contain an array of reviews.');
  }

  const reviews: StudyReview[] = [];
  for (const item of raw.reviews) {
    if (!isObject(item)) continue;
    if (typeof item.review_id !== 'string' || !item.review_id) continue;
    reviews.push(item as unknown as StudyReview);
  }

  return {
    schema_version: String(raw.schema_version ?? '1.0.0'),
    research_only: true,
    trade_ready: false,
    reviews,
  };
}

export async function fetchStudyReviews(signal?: AbortSignal): Promise<StudyReviewFeed> {
  const url = `${import.meta.env.BASE_URL}data/strategy-operations/study-reviews.json`;
  const response = await fetch(url, { cache: 'no-store', signal });
  if (!response.ok) {
    throw new Error(`Failed to load study reviews: HTTP ${response.status}`);
  }
  const json = await response.json();
  return parseStudyReviewFeed(json);
}
