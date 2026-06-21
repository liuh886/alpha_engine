export type ReleaseOutcome =
  | "loading"
  | "empty"
  | "partial"
  | "stale"
  | "failed"
  | "blocked"
  | "success";

export interface ReleaseIdentity {
  jobId?: string;
  snapshotId?: string;
  workflowId?: string;
  runId?: string;
  modelId?: string;
  evidenceId?: string;
}

export interface OutcomeSummary {
  state: ReleaseOutcome;
  reason: string;
}

const IDENTITY_KEYS: Array<[keyof ReleaseIdentity, string]> = [
  ["jobId", "job_id"],
  ["snapshotId", "snapshot_id"],
  ["workflowId", "workflow_id"],
  ["runId", "run_id"],
  ["modelId", "model_id"],
  ["evidenceId", "evidence_id"],
];

export function parseReleaseIdentity(search: string): ReleaseIdentity {
  const params = new URLSearchParams(search);
  const identity: ReleaseIdentity = {};
  for (const [field, key] of IDENTITY_KEYS) {
    const value = params.get(key)?.trim();
    if (value) identity[field] = value;
  }
  return identity;
}

export function releaseSearch(
  changes: Partial<Record<keyof ReleaseIdentity, string | null | undefined>>,
  currentSearch = "",
): string {
  const params = new URLSearchParams(currentSearch);
  for (const [field, key] of IDENTITY_KEYS) {
    if (!(field in changes)) continue;
    const value = changes[field]?.trim();
    if (value) params.set(key, value);
    else params.delete(key);
  }
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

interface DataStatusLike {
  latest_snapshot_id?: unknown;
  quality_status?: unknown;
  quality_warnings?: unknown;
}

export function classifyDataOutcome(status: DataStatusLike | null): OutcomeSummary {
  if (!status?.latest_snapshot_id) {
    return { state: "empty", reason: "No published snapshot is available." };
  }

  const quality = String(status.quality_status || "unknown").toLowerCase();
  if (["failed", "invalid", "rejected"].includes(quality)) {
    return { state: "blocked", reason: "Snapshot quality checks block training." };
  }
  if (["stale", "outdated"].includes(quality)) {
    return { state: "stale", reason: "Snapshot exists but is stale." };
  }
  if (quality !== "ok" || (Array.isArray(status.quality_warnings) && status.quality_warnings.length > 0)) {
    return { state: "partial", reason: "Snapshot has incomplete or warning-level quality evidence." };
  }
  return { state: "success", reason: "Snapshot is approved for training." };
}

export interface WorkflowStatusLike {
  workflow_id: string;
  name: string;
  market: string;
  status: string;
  details?: Record<string, unknown> | null;
  error?: string;
}

interface ModelIdentityLike {
  id: string;
  run_id?: string;
}

export interface WorkflowResolution extends OutcomeSummary {
  snapshotId?: string;
  runId?: string;
  modelId?: string;
}

export function resolveWorkflowResult(
  workflow: WorkflowStatusLike,
  models: ModelIdentityLike[],
  expectedSnapshotId?: string,
): WorkflowResolution {
  const details = workflow.details ?? {};
  const snapshotId = typeof details.snapshot_id === "string" ? details.snapshot_id : undefined;
  const runId = typeof details.run_id === "string" ? details.run_id : undefined;

  if (expectedSnapshotId && snapshotId && snapshotId !== expectedSnapshotId) {
    return {
      state: "blocked",
      snapshotId,
      runId,
      reason: `Workflow snapshot ${snapshotId} does not match requested snapshot ${expectedSnapshotId}.`,
    };
  }

  if (!snapshotId || !runId) {
    return {
      state: "partial",
      snapshotId,
      runId,
      reason: "Workflow succeeded without complete snapshot and run identity.",
    };
  }

  const model = models.find((candidate) => candidate.run_id === runId);
  if (!model) {
    return {
      state: "partial",
      snapshotId,
      runId,
      reason: `No registry model is bound to run ${runId}.`,
    };
  }

  return {
    state: "success",
    snapshotId,
    runId,
    modelId: model.id,
    reason: "Workflow identities are complete.",
  };
}

export interface EvidenceResolution extends OutcomeSummary {
  evidenceId?: string;
}

export function resolveEvidenceIdentity(
  response: { ok?: boolean; bundle?: Record<string, unknown> } | null,
  expectedModelId: string,
): EvidenceResolution {
  const bundle = response?.bundle;
  const subjectType = typeof bundle?.subject_type === "string" ? bundle.subject_type : undefined;
  const subjectId = typeof bundle?.subject_id === "string" ? bundle.subject_id : undefined;

  if (!subjectType || !subjectId) {
    return { state: "partial", reason: "Model evidence is missing an explicit subject identity." };
  }
  if (subjectType !== "model" || subjectId !== expectedModelId) {
    return {
      state: "blocked",
      evidenceId: subjectId,
      reason: `Evidence subject ${subjectType}/${subjectId} does not match model ${expectedModelId}.`,
    };
  }
  return {
    state: "success",
    evidenceId: subjectId,
    reason: `Evidence identity is bound to model ${expectedModelId}.`,
  };
}
