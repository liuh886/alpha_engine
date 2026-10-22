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
  holding_end_date?: string;
  benchmark_id?: string;
  provisional_mtm?: boolean;
  settlement_status?: 'settled' | 'provisional_mtm' | string;
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
  name?: string;
  weight: number;
  price?: number;
  amount?: number;
  [key: string]: unknown;
}
