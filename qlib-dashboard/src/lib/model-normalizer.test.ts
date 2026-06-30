import { describe, it, expect } from "vitest";
import { normalizeModelRegistryEntry } from "./model-normalizer";

describe("normalizeModelRegistryEntry", () => {
  it("maps backend fields to frontend registry fields correctly", () => {
    const rawBackendPayload = {
      id: "us_model_123",
      tag: "test_tag",
      name: "Test Model",
      market: "us",
      model_type: "LGBModel",
      path: "/artifacts/model.pkl",
      run_id: "run_123",
      created_at: "2026-06-21T03:23:46",
      metrics_json: JSON.stringify({
        annual_return: 0.5,
        max_drawdown: -0.2,
        sharpe: 1.5,
      }),
      payload_json: JSON.stringify({
        data: {
          sig_analysis: {
            ic: { ic: 0.05 },
            ric: { ric: 0.04 }
          }
        }
      })
    };

    const normalized = normalizeModelRegistryEntry(rawBackendPayload);

    expect(normalized.id).toBe("us_model_123");
    expect(normalized.name).toBe("Test Model");
    expect(normalized.market).toBe("us");
    expect(normalized.model_type).toBe("LGBModel");
    expect(normalized.path).toBe("/artifacts/model.pkl");
    expect(normalized.created_at).toBe("2026-06-21T03:23:46");
    
    // Metrics check
    expect(normalized.metrics?.annual_return).toBe(0.5);
    expect(normalized.metrics?.max_drawdown).toBe(-0.2);
    expect(normalized.metrics?.sharpe).toBe(1.5);
    expect(normalized.metrics?.["IC"]).toBe(0.05);
    expect(normalized.metrics?.["Rank IC"]).toBe(0.04);
  });

  it("extracts standard metrics from payload.data.indicators if metrics_json is empty", () => {
    const rawBackendPayload = {
      id: "cn_model_123",
      created_ts: 1781982887,
      metrics_json: "{}",
      payload_json: JSON.stringify({
        path: "/artifacts/model2.pkl",
        data: {
          indicators: {
            annual_return: 0.15,
            sharpe: 1.2,
            max_drawdown: -0.1
          }
        }
      })
    };

    const normalized = normalizeModelRegistryEntry(rawBackendPayload);
    expect(normalized.path).toBe("/artifacts/model2.pkl");
    expect(normalized.created_at).toBe(new Date(1781982887 * 1000).toISOString());
    expect(normalized.metrics?.["Annualized Return"]).toBe(0.15);
    expect(normalized.metrics?.["Sharpe Ratio"]).toBe(1.2);
    expect(normalized.metrics?.["Max Drawdown"]).toBe(-0.1);
  });

  it("handles missing fields gracefully", () => {
    const empty = normalizeModelRegistryEntry({});
    expect(empty.id).toBe("");
    expect(empty.market).toBe("");
    expect(empty.stage).toBe("CANDIDATE");
    expect(empty.metrics).toEqual({});
  });

  it("extracts benchmark_return and excess_return from indicators", () => {
    const raw = {
      id: "cn_model_excess",
      payload_json: JSON.stringify({
        data: {
          indicators: {
            total_return: 0.25,
            excess_return: 0.12,
            benchmark_return: 0.13,
            sharpe: 1.5,
            max_drawdown: -0.15,
          },
          sig_analysis: {
            ic: { ic: 0.04 },
            ric: { ric: 0.035 },
            icir: { icir: 0.6 },
            positive_ic_ratio: 0.75,
            consistency: 0.7,
            wf_successful_splits: 8,
            wf_total_splits: 10,
          },
        },
      }),
    };

    const n = normalizeModelRegistryEntry(raw);
    expect(n.metrics?.["Total Return"]).toBe(0.25);
    expect(n.metrics?.["Excess Return"]).toBe(0.12);
    expect(n.metrics?.["Benchmark Return"]).toBe(0.13);
    expect(n.metrics?.["ICIR"]).toBe(0.6);
    expect(n.metrics?.["Positive IC Ratio"]).toBe(0.75);
    expect(n.metrics?.["Consistency"]).toBe(0.7);
    expect(n.metrics?.["WF Successful Splits"]).toBe(8);
    expect(n.metrics?.["WF Total Splits"]).toBe(10);
  });

  it("extracts excess_return_with_cost as fallback for Excess Return", () => {
    const raw = {
      id: "cn_model_cost_fallback",
      payload_json: JSON.stringify({
        data: {
          indicators: {
            total_return: 0.25,
            excess_return_with_cost: 0.10,
            benchmark_return: 0.15,
          },
          sig_analysis: {
            ic: { ic: 0.03 },
          },
        },
      }),
    };

    const n = normalizeModelRegistryEntry(raw);
    expect(n.metrics?.["Total Return"]).toBe(0.25);
    // fallout from excess_return not present → falls back to excess_return_with_cost
    expect(n.metrics?.["Excess Return"]).toBe(0.10);
  });

  it("normalizes CN registry backtest and walk-forward metrics", () => {
    const normalized = normalizeModelRegistryEntry({
      id: "cn-final",
      market: "cn",
      payload: {
        backtest: { metrics: {
          total_return: 0.3365,
          benchmark_return: 0.2899,
          excess_return: 0.0466,
          max_drawdown: -0.0454,
          sharpe_ratio: 1.3063,
        } },
        walk_forward: {
          mean_ic: 0.0176,
          ic_ir: 0.5761,
          positive_ic_ratio: 0.7692,
          consistency: 0.7692,
          n_success: 13,
          n_total_splits: 16,
        },
      },
    });

    expect(normalized.metrics).toMatchObject({
      "Total Return": 0.3365,
      "Benchmark Return": 0.2899,
      "Excess Return": 0.0466,
      "Max Drawdown": -0.0454,
      "Sharpe Ratio": 1.3063,
      "IC": 0.0176,
      "ICIR": 0.5761,
      "Positive IC Ratio": 0.7692,
      "Consistency": 0.7692,
      "WF Successful Splits": 13,
      "WF Total Splits": 16,
    });
  });
});
