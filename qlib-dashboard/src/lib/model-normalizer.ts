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
 * Normalizes a single attribution row from various backend field name conventions
 * into a consistent { instrument, name, value } shape.
 */
export function normalizeAttributionRow(row: any): { instrument: string; name: string; value: number } {
  return {
    instrument: row.instrument ?? row.code ?? row.symbol ?? "",
    name: row.name ?? row.instrument_label ?? row.instrument ?? row.code ?? "",
    value: Number(
      row.pnl ??
      row.net_pnl ??
      row.yield ??
      row.contribution ??
      row.return_contribution ??
      row.pnl_contribution ??
      row.excess_contribution ??
      row.asset_contribution ??
      0
    ),
  };
}

/**
 * Normalizes backend model payload into a consistent ModelVersion frontend shape.
 * Ensures metrics like IC/Rank IC and paths are correctly extracted.
 */
export function normalizeModelRegistryEntry(row: any): ModelVersion {
  const metricsRaw = safeJson<Record<string, number>>(row.metrics ?? row.metrics_json, {});
  const params = safeJson<Record<string, unknown>>(row.params ?? row.params_json, {});
  
  let payload = safeJson<Record<string, any>>(row.payload ?? row.payload_json, null as any);
  if (!payload && (row.data || row.backtest)) {
    payload = { data: row.data, backtest: row.backtest };
  } else if (!payload) {
    payload = {};
  }

  // Initialize metrics with existing values, falling back to payload.backtest.metrics if metrics_json was empty
  const payloadMetrics = payload?.backtest?.metrics ?? {};
  const metrics: Record<string, number> = { ...payloadMetrics, ...metricsRaw };
  const metricAliases: Record<string, string[]> = {
    "Total Return": ["total_return"],
    "Benchmark Return": ["benchmark_return"],
    "Excess Return": ["excess_return", "excess_return_with_cost"],
    "Annualized Return": ["annual_return", "annualized_return"],
    "Sharpe Ratio": ["sharpe_ratio", "sharpe"],
    "Max Drawdown": ["max_drawdown", "mdd"],
    "Annualized Volatility": ["volatility", "annual_volatility"],
  };
  for (const [canonical, aliases] of Object.entries(metricAliases)) {
    const alias = aliases.find((key) => metrics[key] !== undefined);
    if (metrics[canonical] === undefined && alias) metrics[canonical] = Number(metrics[alias]);
  }

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

  const walkForward = payload?.walk_forward;
  if (walkForward) {
    const wfMap: Record<string, string> = {
      "IC": "mean_ic",
      "ICIR": "ic_ir",
      "Positive IC Ratio": "positive_ic_ratio",
      "Consistency": "consistency",
      "WF Successful Splits": "n_success",
      "WF Total Splits": "n_total_splits",
    };
    for (const [canonical, source] of Object.entries(wfMap)) {
      if (metrics[canonical] === undefined && walkForward[source] !== undefined) {
        metrics[canonical] = Number(walkForward[source]);
      }
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
      "Total Return": "total_return",
      "Excess Return": "excess_return",
      "Benchmark Return": "benchmark_return",
    };
    for (const [frontendKey, backendKey] of Object.entries(map)) {
      if (indicators[backendKey] !== undefined && metrics[frontendKey] === undefined) {
        metrics[frontendKey] = Number(indicators[backendKey]);
      }
    }
    // Also capture numeric excess_return with cost as fallback
    if (metrics["Excess Return"] === undefined && indicators["excess_return_with_cost"] !== undefined) {
      metrics["Excess Return"] = Number(indicators["excess_return_with_cost"]);
    }
  }

  // Extract walk-forward metrics from payload.data.sig_analysis
  if (sigAnalysis) {
    if (sigAnalysis.icir?.icir !== undefined && metrics["ICIR"] === undefined) {
      metrics["ICIR"] = Number(sigAnalysis.icir.icir);
    }
    if (sigAnalysis.positive_ic_ratio !== undefined && metrics["Positive IC Ratio"] === undefined) {
      metrics["Positive IC Ratio"] = Number(sigAnalysis.positive_ic_ratio);
    }
    if (sigAnalysis.consistency !== undefined && metrics["Consistency"] === undefined) {
      metrics["Consistency"] = Number(sigAnalysis.consistency);
    }
    // WF split counts for display
    if (sigAnalysis.wf_successful_splits !== undefined) {
      metrics["WF Successful Splits"] = Number(sigAnalysis.wf_successful_splits);
    }
    if (sigAnalysis.wf_total_splits !== undefined) {
      metrics["WF Total Splits"] = Number(sigAnalysis.wf_total_splits);
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

  // Map attribution (normalize field names from various backend conventions)
  const rawAttribution = payload?.data?.attribution_normal || null;
  const attribution = rawAttribution
    ? rawAttribution.map((row: any) => normalizeAttributionRow(row))
    : null;

  // Construct backtest object
  const backtest = {
    meta: {
      start: report.length > 0 ? report[0].date : "N/A",
      end: report.length > 0 ? report[report.length - 1].date : "N/A",
      benchmark: row.market === "us" ? "Nasdaq 100" : "CSI 300",
      market: row.market || "",
      generated_at: row.created_at || ""
    },
    metrics,
    report,
    positions,
    attribution,
    featureImportance: payload?.data?.sig_analysis?.feature_importance || {},
    indicators: payload?.data?.indicators || {}
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
