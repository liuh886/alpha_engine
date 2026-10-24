import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { rdiFixture } from '@/test/rdi-fixture';
import { fetchRdiResearch, parseRdiResearch } from '@/lib/rdi-research';
import { RdiResearchStatus } from './RdiResearchStatus';

vi.mock('@/lib/rdi-research', async importOriginal => ({
  ...await importOriginal<typeof import('@/lib/rdi-research')>(), fetchRdiResearch: vi.fn(),
}));
afterEach(() => { vi.resetAllMocks(); vi.useRealTimers(); });

const sample = {
  ...rdiFixture,
  historical_comparison: [
    { horizon_sessions: 7, drawdown_loss_frequency: 0.12, other_loss_frequency: 0.08, drawdown_observations: 100, other_observations: 200 },
    { horizon_sessions: 14, drawdown_loss_frequency: 0.172496, other_loss_frequency: 0.119864, drawdown_observations: 1200, other_observations: 2200 },
    { horizon_sessions: 28, drawdown_loss_frequency: 0.23, other_loss_frequency: 0.2, drawdown_observations: 140, other_observations: 240 },
  ],
  event_families: [
    rdiFixture.event_families[0],
    { id: 'policy_support', source: 'Synthetic policy source', readiness: 'not_integrated', historical_pit_verified: false },
    { id: 'holiday_positioning', source: 'Synthetic calendar', readiness: 'calendar_known_only', historical_pit_verified: false },
  ],
};

describe('RDI research workspace', () => {
  it('shows all horizons on a common scale and inspects exact values without fetching', async () => {
    vi.mocked(fetchRdiResearch).mockResolvedValue(parseRdiResearch(sample));
    render(<RdiResearchStatus attempt={0} />);
    await screen.findByText('Risk assessment unavailable');
    expect(screen.getByText(sample.reviewed_price_cutoff)).toBeVisible();
    expect(screen.getByText(sample.reviewed_at)).toBeVisible();
    expect(screen.getByRole('button', { name: '14 trading sessions' })).toHaveAttribute('aria-pressed', 'true');
    const initial = screen.getByRole('group', { name: '14-session details' });
    expect(within(initial).getByText('17.25%')).toBeVisible();
    expect(within(initial).getByText('11.99%')).toBeVisible();
    expect(within(initial).getByText('+5.26 pp')).toBeVisible();
    expect(within(initial).getByText('n=1,200')).toBeVisible();
    expect(within(initial).getByText('n=2,200')).toBeVisible();
    const bars = screen.getAllByRole('meter');
    expect(bars).toHaveLength(6);
    for (const bar of bars) {
      expect(bar).toHaveAttribute('aria-valuemin', '0');
      expect(bar).toHaveAttribute('aria-valuemax', '100');
    }
    fireEvent.click(screen.getByRole('button', { name: '7 trading sessions' }));
    const next = screen.getByRole('group', { name: '7-session details' });
    expect(within(next).getByText('12.00%')).toBeVisible();
    expect(within(next).getByText('8.00%')).toBeVisible();
    expect(within(next).getByText('+4.00 pp')).toBeVisible();
    expect(screen.getAllByRole('meter')).toHaveLength(6);
    fireEvent.click(screen.getByRole('button', { name: '28 trading sessions' }));
    expect(within(screen.getByRole('group', { name: '28-session details' })).getByText('+3.00 pp')).toBeVisible();
    expect(fetchRdiResearch).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/not a current loss probability/)).toBeVisible();
    fireEvent.click(screen.getByText('View exact historical values'));
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(4);
  });

  it('filters adapter integration independently from historical certification and provenance', async () => {
    vi.mocked(fetchRdiResearch).mockResolvedValue(parseRdiResearch(sample));
    render(<RdiResearchStatus attempt={0} />);
    await screen.findByText('Risk assessment unavailable');
    fireEvent.click(screen.getByText('Data coverage and sources'));
    expect(screen.getByText('Showing 3 of 3 source families')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Needs integration' }));
    expect(screen.getByText('Showing 1 of 3 source families')).toBeVisible();
    expect(screen.getByText('policy support')).toBeVisible();
    expect(screen.queryByText('holding change')).not.toBeInTheDocument();
    expect(screen.getByText('Historical coverage unverified')).toBeVisible();
    expect(screen.getByText(/does not certify historical completeness/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'All sources' }));
    expect(screen.getByText('holding change')).toBeVisible();
    expect(fetchRdiResearch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('Evidence provenance'));
    expect(screen.getByRole('link', { name: 'Research protocol and limitations' })).toHaveAttribute('href', expect.stringContaining(`/blob/${sample.repository_commit}/`));
  });

  it('explains an empty integration filter without claiming historical certification', async () => {
    vi.mocked(fetchRdiResearch).mockResolvedValue(parseRdiResearch(rdiFixture));
    render(<RdiResearchStatus attempt={0} />);
    await screen.findByText('Risk assessment unavailable');
    fireEvent.click(screen.getByText('Data coverage and sources'));
    fireEvent.click(screen.getByRole('button', { name: 'Needs integration' }));
    expect(screen.getByText(/No sources in this inventory/)).toBeVisible();
    expect(screen.getByText('Showing 0 of 1 source families')).toBeVisible();
  });

  it('hides earlier statistics throughout a failed parent refresh', async () => {
    let reject!: (error: Error) => void;
    vi.mocked(fetchRdiResearch).mockResolvedValueOnce(parseRdiResearch(sample))
      .mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
    const view = render(<RdiResearchStatus attempt={0} />);
    await screen.findByText('Risk assessment unavailable');
    view.rerender(<RdiResearchStatus attempt={1} />);
    expect(screen.getByRole('status')).toHaveTextContent('Reading reviewed evidence');
    expect(screen.queryByRole('meter')).not.toBeInTheDocument();
    await act(async () => reject(new Error('offline')));
    expect(screen.getByRole('alert')).toHaveTextContent('could not be verified');
    expect(screen.queryByRole('meter')).not.toBeInTheDocument();
    expect(fetchRdiResearch).toHaveBeenCalledTimes(2);
  });

  it('suppresses comparison controls and values when evidence identities disagree', async () => {
    vi.mocked(fetchRdiResearch).mockResolvedValue(parseRdiResearch({ ...sample, status: 'evidence_mismatch', historical_comparison: [] }));
    render(<RdiResearchStatus attempt={0} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Source evidence has changed');
    expect(screen.queryByRole('meter')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '14 trading sessions' })).not.toBeInTheDocument();
    expect(screen.getByText(sample.reviewed_price_cutoff)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Retry RDI' })).toBeVisible();
  });

  it('times out a stalled read and ignores its late success', async () => {
    vi.useFakeTimers();
    let resolve!: (value: ReturnType<typeof parseRdiResearch>) => void;
    vi.mocked(fetchRdiResearch).mockReturnValue(new Promise(done => { resolve = done; }));
    render(<RdiResearchStatus attempt={0} />);
    await act(async () => { vi.advanceTimersByTime(10_000); });
    expect(screen.getByRole('alert')).toHaveTextContent('could not be verified');
    await act(async () => { resolve(parseRdiResearch(sample)); });
    expect(screen.queryByRole('meter')).not.toBeInTheDocument();
  });

  it('retries RDI locally without requiring a parent refresh', async () => {
    vi.mocked(fetchRdiResearch).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(parseRdiResearch(sample));
    render(<RdiResearchStatus attempt={0} />);
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'Retry RDI' }));
    await waitFor(() => expect(screen.getByText('Risk assessment unavailable')).toBeVisible());
    expect(fetchRdiResearch).toHaveBeenCalledTimes(2);
  });

  it('aborts superseded reads and cannot overwrite a new success with an old response', async () => {
    let resolveOld!: (value: ReturnType<typeof parseRdiResearch>) => void;
    const newer = parseRdiResearch({ ...sample, historical_comparison: sample.historical_comparison.map(row => ({ ...row, drawdown_loss_frequency: 0.5 })) });
    vi.mocked(fetchRdiResearch).mockReturnValueOnce(new Promise(done => { resolveOld = done; })).mockResolvedValueOnce(newer);
    const view = render(<RdiResearchStatus attempt={0} />);
    view.rerender(<RdiResearchStatus attempt={1} />);
    await screen.findByText('Risk assessment unavailable');
    expect(fetchRdiResearch).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fetchRdiResearch).mock.calls[0][0].aborted).toBe(true);
    expect(within(screen.getByRole('group', { name: '14-session details' })).getByText('50.00%')).toBeVisible();
    await act(async () => resolveOld(parseRdiResearch(sample)));
    expect(within(screen.getByRole('group', { name: '14-session details' })).getByText('50.00%')).toBeVisible();
  });
});
