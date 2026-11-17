import type { ReactNode } from 'react';
import { createContext, useContext, useEffect } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { SecurityEvidence } from '@/lib/security-evidence';
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

const mocks = vi.hoisted(() => ({ loadMarketBaseline: vi.fn() }));

vi.mock('@/lib/security-baseline', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/security-baseline')>();
  return { ...actual, loadMarketBaseline: mocks.loadMarketBaseline };
});

vi.mock('@/components/SecurityLightweightChart', () => ({
  SecurityLightweightChart: ({ mode, markers, modelColorIndex }: {
    mode: string;
    markers: unknown[];
    modelColorIndex?: Map<string, number>;
  }) => (
    <div
      data-testid="security-chart-stub"
      data-mode={mode}
      data-markers={markers.length}
      data-model-colors={modelColorIndex ? [...modelColorIndex.keys()].join(',') : ''}
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

beforeEach(() => {
  window.localStorage.clear();
  mocks.loadMarketBaseline.mockReset();
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
