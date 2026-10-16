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

export type StateDetail = 'current' | 'degraded_delayed' | 'degraded_blocked' | 'blocked';

export interface StalenessInfo {
  asOf: string | null;
  expectedCutoff: string | null;
  sessionsBehind: number | null;
  stale: boolean;
}

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
  modelVersionId: string;
  status: StrategyOperationalStatus;
  readState?: 'protected' | 'unavailable';
  observationState?: 'current' | 'retained_within_cadence' | 'unavailable';
  evaluationChanged?: boolean | null;
  stateDetail?: StateDetail;
  staleness?: StalenessInfo;
  decisionSchedule?: {
    signalDate: string | null;
    completedThrough: string | null;
    cadenceSessions: number | null;
    sessionsUntilDue: number | null;
    state: 'due' | 'within_cadence' | 'unknown';
    executionPending: boolean;
  };
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

interface RuntimeOperationRow {
  strategy_id?: unknown;
  model_version_id?: unknown;
  snapshot?: unknown;
}

interface RuntimeOperationResult {
  data: RuntimeOperationRow | null;
  error: { message?: string } | null;
}

interface RuntimeOperationFilter {
  eq: (column: string, value: string) => RuntimeOperationFilter;
  maybeSingle: () => Promise<RuntimeOperationResult>;
}

interface RuntimeOperationQuery {
  select: (columns: string) => RuntimeOperationFilter;
}

export interface StrategyOperationsClient {
  from: (table: string) => RuntimeOperationQuery;
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
const STATE_DETAILS = new Set<StateDetail>(['current', 'degraded_delayed', 'degraded_blocked', 'blocked']);

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

export function parseStrategyOperationsSnapshot(value: unknown): StrategyOperationsSnapshot {
  assert(Boolean(value) && typeof value === 'object' && !Array.isArray(value), 'Invalid strategy operations record');
  const record = value as Record<string, unknown>;
  const modelVersionId = record.model_version_id;
  const strategyId = record.strategy_id;
  assert(typeof modelVersionId === 'string' && modelVersionId.length > 0, 'Strategy operations model identity is missing');
  assert(typeof strategyId === 'string' && strategyId.length > 0, `Strategy identity is missing for ${modelVersionId}`);
  assert(STATUS.has(record.status as StrategyOperationalStatus), `Unsupported operations status for ${modelVersionId}`);
  assert(FRESHNESS.has(record.data_freshness as StrategyFreshness), `Unsupported data freshness for ${modelVersionId}`);
  assert(FRESHNESS.has(record.factor_freshness as StrategyFreshness), `Unsupported factor freshness for ${modelVersionId}`);
  assert(typeof record.decision_cadence === 'string' && record.decision_cadence.length > 0, `Missing decision cadence for ${modelVersionId}`);
  assert(typeof record.next_decision_policy === 'string' && record.next_decision_policy.length > 0, `Missing next decision policy for ${modelVersionId}`);
  assert(typeof record.state_label === 'string' && record.state_label.length > 0, `Missing state label for ${modelVersionId}`);
  assert(typeof record.decision_reason === 'string' && record.decision_reason.length > 0, `Missing decision reason for ${modelVersionId}`);
  assert(typeof record.delivery_status === 'string' && record.delivery_status.length > 0, `Missing delivery status for ${modelVersionId}`);
  assert(typeof record.source_label === 'string' && record.source_label.length > 0, `Missing source label for ${modelVersionId}`);
  assert(typeof record.note === 'string' && record.note.length > 0, `Missing operations note for ${modelVersionId}`);
  assert(Array.isArray(record.allocations), `Missing allocations for ${modelVersionId}`);
  assert(Array.isArray(record.factor_evidence), `Missing factor evidence for ${modelVersionId}`);
  assert(Boolean(record.source_identity) && typeof record.source_identity === 'object' && !Array.isArray(record.source_identity), `Missing source identity for ${modelVersionId}`);

  const allocations = record.allocations.map((allocation, index) => {
    assert(Boolean(allocation) && typeof allocation === 'object' && !Array.isArray(allocation), `Invalid allocation ${index} for ${modelVersionId}`);
    const row = allocation as Record<string, unknown>;
    assert(typeof row.asset === 'string' && row.asset.length > 0, `Missing allocation asset for ${modelVersionId}`);
    assert(typeof row.current === 'number' && Number.isFinite(row.current), `Invalid current weight for ${modelVersionId}/${row.asset}`);
    assert(typeof row.target === 'number' && Number.isFinite(row.target), `Invalid target weight for ${modelVersionId}/${row.asset}`);
    assert(typeof row.delta === 'number' && Number.isFinite(row.delta), `Invalid allocation delta for ${modelVersionId}/${row.asset}`);
    return { asset: row.asset, current: row.current, target: row.target, delta: row.delta };
  });

  const factorEvidence = record.factor_evidence.map((row, index) => parseFactorEvidence(row, modelVersionId, index));
  if (record.factor_freshness === 'current') {
    assert(factorEvidence.length > 0, `Current factor freshness requires evidence for ${modelVersionId}`);
  }

  let staleness: StalenessInfo | undefined;
  if (record.staleness && typeof record.staleness === 'object' && !Array.isArray(record.staleness)) {
    const s = record.staleness as Record<string, unknown>;
    staleness = {
      asOf: nullableString(s.as_of),
      expectedCutoff: nullableString(s.expected_cutoff),
      sessionsBehind: typeof s.sessions_behind === 'number' ? s.sessions_behind : null,
      stale: Boolean(s.stale),
    };
  }
  const stateDetail = typeof record.state_detail === 'string' && STATE_DETAILS.has(record.state_detail as StateDetail)
    ? (record.state_detail as StateDetail)
    : undefined;

  const source = record.source_identity as Record<string, unknown>;
  assert(record.evaluation_changed == null || typeof record.evaluation_changed === 'boolean',
    `Invalid evaluation change for ${modelVersionId}`);
  if (record.read_state !== undefined) {
    assert(record.read_state === 'protected', `Invalid public operations read state for ${modelVersionId}`);
    assert(allocations.length === 0 && factorEvidence.length === 0 && record.as_of == null && record.evaluation_changed == null,
      `Protected operations contain private evidence for ${modelVersionId}`);
  }
  if (record.observation_state !== undefined) {
    assert(['current', 'retained_within_cadence', 'unavailable'].includes(String(record.observation_state)),
      `Invalid observation state for ${modelVersionId}`);
  }
  const schedule = record.decision_schedule && typeof record.decision_schedule === 'object'
    ? record.decision_schedule as Record<string, unknown> : null;
  if (record.decision_schedule !== undefined) {
    assert(schedule && !Array.isArray(schedule), `Invalid decision schedule for ${modelVersionId}`);
    assert(['due', 'within_cadence', 'unknown'].includes(String(schedule.state)), `Invalid decision schedule state for ${modelVersionId}`);
    for (const field of ['cadence_sessions', 'sessions_until_due']) {
      const value = schedule[field];
      assert(value === null || typeof value === 'number' && Number.isInteger(value) && value >= (field === 'cadence_sessions' ? 1 : 0), `Invalid decision schedule ${field} for ${modelVersionId}`);
    }
  }
  return {
    strategyId,
    modelVersionId,
    status: record.status as StrategyOperationalStatus,
    readState: record.read_state === 'protected' ? 'protected' : undefined,
    observationState: record.observation_state as StrategyOperationsSnapshot['observationState'],
    evaluationChanged: typeof record.evaluation_changed === 'boolean' ? record.evaluation_changed : null,
    stateDetail,
    staleness,
    decisionSchedule: schedule ? {
      signalDate: nullableString(schedule.signal_date),
      completedThrough: nullableString(schedule.completed_through),
      cadenceSessions: nullableNumber(schedule.cadence_sessions),
      sessionsUntilDue: nullableNumber(schedule.sessions_until_due),
      state: schedule.state === 'due' || schedule.state === 'within_cadence' ? schedule.state : 'unknown',
      executionPending: schedule.execution_pending === true,
    } : undefined,
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

function blocked(run: GovernedRunSummary, message: string, strategyId = ''): StrategyOperationsSnapshot {
  return {
    // Missing publication identity is unknown; a model family is not a stable
    // strategy ID and must never become a writable access-policy resource.
    strategyId,
    modelVersionId: run.modelVersionId,
    status: 'blocked',
    stateDetail: 'blocked',
    staleness: {
      asOf: null,
      expectedCutoff: null,
      sessionsBehind: null,
      stale: true,
    },
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

async function fetchOperations(signal?: AbortSignal): Promise<Map<string, unknown>> {
  const response = await fetch(assetUrl('data/strategy-operations/snapshots.json'), { cache: 'no-store', signal });
  if (!response.ok) throw new Error(`Strategy operations snapshot unavailable (${response.status})`);
  const value = await response.json() as OperationsDocument;
  assert(value.schema_version === '2.2.0', 'Unsupported strategy operations schema');
  assert(value.research_only === true && value.trade_ready === false, 'Invalid strategy operations boundary');
  assert(Array.isArray(value.records), 'Strategy operations records are missing');
  // Ambiguous identities invalidate the document; an identified row's payload
  // is checked independently so its failure cannot hide other valid strategies.
  const identities = value.records.map((row) => {
    assert(Boolean(row) && typeof row === 'object' && !Array.isArray(row), 'Strategy operations identity is missing');
    const record = row as Record<string, unknown>;
    assert(typeof record.model_version_id === 'string' && record.model_version_id.length > 0, 'Strategy operations model identity is missing');
    return { model: record.model_version_id, strategy: nullableString(record.strategy_id), row };
  });
  assert(new Set(identities.map((item) => item.model)).size === identities.length, 'Duplicate strategy operations model identity');
  const stableIds = identities.flatMap((item) => item.strategy ? [item.strategy] : []);
  assert(new Set(stableIds).size === stableIds.length, 'Duplicate stable strategy identity');
  return new Map(identities.map((item) => [item.model, item.row]));
}

export function assertStrategyOperationRun(snapshot: StrategyOperationsSnapshot, run: GovernedRunSummary): void {
  assert(snapshot.modelVersionId === run.modelVersionId, 'Operations model identity mismatch');
  assert(Boolean(run.bundleId) && snapshot.sourceIdentity.formalBundleId === run.bundleId, 'Operations formal bundle identity mismatch');
  assert(Boolean(run.runId) && snapshot.sourceIdentity.formalRunId === run.runId, 'Operations formal run identity mismatch');
  assert(Boolean(run.evidenceCutoff) && snapshot.sourceIdentity.formalEvidenceCutoff === run.evidenceCutoff, 'Operations formal cutoff mismatch');
}

export async function loadRuntimeStrategyOperation(
  client: StrategyOperationsClient,
  strategyId: string,
  modelVersionId: string,
): Promise<StrategyOperationsSnapshot | null> {
  const { data, error } = await client
    .from('strategy_operation_snapshots')
    .select('strategy_id,model_version_id,snapshot')
    .eq('strategy_id', strategyId)
    .eq('model_version_id', modelVersionId)
    .maybeSingle();
  if (error) throw new Error(error.message || 'Runtime strategy operations request failed.');
  if (!data) return null;
  assert(data.strategy_id === strategyId, 'Runtime strategy identity mismatch');
  assert(data.model_version_id === modelVersionId, 'Runtime model identity mismatch');
  const snapshot = parseStrategyOperationsSnapshot(data.snapshot);
  assert(snapshot.strategyId === strategyId, 'Runtime snapshot strategy identity mismatch');
  assert(snapshot.modelVersionId === modelVersionId, 'Runtime snapshot model identity mismatch');
  return snapshot;
}

export async function loadStrategyOperations(runs: GovernedRunSummary[], signal?: AbortSignal): Promise<Map<string, StrategyOperationsSnapshot>> {
  const formalRuns = runs.filter((run) => run.channel === 'formal');
  try {
    const snapshots = await fetchOperations(signal);
    return new Map(formalRuns.map((run) => {
      try {
        assert(snapshots.has(run.modelVersionId), `Strategy operations are missing accepted formal model: ${run.modelVersionId}`);
        const snapshot = parseStrategyOperationsSnapshot(snapshots.get(run.modelVersionId));
        assertStrategyOperationRun(snapshot, run);
        return [run.modelVersionId, snapshot];
      } catch (error) {
        const identity = snapshots.get(run.modelVersionId) as Record<string, unknown> | undefined;
        return [run.modelVersionId, blocked(run, error instanceof Error ? error.message : 'Strategy operations record is unavailable.',
          typeof identity?.strategy_id === 'string' ? identity.strategy_id : '')];
      }
    }));
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

export interface StrategySignalSummary {
  direction: 'hold' | 'increase' | 'reduce' | 'attention' | 'pending';
  badgeLabel: string;
  actionText: string;
  summaryNote: string;
  isAttention: boolean;
  isNew: boolean;
  isHold: boolean;
}

export interface StrategyObservationBrief {
  kind: 'changed' | 'unchanged' | 'retained' | 'attention' | 'access' | 'pending';
  label: string;
  reason: string;
  nextStep: string;
  recovery: 'read' | 'delivery' | 'source' | null;
}

/** Present verified operations; never evaluate rules or infer changes from a position delta. */
export function describeStrategyObservation(snapshot?: StrategyOperationsSnapshot, accessible = true): StrategyObservationBrief {
  if (!accessible || snapshot?.readState === 'protected') {
    return { kind: 'access', label: 'Access required', reason: 'Current observations require strategy access.',
      nextStep: 'Sign in or check access. Formal evidence remains public.', recovery: null };
  }
  if (!snapshot || snapshot.readState === 'unavailable') {
    return { kind: snapshot ? 'attention' : 'pending', label: 'Read unavailable', reason: 'Current observations could not be verified.',
      nextStep: 'Retry reading published records. This does not start a data refresh.', recovery: 'read' };
  }
  if (snapshot.status === 'delivery_failed' || snapshot.deliveryStatus === 'failed') {
    return { kind: 'attention', label: 'Delivery failed', reason: 'A decision is retained, but notification delivery failed.',
      nextStep: 'Inspect the delivery attempt before retrying; the retained decision is not a new signal.', recovery: 'delivery' };
  }
  const summary = summarizeStrategySignal(snapshot);
  if (summary.isAttention) {
    return { kind: 'attention', label: summary.badgeLabel, reason: summary.summaryNote,
      nextStep: snapshot.decisionSchedule?.state === 'due'
        ? 'Evaluation is due. Check input availability and the source run before retrying.'
        : 'Check the observation cutoff and source run. Independent valid results remain available.', recovery: 'source' };
  }
  if (summary.badgeLabel === 'Not due') {
    return { kind: 'retained', label: 'Retained within cadence', reason: snapshot.decisionReason,
      nextStep: `${snapshot.decisionSchedule?.sessionsUntilDue} exchange sessions until evaluation.${snapshot.decisionSchedule?.executionPending ? ' Execution evidence remains pending.' : ''}`, recovery: null };
  }
  if (snapshot.status === 'pipeline_unavailable' || snapshot.status === 'awaiting_observation') {
    return { kind: 'pending', label: 'Awaiting observation', reason: snapshot.decisionReason,
      nextStep: 'Check the source run for the next eligible observation.', recovery: 'source' };
  }
  const nextStep = snapshot.deliveryStatus === 'pending' ? 'Notification delivery is pending.'
    : snapshot.decisionSchedule?.executionPending ? 'Execution evidence remains pending.' : snapshot.nextDecision;
  if (typeof snapshot.evaluationChanged === 'boolean') {
    return { kind: snapshot.evaluationChanged ? 'changed' : 'unchanged',
      label: snapshot.evaluationChanged ? 'Changed at last evaluation' : 'Unchanged at last evaluation',
      reason: snapshot.decisionReason, nextStep, recovery: null };
  }
  return { kind: 'pending', label: 'Change not verified', reason: snapshot.decisionReason,
    nextStep: 'Inspect the retained decision; no change claim is inferred from its target weights.', recovery: null };
}

export function summarizeStrategySignal(snapshot?: StrategyOperationsSnapshot): StrategySignalSummary {
  if (!snapshot) {
    return {
      direction: 'pending',
      badgeLabel: 'Pending',
      actionText: 'Operating status unavailable',
      summaryNote: 'No current record',
      isAttention: false,
      isNew: false,
      isHold: false,
    };
  }

  if (snapshot.readState) {
    const protectedRead = snapshot.readState === 'protected';
    return {
      direction: 'pending', badgeLabel: protectedRead ? 'Access required' : 'Read unavailable',
      actionText: protectedRead ? 'Sign in or check strategy access' : 'Retry current operations',
      summaryNote: protectedRead ? 'Current signals require account access; formal evidence remains public.'
        : 'Current operations could not be verified. This does not establish a strategy failure.',
      isAttention: !protectedRead, isNew: false, isHold: false,
    };
  }

  const blockedObservation = snapshot.status === 'blocked' || snapshot.status === 'delivery_failed'
    || snapshot.dataFreshness === 'blocked' || snapshot.factorFreshness === 'blocked'
    || snapshot.stateDetail === 'blocked' || snapshot.stateDetail === 'degraded_blocked';
  const delayedObservation = snapshot.status === 'stale' || snapshot.staleness?.stale === true
    || snapshot.dataFreshness === 'stale' || snapshot.factorFreshness === 'stale'
    || snapshot.stateDetail === 'degraded_delayed';
  const retained = !blockedObservation && snapshot.observationState === 'retained_within_cadence'
    && snapshot.decisionSchedule?.state === 'within_cadence'
    && (snapshot.decisionSchedule.sessionsUntilDue ?? 0) > 0
    && snapshot.sourceIdentity.formalEvidenceCutoff === snapshot.decisionSchedule.completedThrough;
  if (retained) {
    return {
      direction: 'hold', badgeLabel: 'Not due', actionText: 'Retained target',
      summaryNote: `Target from ${snapshot.decisionSchedule?.signalDate}; observation through ${snapshot.decisionSchedule?.completedThrough}. ${snapshot.decisionSchedule?.sessionsUntilDue} sessions until evaluation.`,
      isAttention: false, isNew: false, isHold: true,
    };
  }
  if (blockedObservation || delayedObservation) {
    return {
      direction: 'attention',
      badgeLabel: blockedObservation ? 'Blocked' : 'Stale',
      actionText: 'Previous signal only',
      summaryNote: `${blockedObservation ? 'Observation blocked' : 'Observation delayed'} · ${snapshot.decisionReason || 'Current signal unavailable'}`,
      isAttention: true,
      isNew: false,
      isHold: false,
    };
  }

  if (snapshot.status === 'pipeline_unavailable' || snapshot.status === 'awaiting_observation') {
    return {
      direction: 'pending',
      badgeLabel: 'Pending',
      actionText: 'Awaiting observation',
      summaryNote: snapshot.decisionReason || 'Pipeline unavailable',
      isAttention: false,
      isNew: false,
      isHold: false,
    };
  }

  const totalDelta = snapshot.allocations.reduce((sum, leg) => sum + leg.delta, 0);
  const maxAbsDelta = snapshot.allocations.reduce((max, leg) => Math.max(max, Math.abs(leg.delta)), 0);

  if (maxAbsDelta < 1e-4 || snapshot.status === 'current_no_change') {
    return {
      direction: 'hold',
      badgeLabel: 'Hold',
      actionText: 'Allocation unchanged',
      summaryNote: snapshot.decisionReason || 'Allocation unchanged',
      isAttention: false,
      isNew: false,
      isHold: true,
    };
  }

  if (Math.abs(totalDelta) < 1e-4) {
    return {
      direction: 'hold',
      badgeLabel: 'Hold',
      actionText: 'Internal rebalance',
      summaryNote: snapshot.decisionReason || 'Internal rebalance',
      isAttention: false,
      isNew: true,
      isHold: true,
    };
  }

  if (totalDelta > 0) {
    return {
      direction: 'increase',
      badgeLabel: 'Increase',
      actionText: 'Target exposure',
      summaryNote: snapshot.decisionReason || 'Increase allocation',
      isAttention: false,
      isNew: true,
      isHold: false,
    };
  }

  return {
    direction: 'reduce',
    badgeLabel: 'Reduce',
    actionText: 'Target exposure',
    summaryNote: snapshot.decisionReason || 'Reduce allocation',
    isAttention: false,
    isNew: true,
    isHold: false,
  };
}
