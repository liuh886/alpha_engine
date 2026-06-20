/**
 * Deterministic API response fixtures for frontend tests.
 *
 * Every fixture satisfies the `Ok { ok: true }` contract.
 * Import individual fixtures or the whole module as needed.
 */

import type {
  HealthResponse,
  ModelListResponse,
  ModelVersion,
  BacktestListResponse,
  BacktestRun,
  JobListResponse,
  Job,
  ArenaListResponse,
  Arena,
  ArenaLeaderboardResponse,
  LeaderboardRow,
  FactorRegistryListResponse,
  FactorRecord,
  FactorRegistryStats,
  WatchlistSummaryResponse,
  WatchlistSignalItem,
  StockDecisionResponse,
  StockDecision,
  ReportListResponse,
  Report,
  StrategyListResponse,
  StrategyPluginsResponse,
  ResearchRunsListResponse,
  ResearchRunSummary,
  DataFreshnessResponse,
} from '@/lib/api-types';

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export const healthResponse: HealthResponse = {
  ok: true,
  status: 'healthy',
  version: '1.2.3',
  uptime: 86400,
};

// ---------------------------------------------------------------------------
// Models
// ---------------------------------------------------------------------------

export const modelVersionFixtures: ModelVersion[] = [
  {
    id: 'mv-001',
    tag: 'lgbm-v1',
    name: 'LightGBM Baseline',
    market: 'cn',
    model_type: 'lightgbm',
    path: '/models/mv-001',
    run_id: 'run-abc',
    created_at: '2026-06-01T00:00:00Z',
    description: 'Baseline LGBM model for CN market',
    metrics: { ic: 0.05, sharpe: 1.2, max_drawdown: -0.15 },
    params: { n_estimators: 500, learning_rate: 0.05 },
  },
  {
    id: 'mv-002',
    tag: 'xgb-v2',
    name: 'XGBoost V2',
    market: 'us',
    model_type: 'xgboost',
    path: '/models/mv-002',
    run_id: 'run-def',
    created_at: '2026-06-10T00:00:00Z',
    description: 'XGBoost model for US market',
    metrics: { ic: 0.04, sharpe: 1.0, max_drawdown: -0.18 },
  },
];

export const modelListResponse: ModelListResponse = {
  ok: true,
  versions: modelVersionFixtures,
};

// ---------------------------------------------------------------------------
// Backtest
// ---------------------------------------------------------------------------

export const backtestRunFixtures: BacktestRun[] = [
  {
    id: 'bt-001',
    tag: 'lgbm-v1',
    market: 'cn',
    date: '2026-06-01',
    annual_return: 0.15,
    sharpe: 1.2,
    max_drawdown: -0.12,
    strategy_name: 'TopKDropout',
  },
  {
    id: 'bt-002',
    tag: 'xgb-v2',
    market: 'us',
    date: '2026-06-10',
    annual_return: 0.10,
    sharpe: 0.9,
    max_drawdown: -0.20,
    strategy_name: 'TopKDropout',
  },
];

export const backtestListResponse: BacktestListResponse = {
  ok: true,
  runs: backtestRunFixtures,
};

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export const jobFixtures: Job[] = [
  {
    id: 'job-001',
    type: 'train',
    status: 'completed',
    cmd: 'python train.py',
    name: 'LGBM Training',
    created_at: 1717200000,
    started_at: 1717200010,
    finished_at: 1717203610,
    exit_code: 0,
  },
  {
    id: 'job-002',
    type: 'backtest',
    status: 'running',
    cmd: 'python backtest.py',
    name: 'US Backtest',
    created_at: 1717204000,
    started_at: 1717204010,
  },
];

export const jobListResponse: JobListResponse = {
  ok: true,
  jobs: jobFixtures,
};

// ---------------------------------------------------------------------------
// Arena
// ---------------------------------------------------------------------------

export const arenaFixtures: Arena[] = [
  { id: 'arena-001', name: 'CN Weekly', market: 'cn' },
  { id: 'arena-002', name: 'US Weekly', market: 'us' },
];

export const arenaListResponse: ArenaListResponse = {
  ok: true,
  arenas: arenaFixtures,
};

export const leaderboardRowFixtures: LeaderboardRow[] = [
  {
    rank: 1,
    participant_name: 'lgbm-v1',
    nav: 1.15,
    daily_return: 0.002,
    drawdown: -0.05,
    turnover: 0.3,
    run_id: 'run-abc',
    ic: 0.05,
    ic_ir: 0.8,
    consistency: 0.75,
    risk_status: 'normal',
  },
  {
    rank: 2,
    participant_name: 'xgb-v2',
    nav: 1.08,
    daily_return: 0.001,
    drawdown: -0.08,
    turnover: 0.4,
    run_id: 'run-def',
    ic: 0.04,
    ic_ir: 0.6,
    consistency: 0.65,
    risk_status: 'normal',
  },
];

export const arenaLeaderboardResponse: ArenaLeaderboardResponse = {
  ok: true,
  leaderboard: leaderboardRowFixtures,
  date: '2026-06-15',
};

// ---------------------------------------------------------------------------
// Factors
// ---------------------------------------------------------------------------

export const factorRecordFixtures: FactorRecord[] = [
  {
    id: 1,
    name: 'momentum_20d',
    expression: 'Ref($close, -20) / $close - 1',
    category: 'momentum',
    stage: 'production',
    direction: 'positive',
    created_at: '2026-05-01T00:00:00Z',
    latest_validation: { ic: 0.05, rank_ic: 0.04 },
  },
  {
    id: 2,
    name: 'volatility_60d',
    expression: 'Std($close / Ref($close, -1) - 1, 60)',
    category: 'volatility',
    stage: 'research',
    direction: 'negative',
    created_at: '2026-05-15T00:00:00Z',
    latest_validation: null,
  },
];

export const factorRegistryStatsFixture: FactorRegistryStats = {
  total: 2,
  by_stage: { production: 1, research: 1 },
  by_category: { momentum: 1, volatility: 1 },
};

export const factorRegistryListResponse: FactorRegistryListResponse = {
  ok: true,
  factors: factorRecordFixtures,
  stats: factorRegistryStatsFixture,
};

// ---------------------------------------------------------------------------
// Stock Analysis
// ---------------------------------------------------------------------------

export const stockDecisionFixture: StockDecision = {
  symbol: '600519.SH',
  signal: 'BUY',
  confidence: 0.85,
  score: 78,
  rank: 3,
  risk_flags: [],
  reasoning: 'Strong momentum and value signals',
  price_targets: { low: 1800, mid: 1950, high: 2100 },
};

export const stockDecisionResponse: StockDecisionResponse = {
  ok: true,
  decision: stockDecisionFixture,
  data_freshness: { pred_age_days: 1, is_stale: false },
};

export const watchlistSignalItemFixtures: WatchlistSignalItem[] = [
  {
    symbol: '600519.SH',
    signal: 'BUY',
    confidence: 0.85,
    score: 78,
    rank: 1,
    risk_flags: [],
    price: 1950.0,
    change_pct: 0.012,
    change_5d_pct: 0.035,
  },
  {
    symbol: '000858.SZ',
    signal: 'HOLD',
    confidence: 0.55,
    score: 50,
    rank: 2,
    risk_flags: ['low_volume'],
    price: 150.0,
    change_pct: -0.005,
    change_5d_pct: -0.01,
  },
];

export const watchlistSummaryResponse: WatchlistSummaryResponse = {
  ok: true,
  market: 'cn',
  date: '2026-06-15',
  total: 2,
  summary: watchlistSignalItemFixtures,
};

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

export const reportFixtures: Report[] = [
  {
    id: 'rpt-001',
    type: 'backtest',
    ref_id: 'bt-001',
    date: '2026-06-01',
    paths: { html: '/reports/rpt-001.html' },
  },
  {
    id: 'rpt-002',
    type: 'model',
    ref_id: 'mv-001',
    date: '2026-06-05',
    paths: { html: '/reports/rpt-002.html' },
  },
];

export const reportListResponse: ReportListResponse = {
  ok: true,
  reports: reportFixtures,
};

// ---------------------------------------------------------------------------
// Strategy
// ---------------------------------------------------------------------------

export const strategyListResponse: StrategyListResponse = {
  ok: true,
  files: ['topk_dropout.py', 'equal_weight.py', 'momentum_strategy.py'],
};

export const strategyPluginsResponse: StrategyPluginsResponse = {
  ok: true,
  plugins: [
    { name: 'TopKDropout' },
    { name: 'EqualWeight' },
    { name: 'MomentumStrategy' },
  ],
};

// ---------------------------------------------------------------------------
// Research
// ---------------------------------------------------------------------------

export const researchRunSummaryFixtures: ResearchRunSummary[] = [
  {
    run_id: 'rr-001',
    market: 'cn',
    goal: 'Find alpha factors for CN market',
    status: 'completed',
    recommendation: 'momentum_20d shows consistent IC',
    created_at: '2026-06-10T00:00:00Z',
    completed_at: '2026-06-10T01:00:00Z',
    n_steps: 5,
    n_completed: 5,
    n_failed: 0,
  },
];

export const researchRunsListResponse: ResearchRunsListResponse = {
  ok: true,
  runs: researchRunSummaryFixtures,
  total: 1,
};

// ---------------------------------------------------------------------------
// Data Freshness
// ---------------------------------------------------------------------------

export const dataFreshnessResponse: DataFreshnessResponse = {
  ok: true,
  market: 'cn',
  checked_at: '2026-06-15T12:00:00Z',
  sources: {
    yahoo: { available: true, latest_date: '2026-06-14', age_days: 1 },
    qlib: { available: true, latest_date: '2026-06-14', age_days: 1 },
  },
  warnings: [],
  status: 'fresh',
};
