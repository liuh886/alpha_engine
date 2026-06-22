import type { ModelVersion } from "./api-types";

function safeJson<T>(value: unknown, fallback: T): T {
  if (!value) return fallback;
  if (typeof value === "object") return value as T;
  try {
    return JSON.parse(String(value)) as T;
  } catch {
    return fallback;
  }
}

/**
 * Normalizes backend model payload into a consistent ModelVersion frontend shape.
 * Ensures metrics like IC/Rank IC and paths are correctly extracted.
 */
export function normalizeModelRegistryEntry(row: any): ModelVersion {
  const metricsRaw = safeJson<Record<string, number>>(row.metrics ?? row.metrics_json, {});
  const params = safeJson<Record<string, unknown>>(row.params ?? row.params_json, {});
  const payload = safeJson<Record<string, any>>(row.payload ?? row.payload_json, {});

  // Initialize metrics with existing values
  const metrics: Record<string, number> = { ...metricsRaw };

  // Attempt to extract IC/Rank IC from payload if not present in metrics
  const sigAnalysis = payload?.data?.sig_analysis;
  if (sigAnalysis) {
    if (sigAnalysis.ic?.ic !== undefined && metrics["IC"] === undefined) {
      metrics["IC"] = Number(sigAnalysis.ic.ic);
    }
    if (sigAnalysis.ric?.ric !== undefined && metrics["Rank IC"] === undefined) {
      metrics["Rank IC"] = Number(sigAnalysis.ric.ric);
    }
  }

  return {
    id: String(row.id || ""),
    tag: row.tag || "",
    name: row.name || "",
    market: row.market || "",
    model_type: row.model_type || row.type || "",
    path: row.path || payload?.path || "",
    run_id: row.run_id || "",
    created_at: row.created_at || "",
    stage: row.stage || "CANDIDATE",
    description: row.description || "",
    snapshot_id: row.snapshot_id || (params as any)?.data_snapshot_id || "",
    metrics,
    params,
  };
}
