/**
 * Shared metric definitions for cross-page consistency.
 *
 * All pages that display backtest performance metrics should import from here
 * instead of defining their own metric lists. This ensures consistent labels,
 * formatting, and ordering across ComparePage, ModelsPage, and others.
 *
 * @see requirements 24, 25
 */

import { formatPct, formatNum } from "@/lib/format";

// ---------------------------------------------------------------------------
// Schema version — bump when metric keys, labels, or semantics change.
// Consumers can compare versions to detect stale caches or incompatible data.
// ---------------------------------------------------------------------------

/** Current metric schema version. Bump on breaking changes to metric keys or semantics. */
export const METRIC_SCHEMA_VERSION = "1.0.0" as const;

// ---------------------------------------------------------------------------
// MetricDefinition
// ---------------------------------------------------------------------------

/** Describes a single standard performance metric. */
export interface MetricDefinition {
  /** Canonical key used in `Record<string, number>` metric maps (Title Case). */
  key: string;
  /** Short display label for table headers and cards. */
  label: string;
  /** Unit type — drives default formatting and axis labels. */
  unit: "pct" | "ratio" | "count";
  /** Formatter: takes raw numeric value (or null/undefined) and returns display string. */
  format: (value: number | null | undefined) => string;
  /** Human-readable description for tooltips and docs. */
  description: string;
  /** Whether this metric must be present for a valid backtest report. */
  required: boolean;
  /**
   * Alternative keys to try when looking up a metric from API responses
   * that may use different naming conventions (e.g., snake_case from the backend).
   * Tried in order after the canonical `key`.
   */
  apiKeys?: string[];
}

// ---------------------------------------------------------------------------
// Standard metric definitions
// ---------------------------------------------------------------------------

/** All standard backtest performance metrics in display order. */
export const STANDARD_METRICS: MetricDefinition[] = [
  {
    key: "Annualized Return",
    label: "Ann. Return",
    unit: "pct",
    format: formatPct,
    description: "Annualized rate of return over the backtest period",
    required: true,
    apiKeys: ["annualized_return", "annual_return", "return"],
  },
  {
    key: "Sharpe Ratio",
    label: "Sharpe Ratio",
    unit: "ratio",
    format: (v) => formatNum(v, 3),
    description: "Risk-adjusted return relative to the risk-free rate",
    required: true,
    apiKeys: ["sharpe_ratio", "sharpe"],
  },
  {
    key: "Information Ratio",
    label: "Info Ratio",
    unit: "ratio",
    format: (v) => formatNum(v, 3),
    description: "Excess return per unit of tracking error vs benchmark",
    required: true,
    apiKeys: ["information_ratio", "ir"],
  },
  {
    key: "Max Drawdown",
    label: "Max DD",
    unit: "pct",
    format: formatPct,
    description: "Worst peak-to-trough decline during the backtest period",
    required: true,
    apiKeys: ["max_drawdown", "mdd"],
  },
  {
    key: "Annualized Volatility",
    label: "Ann. Vol",
    unit: "pct",
    format: formatPct,
    description: "Annualized standard deviation of returns",
    required: false,
    apiKeys: ["annualized_volatility", "annual_volatility", "volatility"],
  },
  {
    key: "Total Return",
    label: "Total Return",
    unit: "pct",
    format: formatPct,
    description: "Cumulative return over the entire backtest period",
    required: false,
    apiKeys: ["total_return"],
  },
  {
    key: "Excess Return",
    label: "Excess Return",
    unit: "pct",
    format: formatPct,
    description: "Return above the benchmark after costs",
    required: false,
    apiKeys: ["excess_return", "excess_return_with_cost"],
  },
  {
    key: "Turnover",
    label: "Turnover",
    unit: "ratio",
    format: (v) => formatNum(v, 3),
    description: "Average daily portfolio turnover rate",
    required: false,
    apiKeys: ["turnover", "turnover_rate"],
  },
];

// ---------------------------------------------------------------------------
// Lookup helpers
// ---------------------------------------------------------------------------

/** Map from canonical key to MetricDefinition for O(1) lookup. */
const METRIC_BY_KEY = new Map<string, MetricDefinition>();
for (const def of STANDARD_METRICS) {
  METRIC_BY_KEY.set(def.key, def);
}

/** Map from all known keys (canonical + apiKeys) to MetricDefinition. */
const METRIC_BY_ANY_KEY = new Map<string, MetricDefinition>();
for (const def of STANDARD_METRICS) {
  METRIC_BY_ANY_KEY.set(def.key, def);
  if (def.apiKeys) {
    for (const alias of def.apiKeys) {
      METRIC_BY_ANY_KEY.set(alias, def);
    }
  }
}

/** Look up a MetricDefinition by its canonical key. Returns undefined if not found. */
export function getMetricDefinition(key: string): MetricDefinition | undefined {
  return METRIC_BY_KEY.get(key);
}

/**
 * Look up a numeric metric value from a metrics map, trying the canonical key
 * first, then any registered API key aliases.
 *
 * Returns `null` if the metric is not found or not numeric.
 */
export function lookupMetricValue(
  metrics: Record<string, number | null | undefined> | undefined,
  def: MetricDefinition,
): number | null {
  if (!metrics) return null;
  const candidates = [def.key, ...(def.apiKeys ?? [])];
  for (const k of candidates) {
    const v = metrics[k];
    if (v != null && !Number.isNaN(v)) return Number(v);
  }
  return null;
}

/**
 * Convenience: look up a metric value by canonical key using the full
 * STANDARD_METRICS registry. Returns null if the key is unknown or the
 * value is absent.
 */
export function lookupMetricValueByKey(
  metrics: Record<string, number | null | undefined> | undefined,
  key: string,
): number | null {
  const def = METRIC_BY_ANY_KEY.get(key);
  if (!def) return null;
  return lookupMetricValue(metrics, def);
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

/**
 * Format a metric value using its definition's formatter.
 * This is the single entry-point for rendering metric values across the UI.
 */
export function formatMetricValue(
  value: number | null | undefined,
  definition: MetricDefinition,
): string {
  return definition.format(value);
}

// ---------------------------------------------------------------------------
// Compatibility checking (for ComparePage)
// ---------------------------------------------------------------------------

export interface CompatibilityWarning {
  /** Short machine-readable reason code. */
  code: "market" | "benchmark" | "window";
  /** Human-readable explanation shown to the user. */
  message: string;
}

/**
 * Check whether a set of models are compatible for meaningful side-by-side
 * comparison. Returns an array of warnings; empty means fully compatible.
 *
 * Checks:
 * - Same market
 * - Same benchmark
 * - Overlapping date windows (at least 60 days overlap)
 */
export function checkModelCompatibility(
  models: Array<{
    id: string;
    market?: string;
    backtest: {
      meta?: {
        benchmark?: string;
        market?: string;
        start?: string;
        end?: string;
      };
    };
  }>,
): CompatibilityWarning[] {
  if (models.length < 2) return [];

  const warnings: CompatibilityWarning[] = [];

  // --- Market check ---
  const markets = new Set(
    models.map((m) => (m.market || m.backtest?.meta?.market || "").toLowerCase()),
  );
  markets.delete(""); // ignore empty
  if (markets.size > 1) {
    warnings.push({
      code: "market",
      message: `Models span different markets (${[...markets].join(", ")}). Metrics may not be directly comparable.`,
    });
  }

  // --- Benchmark check ---
  const benchmarks = new Set(
    models.map((m) => (m.backtest?.meta?.benchmark || "").toLowerCase()),
  );
  benchmarks.delete("");
  if (benchmarks.size > 1) {
    warnings.push({
      code: "benchmark",
      message: `Models use different benchmarks (${[...benchmarks].join(", ")}). Risk-adjusted ratios are not directly comparable.`,
    });
  }

  // --- Date window check ---
  const starts = models
    .map((m) => m.backtest?.meta?.start)
    .filter(Boolean) as string[];
  const ends = models
    .map((m) => m.backtest?.meta?.end)
    .filter(Boolean) as string[];

  if (starts.length > 0 && ends.length > 0) {
    const latestStart = starts.sort().pop()!;
    const earliestEnd = ends.sort().shift()!;

    if (latestStart > earliestEnd) {
      warnings.push({
        code: "window",
        message: `Date windows do not overlap (latest start: ${latestStart}, earliest end: ${earliestEnd}). Comparison is not meaningful.`,
      });
    } else {
      // Check for at least 60 days overlap
      const overlapDays =
        (new Date(earliestEnd).getTime() - new Date(latestStart).getTime()) /
        86_400_000;
      if (overlapDays < 60) {
        warnings.push({
          code: "window",
          message: `Date windows overlap by only ${Math.round(overlapDays)} days. Results may be unreliable.`,
        });
      }
    }
  }

  return warnings;
}
