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

function normalizeTimestampSecondsOrMs(value: unknown): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const ms = value < 10_000_000_000 ? value * 1000 : value;
  return new Date(ms).toISOString();
}

/**
 * Normalizes backend model payload into a consistent ModelVersion frontend shape.
 * Ensures metrics like IC/Rank IC and paths are correctly extracted.
 */
export function normalizeModelRegistryEntry(row: any): ModelVersion {
  const metricsRaw = safeJson<Record<string, number>>(row.metrics ?? row.metrics_json, {});
  const params = safeJson<Record<string, unknown>>(row.params ?? row.params_json, {});
  const payload = safeJson<Record<string, any>>(row.payload ?? row.payload_json, {});

  // Initialize metrics with existing values, falling back to payload.backtest.metrics if metrics_json was empty
  const payloadMetrics = payload?.backtest?.metrics ?? {};
  const metrics: Record<string, number> = { ...payloadMetrics, ...metricsRaw };

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

  // Attempt to extract standard metrics from payload.data.indicators if not present in metrics
  const indicators = payload?.data?.indicators;
  if (indicators) {
    const map: Record<string, string> = {
      "Annualized Return": "annual_return",
      "Sharpe Ratio": "sharpe",
      "Information Ratio": "information_ratio",
      "Max Drawdown": "max_drawdown",
      "Annualized Volatility": "annual_volatility",
      "Total Return": "total_return"
    };
    for (const [frontendKey, backendKey] of Object.entries(map)) {
      if (indicators[backendKey] !== undefined && metrics[frontendKey] === undefined) {
        metrics[frontendKey] = Number(indicators[backendKey]);
      }
    }
  }

  // Map report_normal to report array
  const report: any[] = [];
  if (payload?.data?.report_normal?.columns && payload?.data?.report_normal?.index) {
    const cols = payload.data.report_normal.columns;
    const data = payload.data.report_normal.data;
    const index = payload.data.report_normal.index;

    index.forEach((date: string, i: number) => {
      const row: any = { date: date.split('T')[0] };
      cols.forEach((col: string, j: number) => {
        row[col] = data[i][j];
      });
      report.push(row);
    });
  }

  // Map positions_normal
  const positions = payload?.data?.positions_normal || [];

  const backtest = {
    metrics,
    report,
    positions
  };

  // Ensure created_at uses created_ts if created_at string is empty
  let created_at = row.created_at || "";
  if (!created_at && row.created_ts) {
    created_at = normalizeTimestampSecondsOrMs(row.created_ts) || "";
  }

  return {
    id: String(row.id || ""),
    tag: row.tag || "",
    name: row.name || "",
    market: row.market || "",
    model_type: row.model_type || row.type || "",
    path: row.path || payload?.path || "",
    run_id: row.run_id || "",
    created_at,
    stage: row.stage || "CANDIDATE",
    description: row.description || "",
    snapshot_id: row.snapshot_id || (params as any)?.data_snapshot_id || "",
    metrics,
    params,
    backtest,
  };
}
