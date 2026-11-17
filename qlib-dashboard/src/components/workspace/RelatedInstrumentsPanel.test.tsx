import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { RelatedInstrumentsPanel } from './RelatedInstrumentsPanel';

const mocks = vi.hoisted(() => ({
  readRelatedTradeInstruments: vi.fn(),
  loadSecurityCatalog: vi.fn(),
}));

vi.mock('@/lib/related-entities', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/related-entities')>();
  return { ...actual, readRelatedTradeInstruments: mocks.readRelatedTradeInstruments };
});

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
    { symbol: '515180', name: '515180.SH', instrument_id: 'cn:515180', path: 'symbols/515180.json', sha256: sha, source_sha256: sha, source_instruments: ['515180', '515180.SH'], roles: [] },
  ],
  formal_bindings: [],
};

const run: GovernedRunSummary = {
  key: 'formal:byd_allocation:byd_v1_3:run',
  modelFamilyId: 'byd_allocation',
  modelVersionId: 'byd_v1_3',
  runId: 'run',
  bundleId: 'b'.repeat(64),
  title: 'BYD v1.3',
  modelKind: 'rules_based_allocation',
  channel: 'formal',
  publicationStatus: 'accepted_formal_baseline',
  market: 'cn',
  benchmark: '000300',
  generatedAt: '2026-11-17T00:00:00Z',
  evidenceCutoff: '2026-11-16',
  evidenceStatus: 'complete',
  decisionStatus: 'supported',
  manifestPath: null,
  manifestSha256: null,
  summary: {},
  manifest: null,
  loadWarnings: [],
};

function renderPanel() {
  return render(
    <MemoryRouter initialEntries={['/strategies/byd_v1_3']}>
      <RelatedInstrumentsPanel run={run} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mocks.readRelatedTradeInstruments.mockReset();
  mocks.loadSecurityCatalog.mockReset();
  mocks.loadSecurityCatalog.mockResolvedValue(cnCatalog);
});

describe('RelatedInstrumentsPanel', () => {
  it('lists retained-ledger instruments with count and last action, and links resolvable symbols', async () => {
    mocks.readRelatedTradeInstruments.mockResolvedValue({
      status: 'ready',
      instruments: [
        { instrument: 'BYD', tradeCount: 113, lastAction: 'SELL', lastDate: '2026-08-04' },
        { instrument: '515180.SH', tradeCount: 49, lastAction: 'BUY', lastDate: '2026-08-04' },
      ],
    });
    renderPanel();

    const rows = await screen.findAllByTestId('related-instrument');
    expect(rows.map(row => row.getAttribute('data-instrument'))).toEqual(['BYD', '515180.SH']);
    expect(rows[0]).toHaveTextContent('113 retained trades · last Sell on 2026-08-04');
    expect(rows[1]).toHaveTextContent('49 retained trades · last Buy on 2026-08-04');
    expect(await screen.findByRole('link', { name: 'View BYD price and model events' })).toHaveAttribute(
      'href',
      '#/securities/cn/002594?model=byd_v1_3',
    );
    expect(screen.getByRole('link', { name: 'View 515180.SH price and model events' })).toHaveAttribute(
      'href',
      '#/securities/cn/515180?model=byd_v1_3',
    );
    await waitFor(() => expect(screen.getAllByRole('link')).toHaveLength(2));
    // Same-market only: a CN model never links a US route.
    for (const link of screen.getAllByRole('link')) {
      expect(link.getAttribute('href')).toContain('/securities/cn/');
    }
  });

  it('keeps an unpublished instrument plain text with a reason instead of a dead link', async () => {
    mocks.readRelatedTradeInstruments.mockResolvedValue({
      status: 'ready',
      instruments: [{ instrument: 'CASH', tradeCount: 2, lastAction: 'SELL', lastDate: '2026-01-01' }],
    });
    renderPanel();
    const row = await screen.findByTestId('related-instrument');
    expect(row).toHaveTextContent('CASH');
    await waitFor(() => expect(row).toHaveTextContent('No published price history'));
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('states an unavailable ledger rather than guessing instruments', async () => {
    mocks.readRelatedTradeInstruments.mockResolvedValue({ status: 'unavailable', reason: 'trades is not_retained' });
    renderPanel();
    expect(await screen.findByTestId('related-instruments')).toHaveTextContent(
      'Retained trade ledger unavailable · trades is not_retained',
    );
    expect(screen.queryByTestId('related-instrument')).not.toBeInTheDocument();
  });

  it('renders nothing for a verified empty ledger', async () => {
    mocks.readRelatedTradeInstruments.mockResolvedValue({ status: 'ready', instruments: [] });
    const { container } = renderPanel();
    await waitFor(() => expect(mocks.readRelatedTradeInstruments).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
