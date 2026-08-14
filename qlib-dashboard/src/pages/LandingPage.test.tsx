import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LandingPage } from './LandingPage';

const membershipState = vi.hoisted(() => ({
  loading: false,
  signedIn: false,
  isPro: false,
  isOwner: false,
  entitlements: [] as string[],
  userId: null as string | null,
  openAccount: vi.fn(),
  getClient: vi.fn(),
}));

vi.mock('@/hooks/useAlphaMembership', () => ({
  useAlphaMembership: () => membershipState,
}));

vi.mock('@/lib/governed-run', () => ({
  loadFormalRuns: vi.fn().mockResolvedValue({ runs: [], errors: [] }),
  loadRunSection: vi.fn().mockResolvedValue({ report: [] }),
}));

describe('Alpha Engine landing page', () => {
  beforeEach(() => {
    sessionStorage.clear();
    membershipState.loading = false;
    membershipState.signedIn = false;
    membershipState.isPro = false;
    membershipState.isOwner = false;
    membershipState.entitlements = [];
    membershipState.userId = null;
    membershipState.openAccount.mockReset();
    membershipState.getClient.mockReset();
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockImplementation(() => ({
        matches: false,
        media: '',
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  it('leads with product value, public proof and a real account entry point', () => {
    const { container } = render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: /know what your systematic strategy is doing/i })).toBeInTheDocument();
    expect(screen.getByText('QQQR v4.3')).toBeInTheDocument();
    expect(screen.getByText('CN x1.1')).toBeInTheDocument();
    expect(screen.getByText('BYD v1.3')).toBeInTheDocument();
    expect(screen.getByText('US x1.3')).toBeInTheDocument();

    const fleetTable = container.querySelector('.landing-run-table');
    expect(fleetTable).not.toBeNull();
    const fleet = within(fleetTable as HTMLElement);
    expect(fleet.getAllByText('CAGR', { exact: true })).toHaveLength(4);
    expect(fleet.getAllByText('MDD', { exact: true })).toHaveLength(4);

    expect(screen.getByRole('heading', { name: /performance before persuasion/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /every decision is traceable/i })).toBeInTheDocument();
    expect(screen.getAllByText('Strategy fleet')).toHaveLength(1);

    expect(screen.getByRole('link', { name: /explore public strategies/i })).toHaveAttribute('href', '/strategies');
    expect(screen.getByText(/public strategy evidence stays open/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeInTheDocument();
    const signInActions = screen.getAllByRole('button', { name: /sign in to alpha engine/i });
    expect(signInActions).toHaveLength(2);
    fireEvent.click(signInActions[0]);
    expect(membershipState.openAccount).toHaveBeenCalledTimes(1);

    expect(screen.getByRole('button', { name: /share alpha engine/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /inspect formal performance/i })).toHaveAttribute('href', '/strategies');
    expect(screen.getByRole('link', { name: /open research evidence/i })).toHaveAttribute('href', '/research');
  });

  it('turns the same landing CTAs into console entry after sign-in', () => {
    membershipState.signedIn = true;

    render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('link', { name: /^open console$/i })).toHaveAttribute('href', '/app');
    const consoleActions = screen.getAllByRole('link', { name: /open strategy console/i });
    expect(consoleActions).toHaveLength(2);
    consoleActions.forEach((action) => expect(action).toHaveAttribute('href', '/app'));
    expect(screen.getByText(/^signed in\./i)).toBeInTheDocument();
  });

  it('surfaces Pro state without adding a separate login route', () => {
    membershipState.signedIn = true;
    membershipState.isPro = true;

    render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('link', { name: /^open pro$/i })).toHaveAttribute('href', '/app');
    const proActions = screen.getAllByRole('link', { name: /open alpha engine pro/i });
    expect(proActions).toHaveLength(2);
    proActions.forEach((action) => expect(action).toHaveAttribute('href', '/app'));
    expect(screen.getByText(/alpha engine pro is active/i)).toBeInTheDocument();
  });
});
