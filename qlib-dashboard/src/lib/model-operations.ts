/**
 * Model Operations immutable read model types and reader (T47.8).
 *
 * Strict read-only consumption of data/model-operations/operations_summary.json.
 * Follows fail-closed governance: invalid schemas or trade-ready flags trigger errors.
 */

export interface ChampionInfo {
  model_version_id: string;
  artifact_id: string;
  declared_at: string;
  declared_by: string;
  snapshot_id: string;
  metrics: {
    excess_return_with_cost?: number;
    annualized_return?: number;
    max_drawdown?: number;
    information_ratio?: number;
    [key: string]: number | undefined;
  };
  previous_champion_id: string | null;
  promotion_reason: string;
}

export interface ChallengerInfo {
  challenger_id: string;
  status: string;
  evaluation_window: string;
  metrics: {
    excess_return_with_cost?: number;
    annualized_return?: number;
    max_drawdown?: number;
    [key: string]: number | undefined;
  };
  challenge_passed: boolean;
  comparison_summary: string;
}

export interface DriftCheckItem {
  check_name: string;
  measured_value: number;
  baseline: number;
  threshold: number;
  severity: 'ok' | 'watch' | 'warning' | 'critical';
  evidence_window: string;
  recommended_action: string;
}

export interface DriftReport {
  model_version_id: string;
  overall_severity: 'ok' | 'watch' | 'warning' | 'critical';
  checked_at: string;
  checks: DriftCheckItem[];
}

export interface GateResultItem {
  name: string;
  status: 'pass' | 'fail' | 'inconclusive';
  detail: string;
}

export interface GateDecision {
  record_id: string;
  policy_version: string;
  decided_at: string;
  market: string;
  model_version_id: string;
  champion_id: string | null;
  decision: 'continue' | 'retrain' | 'demote' | 'stop' | 'rollback';
  plan_eligible: boolean;
  gates: GateResultItem[];
  hard_blocks: string[];
  recovery_conditions: string[];
  challenger_created: boolean;
  champion_unchanged: boolean;
}

export interface PlanDecisionItem {
  instrument: string;
  score: number;
  sector: string | null;
  status: string;
  weight: number | null;
  reason_code: string;
  detail: string;
}

export interface ExecutionPlanState {
  plan_id: string;
  asof_date: string;
  market: string;
  model_version_id: string;
  target_weights: Record<string, number>;
  cash_weight: number;
  gross_exposure: number;
  net_exposure: number;
  traded_notional_fraction: number;
  one_sided_turnover: number;
  expected_transaction_cost: number;
  decisions: PlanDecisionItem[];
  constraint_snapshot: Record<string, unknown>;
  reconciliation: Record<string, boolean>;
  warnings: string[];
  advisory_only: boolean;
}

export interface PaperFillItem {
  client_order_id: string;
  instrument: string;
  side: string;
  trade_date: string;
  exec_price: number;
  filled_quantity: number;
  fees: number;
  slippage_cost: number;
}

export interface PaperLedgerState {
  initial_cash: number;
  cash_balance: number;
  current_nav: number;
  unrealized_pnl: number;
  total_events: number;
  hash_chain_verified: boolean;
  latest_digest: string;
  positions: Record<string, number>;
  recent_fills: PaperFillItem[];
}

export interface AttributionState {
  total_return_arithmetic: number;
  compounded_return: number;
  benchmark_return_sum: number;
  contributions: {
    costs?: number;
    market_exposure?: number;
    sector_effect?: number;
    slippage?: number;
    stock_selection?: number;
    timing?: number;
    [key: string]: number | undefined;
  };
  residual: number;
  reconciliation: {
    within_tolerance: boolean;
    abs_residual: number;
    components_sum_matches_total: boolean;
  };
}

export interface MarketOperationsSnapshot {
  market: 'us' | 'cn';
  champion: ChampionInfo | null;
  challenger: ChallengerInfo | null;
  drift: DriftReport;
  gate_decision: GateDecision;
  execution_plan: ExecutionPlanState | null;
  paper_ledger: PaperLedgerState;
  attribution: AttributionState;
}

export interface ModelOperationsSnapshot {
  schema_version: 'model_operations_v1';
  generated_at: string;
  research_only: true;
  trade_ready: false;
  digest: string;
  markets: MarketOperationsSnapshot[];
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function parseModelOperations(value: unknown): ModelOperationsSnapshot {
  if (!isObject(value)) {
    throw new Error('Model operations payload must be an object.');
  }
  if (value.schema_version !== 'model_operations_v1') {
    throw new Error(`Unsupported schema_version: ${String(value.schema_version)}`);
  }
  if (value.research_only !== true) {
    throw new Error('research_only must be true');
  }
  if (value.trade_ready !== false) {
    throw new Error('trade_ready must be false');
  }
  if (!Array.isArray(value.markets)) {
    throw new Error('markets must be an array');
  }

  return value as unknown as ModelOperationsSnapshot;
}

function assetUrl(path: string): string {
  const base = import.meta.env.BASE_URL.endsWith('/') ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
  return `${base}${path}`;
}

export async function fetchModelOperations(): Promise<ModelOperationsSnapshot | null> {
  try {
    const response = await fetch(assetUrl('data/model-operations/operations_summary.json'), { cache: 'no-cache' });
    if (!response.ok) {
      return null;
    }
    const raw = await response.json() as unknown;
    return parseModelOperations(raw);
  } catch {
    return null;
  }
}
