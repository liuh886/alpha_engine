/** Types and constants for AttributionPage */

export type FactorStatus = "Active" | "Validated" | "Candidate";

export interface FactorAttribution {
  factor_id: number;
  factor_name: string;
  factor_expression: string;
  ic: number;
  return_contribution: number; // percentage, e.g. 2.5 means 2.5%
  risk_contribution: number;   // percentage
  exposure: number;            // beta
  status: FactorStatus;
}

export interface AttributionSummary {
  total_return: number;       // percentage
  excess_return: number;      // percentage
  factor_coverage: number;    // R^2, 0-1
  unexplained_return: number; // percentage
  benchmark_return?: number;  // percentage
  period?: string;            // e.g. "2025-01-01 to 2026-01-01"
  market?: string;            // "us" | "cn"
  strategy_name?: string;
}

export interface AttributionResponse {
  ok: boolean;
  summary: AttributionSummary;
  factors: FactorAttribution[];
  error?: string;
}

export const STATUS_COLORS: Record<FactorStatus, string> = {
  Active: "bg-green-500/20 text-green-400 border-green-500/30",
  Validated: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Candidate: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
};

export function formatSignedPct(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "N/A";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(decimals)}%`;
}

export function truncateExpression(expr: string, maxLen = 40): string {
  if (expr.length <= maxLen) return expr;
  return expr.slice(0, maxLen - 3) + "...";
}
