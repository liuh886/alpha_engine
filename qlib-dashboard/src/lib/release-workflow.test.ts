import { describe, expect, it } from "vitest";
import {
  classifyDataOutcome,
  parseReleaseIdentity,
  releaseSearch,
  resolveEvidenceIdentity,
  resolveWorkflowResult,
} from "./release-workflow";

describe("release workflow identity", () => {
  it("round-trips exact identities through URL search params", () => {
    const search = releaseSearch({
      jobId: "job-data-1",
      snapshotId: "snapshot-cn-20260620",
      workflowId: "workflow-17",
      runId: "run-abc",
      modelId: "model-42",
      evidenceId: "evidence-model-42",
    });

    expect(parseReleaseIdentity(search)).toEqual({
      jobId: "job-data-1",
      snapshotId: "snapshot-cn-20260620",
      workflowId: "workflow-17",
      runId: "run-abc",
      modelId: "model-42",
      evidenceId: "evidence-model-42",
    });
  });

  it("preserves existing identity while replacing only supplied fields", () => {
    const search = releaseSearch(
      { modelId: "model-43" },
      "?snapshot_id=snapshot-1&run_id=run-1&model_id=model-42",
    );

    expect(search).toBe("?snapshot_id=snapshot-1&run_id=run-1&model_id=model-43");
  });
});

describe("release workflow outcome", () => {
  it("treats an approved snapshot as success", () => {
    expect(classifyDataOutcome({
      latest_snapshot_id: "snapshot-1",
      quality_status: "ok",
      quality_warnings: [],
    })).toEqual({ state: "success", reason: "Snapshot is approved for training." });
  });

  it("distinguishes empty, stale, partial, and blocked data", () => {
    expect(classifyDataOutcome({ quality_status: "ok" }).state).toBe("empty");
    expect(classifyDataOutcome({ latest_snapshot_id: "s1", quality_status: "stale" }).state).toBe("stale");
    expect(classifyDataOutcome({ latest_snapshot_id: "s1", quality_status: "warning" }).state).toBe("partial");
    expect(classifyDataOutcome({ latest_snapshot_id: "s1", quality_status: "failed" }).state).toBe("blocked");
  });

  it("resolves only the model bound to the completed workflow run", () => {
    const result = resolveWorkflowResult(
      {
        workflow_id: "workflow-17",
        name: "Pipeline Run",
        market: "US",
        status: "SUCCESS",
        details: { run_id: "run-abc", snapshot_id: "snapshot-1" },
      },
      [
        { id: "model-latest", run_id: "run-latest" },
        { id: "model-42", run_id: "run-abc" },
      ],
    );

    expect(result).toEqual({
      state: "success",
      snapshotId: "snapshot-1",
      runId: "run-abc",
      modelId: "model-42",
      reason: "Workflow identities are complete.",
    });
  });

  it("reports partial instead of falling back to the latest model", () => {
    const result = resolveWorkflowResult(
      {
        workflow_id: "workflow-17",
        name: "Pipeline Run",
        market: "US",
        status: "SUCCESS",
        details: { run_id: "run-missing", snapshot_id: "snapshot-1" },
      },
      [{ id: "model-latest", run_id: "run-latest" }],
    );

    expect(result.state).toBe("partial");
    expect(result.modelId).toBeUndefined();
  });

  it("blocks a completed workflow when the backend used a different snapshot", () => {
    const result = resolveWorkflowResult(
      {
        workflow_id: "workflow-17",
        name: "Pipeline Run",
        market: "US",
        status: "SUCCESS",
        details: { run_id: "run-abc", snapshot_id: "snapshot-latest" },
      },
      [{ id: "model-42", run_id: "run-abc" }],
      "snapshot-requested",
    );

    expect(result).toEqual({
      state: "blocked",
      snapshotId: "snapshot-latest",
      runId: "run-abc",
      reason: "Workflow snapshot snapshot-latest does not match requested snapshot snapshot-requested.",
    });
  });

  it("accepts evidence only when its subject identity matches the exact model", () => {
    expect(resolveEvidenceIdentity({
      ok: true,
      bundle: { subject_type: "model", subject_id: "model-42" },
    }, "model-42")).toEqual({
      state: "success",
      evidenceId: "model-42",
      reason: "Evidence identity is bound to model model-42.",
    });

    expect(resolveEvidenceIdentity({
      ok: true,
      bundle: { subject_type: "model", subject_id: "model-latest" },
    }, "model-42").state).toBe("blocked");
  });
});
