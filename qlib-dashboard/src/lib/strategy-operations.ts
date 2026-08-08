import type { GovernedRunSummary } from './governed-run';
import { assetUrl } from './runtime-capabilities';

export type StrategyOperationalStatus =
  | 'pipeline_unavailable'
  | 'awaiting_observation'
  | 'current_no_change'
  | 'target_pending_execution'
  | 'execution_observed'
  | 'stale'
  | 'blocked'
  | 'delivery_failed';

export type StrategyFreshness = 'current' | 'stale' | 'blocked' | 'unknown';
export type FactorEffect = 'support' | 'veto' | 'neutral';

export interface StrategyAllocationLeg {
  asset: string;
  current: number;
  target: number;
  delta: number;
}

export interface StrategyFactorEvidence {
  factorId: string;
  factorVersion: string;
  implementationHash: string;
  displayName: string;
  informationFamily: string;
  value: number | string | boolean;
  reference: unknown;
  state: string;
  effect: FactorEffect;
  reasonCode: string;
  observedAt: string;
}

export interface StrategySourceIdentity {
  formalBundleId: string | null;
  formalRunId: string | null;
  formalEvidenceCutoff: string | null;
  ledgerFingerprint: string | null;
  signalSha256: string | null;
  factorCatalogImplementationHash: string | null;
  workflowRunId: string | null;
  commitSha: string | null;
  githubIssueNumber: number | null;
}

export interface StrategyOperationsSnapshot {
  strategyId: string;
  status: StrategyOperationalStatus;
  asOf: string | null;
  latestCompletedSession: string | null;
  decisionCadence: string;
  nextDecision: string;
  stateLabel: string;
  decisionReason: string;
  allocations: StrategyAllocationLeg[];
  turnover: number | null;
  estimatedCost: number | null;
  dataFreshness: StrategyFreshness;
  factorFreshness: StrategyFreshness;
  deliveryStatus: string;
  sourceLabel: string;
  sourceHref: string | null;
  note: string;
  factorEvidence: StrategyFactorEvidence[];
  sourceIdentity: StrategySourceIdentity;
}

interface OperationsDocument {
  schema_version?: unknown;
  research_only?: unknown;
  trade_ready?: unknown;
  records?: unknown;
}

const STATUS = new Set<StrategyOperationalStatus>([
  'pipeline_unavailable',
  'awaiting_observation',
  'current_no_change',
  'target_pending_execution',
  'execution_observed',
  'stale',
  'blocked',
  'delivery_failed',
]);
const FRESHNESS = new Set<StrategyFreshness>(['current', 'stale', 'blocked', 'unknown']);
const EFFECT = new Set<FactorEffect>(['support', 'veto', 'neutral']);

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function parseFactorEvidence(value: unknown, id: string, index: number): StrategyFactorEvidence {
  assert(Boolean(value) && typeof value === 'object' && !Array.isArray(value), `Invalid factor evidence ${index} for ${id}`);
  const row = value as Record<string, unknown>;
  assert(typeof row.factor_id === 'string' && row.factor_id.length > 0, `Missing factor id for ${id}`);
  assert(typeof row.factor_version === 'string' && row.factor_version.length > 0, `Missing factor version for ${id}/${row.factor_id}`);
  assert(typeof row.implementation_hash === 'string' && /^[a-f0-9]{64}$/.test(row.implementation_hash), `Invalid factor implementation hash for ${id}/${row.factor_id}`);
  assert(typeof row.display_name === 'string' && row.display_name.length > 0, `Missing factor display name for ${id}/${row.factor_id}`);
  assert(typeof row.information_family === 'string' && row.information_family.length > 0, `Missing factor family for ${id}/${row.factor_id}`);
  assert(typeof row.state === 'string' && row.state.length > 0, `Missing factor state for ${id}/${row.factor_id}`);
  assert(EFFECT.has(row.effect as FactorEffect), `Invalid factor effect for ${id}/${row.factor_id}`);
  assert(typeof row.reason_code === 'string' && row.reason_code.length > 0, `Missing factor reason code for ${id}/${row.factor_id}`);
  assert(typeof row.observed_at === 'string' && row.observed_at.length > 0, `Missing factor observation date for ${id}/${row.factor_id}`);
  const observedValue = row.value;
  assert(
    (typeof observedValue === 'number' && Number.isFinite(observedValue)) || typeof observedValue === 'string' || typeof observedValue === 'boolean',
    `Invalid factor value for ${id}/${row.factor_id}`,
  );
  return {
    factorId: row.factor_id,
    factorVersion: row.factor_version,
    implementationHash: row.implementation_hash,
    displayName: row.display_name,
    informationFamily: row.information_family,
    value: observedValue,
    reference: row.reference,
    state: row.state,
    effect: row.effect as FactorEffect,
    reasonCode: row.reason_code,
    observedAt: row.observed_at,
  };
}

function parseSnapshot(value: unknown): StrategyOperationsSnapshot {
  assert(Boolean(value) && typeof value === 'object' && !Array.isArray(value), 'Invalid strategy operations record');
  const record = value as Record<string, unknown>;
  const id = record.model_version_id;
  assert(typeof id === 'string' && id.length > 0, 'Strategy operations model identity is missing');
  assert(STATUS.has(record.status as StrategyOperationalStatus), `Unsupported operations status for ${id}`);
  assert(FRESHNESS.has(record.data_freshness as StrategyFreshness), `Unsupported data freshness for ${id}`);
  assert(FRESHNESS.has(record.factor_freshness as StrategyFreshness), `Unsupported factor freshness for ${id}`);
  assert(typeof record.decision_cadence === 'string' && record.decision_cadence.length > 0, `Missing decision cadence for ${id}`);
  assert(typeof record.next_decision_policy === 'string' && record.next_decision_policy.length > 0, `Missing next decision policy for ${id}`);
  assert(typeof record.state_label === 'string' && record.state_label.length > 0, `Missing state label for ${id}`);
  assert(typeof record.decision_reason === 'string' && record.decision_reason.length > 0, `Missing decision reason for ${id}`);
  assert(typeof record.delivery_status === 'string' && record.delivery_status.length > 0, `Missing delivery status for ${id}`);
  assert(typeof record.source_label === 'string' && record.source_label.length > 0, `Missing source label for ${id}`);
  assert(typeof record.note === 'string' && record.note.length > 0, `Missing operations note for ${id}`);
  assert(Array.isArray(record.allocations), `Missing allocations for ${id}`);
  assert(Array.isArray(record.factor_evidence), `Missing factor evidence for ${id}`);
  assert(Boolean(record.source_identity) && typeof record.source_identity === 'object' && !Array.isArray(record.source_identity), `Missing source identity for ${id}`);

  const allocations = record.allocations.map((value, index) => {
    assert(Boolean(value) && typeof value === 'object' && !Array.isArray(value), `Invalid allocation ${index} for ${id}`);
    const row = value as Record<string, unknown>;
    assert(typeof row.asset === 'string' && row.asset.length > 0, `Missing allocation asset for ${id}`);
    assert(typeof row.current === 'number' && Number.isFinite(row.current), `Invalid current weight for ${id}/${row.asset}`);
    assert(typeof row.target === 'number' && Number.isFinite(row.target), `Invalid target weight for ${id}/${row.asset}`);
    assert(typeof row.delta === 'number' && Number.isFinite(row.delta), `Invalid allocation delta for ${id}/${row.asset}`);
    return { asset: row.asset, current: row.current, target: row.target, delta: row.delta };
  });

  const factorEvidence = record.factor_evidence.map((row, index) => parseFactorEvidence(row, id, index));
  if (record.factor_freshness === 'current') {
    assert(factorEvidence.length > 0, `Current factor freshness requires evidence for ${id}`);
  }

  const source = record.source_identity as Record<string, unknown>;
  return {
    strategyId: id,
    status: record.status as StrategyOperationalStatus,
    asOf: nullableString(record.as_of),
    latestCompletedSession: nullableString(record.latest_completed_session),
    decisionCadence: record.decision_cadence,
    nextDecision: record.next_decision_policy,
    stateLabel: record.state_label,
    decisionReason: record.decision_reason,
    allocations,
    turnover: nullableNumber(record.turnover),
    estimatedCost: nullableNumber(record.estimated_cost),
    dataFreshness: record.data_freshness as StrategyFreshness,
    factorFreshness: record.factor_freshness as StrategyFreshness,
    deliveryStatus: record.delivery_status,
    sourceLabel: record.source_label,
    sourceHref: nullableString(record.source_href),
    note: record.note,
    factorEvidence,
    sourceIdentity: {
      formalBundleId: nullableString(source.formal_bundle_id),
      formalRunId: nullableString(source.formal_run_id),
      formalEvidenceCutoff: nullableString(source.formal_evidence_cutoff),
      ledgerFingerprint: nullableString(source.ledger_fingerprint),
      signalSha256: nullableString(source.signal_sha256),
      factorCatalogImplementationHash: nullableString(source.factor_catalog_implementation_hash),
      workflowRunId: nullableString(source.workflow_run_id),
      commitSha: nullableString(source.commit_sha),
      githubIssueNumber: typeof source.github_issue_number === 'number' && Number.isInteger(source.github_issue_number)
        ? source.github_issue_number
        : null,
    },
  };
}

function blocked(run: GovernedRunSummary, message: string): StrategyOperationsSnapshot {
  return {
    strategyId: run.modelVersionId,
    status: 'blocked',
    asOf: null,
    latestCompletedSession: run.evidenceCutoff || null,
    decisionCadence: 'Operations read model unavailable',
    nextDecision: 'Restore the governed operations publication before using current-state claims.',
    stateLabel: 'Operating data blocked',
    decisionReason: message,
    allocations: [],
    turnover: null,
    estimatedCost: null,
    dataFreshness: 'blocked',
    factorFreshness: 'blocked',
    deliveryStatus: 'not available',
    sourceLabel: 'Governed operations snapshot',
    sourceHref: null,
    note: message,
    factorEvidence: [],
    sourceIdentity: {
      formalBundleId: null,
      formalRunId: run.runId,
      formalEvidenceCutoff: run.evidenceCutoff || null,
      ledgerFingerprint: null,
      signalSha256: null,
      factorCatalogImplementationHash: null,
      workflowRunId: null,
      commitSha: null,
      githubIssueNumber: null,
    },
  };
}

async function fetchOperations(): Promise<Map<string, StrategyOperationsSnapshot>> {
  const response = await fetch(assetUrl('data/strategy-operations/snapshots.json'), { cache: 'no-store' });
  if (!response.ok) throw new Error(`Strategy operations snapshot unavailable (${response.status})`);
  const value = await response.json() as OperationsDocument;
  assert(value.schema_version === '2.0.0', 'Unsupported strategy operations schema');
  assert(value.research_only === true && value.trade_ready === false, 'Invalid strategy operations boundary');
  assert(Array.isArray(value.records), 'Strategy operations records are missing');
  const snapshots = value.records.map(parseSnapshot);
  assert(new Set(snapshots.map((snapshot) => snapshot.strategyId)).size === snapshots.length, 'Duplicate strategy operations model identity');
  return new Map(snapshots.map((snapshot) => [snapshot.strategyId, snapshot]));
}

export async function loadStrategyOperations(runs: GovernedRunSummary[]): Promise<Map<string, StrategyOperationsSnapshot>> {
  const formalRuns = runs.filter((run) => run.channel === 'formal');
  try {
    const snapshots = await fetchOperations();
    const formalIds = formalRuns.map((run) => run.modelVersionId).sort();
    const operationIds = Array.from(snapshots.keys()).sort();
    assert(JSON.stringify(formalIds) === JSON.stringify(operationIds), 'Strategy operations model set does not match the accepted formal catalog');
    return snapshots;
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Strategy operations snapshot is unavailable.';
    return new Map(formalRuns.map((run) => [run.modelVersionId, blocked(run, message)]));
  }
}

export const STRATEGY_STATUS_LABEL: Record<StrategyOperationalStatus, string> = {
  pipeline_unavailable: 'Signal unavailable',
  awaiting_observation: 'Awaiting observation',
  current_no_change: 'Current · no change',
  target_pending_execution: 'New target',
  execution_observed: 'Execution observed',
  stale: 'Stale data',
  blocked: 'Operating data blocked',
  delivery_failed: 'Delivery failed',
};
