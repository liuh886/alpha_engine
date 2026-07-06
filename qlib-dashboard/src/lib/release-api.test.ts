import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { apiClient } from "./api-client";
import { releaseApi } from "./release-api";

describe("releaseApi", () => {
  beforeEach(() => vi.clearAllMocks());

  it("requests one workflow by exact workflow identity", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce([]);

    await releaseApi.getWorkflow("workflow-17");

    expect(apiClient.get).toHaveBeenCalledWith("/api/workflow/status", {
      params: { workflow_id: "workflow-17", limit: 1 },
    });
  });

  it("submits training with an explicit snapshot identity", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      ok: true,
      workflow_id: "workflow-17",
      message: "started",
    });

    await releaseApi.submitTraining({
      market: "us",
      model_type: "lgbm",
      tag: "release-17",
      snapshot_id: "snapshot-1",
    });

    expect(apiClient.post).toHaveBeenCalledWith("/api/workflow/train", {
      market: "us",
      model_type: "lgbm",
      tag: "release-17",
      details: { snapshot_id: "snapshot-1" },
    });
  });

  it("loads model-bound evidence without using latest aliases", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ ok: true, bundle: {} });

    await releaseApi.getModelEvidence("model-42");

    expect(apiClient.get).toHaveBeenCalledWith("/api/evidence/model/model-42");
  });

  it("loads the latest fixed-10D signal discovery report for a market", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ ok: true, report: {}, artifact_path: "report.json" });

    await releaseApi.getLatestSignalDiscovery("us");

    expect(apiClient.get).toHaveBeenCalledWith("/api/evidence/signal-discovery/latest", {
      signal: undefined,
      params: { market: "us" },
      init: { cache: "no-store" },
    });
  });

  it("promotes and deletes by the backend artifact identity", async () => {
    vi.mocked(apiClient.post)
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({ ok: true });

    await releaseApi.promoteModel("model-42", "RECOMMENDED");
    await releaseApi.deleteModel("model-42");

    expect(apiClient.post).toHaveBeenNthCalledWith(1, "/api/models/promote", {
      artifact_id: "model-42",
      stage: "RECOMMENDED",
    });
    expect(apiClient.post).toHaveBeenNthCalledWith(2, "/api/models/delete", {
      artifact_id: "model-42",
    });
  });
});
