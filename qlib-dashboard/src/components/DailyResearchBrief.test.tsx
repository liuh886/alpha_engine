import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DailyResearchBrief } from './DailyResearchBrief';
import { useAccessControl } from '@/hooks/useAccessControl';
import { parseStrategyOperationsSnapshot } from '@/lib/strategy-operations';
import type { GovernedRunSummary } from '@/lib/governed-run';

vi.mock('@/hooks/useAccessControl', () => ({ useAccessControl: vi.fn() }));
const run = { key: 'qqq', title: 'QQQR v4.3', modelVersionId: 'qqq', market: 'us', evidenceCutoff: '2026-09-30' } as GovernedRunSummary;
const record = { model_version_id: 'qqq', strategy_id: 'qqq_rotation', status: 'current_no_change',
  as_of: '2026-09-30', latest_completed_session: '2026-09-30', evaluation_changed: true,
  data_freshness: 'current', factor_freshness: 'unknown', decision_cadence: 'Every completed session',
  next_decision_policy: 'Next completed session', state_label: 'Transition', decision_reason: 'Volatility eased',
  delivery_status: 'sent', source_label: 'Verified ledger', note: 'Research observation',
  allocations: [], factor_evidence: [], source_identity: { formal_evidence_cutoff: '2026-09-30' } };
const reload = vi.fn();
const openAccount = vi.fn();

describe('DailyResearchBrief', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useAccessControl).mockReturnValue({ policyLoading: false, requiredTier: () => 'public',
      canAccess: () => true, openAccount } as unknown as ReturnType<typeof useAccessControl>);
  });

  it('keeps a fresh change, retained periodic target and due stale observation distinct', () => {
    const periodic = { ...run, key: 'us', title: 'US ranker', modelVersionId: 'us' };
    const delayed = { ...run, key: 'cn', title: 'CN ranker', modelVersionId: 'cn', market: 'cn' };
    const snapshots = new Map([
      ['qqq', parseStrategyOperationsSnapshot(record)],
      ['us', parseStrategyOperationsSnapshot({ ...record, model_version_id: 'us', strategy_id: 'us_x',
        as_of: '2026-09-17', latest_completed_session: '2026-09-17', data_freshness: 'stale', factor_freshness: 'stale',
        observation_state: 'retained_within_cadence', decision_reason: 'Retained periodic target',
        decision_schedule: { signal_date: '2026-09-17', completed_through: '2026-09-30',
          cadence_sessions: 10, sessions_until_due: 2, state: 'within_cadence', execution_pending: true } })],
      ['cn', parseStrategyOperationsSnapshot({ ...record, model_version_id: 'cn', strategy_id: 'cn_x',
        data_freshness: 'stale', decision_reason: 'Source observation delayed',
        decision_schedule: { cadence_sessions: 10, sessions_until_due: 0, state: 'due', execution_pending: false } })],
    ]);
    render(<MemoryRouter><DailyResearchBrief runs={[run, periodic, delayed]} snapshots={snapshots} loading={false} reload={reload} /></MemoryRouter>);
    expect(screen.getByText('1 changed · 0 unchanged · 1 retained · 1 need attention · 0 require access · 0 awaiting verification')).toBeInTheDocument();
    const retained = screen.getByRole('article', { name: 'US ranker daily observation' });
    expect(within(retained).getByText(/Observed 2026-09-17 · target dated 2026-09-17/)).toBeInTheDocument();
    expect(within(retained).getByText(/Execution evidence remains pending/)).toBeInTheDocument();
    const stale = screen.getByRole('article', { name: 'CN ranker daily observation' });
    expect(within(stale).getByText(/Evaluation is due/)).toBeInTheDocument();
    fireEvent.click(within(stale).getByText('Recovery steps'));
    expect(within(stale).getByRole('link', { name: 'Open data refresh workflow' })).toHaveAttribute('href', expect.stringContaining('formal-backtest-refresh.yml'));
  });

  it('hides current reasons, dates and change claims when strategy access is restricted', () => {
    vi.mocked(useAccessControl).mockReturnValue({ policyLoading: false, requiredTier: () => 'pro',
      canAccess: () => false, openAccount } as unknown as ReturnType<typeof useAccessControl>);
    const privateSnapshot = parseStrategyOperationsSnapshot({ ...record, as_of: '2026-10-15',
      latest_completed_session: '2026-10-15', decision_reason: 'PRIVATE decision' });
    render(<MemoryRouter><DailyResearchBrief runs={[run]} snapshots={new Map([['qqq', privateSnapshot]])} loading={false} reload={reload} /></MemoryRouter>);
    expect(screen.queryByText(/PRIVATE/)).not.toBeInTheDocument();
    expect(screen.queryByText(/2026-10-15/)).not.toBeInTheDocument();
    expect(screen.getByText(/0 changed.*1 require access/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Check strategy access' }));
    expect(openAccount).toHaveBeenCalledOnce();
  });

  it('offers read retry separately from a failed notification recovery', () => {
    const other = { ...run, key: 'delivery', title: 'Delivery example', modelVersionId: 'delivery' };
    const snapshots = new Map([
      ['qqq', { ...parseStrategyOperationsSnapshot(record), readState: 'unavailable' as const }],
      ['delivery', parseStrategyOperationsSnapshot({ ...record, model_version_id: 'delivery', delivery_status: 'failed', status: 'delivery_failed' })],
    ]);
    render(<MemoryRouter><DailyResearchBrief runs={[run, other]} snapshots={snapshots} loading={false} reload={reload} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Retry reading observations' }));
    expect(reload).toHaveBeenCalledOnce();
    expect(screen.getByRole('link', { name: 'Open delivery workflow' })).toHaveAttribute('href', expect.stringContaining('strategy-signal-delivery-outbox.yml'));
    expect(screen.getByText('A decision is retained, but notification delivery failed.')).toBeInTheDocument();
  });
});
