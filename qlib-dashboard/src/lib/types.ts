/**
 * Shared type definitions for dashboard data structures.
 * Use these instead of `any[]` for type safety.
 */

// ---------------------------------------------------------------------------
// Backtest report data (per-day row from the report array)
// ---------------------------------------------------------------------------

export interface ReportRow {
  date: string;
  account: number;
  value?: number;
  turnover?: number;
  bench?: number;          // Qlib native daily benchmark returns
  bench_qqq?: number;      // merged US benchmark (equity level or daily return)
  bench_hs300?: number;    // merged CN benchmark (equity level or daily return)
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Position / holdings data
// ---------------------------------------------------------------------------

export interface Position {
  date: string;
  instrument: string;
  instrument_label?: string;
  weight: number;
  price?: number;
  amount?: number;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Model data (parsed from dashboard.json)
// ---------------------------------------------------------------------------

export interface ModelBacktest {
  report: ReportRow[];
  positions: Position[];
  metrics: Record<string, number>;
  indicators?: Record<string, unknown>;
}

export interface ModelParams {
  model_path?: string;
  source_model_path?: string;
  meta?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ModelData {
  id: string;
  name: string;
  market?: string;
  backtest: ModelBacktest;
  params: ModelParams;
}

// ---------------------------------------------------------------------------
// Factor-related types
// ---------------------------------------------------------------------------

export interface FactorICResult {
  factor_name: string;
  ic: number;
  rank_ic?: number;
  ic_ir?: number;
  t_stat?: number;
  positive_ic_ratio?: number;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Tooltip payload types (recharts)
// ---------------------------------------------------------------------------

export interface RechartsTooltipPayload {
  name: string;
  value: number | string;
  color: string;
  dataKey: string;
  payload: Record<string, unknown>;
}

export interface RechartsTooltipProps {
  active?: boolean;
  payload?: RechartsTooltipPayload[];
  label?: string;
}

// ---------------------------------------------------------------------------
// Model version (from /api/models)
// ---------------------------------------------------------------------------

export interface ModelVersion {
  id: string;
  tag?: string;
  name?: string;
  market?: string;
  model_type?: string;
  path?: string;
  run_id?: string;
  created_at?: string;
  description?: string;
  metrics?: Record<string, number>;
  params?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Agent / tool types
// ---------------------------------------------------------------------------

export interface AgentToolResult {
  ok: boolean;
  result?: unknown;
  error?: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Job status
// ---------------------------------------------------------------------------

export interface Job {
  id: string;
  type: string;
  status: string;
  cmd?: string;
  commands?: string;
  name?: string;
  [key: string]: unknown;
}
