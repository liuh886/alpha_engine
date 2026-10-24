import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { rdiFixture } from '@/test/rdi-fixture';
import { fetchRdiResearch, parseRdiResearch } from '@/lib/rdi-research';
import { RdiResearchStatus } from './RdiResearchStatus';

vi.mock('@/lib/rdi-research', async importOriginal => ({
  ...await importOriginal<typeof import('@/lib/rdi-research')>(), fetchRdiResearch: vi.fn(),
}));
afterEach(() => { vi.resetAllMocks(); vi.useRealTimers(); });

describe('RDI research briefing', () => {
  it('keeps history distinct from a forecast and allows source inspection', async () => {
    vi.mocked(fetchRdiResearch).mockResolvedValue(parseRdiResearch(rdiFixture));
    render(<RdiResearchStatus attempt={0} />);
    await screen.findByText('Risk assessment unavailable');
    expect(screen.getByText(rdiFixture.reviewed_price_cutoff)).toBeVisible();
    const disclosure = screen.getByText('Historical price comparison · not an RDI forecast');
    fireEvent.click(disclosure);
    expect(screen.getByText('7 sessions')).toBeVisible();
    expect(screen.getByText('14 sessions')).toBeVisible();
    expect(screen.getByText('28 sessions')).toBeVisible();
    expect(screen.getByText(/not a current loss probability/)).toBeVisible();
  });
  it('does not keep earlier statistics visible during a failed refresh', async () => {
    vi.mocked(fetchRdiResearch).mockResolvedValueOnce(parseRdiResearch(rdiFixture)).mockRejectedValueOnce(new Error('offline'));
    const view = render(<RdiResearchStatus attempt={0} />);
    await screen.findByText('Risk assessment unavailable');
    view.rerender(<RdiResearchStatus attempt={1} />);
    await screen.findByRole('alert');
    expect(screen.queryByText('7 sessions')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Refresh status');
  });
  it('suppresses historical statistics when source identities disagree', async () => {
    vi.mocked(fetchRdiResearch).mockResolvedValue(parseRdiResearch({
      ...rdiFixture, status: 'evidence_mismatch', historical_comparison: [],
    }));
    render(<RdiResearchStatus attempt={0} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Source evidence has changed');
    expect(screen.queryByText('7 sessions')).not.toBeInTheDocument();
  });
  it('times out a stalled read and ignores its late success', async () => {
    vi.useFakeTimers();
    let resolve!: (value: ReturnType<typeof parseRdiResearch>) => void;
    vi.mocked(fetchRdiResearch).mockReturnValue(new Promise(done => { resolve = done; }));
    render(<RdiResearchStatus attempt={0} />);
    await act(async () => { vi.advanceTimersByTime(10_000); });
    expect(screen.getByRole('alert')).toHaveTextContent('could not be verified');
    await act(async () => { resolve(parseRdiResearch(rdiFixture)); });
    expect(screen.queryByText('7 sessions')).not.toBeInTheDocument();
  });
  it('can recover without rerunning research', async () => {
    vi.mocked(fetchRdiResearch).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(parseRdiResearch(rdiFixture));
    const view = render(<RdiResearchStatus attempt={0} />);
    await screen.findByRole('alert');
    view.rerender(<RdiResearchStatus attempt={1} />);
    await waitFor(() => expect(screen.getByText('Risk assessment unavailable')).toBeVisible());
    expect(fetchRdiResearch).toHaveBeenCalledTimes(2);
  });
});
