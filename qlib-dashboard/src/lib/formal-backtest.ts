import type { Position, ReportRow } from './types';

export type FormalBacktestCompletenessStatus = 'complete' | 'partial';

export interface FormalBacktestTrade {
  date: string;
  instrument: string;
  action: string;
  previous_weight?: number;
  target_weight?: number;
  weight_delta?: number;
  transaction_cost?: number;
  holding_end_date?: string;
  reason?: string;
  window?: string;
  [key: string]: unknown;
}

export interface FormalBacktestCompleteness {
  status: FormalBacktestCompletenessStatus;
  performance_trace?: string;
  holdings?: string;
  trades?: string;
  attribution?: string;
  missing: string[];
  [key: string]: unknown;
}

export interface FormalBacktestPackage {
  schema_version: '1.0.0';
  record_type: 'formal_model_backtest';
  backtest_id: string;
  model_id: string;
  display_name: string;
  market: string;
  benchmark: string;
  publication_status: 'accepted_formal_baseline';
  generated_at: string;
  evidence_cutoff: string;
  trace_frequency: string;
  date_range: { start: string; end: string };
  metrics: Record<string, number>;
  portfolio_contract: Record<string, unknown>;
  report: ReportRow[];
  positions: Position[];
  trades: FormalBacktestTrade[];
  attribution: Array<{ instrument?: string; name?: string; value?: number; [key: string]: unknown }>;
  window_summary: Array<Record<string, unknown>>;
  evidence: Record<string, unknown>;
  evidence_completeness: FormalBacktestCompleteness;
  interpretation_notes: string[];
  research_only: true;
  trade_ready: false;
  [key: string]: unknown;
}
