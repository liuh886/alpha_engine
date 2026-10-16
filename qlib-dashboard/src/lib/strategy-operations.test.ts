import { afterEach, describe, expect, it, vi } from 'vitest';
import { assertStrategyOperationRun, describeStrategyObservation, loadStrategyOperations, parseStrategyOperationsSnapshot, summarizeStrategySignal } from './strategy-operations';
import type { GovernedRunSummary } from './governed-run';

const record = {
  model_version_id: 'cn_x1_2', strategy_id: 'cn_x', status: 'current_no_change',
  data_freshness: 'stale', factor_freshness: 'stale', decision_cadence: 'Every 10 sessions',
  next_decision_policy: 'Next eligible open', state_label: 'Risk-off', decision_reason: 'Retained target',
  delivery_status: 'not_required', source_label: 'Governed ledger', note: 'Daily observation is stale',
  allocations: [], factor_evidence: [], source_identity: {},
  decision_schedule: { signal_date: '2026-09-17', completed_through: '2026-09-30',
    cadence_sessions: 10, sessions_until_due: 2, state: 'within_cadence', execution_pending: false },
};

describe('evaluation timing', () => {
  it('keeps stale daily data distinct from an evaluation that is not due', () => {
    const parsed = parseStrategyOperationsSnapshot(record);
    expect(parsed.dataFreshness).toBe('stale');
    expect(parsed.decisionSchedule?.state).toBe('within_cadence');
    expect(parsed.decisionSchedule?.sessionsUntilDue).toBe(2);
  });
  it('rejects malformed timing instead of presenting a current assessment', () => {
    expect(() => parseStrategyOperationsSnapshot({ ...record,
      decision_schedule: { ...record.decision_schedule, sessions_until_due: -1 },
    })).toThrow('Invalid decision schedule');
  });
});

describe('retained observation health', () => {
  it('uses the sealed change flag rather than a still pending target', () => {
    const snapshot = parseStrategyOperationsSnapshot({ ...record, status: 'target_pending_execution',
      data_freshness: 'current', factor_freshness: 'unknown', evaluation_changed: false });
    expect(describeStrategyObservation(snapshot)).toMatchObject({ kind: 'unchanged' });
    expect(describeStrategyObservation({ ...snapshot, evaluationChanged: null })).toMatchObject({ kind: 'pending' });
    expect(describeStrategyObservation({ ...snapshot, evaluationChanged: true })).toMatchObject({ kind: 'changed' });
    expect(describeStrategyObservation({ ...snapshot, dataFreshness: 'stale' })).toMatchObject({ kind: 'attention' });
  });

  it('does not expose a private decision or change flag without access', () => {
    const snapshot = parseStrategyOperationsSnapshot({ ...record, decision_reason: 'PRIVATE reason', evaluation_changed: true });
    expect(JSON.stringify(describeStrategyObservation(snapshot, false))).not.toContain('PRIVATE');
    expect(describeStrategyObservation(snapshot, false).kind).toBe('access');
    expect(() => parseStrategyOperationsSnapshot({ ...record, read_state: 'protected', evaluation_changed: true }))
      .toThrow('Protected operations contain private evidence');
  });

  it('shows verified retention without relabeling old factors as fresh', () => {
    const snapshot = parseStrategyOperationsSnapshot({ ...record, observation_state: 'retained_within_cadence',
      source_identity: { formal_evidence_cutoff: record.decision_schedule.completed_through } });
    expect(summarizeStrategySignal(snapshot)).toMatchObject({ badgeLabel: 'Not due', isAttention: false, isNew: false });
    expect(snapshot.factorFreshness).toBe('stale');
    expect(summarizeStrategySignal({ ...snapshot, sourceIdentity: { ...snapshot.sourceIdentity,
      formalEvidenceCutoff: '2026-09-29' } }).isAttention).toBe(true);
  });

  it('distinguishes restricted reads and read failures from a strategy blocker', () => {
    const snapshot = parseStrategyOperationsSnapshot({ ...record, status: 'blocked', read_state: 'protected' });
    expect(summarizeStrategySignal(snapshot)).toMatchObject({ badgeLabel: 'Access required', isAttention: false });
    expect(summarizeStrategySignal({ ...snapshot, readState: 'unavailable' })).toMatchObject({ badgeLabel: 'Read unavailable', isAttention: true });
    expect(summarizeStrategySignal({ ...snapshot, readState: undefined })).toMatchObject({ badgeLabel: 'Blocked', isAttention: true });
  });

  it('requires attention for stale observations even while the decision is within cadence', () => {
    const snapshot = parseStrategyOperationsSnapshot(record);
    expect(summarizeStrategySignal(snapshot)).toMatchObject({ badgeLabel: 'Stale', isAttention: true, isNew: false });
    expect(snapshot.decisionSchedule).toMatchObject({ state: 'within_cadence', sessionsUntilDue: 2 });
  });

  it.each([
    { state_detail: 'degraded_delayed' }, { staleness: { stale: true } },
    { data_freshness: 'stale' }, { factor_freshness: 'stale' },
    { state_detail: 'degraded_blocked' }, { data_freshness: 'blocked' },
  ])('uses observation health independently of decision status: %j', (health) => {
    const snapshot = parseStrategyOperationsSnapshot({ ...record, data_freshness: 'current', factor_freshness: 'unknown', ...health });
    expect(summarizeStrategySignal(snapshot).isAttention).toBe(true);
  });

  it('keeps a current observation healthy when evaluation is simply due', () => {
    const snapshot = parseStrategyOperationsSnapshot({ ...record, data_freshness: 'current', factor_freshness: 'unknown',
      decision_schedule: { ...record.decision_schedule, state: 'due', sessions_until_due: 0 } });
    expect(summarizeStrategySignal(snapshot)).toMatchObject({ badgeLabel: 'Hold', isAttention: false });
  });
});

describe('operations publication reader', () => {
  const run = { channel: 'formal', modelVersionId: 'cn_x1_2', modelFamilyId: 'cn_ranker', runId: 'formal-run',
    bundleId: 'a'.repeat(64), evidenceCutoff: '2026-09-30' } as GovernedRunSummary;
  const published = { ...record, strategy_id: 'cn_x', source_identity: {
    formal_bundle_id: run.bundleId, formal_run_id: run.runId, formal_evidence_cutoff: run.evidenceCutoff,
  } };
  const otherRun = { ...run, modelVersionId: 'us_x1_3', modelFamilyId: 'us_ranker', runId: 'other-run' };
  const other = { ...published, model_version_id: otherRun.modelVersionId, strategy_id: 'us_x',
    source_identity: { ...published.source_identity, formal_run_id: otherRun.runId } };
  function serve(records: unknown[], envelope = {}) {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      schema_version: '2.2.0', research_only: true, trade_ready: false, records, ...envelope,
    }) }));
  }
  afterEach(() => vi.unstubAllGlobals());

  it.each(['missing', 'malformed', 'mismatched', 'missing strategy', 'empty strategy'])('scopes %s row failure to that strategy', async (failure) => {
    const rows = failure === 'missing' ? [published] : [published, failure === 'malformed'
      ? { ...other, allocations: null } : failure === 'missing strategy' ? { ...other, strategy_id: undefined }
      : failure === 'empty strategy' ? { ...other, strategy_id: '' }
      : { ...other, source_identity: { ...other.source_identity, formal_run_id: 'old-run' } }];
    serve(rows);
    const snapshots = await loadStrategyOperations([run, otherRun]);
    expect(snapshots.get(run.modelVersionId)?.status).toBe('current_no_change');
    expect(snapshots.get(otherRun.modelVersionId)).toMatchObject({ status: 'blocked', strategyId: failure.includes('strategy') || failure === 'missing' ? '' : 'us_x', allocations: [] });
  });

  it.each([
    { formal_bundle_id: 'b'.repeat(64) }, { formal_run_id: 'old-run' },
    { formal_evidence_cutoff: '2026-09-29' }, { formal_bundle_id: null },
  ])('rejects different or absent formal identity: %j', async (identity) => {
    const snapshot = { ...published, source_identity: { ...published.source_identity, ...identity } };
    expect(() => assertStrategyOperationRun(parseStrategyOperationsSnapshot(snapshot), run)).toThrow();
    serve([snapshot]);
    expect((await loadStrategyOperations([run])).get(run.modelVersionId)?.status).toBe('blocked');
  });

  it.each(['duplicate model', 'duplicate strategy', 'boundary', 'schema'])('rejects ambiguous or invalid documents: %s', async (failure) => {
    serve(failure === 'duplicate model' ? [published, published] : failure === 'duplicate strategy'
      ? [published, { ...other, strategy_id: published.strategy_id }] : [published, other],
    failure === 'boundary' ? { trade_ready: true } : failure === 'schema' ? { schema_version: 'bad' } : {});
    const snapshots = await loadStrategyOperations([run, otherRun]);
    expect([...snapshots.values()].every((snapshot) => snapshot.status === 'blocked')).toBe(true);
  });
});
