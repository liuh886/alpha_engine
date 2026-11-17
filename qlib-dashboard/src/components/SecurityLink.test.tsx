import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SecurityLink } from './SecurityLink';

const mocks = vi.hoisted(() => ({ loadSecurityCatalog: vi.fn() }));

vi.mock('@/lib/security-evidence', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/security-evidence')>();
  return { ...actual, loadSecurityCatalog: mocks.loadSecurityCatalog };
});

const sha = 'a'.repeat(64);
const boundary = { view: 'security_detail_v1', research_only: true as const, trade_ready: false as const };
const usCatalog = {
  ...boundary,
  market: 'us' as const,
  evidence_type: 'market_evidence_catalog',
  cutoff: '2026-01-31',
  provider_manifest_sha256: sha,
  symbols: [
    { symbol: 'AAPL', name: 'Apple', instrument_id: 'us:AAPL', path: 'symbols/AAPL.json', sha256: sha, source_sha256: sha, source_instruments: ['AAPL'], roles: [] },
  ],
  formal_bindings: [],
};
const cnCatalog = {
  ...boundary,
  market: 'cn' as const,
  evidence_type: 'market_evidence_catalog',
  cutoff: '2026-01-31',
  provider_manifest_sha256: sha,
  symbols: [
    { symbol: '002594', name: 'BYD', instrument_id: 'cn:002594', path: 'symbols/002594.json', sha256: sha, source_sha256: sha, source_instruments: ['002594', 'BYD'], roles: [] },
  ],
  formal_bindings: [],
};

function renderLink(props: { market?: string; instrument: string; model?: string; children?: string }) {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <SecurityLink {...props} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mocks.loadSecurityCatalog.mockReset();
  mocks.loadSecurityCatalog.mockImplementation(async (market: 'us' | 'cn') => (
    market === 'us' ? usCatalog : cnCatalog
  ));
});

describe('SecurityLink', () => {
  it('links only when the same-market catalog resolves the symbol', async () => {
    renderLink({ market: 'us', instrument: 'AAPL', model: 'model_a' });
    const link = await screen.findByRole('link', { name: 'View AAPL price and model events' });
    expect(link).toHaveAttribute('href', '#/securities/us/AAPL?model=model_a');
  });

  it('resolves a published alias to the canonical catalog symbol', async () => {
    renderLink({ market: 'cn', instrument: 'BYD' });
    const link = await screen.findByRole('link', { name: 'View BYD price and model events' });
    expect(link).toHaveAttribute('href', '#/securities/cn/002594');
  });

  it('renders plain text with a short reason when the symbol is not published', async () => {
    renderLink({ market: 'us', instrument: 'CASH' });
    await waitFor(() => expect(screen.getByTestId('security-link-unresolved')).toHaveAttribute('data-resolution', 'unresolved'));
    expect(screen.getByText('CASH')).toBeInTheDocument();
    expect(screen.getByTestId('security-link-unresolved')).toHaveTextContent('No published price history');
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('never links a cross-market instrument', async () => {
    renderLink({ market: 'cn', instrument: 'us:AAPL' });
    await waitFor(() => expect(screen.getByTestId('security-link-unresolved')).toHaveAttribute('data-resolution', 'unresolved'));
    expect(screen.queryByRole('link')).not.toBeInTheDocument();

    renderLink({ market: 'us', instrument: '002594' });
    await waitFor(() => expect(screen.getAllByTestId('security-link-unresolved')).toHaveLength(2));
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('never links an unsupported market', async () => {
    renderLink({ market: 'hk', instrument: '0700' });
    await waitFor(() => expect(screen.getByTestId('security-link-unresolved')).toHaveAttribute('data-resolution', 'unresolved'));
    expect(screen.getByTestId('security-link-unresolved')).toHaveTextContent('No governed market');
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(mocks.loadSecurityCatalog).not.toHaveBeenCalled();
  });

  it('stays plain text with a catalog reason when the market catalog is unavailable', async () => {
    mocks.loadSecurityCatalog.mockRejectedValue(new Error('Security history unavailable (404).'));
    renderLink({ market: 'us', instrument: 'AAPL' });
    await waitFor(() => expect(screen.getByTestId('security-link-unresolved')).toHaveAttribute('data-resolution', 'unresolved'));
    expect(screen.getByTestId('security-link-unresolved')).toHaveTextContent('Price catalog unavailable');
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});
