import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { loadRunSection, type GovernedRunSummary } from '@/lib/governed-run';
import { fetchSystemHealth, type LiveSystemHealth } from '@/lib/system-health';
import { ModelOperationsPage } from './ModelOperationsPage';

vi.mock('@/lib/system-health', () => ({ fetchSystemHealth: vi.fn() }));
vi.mock('@/lib/governed-run', () => ({ loadRunSection: vi.fn() }));
const run = (id: string, bundleId = `${id}-bundle`): GovernedRunSummary => ({ key: `${id}:${bundleId}`, title: id, modelVersionId: id, bundleId, runId: `${id}-run`, channel: 'formal', market: 'us', evidenceCutoff: '2026-10-05', evidenceStatus: 'complete' } as GovernedRunSummary);
const health = (runs: GovernedRunSummary[]): LiveSystemHealth => ({
  status: 'current', deploymentStatus: 'current', message: 'Verified runtime health',
  health: { generated_at: '2026-10-06T17:00:00Z', strategies: runs.map((run) => ({
    model_version_id: run.modelVersionId, formal_bundle_id: run.bundleId,
    formal_run_id: run.runId, market: run.market, formal_cutoff: run.evidenceCutoff,
    state: 'delayed', provider_cutoff: '2026-10-02', factor_cutoff: '2026-09-25',
    last_signal_evaluation: '2026-09-25', delivery_status: 'not_required',
    stages: { provider: 'delayed', formal: 'current', signal: 'delayed', factor: 'delayed', delivery: 'not_applicable', model_data: 'not_applicable' },
  })) } as unknown as LiveSystemHealth['health'],
});
function shell(runs: GovernedRunSummary[]) {
  return <MemoryRouter><Routes><Route element={<Outlet context={{ runs }} />}><Route path="/" element={<ModelOperationsPage />} /></Route></Routes></MemoryRouter>;
}
describe('ModelOperationsPage authoritative monitoring', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(fetchSystemHealth).mockResolvedValue(health([run('a'), run('b')]));
    vi.mocked(loadRunSection).mockImplementation(async (run) => ({ research_only: true, trade_ready: false, interpretation_notes: [`${run.title}: retained failure`] }));
  });
  it('keeps formal evidence and drift absence visible during health loading', () => {
    vi.mocked(fetchSystemHealth).mockReturnValue(new Promise(() => {}));
    vi.mocked(loadRunSection).mockReturnValue(new Promise(() => {}));
    render(shell([run('a')]));
    expect(screen.getByText('Checking monitoring evidence...')).toBeInTheDocument();
    expect(screen.getByText(/Formal evidence through 2026-10-05/)).toBeInTheDocument();
    expect(screen.getByText('Statistical drift: unavailable')).toBeInTheDocument();
    expect(screen.queryByText(/Approved Champion/)).not.toBeInTheDocument();
  });
  it('binds health to the exact formal identity and retains actual stage dates', async () => {
    render(shell([run('a')]));
    expect(await screen.findByText('a: retained failure')).toBeInTheDocument();
    expect(await screen.findByText('2026-10-02')).toBeInTheDocument();
    expect(screen.getByText('2026-09-25')).toBeInTheDocument();
    expect(screen.getAllByText('Delayed').length).toBeGreaterThan(0);
    expect(loadRunSection).toHaveBeenCalledWith(expect.objectContaining({ modelVersionId: 'a' }), 'diagnostics');
    expect(loadRunSection).toHaveBeenCalledTimes(1);
  });
  it.each(['formal_bundle_id', 'formal_run_id', 'market', 'formal_cutoff'])('rejects mismatched %s without hiding formal limits', async (field) => {
    const value = health([run('a')]);
    (value.health!.strategies[0] as unknown as Record<string, unknown>)[field] = 'mismatched';
    vi.mocked(fetchSystemHealth).mockResolvedValue(value);
    render(shell([run('a')]));
    expect(await screen.findByText(/Monitoring identity does not match/)).toBeInTheDocument();
    expect(await screen.findByText('a: retained failure')).toBeInTheDocument();
    expect(screen.queryByText('2026-10-02')).not.toBeInTheDocument();
  });
  it('does not accept duplicate health records for the same model', async () => {
    const value = health([run('a'), run('a')]);
    vi.mocked(fetchSystemHealth).mockResolvedValue(value);
    render(shell([run('a')]));
    expect(await screen.findByText(/Source-bound operational health is unavailable/)).toBeInTheDocument();
  });
  it('keeps healthy operational evidence readable while one interpretation request is pending', async () => {
    vi.mocked(loadRunSection).mockImplementation(async (run) => run.title === 'b' ? new Promise(() => {}) : { research_only: true, trade_ready: false, interpretation_notes: ['Verified a notes'] });
    render(shell([run('a'), run('b')]));
    expect(await screen.findByText('Verified a notes')).toBeInTheDocument();
    expect(await screen.findAllByText('2026-10-02')).toHaveLength(2);
    expect(screen.getByText('Checking interpretation evidence...')).toBeInTheDocument();
  });
  it('retries rejected interpretation evidence through the verified section reader', async () => {
    vi.mocked(loadRunSection).mockRejectedValueOnce(new Error('Section integrity mismatch'))
      .mockResolvedValueOnce({ research_only: true, trade_ready: false, interpretation_notes: ['Verified after retry'] });
    render(shell([run('a')]));
    expect(await screen.findByRole('alert')).toHaveTextContent('Section integrity mismatch');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh monitoring' }));
    expect(await screen.findByText('Verified after retry')).toBeInTheDocument();
    expect(screen.queryByText('Section integrity mismatch')).not.toBeInTheDocument();
    expect(loadRunSection).toHaveBeenCalledTimes(2);
  });
  it('hides previous health and interpretation notes immediately when the formal run changes', async () => {
    const view = render(shell([run('a')]));
    await screen.findByText('a: retained failure');
    vi.mocked(fetchSystemHealth).mockReturnValue(new Promise(() => {}));
    vi.mocked(loadRunSection).mockReturnValue(new Promise(() => {}));
    await act(async () => { view.rerender(shell([run('a', 'new-bundle')])); });
    expect(screen.queryByText('a: retained failure')).not.toBeInTheDocument();
    expect(screen.queryByText('2026-10-02')).not.toBeInTheDocument();
  });
});
