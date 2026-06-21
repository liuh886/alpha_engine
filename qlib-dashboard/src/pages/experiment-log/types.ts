/** Types and constants for ExperimentLogPage */

export type ExperimentType = "factor" | "model" | "wf";
export type ExperimentResult = "pass" | "fail" | "in_progress";

export interface ExperimentSummary {
  total_experiments: number;
  active_factors: number;
  wf_results: number;
  failed_experiments: number;
}

export interface ExperimentEntry {
  id: number;
  timestamp: string;
  type: ExperimentType;
  name: string;
  result: ExperimentResult;
  metrics: Record<string, number | string | null>;
}

export interface FailedExperiment {
  id: string | number;
  timestamp: string;
  type: ExperimentType;
  name: string;
  failure_reason: string;
  details: Record<string, number | string | null>;
}

export const TYPE_COLORS: Record<ExperimentType, string> = {
  factor: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  model: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  wf: "bg-orange-500/20 text-orange-400 border-orange-500/30",
};

export const TYPE_LABELS: Record<ExperimentType, string> = {
  factor: "Factor",
  model: "Model",
  wf: "Walk-Forward",
};

export const RESULT_COLORS: Record<ExperimentResult, string> = {
  pass: "text-green-500",
  fail: "text-red-500",
  in_progress: "text-yellow-500",
};

export const ALL_TYPES: ExperimentType[] = ["factor", "model", "wf"];

export function formatTimestamp(ts: string): string {
  if (!ts) return "N/A";
  const compact = ts.match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/);
  const normalized = compact
    ? `${compact[1]}-${compact[2]}-${compact[3]}T${compact[4]}:${compact[5]}:${compact[6]}`
    : ts;
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return ts.slice(0, 16);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatMetricValue(v: number | string | null | undefined): string {
  if (v === null || v === undefined) return "N/A";
  if (typeof v === "number") {
    if (Number.isNaN(v)) return "N/A";
    if (Math.abs(v) < 1 && Math.abs(v) > 0) return v.toFixed(4);
    return v.toFixed(2);
  }
  return String(v);
}
