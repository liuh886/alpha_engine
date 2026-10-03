import { describe, expect, it } from 'vitest';
import { parseStrategyOperationsSnapshot } from './strategy-operations';

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
