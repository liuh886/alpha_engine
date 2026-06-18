/** Types and constants for FactorRegistryPage */

export type FactorStage = "Proposed" | "Candidate" | "Validated" | "Active" | "Deprecated";

export interface FactorRecord {
  id: number;
  name: string;
  expression: string;
  category: string;
  direction: string;
  lookback_days: number;
  thesis: string;
  stage: FactorStage;
  created_at: string;
  updated_at: string;
}

export interface FactorValidationRecord {
  id: number;
  factor_id: number;
  market: string;
  ic: number | null;
  rank_ic: number | null;
  icir: number | null;
  t_stat: number | null;
  positive_ratio: number | null;
  mean_decay_1d: number | null;
  mean_decay_5d: number | null;
  quintile_spread: number | null;
  passed: boolean;
  validated_at: string;
}

export interface FactorUsageRecord {
  id: number;
  factor_id: number;
  strategy_config: string | null;
  weight: number;
  added_at: string;
}

export interface FactorWithValidation extends FactorRecord {
  latest_validation?: FactorValidationRecord | null;
}

export interface FactorDetail {
  factor: FactorRecord;
  validations: FactorValidationRecord[];
  usage: FactorUsageRecord[];
}

export interface RegistryStats {
  total_factors: number;
  by_stage: Record<string, number>;
  by_category: Record<string, number>;
  by_direction: Record<string, number>;
  total_validations: number;
  total_passed_validations: number;
  total_usage_records: number;
}

export interface ScanStats {
  total_scanned: number;
  passed: number;
  failed: number;
  scan_date: string;
}

export const STAGE_COLORS: Record<FactorStage, string> = {
  Proposed: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  Candidate: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  Validated: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  Active: "bg-green-500/20 text-green-400 border-green-500/30",
  Deprecated: "bg-red-500/20 text-red-400 border-red-500/30",
};

export const ALL_STAGES: FactorStage[] = ["Proposed", "Candidate", "Validated", "Active", "Deprecated"];

export function truncateExpression(expr: string, maxLen = 45): string {
  if (expr.length <= maxLen) return expr;
  return expr.slice(0, maxLen - 3) + "...";
}

export function stageIndex(stage: string): number {
  return ALL_STAGES.indexOf(stage as FactorStage);
}
