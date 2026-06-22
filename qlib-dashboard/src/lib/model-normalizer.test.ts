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

  it("handles missing fields gracefully", () => {
    const empty = normalizeModelRegistryEntry({});
    expect(empty.id).toBe("");
    expect(empty.market).toBe("");
    expect(empty.stage).toBe("CANDIDATE");
    expect(empty.metrics).toEqual({});
  });
});
