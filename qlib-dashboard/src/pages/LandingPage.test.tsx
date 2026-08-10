import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { LandingPage } from './LandingPage';

vi.mock('@/lib/governed-run', () => ({
  loadFormalRuns: vi.fn().mockResolvedValue({ runs: [], errors: [] }),
  loadRunSection: vi.fn().mockResolvedValue({ report: [] }),
}));

describe('Alpha Engine landing page', () => {
  it('leads with product value, comparative performance proof and traceable evidence', () => {
    const { container } = render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: /know what your systematic strategy is doing/i })).toBeInTheDocument();
    expect(screen.getByText('QQQR v4.3')).toBeInTheDocument();
    expect(screen.getByText('CN x1.1')).toBeInTheDocument();
    expect(screen.getByText('BYD v1.2')).toBeInTheDocument();

    const fleetTable = container.querySelector('.landing-run-table');
    expect(fleetTable).not.toBeNull();
    const fleet = within(fleetTable as HTMLElement);
    expect(fleet.getAllByText('CAGR', { exact: true })).toHaveLength(4);
    expect(fleet.getAllByText('MDD', { exact: true })).toHaveLength(4);

    expect(screen.getByRole('heading', { name: /performance before persuasion/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /every decision is traceable/i })).toBeInTheDocument();
    expect(screen.getAllByText('Strategy fleet')).toHaveLength(1);

    expect(screen.getByRole('link', { name: /explore strategies/i })).toHaveAttribute('href', '/strategies');
    expect(screen.getAllByRole('link', { name: /open console/i }).length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: /inspect formal performance/i })).toHaveAttribute('href', '/strategies');
    expect(screen.getByRole('link', { name: /open research evidence/i })).toHaveAttribute('href', '/research');
  });
});
