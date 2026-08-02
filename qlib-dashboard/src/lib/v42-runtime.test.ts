import { describe, expect, it } from 'vitest';
import {
  buildRuntimeIndex,
  decodeMachineMarker,
  type GitHubIssueRecord,
  type V42EventRecord,
  type V42MonthlySummary,
} from './v42-runtime';

function encodeMarker(prefix: string, payload: object): string {
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  const encoded = btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  return `<!-- ${prefix}:${encoded} -->`;
}

function eventRecord(overrides: Partial<V42EventRecord> = {}): V42EventRecord {
  return {
    schema_version: '1.0',
    event_id: 'event-1',
    event_type: 'state_change',
    research_only: true,
    trade_ready: false,
    actionable: true,
    status: 'awaiting_next_open',
    signal_date: '2026-07-31',
    latest_data_date_at_creation: '2026-07-31',
    data_freshness_ok: true,
    execution_time: 'next_session_open',
    fingerprint: 'fingerprint',
    transition_type: 'open_risk_bridge',
    decision_reason: 'enter_qqq_early_repair_vix_easing',
    current_state: 0,
    target_state: 1,
    current_weights: { QQQI: 1, QQQ: 0, TQQQ: 0 },
    target_weights: { QQQI: 0.5, QQQ: 0.5, TQQQ: 0 },
    turnover_units: 1,
    estimated_transaction_cost: 0.001,
    signal_close_features: { vix_close: 15.99 },
    recovery_precursor_boolean: false,
    outcome_horizons_sessions: [1, 2, 3, 5, 10, 20, 40],
    ...overrides,
  };
}

function issue(number: number, body: string): GitHubIssueRecord {
  return {
    number,
    title: `Issue ${number}`,
    body,
    state: 'open',
    html_url: `https://github.com/liuh886/alpha_engine/issues/${number}`,
    updated_at: '2026-08-02T00:00:00Z',
  };
}

describe('v4.2 runtime ledger parser', () => {
  it('decodes base64-url machine markers without scraping prose', () => {
    const payload = { status: 'awaiting_next_open', note: '研究证据' };
    const marker = encodeMarker('prospective-evidence-record', payload);

    expect(decodeMachineMarker(marker, 'prospective-evidence-record')).toEqual(payload);
    expect(decodeMachineMarker('plain issue prose', 'prospective-evidence-record')).toBeNull();
    expect(decodeMachineMarker('<!-- prospective-evidence-record:not-json -->', 'prospective-evidence-record')).toBeNull();
  });

  it('selects the latest state change separately from a shadow precursor', () => {
    const older = eventRecord({ event_id: 'older', signal_date: '2026-07-01' });
    const latest = eventRecord({ event_id: 'latest', signal_date: '2026-07-31' });
    const precursor = eventRecord({
      event_id: 'precursor',
      event_type: 'recovery_precursor',
      actionable: false,
      signal_date: '2026-08-01',
    });

    const index = buildRuntimeIndex([
      issue(10, encodeMarker('prospective-evidence-record', older)),
      issue(11, encodeMarker('prospective-evidence-record', latest)),
      issue(12, encodeMarker('prospective-evidence-record', precursor)),
    ]);

    expect(index.latestStateChange?.record.event_id).toBe('latest');
    expect(index.latestPrecursor?.record.event_id).toBe('precursor');
  });

  it('retains the newest monthly accumulation summary', () => {
    const july: V42MonthlySummary = {
      schema_version: '1.0',
      month: '2026-07',
      research_only: true,
      trade_ready: false,
      event_count: 1,
      state_change_event_count: 1,
      recovery_precursor_event_count: 0,
      unresolved_40_session_count: 1,
      completed_horizon_counts: { '1': 0 },
      model_change_authorized: false,
    };
    const august = { ...july, month: '2026-08', event_count: 2 };

    const index = buildRuntimeIndex([
      issue(20, encodeMarker('prospective-evidence-month', july)),
      issue(21, encodeMarker('prospective-evidence-month', august)),
    ]);

    expect(index.latestMonthlySummary?.summary.month).toBe('2026-08');
    expect(index.latestMonthlySummary?.summary.event_count).toBe(2);
  });

  it('rejects records that weaken the research boundary', () => {
    const invalid = {
      ...eventRecord(),
      research_only: false,
      trade_ready: true,
    };

    const index = buildRuntimeIndex([
      issue(30, encodeMarker('prospective-evidence-record', invalid)),
    ]);

    expect(index.latestStateChange).toBeNull();
  });
});
