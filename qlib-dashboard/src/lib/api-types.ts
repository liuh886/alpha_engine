/**
 * Typed API response contracts — maps backend router responses to TypeScript
 * interfaces. Keep these in sync with src/api/routers/*.py.
 *
 * Convention: every endpoint returns `{ ok: boolean, ... }`. Success payloads
 * extend `Ok` or `OkWithData<T>`. Error payloads are normalised to `ApiError`.
 */

// ---------------------------------------------------------------------------
// Error contract
// ---------------------------------------------------------------------------

/** Normalised error returned by `apiClient.request()` on non-2xx responses. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// ---------------------------------------------------------------------------
// Generic wrappers
// ---------------------------------------------------------------------------

/** Base shape of every successful API response. */
export interface Ok {
  ok: true;
}

/** Wrapper that adds a typed `data` field. */
export interface OkWithData<T> extends Ok {
  data: T;
}

// ---------------------------------------------------------------------------
// Health / System
// ---------------------------------------------------------------------------

export interface HealthResponse extends Ok {
  status: string;
  version?: string;
  uptime?: number;
}

export interface SystemPathsResponse extends Ok {
  paths: {
    project_root: string;
    dashboard_db_path: string;
    metadata_db_path: string;
    data_dir: string;
    artifacts_dir: string;
    reports_dir: string;
    mlruns_dir: string;
    models_dir: string;
    runs_dir: string;
  };
}

export interface SystemDocResponse extends Ok {
  path: string;
  content: string;
  updated_at: number;
}

export interface ThoughtStreamResponse extends Ok {
  stream: Array<Record<string, unknown>>;
}

export interface PanicResponse extends Ok {
  halted_jobs: number;
  total_marked_failed: number;
  reason: string;
  triggered_at: number;
}

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

export interface DataStatus {
  latest_calendar_date?: string;
  latest_calendar_day?: string;
  dashboard_generated_at?: string;
  latest_snapshot_id?: string;
  quality_status?: string;
  quality_warnings?: string[];
  /** Number of symbols configured in the watchlist. */
  symbols_configured?: number;
  /** Number of symbols successfully updated in the latest data update. */
  symbols_updated?: number;
  /** Number of symbols that failed to update. */
  symbols_failed?: number;
  /** Number of symbols with stale data (no recent update). */
  symbols_stale?: number;
  [key: string]: unknown;
}

export interface DataStatusResponse extends Ok {
  data: DataStatus;
}

export interface InstrumentsResponse extends Ok {
  market: string;
  instruments: string[];
}

export interface WatchlistResponse extends Ok {
  watchlist: Record<string, Array<{ symbol: string; name: string }>>;
}

export interface NameMapResponse extends Ok {
  name_map: Record<string, string>;
}

export interface FeaturesResponse extends Ok {
  features: string[];
}

export interface CompletenessResponse extends Ok {
  data: Record<string, unknown>;
}

export interface SnapshotResponse extends Ok {
  snapshot: Record<string, unknown>;
}

export interface QualityResponse extends Ok {
  quality: Record<string, unknown>;
}

export interface IntegrityResponse extends Ok {
  [key: string]: unknown;
}

export interface AddSymbolsResponse extends Ok {
  added: string[];
  total: number;
  message?: string;
}

export interface RemoveSymbolsResponse extends Ok {
  removed: string[];
  total: number;
  message?: string;
}

export interface StockDataResponse {
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Models
// ---------------------------------------------------------------------------

export interface ModelVersion {
  id: string;
  tag?: string;
  name?: string;
  market?: string;
  model_type?: string;
  path?: string;
  run_id?: string;
  snapshot_id?: string;
  evidence_id?: string;
  stage?: string;
  created_at?: string;
  description?: string;
  metrics?: Record<string, number>;
  metrics_json?: string;
  params?: Record<string, unknown>;
  params_json?: string;
}

export interface ModelListResponse extends Ok {
  versions: ModelVersion[];
}

export interface ModelDetailResponse extends Ok {
  [key: string]: unknown;
}

export interface ModelHealthCheck extends Ok {
  checks: Record<string, Record<string, unknown>>;
  warnings: string[];
  status: 'healthy' | 'degraded' | 'unhealthy';
}

export interface ModelPromoteResponse {
  ok: boolean;
  gate_failures?: string[];
}

export interface ModelDeleteResponse {
  ok: boolean;
}

// ---------------------------------------------------------------------------
// Backtest
// ---------------------------------------------------------------------------

export interface BacktestRun {
  id: string;
  tag: string;
  market: string;
  date: string;
  annual_return: number;
  sharpe: number;
  max_drawdown: number;
  strategy_name: string;
}

export interface BacktestListResponse extends Ok {
  runs: BacktestRun[];
}

export interface CurvePoint {
  date: string;
  nav?: number;
  drawdown?: number;
  [key: string]: unknown;
}

export interface BacktestCurveResponse extends Ok {
  curve: CurvePoint[];
  run_id: string;
  message?: string;
}

export interface BacktestCompareResponse extends Ok {
  comparisons: Record<string, {
    tag: string;
    market: string;
    curve: CurvePoint[];
  }>;
}

export interface BacktestAttributionResponse extends Ok {
  run_id: string;
  attribution: Record<string, unknown>;
}

export interface BacktestLedgerResponse extends Ok {
  run_id: string;
  holdings?: unknown[];
  trades?: unknown[];
  [key: string]: unknown;
}

export interface AlphaDecompositionResponse extends Ok {
  run_id: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export interface Job {
  id: string;
  type: string;
  status: string;
  cmd?: string;
  commands?: string[];
  name?: string;
  log_path?: string;
  created_at?: number;
  started_at?: number;
  finished_at?: number;
  exit_code?: number;
  error?: string;
  [key: string]: unknown;
}

export interface JobListResponse extends Ok {
  jobs: Job[];
}

export interface JobDetailResponse extends Ok {
  job: Job;
}

export interface JobSubmitResponse extends Ok {
  job_id: string;
  message?: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export interface Report {
  id: string;
  type: string;
  ref_id: string;
  date?: string;
  paths?: Record<string, string>;
  [key: string]: unknown;
}

export interface ReportListResponse extends Ok {
  reports: Report[];
}

export interface ReportDetailResponse extends Ok {
  report: Report;
}

// ---------------------------------------------------------------------------
// Arena
// ---------------------------------------------------------------------------

export interface Arena {
  id: string;
  name: string;
  market: string;
}

export interface ArenaListResponse extends Ok {
  arenas: Arena[];
}

export interface LeaderboardRow {
  rank?: number;
  participant_name?: string;
  nav?: number;
  daily_return?: number;
  drawdown?: number;
  turnover?: number;
  run_id?: string;
  model_version_id?: string;
  edge_explanation?: string;
  ic?: number;
  ic_ir?: number;
  consistency?: number;
  risk_status?: 'normal' | 'warning' | 'downgrade';
  factor_exposure?: string;
  walk_forward_stable?: boolean;
}

export interface ArenaLeaderboardResponse extends Ok {
  leaderboard: LeaderboardRow[];
  date: string;
}

// ---------------------------------------------------------------------------
// Factors
// ---------------------------------------------------------------------------

export interface FactorRecord {
  id: number;
  name: string;
  expression: string;
  category: string;
  stage: string;
  direction?: string;
  created_at?: string;
  updated_at?: string;
  latest_validation?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface FactorRegistryStats {
  total?: number;
  by_stage?: Record<string, number>;
  by_category?: Record<string, number>;
  [key: string]: unknown;
}

export interface FactorICReport extends Ok {
  report: Record<string, unknown>;
  cached: boolean;
}

export interface FactorTopResponse extends Ok {
  market: string;
  n: number;
  top_factors: Array<Record<string, unknown>>;
  cached: boolean;
}

export interface FactorDecayPoint {
  lag: number;
  ic: number;
  [key: string]: unknown;
}

export interface FactorDecayResponse extends Ok {
  factor: string;
  market: string;
  decay: FactorDecayPoint[];
}

export interface FactorRegistryListResponse extends Ok {
  factors: FactorRecord[];
  stats: FactorRegistryStats;
}

export interface FactorRegistryDetailResponse extends Ok {
  factor: FactorRecord;
  validations: Array<Record<string, unknown>>;
  usage: Array<Record<string, unknown>>;
}

export interface FactorScanReport extends Ok {
  report: Record<string, unknown>;
}

export interface FactorAttributionSummary {
  total_return: number;
  excess_return: number;
  factor_coverage: number;
  unexplained_return: number;
}

export interface FactorAttributionEntry {
  factor_id: number;
  factor_name: string;
  factor_expression: string;
  ic: number;
  return_contribution: number;
  risk_contribution: number;
  exposure: number;
  status: string;
}

export interface FactorAttributionResponse extends Ok {
  summary: FactorAttributionSummary;
  factors: FactorAttributionEntry[];
}

export interface RollingAttributionResponse extends Ok {
  result: Record<string, unknown>;
}

export interface FactorExistsResponse extends Ok {
  exists: boolean;
  factor_id?: number;
  name?: string;
  stage?: string;
  category?: string;
  message?: string;
}

// ---------------------------------------------------------------------------
// Decay Monitor
// ---------------------------------------------------------------------------

export interface DecayReport extends Ok {
  [key: string]: unknown;
}

export interface DecayFactorReport extends Ok {
  report: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Portfolio Constraints
// ---------------------------------------------------------------------------

export interface PortfolioCheckResponse extends Ok {
  market: string;
  n_positions: number;
  data_status: Record<string, string>;
  data_warnings: string[];
  violations?: unknown[];
  [key: string]: unknown;
}

export interface PortfolioConfigResponse extends Ok {
  config: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Stock Analysis
// ---------------------------------------------------------------------------

export interface StockDecision {
  symbol: string;
  signal: 'BUY' | 'HOLD' | 'SELL';
  confidence: number;
  score: number;
  rank: number;
  risk_flags: string[];
  reasoning?: string;
  price_targets?: Record<string, number>;
  recommended_strategy?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DataFreshness {
  pred_age_days?: number;
  is_stale?: boolean;
  pred_path?: string;
}

export interface StockDecisionResponse extends Ok {
  decision: StockDecision;
  data_freshness?: DataFreshness;
}

export interface StockFactor {
  name: string;
  expression: string;
  category: string;
  value: number | null;
  z_score: number | null;
  percentile: number | null;
}

export interface StockFactorsResponse extends Ok {
  symbol: string;
  market: string;
  factors: StockFactor[];
  message?: string;
}

export interface WatchlistSignalItem {
  symbol: string;
  signal: string;
  confidence: number;
  score: number | null;
  rank: number;
  risk_flags: string[];
  price?: number;
  change_pct?: number;
  change_5d_pct?: number;
  recommended_strategy?: string;
}

export interface WatchlistSummaryResponse extends Ok {
  market: string;
  date: string;
  total: number;
  summary: WatchlistSignalItem[];
  data_freshness?: DataFreshness;
}

export interface SignalHistoryEntry {
  signal: string;
  confidence: number;
  score: number | null;
  rank: number;
  recorded_at: string;
  price_targets?: Record<string, number>;
  recommended_strategy?: Record<string, unknown>;
}

export interface SignalHistoryResponse extends Ok {
  symbol: string;
  market: string;
  days: number;
  count: number;
  history: SignalHistoryEntry[];
}

export interface SignalGrade {
  grade: string;
  percentile: number;
  [key: string]: unknown;
}

export interface SignalGradeResponse extends Ok {
  symbol: string;
  market: string;
  step_size: number;
  grade: SignalGrade;
  history?: SignalGrade[];
}

export interface SignalMarker {
  time: string;
  position: string;
  color: string;
  shape: string;
  text: string;
  size: number;
}

export interface SignalMarkersResponse extends Ok {
  symbol: string;
  market: string;
  step_size: number;
  total_markers: number;
  markers: SignalMarker[];
}

export interface DailySignalPoint {
  date: string;
  percentile: number;
  grade: string;
  [key: string]: unknown;
}

export interface DailySignalSeriesResponse extends Ok {
  symbol: string;
  market: string;
  step_size: number;
  total_points: number;
  series: DailySignalPoint[];
}

export interface GradePerformance {
  occurrences: number;
  win_rate: number;
  mean_return: number;
  cumulative_return: number;
}

export interface StockRankingEntry {
  symbol: string;
  weighted_score: number;
  total_signals: number;
  grade_details: Record<string, GradePerformance>;
  [key: string]: unknown;
}

export interface StockRankingResponse extends Ok {
  market: string;
  step_size: number;
  forward_days: number;
  sort_by: string;
  sort_grade: string;
  total_stocks: number;
  ranking: StockRankingEntry[];
}

export interface DataFreshnessResponse extends Ok {
  market: string;
  checked_at: string;
  sources: Record<string, {
    available: boolean;
    latest_date?: string;
    age_days?: number;
    error?: string;
  }>;
  warnings: string[];
  status?: 'fresh' | 'stale' | 'outdated';
}

export interface PortfolioAnalysisResponse extends Ok {
  market: string;
  date: string;
  total: number;
  stats: Record<string, number>;
  decisions: StockDecision[];
  data_freshness?: DataFreshness;
}

// ---------------------------------------------------------------------------
// Strategy
// ---------------------------------------------------------------------------

export interface StrategyCompileResponse extends Ok {
  [key: string]: unknown;
}

export interface StrategyListResponse extends Ok {
  files: string[];
}

export interface StrategyContentResponse extends Ok {
  filename: string;
  content: string;
}

export interface StrategyPlugin {
  name: string;
  [key: string]: unknown;
}

export interface StrategyPluginsResponse extends Ok {
  plugins: StrategyPlugin[];
}

export interface NLCompileResponse extends Ok {
  profile: Record<string, unknown>;
  profile_path: string;
  yaml_path: string;
  market: string;
  summary: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Workflow
// ---------------------------------------------------------------------------

export interface WorkflowSubmitResponse extends Ok {
  workflow_id?: string;
  message: string;
}

export interface WorkflowStatusEntry {
  workflow_id: string;
  name: string;
  market: string;
  status: string;
  details?: Record<string, unknown> | null;
  error?: string;
  [key: string]: unknown;
}

export interface DashboardArtifactResponse {
  generated_at?: string;
  models?: unknown[];
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Research
// ---------------------------------------------------------------------------

export interface ResearchRunSubmitResponse extends Ok {
  run_id: string;
  message: string;
}

export interface ResearchRunSummary {
  run_id: string;
  market: string;
  goal: string;
  status: string;
  recommendation?: string;
  created_at: string;
  completed_at?: string;
  n_steps: number;
  n_completed: number;
  n_failed: number;
}

export interface ResearchRunsListResponse extends Ok {
  runs: ResearchRunSummary[];
  total: number;
}

export interface ResearchRunDetailResponse extends Ok {
  run: Record<string, unknown>;
}

export interface ResearchStepsResponse extends Ok {
  run_id: string;
  steps: Array<Record<string, unknown>>;
  summary: {
    total: number;
    completed: number;
    failed: number;
    pending: number;
  };
}

// ---------------------------------------------------------------------------
// Walk-Forward
// ---------------------------------------------------------------------------

export interface WalkForwardSubmitResponse extends Ok {
  job_id: string;
}

export interface WalkForwardResultResponse extends Ok {
  job_id: string;
  status: string;
  result?: Record<string, unknown>;
  source?: string;
}

// ---------------------------------------------------------------------------
// Agent Chat
// ---------------------------------------------------------------------------

export interface AgentChatResponse extends Ok {
  reply: string;
  result?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------

export interface EvidenceBundleResponse extends Ok {
  bundle: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

export interface ToolCapabilitiesResponse extends Ok {
  capabilities: unknown[];
}

export interface ToolChatResponse extends Ok {
  reply: string;
}
