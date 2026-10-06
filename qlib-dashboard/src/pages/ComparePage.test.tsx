import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { loadRunSection, type GovernedRunSummary } from '@/lib/governed-run';
import type { ModelRunComparabilityKey } from '@/lib/model-run-bundle-v2';
import { ComparePage } from './ComparePage';

vi.mock('@/lib/governed-run', async (original) => ({ ...await original<typeof import('@/lib/governed-run')>(), loadRunSection: vi.fn() }));
function run(id: string, overrides: Partial<ModelRunComparabilityKey> = {}): GovernedRunSummary {
  return { key: `formal:${id}:run`, modelVersionId: id, runId: `${id}-run`, title: id,
    market: 'us', channel: 'formal', modelKind: 'cross_sectional_ranker', evidenceCutoff: '2026-10-05', evidenceStatus: 'complete',
    manifest: { comparability_key: { market: 'us', universe_id: 'us87', benchmark_id: 'QQQ', start: '2024-01-02', end: '2026-10-05', trace_frequency: 'daily', horizon: '10_sessions', rebalance_contract_id: '10_sessions', cost_contract_id: '20bps', ...overrides } },
    summary: { metrics: [{ metric_id: 'sharpe_ratio', value: id === 'a' ? 1 : 2, unit: 'decimal', direction: 'higher_is_better', estimator: 'same', annualization: '252_sessions', sample_count: 60, scope: 'same_window', availability_status: 'available', unavailable_reason: null }] },
  } as unknown as GovernedRunSummary;
}
function show(runs: GovernedRunSummary[]) {
  return render(<MemoryRouter initialEntries={['/compare']}><Routes><Route element={<Outlet context={{ runs }} />}><Route path="compare" element={<ComparePage />} /></Route></Routes></MemoryRouter>);
}
describe('ComparePage governed comparison', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(loadRunSection).mockImplementation(async (run, section) => ({ research_only: true, trade_ready: false, ...(section === 'diagnostics' ? { interpretation_notes: [`${run.title}: retained drawdown gate did not pass.`] } : { report: [] }) }));
  });
  it('uses v2 identities and separately checked notes for every selected record', async () => {
    show([run('a'), run('b', { benchmark_id: 'SPY', start: '2025-01-02' })]);
    expect(within(screen.getByRole('row', { name: /^Benchmark/ })).getByText('QQQ')).toBeInTheDocument();
    expect(within(screen.getByRole('row', { name: /^Start/ })).getByText('2025-01-02')).toBeInTheDocument();
    expect(await screen.findByText('a: retained drawdown gate did not pass.')).toBeInTheDocument();
    expect(await screen.findByText('b: retained drawdown gate did not pass.')).toBeInTheDocument();
    expect(screen.getByText(/No winner is inferred/)).toBeInTheDocument();
    expect(screen.getByText('2.000')).not.toHaveClass('font-bold');
    expect(loadRunSection).toHaveBeenCalledTimes(4);
    expect(vi.mocked(loadRunSection).mock.calls.map(([, section]) => section).sort()).toEqual(['diagnostics', 'diagnostics', 'performance', 'performance']);
  });
  it('does not equate missing identities or highlight metrics without their contract', async () => {
    show([run('a', { cost_contract_id: '' }), run('b', { cost_contract_id: '' })]);
    await screen.findByText('a: retained drawdown gate did not pass.');
    expect(within(screen.getByRole('row', { name: /^Cost contract/ })).getAllByText('Contract violation')).toHaveLength(2);
    expect(screen.getByText(/No winner is inferred/)).toBeInTheDocument();
    expect(screen.getByText('2.000')).not.toHaveClass('font-bold');
  });
  it('highlights aligned metrics but rejects a mismatched metric scope', async () => {
    const first = run('a'); const second = run('b');
    const view = show([first, second]);
    await screen.findByText('a: retained drawdown gate did not pass.');
    expect(screen.getByText('2.000')).toHaveClass('font-bold');
    view.unmount();
    const changed = { ...second, summary: { metrics: (second.summary.metrics as Array<Record<string, unknown>>).map((metric) => ({ ...metric, scope: 'different_window' })) } };
    show([first, changed]);
    await screen.findByText('a: retained drawdown gate did not pass.');
    expect(screen.getByText('2.000')).not.toHaveClass('font-bold');
  });
  it('keeps a diagnostics integrity failure scoped to that record', async () => {
    vi.mocked(loadRunSection).mockImplementation(async (run, section) => {
      if (run.title === 'a' && section === 'diagnostics') throw new Error('Section integrity mismatch');
      return { research_only: true, trade_ready: false, report: [], interpretation_notes: [`${run.title}: verified notes`] };
    });
    show([run('a'), run('b')]);
    expect(await screen.findByRole('alert')).toHaveTextContent('Section integrity mismatch');
    expect(await screen.findByText('b: verified notes')).toBeInTheDocument();
    expect(screen.getByText('2.000')).toBeInTheDocument();
  });
  it('ignores late sections from an unselected run', async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(loadRunSection).mockImplementation(async (run, section) => {
      if (run.title === 'b' && section === 'diagnostics') return new Promise((done) => { resolve = done; });
      return { research_only: true, trade_ready: false, report: [], interpretation_notes: ['Current a notes'] };
    });
    show([run('a'), run('b')]);
    fireEvent.click(screen.getByRole('button', { name: /b · b-run/ }));
    await act(async () => { resolve({ research_only: true, trade_ready: false, interpretation_notes: ['Obsolete notes'], report: [] }); });
    expect(await screen.findByText('Current a notes')).toBeInTheDocument();
    expect(screen.queryByText('Obsolete notes')).not.toBeInTheDocument();
    expect(screen.queryByText('Interpretation limits · b · b-run')).not.toBeInTheDocument();
  });
});
