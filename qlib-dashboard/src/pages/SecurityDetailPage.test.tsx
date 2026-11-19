import type { ReactNode } from 'react';
import { createContext, useContext, useEffect } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { SecurityEvidence, SecuritySymbol } from '@/lib/security-evidence';
import { SecurityAsOfMetrics, SecurityHistory } from './SecurityDetailPage';

// Radix focus/positioning scopes are costly under jsdom; this mirrors the
// baseline-control test and keeps the controlled open state and trigger.
vi.mock('@radix-ui/react-popover', () => {
  const PopoverContext = createContext<{ open: boolean; setOpen?: (open: boolean) => void }>({ open: false });
  return {
    Root: ({ children, open, onOpenChange }: {
      children: ReactNode;
      open?: boolean;
      onOpenChange?: (open: boolean) => void;
    }) => (
      <PopoverContext.Provider value={{ open: Boolean(open), setOpen: onOpenChange }}>
        {children}
      </PopoverContext.Provider>
    ),
    Trigger: ({ children }: { children: ReactNode }) => {
      const context = useContext(PopoverContext);
      return (
        <span
          onClick={event => {
            const button = (event.target as HTMLElement).closest('button');
            if (button?.disabled) return;
            context.setOpen?.(!context.open);
          }}
        >
          {children}
        </span>
      );
    },
    Portal: ({ children }: { children: ReactNode }) => <>{children}</>,
    Content: ({ children, onOpenAutoFocus }: {
      children: ReactNode;
      onOpenAutoFocus?: (event: Event) => void;
    }) => {
      const { open } = useContext(PopoverContext);
      useEffect(() => {
        if (open) onOpenAutoFocus?.(new Event('focus'));
      }, [open, onOpenAutoFocus]);
      return open ? <div>{children}</div> : null;
    },
  };
});

const mocks = vi.hoisted(() => ({
  loadMarketBaseline: vi.fn(),
  readMarketEvidence: vi.fn(),
  loadSecurityCatalog: vi.fn(),
  loadFormalNav: vi.fn(),
  readLatestPublishedHolding: vi.fn(),
}));

vi.mock('@/lib/security-baseline', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/security-baseline')>();
  return { ...actual, loadMarketBaseline: mocks.loadMarketBaseline };
});

vi.mock('@/lib/security-evidence', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/security-evidence')>();
  return { ...actual, loadSecurityCatalog: mocks.loadSecurityCatalog };
});

vi.mock('@/lib/formal-nav', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/formal-nav')>();
  return { ...actual, loadFormalNav: mocks.loadFormalNav };
});

vi.mock('@/lib/market-evidence-cache', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/market-evidence-cache')>();
  return { ...actual, readMarketEvidence: mocks.readMarketEvidence };
});

vi.mock('@/lib/related-entities', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/related-entities')>();
  return { ...actual, readLatestPublishedHolding: mocks.readLatestPublishedHolding };
});

vi.mock('@/components/SecurityLightweightChart', () => ({
  SecurityLightweightChart: ({ mode, markers, modelColorIndex, overlays }: {
    mode: string;
    markers: unknown[];
    modelColorIndex?: Map<string, number>;
    overlays?: readonly { id: string }[];
  }) => (
    <div
      data-testid="security-chart-stub"
      data-mode={mode}
      data-markers={markers.length}
      data-model-colors={modelColorIndex ? [...modelColorIndex.keys()].join(',') : ''}
      data-overlays={(overlays ?? []).map(overlay => overlay.id).join(',')}
      data-overlay-count={(overlays ?? []).length}
    />
  ),
}));

function renderMetrics(asOf: string | null, cutoff: string) {
  return render(
    <dl>
      <SecurityAsOfMetrics asOf={asOf} cutoff={cutoff} />
    </dl>,
  );
}

const bars = [
  { time: '2026-01-02', open: 100, high: 102, low: 99, close: 101, volume: 1000 },
  { time: '2026-01-05', open: 101, high: 104, low: 100, close: 103, volume: 1200 },
  { time: '2026-01-06', open: 103, high: 105, low: 102, close: 104, volume: 900 },
];

const baselineBars = [
  { time: '2026-01-02', open: 200, high: 202, low: 199, close: 201, volume: 2000 },
  { time: '2026-01-05', open: 201, high: 204, low: 200, close: 203, volume: 2200 },
  { time: '2026-01-06', open: 203, high: 205, low: 202, close: 204, volume: 1900 },
];

const longBars = Array.from({ length: 40 }, (_, index) => {
  const time = new Date(Date.UTC(2025, 10, 1 + index)).toISOString().slice(0, 10);
  const close = 100 + Math.sin(index / 3) * 10;
  return { time, open: close, high: close + 1, low: close - 1, close, volume: 1000 + index };
});

const evidence = (overrides: Partial<SecurityEvidence> = {}): SecurityEvidence => ({
  market: 'us',
  symbol: 'AAPL',
  name: 'Apple',
  cutoff: '2026-01-31',
  source_sha256: 'a'.repeat(64),
  provider_manifest_sha256: 'b'.repeat(64),
  bars,
  events: [{
    time: '2026-01-05',
    model_id: 'qqq_v1',
    run_id: 'run-1',
    instrument_id: 'us:AAPL',
    action: 'BUY',
    previous_weight: 0,
    target_weight: 0.5,
    reason: 'frozen_rule',
  }],
  bindings: [{ model_version_id: 'qqq_v1', run_id: 'run-1', bundle_id: 'c'.repeat(64) }],
  roles: [],
  benchmark: null,
  ...overrides,
});

const run: GovernedRunSummary = {
  key: 'us:qqq_v1',
  modelFamilyId: 'qqq-family',
  modelVersionId: 'qqq_v1',
  runId: 'run-1',
  bundleId: 'c'.repeat(64),
  title: 'QQQ Rotation',
  modelKind: 'rules_based_allocation',
  channel: 'formal',
  publicationStatus: 'accepted_formal_baseline',
  market: 'us',
  benchmark: 'QQQ',
  generatedAt: '2026-01-12T00:00:00Z',
  evidenceCutoff: '2026-01-31',
  evidenceStatus: 'complete',
  decisionStatus: 'supported',
  manifestPath: null,
  manifestSha256: null,
  summary: {},
  manifest: null,
  loadWarnings: [],
};

const runTwo: GovernedRunSummary = {
  ...run,
  key: 'us:qqq_v2',
  modelVersionId: 'qqq_v2',
  runId: 'run-2',
  bundleId: 'e'.repeat(64),
  title: 'QQQ Rotation Two',
};

function renderHistory(runs: GovernedRunSummary[] = [run], value: SecurityEvidence = evidence()) {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<Outlet context={{ runs }} />}>
          <Route index element={<SecurityHistory evidence={value} runs={runs} />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

const symbolRecord = (market: 'us' | 'cn', symbol: string, name: string, roles: string[] = []): SecuritySymbol => ({
  symbol,
  name,
  instrument_id: `${market}:${symbol}`,
  path: `symbols/${symbol}.json`,
  sha256: 'd'.repeat(64),
  source_sha256: 'd'.repeat(64),
  source_instruments: [symbol],
  roles,
});

const usSymbols = [
  symbolRecord('us', 'AAPL', 'Apple'),
  symbolRecord('us', 'MSFT', 'Microsoft'),
  symbolRecord('us', 'NVDA', 'NVIDIA'),
  symbolRecord('us', 'AMD', 'Advanced Micro Devices'),
  symbolRecord('us', 'GOOG', 'Alphabet'),
  symbolRecord('us', 'QQQ', 'Invesco QQQ Trust', ['benchmark', 'formal_traded']),
  symbolRecord('us', 'SPX', 'S&P 500', ['formal_auxiliary']),
];
const cnSymbols = [
  symbolRecord('cn', '002594', 'BYD'),
  symbolRecord('cn', '000001', 'Ping An Bank'),
];

const catalogFor = (market: 'us' | 'cn') => ({
  market,
  cutoff: '2026-01-31',
  provider_manifest_sha256: 'b'.repeat(64),
  symbols: market === 'us' ? usSymbols : cnSymbols,
  formal_bindings: [],
});

const modelRows = longBars.slice(10).map((bar, index) => ({ date: bar.time, account: 100 + index }));

beforeEach(() => {
  window.localStorage.clear();
  mocks.loadMarketBaseline.mockReset();
  mocks.readMarketEvidence.mockReset();
  mocks.loadSecurityCatalog.mockReset();
  mocks.loadFormalNav.mockReset();
  mocks.readLatestPublishedHolding.mockReset();
  mocks.readLatestPublishedHolding.mockResolvedValue({
    status: 'not_held',
    asOf: '2026-01-30',
    cutoff: '2026-01-31',
  });
  mocks.readMarketEvidence.mockRejectedValue(
    new Error('This instrument has no published price history in this market.'),
  );
  mocks.loadSecurityCatalog.mockImplementation(async (market: 'us' | 'cn') => catalogFor(market));
  mocks.loadFormalNav.mockResolvedValue({ rows: modelRows, key: 'formal:model' });
});

describe('SecurityAsOfMetrics', () => {
  it('shows one labelled metric when the as-of date equals the evidence cutoff', () => {
    renderMetrics('2026-11-11', '2026-11-11');
    expect(screen.getByText('As of · evidence cutoff')).toBeInTheDocument();
    expect(screen.getByTestId('security-as-of-cutoff')).toHaveTextContent('2026-11-11');
    expect(screen.queryByText('As of')).not.toBeInTheDocument();
    expect(screen.queryByText('Evidence cutoff')).not.toBeInTheDocument();
    expect(screen.queryByTestId('security-as-of')).not.toBeInTheDocument();
  });

  it('keeps both labelled metrics when the dates differ', () => {
    renderMetrics('2026-11-10', '2026-11-12');
    expect(screen.getByText('As of')).toBeInTheDocument();
    expect(screen.getByText('Evidence cutoff')).toBeInTheDocument();
    expect(screen.getByTestId('security-as-of')).toHaveTextContent('2026-11-10');
    expect(screen.getByTestId('security-evidence-cutoff')).toHaveTextContent('2026-11-12');
    expect(screen.queryByText('As of · evidence cutoff')).not.toBeInTheDocument();
  });

  it('never borrows a cutoff when no observation date is retained', () => {
    renderMetrics(null, '2026-11-12');
    expect(screen.getByText('As of')).toBeInTheDocument();
    expect(screen.getByTestId('security-as-of')).toHaveTextContent('—');
    expect(screen.getByTestId('security-evidence-cutoff')).toHaveTextContent('2026-11-12');
    expect(screen.queryByText('As of · evidence cutoff')).not.toBeInTheDocument();
  });
});

describe('security baseline control', () => {
  it('opens in price mode with the governed market baseline still named', () => {
    renderHistory();
    expect(screen.getByRole('button', { name: 'US baseline: No baseline' })).toBeInTheDocument();
    expect(screen.getByTestId('security-chart-stub')).toHaveAttribute('data-mode', 'price');
    expect(screen.getByTestId('security-chart-basis')).toHaveTextContent('Raw OHLC price candles');
    expect(screen.getByTestId('security-chart-baseline')).toHaveTextContent('Baseline: QQQ · governed US market index');
    expect(screen.getByTestId('security-baseline-scope')).toHaveTextContent('no separate model-benchmark series');
  });

  it('selects the governed market baseline through the shared control', async () => {
    mocks.loadMarketBaseline.mockResolvedValue(evidence({ symbol: 'QQQ', bars: baselineBars, events: [], bindings: [] }));
    renderHistory();
    fireEvent.click(screen.getByRole('button', { name: 'US baseline: No baseline' }));
    fireEvent.click(screen.getByRole('option', { name: /QQQ/ }));

    await waitFor(() => expect(screen.getByTestId('security-chart-stub')).toHaveAttribute('data-mode', 'baseline'));
    expect(mocks.loadMarketBaseline).toHaveBeenCalledWith('us', '2026-01-31');
    expect(screen.getByRole('button', { name: 'US baseline: QQQ' })).toBeInTheDocument();
    expect(screen.getByTestId('security-chart-basis')).toHaveTextContent('Open-to-open price return');
    expect(screen.getByTestId('security-chart-basis')).toHaveTextContent('not total return');
  });

  it('keeps a governed self-comparison unavailable and explains it', () => {
    renderHistory([run], evidence({ symbol: 'QQQ', name: 'QQQ' }));
    expect(screen.getByTestId('security-baseline-disabled')).toHaveTextContent('No self-comparison baseline');
    fireEvent.click(screen.getByRole('button', { name: 'US baseline: No baseline' }));
    expect(screen.getByRole('option', { name: /QQQ/ })).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByTestId('security-chart-stub')).toHaveAttribute('data-mode', 'price');
  });
});

describe('governed indicators', () => {
  it('offers the instrument entries and defaults to one SMA 20 price overlay', async () => {
    renderHistory([run], evidence({ bars: longBars }));
    const chart = screen.getByTestId('security-chart-stub');
    await waitFor(() => expect(chart).toHaveAttribute('data-overlays', 'instrument_sma_20:value'));

    fireEvent.click(screen.getByRole('button', { name: 'US indicators: 1 active' }));
    const group = screen.getByRole('group', { name: 'US chart indicators' });
    for (const label of [
      'SMA 20', 'SMA 50', 'SMA 200', 'EMA 12', 'EMA 26', 'RSI 14',
      'MACD 12/26/9', 'Bollinger 20/2', 'Volume SMA 20', 'VIX', 'VIX SMA 20',
    ]) {
      expect(within(group).getByText(label, { exact: true })).toBeInTheDocument();
    }
    expect(within(group).getByRole('button', { name: /^SMA 20 Price pane/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('indicator-legend')).toHaveTextContent('SMA 20');
    expect(screen.getByTestId('indicator-disclosure')).toHaveTextContent('not a signal');
  });

  it('adds a dedicated indicator pane series on toggle without remounting the chart', async () => {
    renderHistory([run], evidence({ bars: longBars }));
    const chart = screen.getByTestId('security-chart-stub');
    fireEvent.click(screen.getByRole('button', { name: 'US indicators: 1 active' }));
    fireEvent.click(screen.getByRole('button', { name: /RSI 14/ }));

    await waitFor(() => expect(chart).toHaveAttribute(
      'data-overlays',
      'instrument_sma_20:value,instrument_rsi_14:value',
    ));
    expect(screen.getByTestId('security-chart-stub')).toBe(chart);
    expect(screen.getByTestId('indicator-legend')).toHaveTextContent('RSI 14');
  });

  it('reports insufficient history as an omitted series with the exact reason', async () => {
    renderHistory();
    await waitFor(() => expect(screen.getByTestId('indicator-unavailable')).toBeInTheDocument());
    const note = screen.getByTestId('indicator-unavailable');
    expect(note).toHaveTextContent('SMA 20 omitted.');
    expect(note).toHaveTextContent('Indicator needs 20 observations but received 3.');
    expect(screen.queryByTestId('indicator-legend')).not.toBeInTheDocument();
  });

  it('offers VIX on a US chart and states the withdrawn data plane rather than fabricating a series', async () => {
    renderHistory([run], evidence({ bars: longBars }));
    await waitFor(() => expect(screen.getByTestId('indicator-vix-unavailable')).toBeInTheDocument());
    expect(mocks.readMarketEvidence).toHaveBeenCalledWith('us', 'VIX');
    const note = screen.getByTestId('indicator-vix-unavailable');
    expect(note).toHaveTextContent('VIX unavailable.');
    expect(note).toHaveTextContent('no published price history');
    expect(note).toHaveTextContent('No substitute series is shown.');

    fireEvent.click(screen.getByRole('button', { name: 'US indicators: 1 active' }));
    const group = screen.getByRole('group', { name: 'US chart indicators' });
    expect(within(group).getByRole('button', { name: /^VIX Unavailable/ })).toHaveTextContent('Unavailable');
  });

  it('never offers VIX or reads a cross-market series on a CN chart', async () => {
    renderHistory([run], evidence({ market: 'cn', symbol: '002594', name: 'BYD', bars: longBars }));
    expect(mocks.readMarketEvidence).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'CN indicators: 1 active' }));
    expect(screen.queryByText('VIX', { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText('VIX SMA 20', { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByTestId('indicator-vix-unavailable')).not.toBeInTheDocument();
  });
});

describe('entity workspace kinds', () => {
  it('renders the instrument shell for a selected-pool candidate', () => {
    renderHistory([run], evidence({ roles: ['selected_pool_candidate'], benchmark: 'QQQ' }));
    expect(screen.getByTestId('entity-workspace')).toHaveAttribute('data-entity-kind', 'instrument');
    expect(screen.getByTestId('entity-kind-badge')).toHaveTextContent('Instrument');
    expect(screen.getByTestId('entity-facts')).toHaveTextContent('Selected pool candidate');
    expect(screen.queryByTestId('entity-role-context')).not.toBeInTheDocument();
  });

  it('derives the index badge from the governed benchmark role', () => {
    renderHistory([run], evidence({
      symbol: 'QQQ',
      name: 'QQQ',
      roles: ['benchmark', 'formal_traded'],
      benchmark: 'QQQ',
    }));
    expect(screen.getByTestId('entity-workspace')).toHaveAttribute('data-entity-kind', 'index');
    expect(screen.getByTestId('entity-kind-badge')).toHaveTextContent('Index');
    expect(screen.getByTestId('entity-facts')).toHaveTextContent('Market benchmark');
    expect(screen.getByTestId('entity-role-context')).toBeInTheDocument();
    expect(screen.getByTestId('entity-role-kind')).toHaveTextContent('Index');
  });

  it('derives the reference badge from a governed auxiliary role and omits unbound model evidence', () => {
    renderHistory([run], evidence({
      symbol: 'SPX',
      name: 'S&P 500',
      roles: ['formal_auxiliary'],
      benchmark: 'QQQ',
      events: [],
      bindings: [],
    }));
    expect(screen.getByTestId('entity-workspace')).toHaveAttribute('data-entity-kind', 'reference');
    expect(screen.getByTestId('entity-kind-badge')).toHaveTextContent('Reference');
    expect(screen.getByTestId('entity-facts')).toHaveTextContent('Formal auxiliary');
    expect(screen.getByTestId('entity-role-context')).toHaveTextContent('Formal auxiliary');
    expect(screen.queryByRole('region', { name: 'Historical model event ledger' })).not.toBeInTheDocument();
    expect(screen.queryByText('No retained model events for this instrument and selection.')).not.toBeInTheDocument();
    expect(screen.queryByTestId('related-models')).not.toBeInTheDocument();
  });

  it('keeps a traded index on the real bound event ledger', () => {
    renderHistory([run], evidence({
      symbol: 'QQQ',
      name: 'QQQ',
      roles: ['benchmark', 'formal_traded'],
      benchmark: 'QQQ',
    }));
    expect(screen.getByRole('region', { name: 'Historical model event ledger' })).toBeInTheDocument();
    expect(screen.getByTestId('entity-workspace')).toHaveAttribute('data-entity-kind', 'index');
  });

  it('uses one shared chart disclosure on instrument and index pages', () => {
    renderHistory([run], evidence({ roles: ['selected_pool_candidate'] }));
    expect(screen.getByTestId('entity-chart-disclosure')).toHaveTextContent(
      'Historical research evidence, not a live signal or fill.',
    );
  });
});

describe('related models panel', () => {
  const multiModelEvidence = () => evidence({
    events: [
      { time: '2026-01-05', model_id: 'qqq_v1', run_id: 'run-1', instrument_id: 'us:AAPL', action: 'BUY', previous_weight: 0, target_weight: 0.5, reason: 'frozen_rule' },
      { time: '2026-01-06', model_id: 'qqq_v2', run_id: 'run-2', instrument_id: 'us:AAPL', action: 'SELL', previous_weight: 0.5, target_weight: 0, reason: 'frozen_rule' },
      { time: '2026-01-08', model_id: 'qqq_v2', run_id: 'run-2', instrument_id: 'us:AAPL', action: 'BUY', previous_weight: 0, target_weight: 0.5, reason: 'frozen_rule' },
    ],
    bindings: [
      { model_version_id: 'qqq_v1', run_id: 'run-1', bundle_id: 'c'.repeat(64) },
      { model_version_id: 'qqq_v2', run_id: 'run-2', bundle_id: 'e'.repeat(64) },
    ],
  });

  it('lists each bound model with event count, last action and a model route', async () => {
    mocks.readLatestPublishedHolding.mockImplementation(async (candidate: GovernedRunSummary) => (
      candidate.modelVersionId === 'qqq_v2'
        ? { status: 'held', weight: 0.25, asOf: '2026-01-30', cutoff: '2026-01-31', instrument: 'AAPL' }
        : { status: 'not_held', asOf: '2026-01-30', cutoff: '2026-01-31' }
    ));
    renderHistory([run, runTwo], multiModelEvidence());

    await waitFor(() => expect(screen.getAllByTestId('related-model')).toHaveLength(2));
    const rows = screen.getAllByTestId('related-model');
    expect(rows[0]).toHaveAttribute('data-model-id', 'qqq_v2');
    expect(rows[0]).toHaveTextContent('2 retained events · last Buy on 2026-01-08');
    expect(rows[0]).toHaveTextContent('Held at last publication · 25.0% · as of 2026-01-30 · cutoff 2026-01-31');
    expect(rows[1]).toHaveAttribute('data-model-id', 'qqq_v1');
    expect(rows[1]).toHaveTextContent('1 retained event · last Buy on 2026-01-05');
    const panel = within(screen.getByTestId('related-models'));
    expect(panel.getByRole('link', { name: 'QQQ Rotation Two' })).toHaveAttribute('href', '/strategies/qqq_v2');
    expect(panel.getByRole('link', { name: 'QQQ Rotation' })).toHaveAttribute('href', '/strategies/qqq_v1');
  });

  it('states the reason when a bound run has no available portfolio section', async () => {
    mocks.readLatestPublishedHolding.mockResolvedValue({
      status: 'unavailable',
      reason: 'Run section is not Bundle v2-backed: formal:family:qqq_v1:run-1',
    });
    renderHistory([run], evidence());
    await waitFor(() => expect(screen.getByTestId('related-model-holding')).toHaveAttribute('data-holding-status', 'unavailable'));
    expect(screen.getByTestId('related-model-holding')).toHaveTextContent(
      'Latest holdings unavailable · Run section is not Bundle v2-backed',
    );
  });

  it('includes a model held at last publication even without retained events', async () => {
    mocks.readLatestPublishedHolding.mockResolvedValue({
      status: 'held',
      weight: 0.75,
      asOf: '2026-01-30',
      cutoff: '2026-01-31',
      instrument: 'AAPL',
    });
    renderHistory([run], evidence({ events: [] }));
    await waitFor(() => expect(screen.getByTestId('related-model')).toHaveAttribute('data-model-id', 'qqq_v1'));
    expect(screen.getByTestId('related-model-events')).toHaveTextContent('No retained trade events');
    expect(screen.getByTestId('related-model-holding')).toHaveTextContent('Held at last publication · 75.0%');
  });

  it('renders nothing when no bound model traded or held the instrument', async () => {
    renderHistory([run], evidence({ events: [], bindings: [] }));
    expect(screen.queryByTestId('related-models')).not.toBeInTheDocument();
    expect(screen.queryByTestId('related-model')).not.toBeInTheDocument();
    expect(mocks.readLatestPublishedHolding).not.toHaveBeenCalled();
  });
});

describe('any-entity compare mode', () => {
  const compareEvidence = (symbol: string, name: string, market: 'us' | 'cn' = 'us') => evidence({
    market,
    symbol,
    name,
    bars: longBars,
    events: [],
    bindings: [],
  });

  it('indexes the page instrument and adds same-market model and instrument overlays', async () => {
    mocks.readMarketEvidence.mockImplementation(async (market: 'us' | 'cn', symbol: string) => (
      compareEvidence(symbol, symbol, market)
    ));
    renderHistory([run], evidence({ bars: longBars }));

    fireEvent.click(screen.getByTestId('security-compare-toggle'));
    expect(screen.getByTestId('security-chart-stub')).toHaveAttribute('data-mode', 'compare');
    expect(screen.getByTestId('compare-scope')).toHaveTextContent('Same-market comparison only');
    expect(screen.getByTestId('compare-scope')).toHaveTextContent('Compare shows indexed strength only');
    expect(screen.getByTestId('compare-scope')).toHaveTextContent(
      'Model buy/sell markers, price indicators and volume are hidden',
    );
    expect(screen.getByTestId('compare-exit')).toHaveTextContent(
      'Exit compare to show markers and indicators',
    );
    await waitFor(() => expect(mocks.loadSecurityCatalog).toHaveBeenCalledWith('us'));

    fireEvent.click(screen.getByTestId('compare-control-trigger'));
    expect(screen.getByTestId('compare-search')).toHaveAttribute('placeholder', 'Search symbol, name or model');
    expect(screen.getByTestId('compare-option-model:us:qqq_v1')).toBeInTheDocument();
    // The page's own instrument is never offered again.
    expect(screen.queryByTestId('compare-option-instrument:us:AAPL')).not.toBeInTheDocument();
    expect(screen.getByTestId('compare-option-instrument:us:MSFT')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('compare-option-instrument:us:MSFT'));
    await waitFor(() => expect(screen.getByTestId('security-chart-stub')).toHaveAttribute(
      'data-overlays',
      expect.stringContaining('instrument:us:MSFT'),
    ));
    expect(screen.getByTestId('compare-legend')).toHaveTextContent('MSFT');
    expect(screen.getByTestId('security-chart-basis')).toHaveTextContent(/Indexed to 100 at the exact common start \d{4}-\d{2}-\d{2}/);
    // The base instrument is part of the same indexed window.
    expect(screen.getByTestId('security-chart-stub')).toHaveAttribute('data-overlays', expect.stringContaining('base:instrument'));

    fireEvent.click(screen.getByRole('button', { name: 'Remove MSFT from comparison' }));
    await waitFor(() => expect(screen.queryByTestId('compare-legend-instrument:us:MSFT')).not.toBeInTheDocument());
    expect(screen.getByTestId('security-chart-stub')).toHaveAttribute('data-overlay-count', '1');
    expect(screen.getByTestId('security-chart-stub')).toHaveAttribute('data-mode', 'compare');

    // The compare note names the trade-off and offers an obvious keyboard exit.
    const exit = screen.getByTestId('compare-exit');
    exit.focus();
    expect(exit).toHaveFocus();
    fireEvent.click(exit);
    expect(screen.getByTestId('security-chart-stub')).toHaveAttribute('data-mode', 'price');
    expect(screen.queryByTestId('compare-scope')).not.toBeInTheDocument();
  });

  it('enforces the four-overlay cap with a visible message and disabled extras', async () => {
    mocks.readMarketEvidence.mockImplementation(async (market: 'us' | 'cn', symbol: string) => (
      compareEvidence(symbol, symbol, market)
    ));
    renderHistory([run], evidence({ bars: longBars }));
    fireEvent.click(screen.getByTestId('security-compare-toggle'));
    fireEvent.click(screen.getByTestId('compare-control-trigger'));
    await waitFor(() => expect(screen.getByTestId('compare-option-instrument:us:AMD')).toBeInTheDocument());
    for (const symbol of ['AMD', 'GOOG', 'MSFT', 'NVDA']) {
      fireEvent.click(screen.getByTestId(`compare-option-instrument:us:${symbol}`));
    }
    await waitFor(() => expect(screen.getByTestId('security-chart-stub')).toHaveAttribute('data-overlay-count', '5'));
    expect(screen.getByTestId('compare-max-message')).toHaveTextContent('Compare is limited to 4 overlays');
    expect(screen.getByTestId('compare-option-instrument:us:QQQ')).toHaveAttribute('aria-disabled', 'true');
  });

  it('deduplicates the active market baseline by entity identity', async () => {
    mocks.loadMarketBaseline.mockResolvedValue(evidence({ symbol: 'QQQ', name: 'Invesco QQQ Trust', bars: baselineBars, events: [], bindings: [] }));
    renderHistory();
    fireEvent.click(screen.getByRole('button', { name: 'US baseline: No baseline' }));
    fireEvent.click(screen.getByRole('option', { name: /QQQ/ }));
    await waitFor(() => expect(screen.getByTestId('security-chart-stub')).toHaveAttribute('data-mode', 'baseline'));

    fireEvent.click(screen.getByTestId('security-compare-toggle'));
    fireEvent.click(screen.getByTestId('compare-control-trigger'));
    await waitFor(() => expect(screen.getByTestId('compare-option-instrument:us:QQQ')).toBeInTheDocument());
    const qqq = screen.getByTestId('compare-option-instrument:us:QQQ');
    expect(qqq).toHaveAttribute('aria-disabled', 'true');
    expect(qqq).toHaveTextContent('Already displayed as the QQQ baseline.');
    // The baseline is already part of the indexed legend, not a duplicate line.
    expect(screen.getByTestId('compare-legend-baseline:market')).toHaveTextContent('QQQ');
  });

  it('shows an unavailable entity reason and never plots its series', async () => {
    mocks.loadFormalNav.mockRejectedValue(new Error('Formal NAV projection is unavailable for this run.'));
    renderHistory([run], evidence({ bars: longBars }));
    fireEvent.click(screen.getByTestId('security-compare-toggle'));
    fireEvent.click(screen.getByTestId('compare-control-trigger'));
    fireEvent.click(screen.getByTestId('compare-option-model:us:qqq_v1'));
    await waitFor(() => expect(screen.getByTestId('compare-unavailable-model:us:qqq_v1')).toBeInTheDocument());
    expect(screen.getByTestId('compare-unavailable-model:us:qqq_v1')).toHaveTextContent(
      'Not plotted: Formal NAV projection is unavailable for this run.',
    );
    expect(screen.getByTestId('security-chart-stub')).not.toHaveAttribute(
      'data-overlays',
      expect.stringContaining('model:us:qqq_v1'),
    );
    expect(screen.getByTestId('security-chart-stub')).toHaveAttribute('data-overlays', 'base:instrument');
  });

  it('never offers a model or instrument from another market', async () => {
    renderHistory([run], evidence({ market: 'cn', symbol: '002594', name: 'BYD', bars: longBars }));
    expect(screen.queryByTestId('compare-control-trigger')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('security-compare-toggle'));
    await waitFor(() => expect(mocks.loadSecurityCatalog).toHaveBeenCalledWith('cn'));
    fireEvent.click(screen.getByTestId('compare-control-trigger'));
    expect(screen.getByTestId('compare-option-instrument:cn:000001')).toBeInTheDocument();
    expect(screen.queryByTestId('compare-option-instrument:us:MSFT')).not.toBeInTheDocument();
    // The only formal run in this fixture is US, so no CN model is offered.
    expect(screen.queryByTestId('compare-option-model:us:qqq_v1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('compare-option-model:cn:qqq_v1')).not.toBeInTheDocument();
  });
});
