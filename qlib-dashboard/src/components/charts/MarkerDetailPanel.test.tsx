import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { MarkerDetailView } from '@/lib/chart-markers';
import { MarkerDetailPanel } from './MarkerDetailPanel';

const mocks = vi.hoisted(() => ({ loadSecurityCatalog: vi.fn() }));

vi.mock('@/lib/security-evidence', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/security-evidence')>();
  return { ...actual, loadSecurityCatalog: mocks.loadSecurityCatalog };
});

const sha = 'a'.repeat(64);
const boundary = { view: 'security_detail_v1', research_only: true as const, trade_ready: false as const };
const cnCatalog = {
  ...boundary,
  market: 'cn' as const,
  evidence_type: 'market_evidence_catalog',
  cutoff: '2026-11-16',
  provider_manifest_sha256: sha,
  symbols: [
    { symbol: '002594', name: 'BYD', instrument_id: 'cn:002594', path: 'symbols/002594.json', sha256: sha, source_sha256: sha, source_instruments: ['002594', 'BYD'], roles: [] },
  ],
  formal_bindings: [],
};

const detail: MarkerDetailView = {
  date: '2026-08-04',
  side: 'sell',
  count: 1,
  unit: 'trade',
  models: [{ modelId: 'byd_v1_3', label: 'BYD v1.3' }],
  entries: [{
    key: '2026-08-04:0',
    modelId: 'byd_v1_3',
    modelLabel: 'BYD v1.3',
    action: 'Sell',
    instrument: 'BYD',
    previousWeight: 1,
    targetWeight: 0.75,
    reason: 'rebalance',
  }],
};

beforeEach(() => {
  mocks.loadSecurityCatalog.mockReset();
  mocks.loadSecurityCatalog.mockResolvedValue(cnCatalog);
});

describe('MarkerDetailPanel instrument link', () => {
  it('links a model marker instrument through its market catalog', async () => {
    render(<MarkerDetailPanel detail={detail} testId="marker" ariaLabel="Marker" market="cn" model="byd_v1_3" />);
    expect(await screen.findByRole('link', { name: 'View BYD price and model events' })).toHaveAttribute(
      'href',
      '#/securities/cn/002594?model=byd_v1_3',
    );
    expect(screen.getByTestId('marker')).toHaveTextContent('BYD');
  });

  it('keeps the instrument as plain text when no market is supplied', () => {
    render(<MarkerDetailPanel detail={detail} testId="marker" ariaLabel="Marker" />);
    expect(screen.getByTestId('marker')).toHaveTextContent('BYD');
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(mocks.loadSecurityCatalog).not.toHaveBeenCalled();
  });
});
