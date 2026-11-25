import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { ReportRow } from '@/lib/types';
import { StrategyChartHero } from './StrategyChartHero';

const mocks = vi.hoisted(() => ({
  loadFormalNav: vi.fn(),
  loadRunSection: vi.fn(),
  loadSecurityEvidence: vi.fn(),
  loadSecurityCatalog: vi.fn(),
}));

vi.mock('@/lib/formal-nav', () => ({ loadFormalNav: mocks.loadFormalNav }));
vi.mock('@/lib/governed-run', () => ({ loadRunSection: mocks.loadRunSection }));
vi.mock('@/lib/market-evidence-cache', () => ({
  readMarketEvidence: (market: string, symbol?: string) => mocks.loadSecurityEvidence(
    market,
    symbol ?? (market === 'cn' ? '000300' : 'QQQ'),
  ),
}));
vi.mock('@/lib/security-evidence', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/security-evidence')>();
  return {
    ...actual,
    loadSecurityEvidence: mocks.loadSecurityEvidence,
    loadSecurityCatalog: mocks.loadSecurityCatalog,
  };
});

vi.mock('@/components/charts/BaselineControl', () => ({
  BaselineControl: ({ options, value, onChange, marketLabel }: {
    options: Array<{ key: string; label: string; kind: string; available: boolean }>;
    value: string;
    onChange: (kind: string) => void;
    marketLabel: string;
  }) => (
    <div data-testid="baseline-control" data-value={value} data-market={marketLabel}>
      {options.map(option => (
        <button
          key={option.key}
          type="button"
          aria-label={`${option.label} ${option.kind}`}
          disabled={!option.available}
          onClick={() => onChange(option.kind)}
        >
          {option.label}
        </button>
      ))}
    </div>
  ),
}));

vi.mock('@/components/charts/CompareControl', () => ({
  CompareControl: ({ options, selected, onToggle, max, displayed }: {
    options: Array<{ id: string; label: string; available: boolean; reason?: string }>;
    selected: Array<{ id: string }>;
    onToggle: (id: string) => void;
    max: number;
    displayed: ReadonlyMap<string, string>;
  }) => {
    const atLimit = selected.length >= max;
    return (
      <div data-testid="model-compare-control" data-max={max}>
        {options.map(option => {
          const alreadySelected = selected.some(item => item.id === option.id);
          const duplicateReason = displayed.get(option.id);
          const blocked = !option.available || (atLimit && !alreadySelected);
          return (
            <button
              key={option.id}
              type="button"
              data-testid={`model-option-${option.id}`}
              aria-disabled={blocked || undefined}
              onClick={() => { if (!blocked || alreadySelected) onToggle(option.id); }}
            >
              {option.label}
              {option.reason ? ` — ${option.reason}` : ''}
              {duplicateReason ? ` — ${duplicateReason}` : ''}
            </button>
          );
        })}
        <span data-testid="model-compare-count">{selected.length}</span>
        {atLimit && <span data-testid="model-compare-max">Compare is limited to {max} overlays.</span>}
      </div>
    );
  },
}));

vi.mock('@/components/charts/NavChart', () => ({
  NavChart: (props: {
    series: unknown[];
    markers: Array<{ date: string }>;
    periodLabel: string;
    summaryLabel?: string;
    coverage?: { state: string };
    markerScope?: string;
    onMarkerSelect?: (marker: { date: string }) => void;
  }) => (
    <div
      data-testid="nav-chart-stub"
      data-period={props.periodLabel}
      data-summary={props.summaryLabel ?? ''}
      data-series={JSON.stringify(props.series)}
      data-series-count={props.series.length}
      data-marker-count={props.markers.length}
      data-marker-scope={props.markerScope ?? ''}
      data-coverage-state={props.coverage?.state ?? ''}
    >
      <button
        type="button"
        onClick={() => {
          const first = props.markers[0];
          if (first && props.onMarkerSelect) props.onMarkerSelect(first);
        }}
      >
        select first marker
      </button>
    </div>
  ),
}));

const DAY_MS = 86_400_000;

function makeRun(overrides: Partial<GovernedRunSummary> = {}): GovernedRunSummary {
  return {
    key: 'us:qqq_v1',
    modelFamilyId: 'qqq-family',
    modelVersionId: 'qqq_v1',
    runId: 'run-qqq',
    bundleId: 'b'.repeat(64),
    title: 'QQQ Rotation',
    modelKind: 'rules_based_allocation',
    channel: 'formal',
    publicationStatus: 'accepted_formal_baseline',
    market: 'us',
    benchmark: 'QQQ',
    generatedAt: '2026-01-12T00:00:00Z',
    evidenceCutoff: '2026-01-11',
    evidenceStatus: 'complete',
    decisionStatus: 'supported',
    manifestPath: null,
    manifestSha256: null,
    summary: {},
    manifest: null,
    loadWarnings: [],
    ...overrides,
  };
}

function makeRows(start = '2025-01-01', count = 76, stepDays = 5): ReportRow[] {
  const startMs = Date.parse(`${start}T00:00:00Z`);
  return Array.from({ length: count }, (_, index) => ({
    date: new Date(startMs + index * stepDays * DAY_MS).toISOString().slice(0, 10),
    account: 100 + index,
    bench_qqq: 200 + index * 0.5,
  }));
}

const rows = makeRows();
/** Weekly VIX observations cover the 1Y test window and exceed the SMA 20 warm-up. */
const vixBars = Array.from({ length: 60 }, (_, index) => {
  const time = new Date(Date.UTC(2025, 0, 1 + index * 7)).toISOString().slice(0, 10);
  const close = 14 + Math.sin(index / 4) * 3;
  return { time, open: close, high: close + 0.5, low: close - 0.5, close, volume: 0 };
});
const run = makeRun();
const overlayRun = makeRun({
  key: 'us:us_x1_3',
  modelFamilyId: 'us_ranker',
  modelVersionId: 'us_x1_3',
  runId: 'run-us-x1',
  title: 'US x1.3',
});
const cnRun = makeRun({
  key: 'cn:cn_27_v1_3',
  modelFamilyId: 'cn_27_rotation',
  modelVersionId: 'cn_27_v1_3',
  runId: 'run-cn',
  title: 'CN_27 V1.3',
  market: 'cn',
  benchmark: '000300',
});
const overlayRows = makeRows('2025-02-10', 68, 5);

function renderHero(value: GovernedRunSummary = run, catalog: GovernedRunSummary[] = [value]) {
  return render(
    <MemoryRouter>
      <StrategyChartHero run={value} runs={catalog} />
    </MemoryRouter>,
  );
}

function loadedSeries(): Array<{ key: string; label: string; nav: Array<{ date: string; value: number }> }> {
  return JSON.parse(screen.getByTestId('nav-chart-stub').getAttribute('data-series') ?? '[]');
}

beforeEach(() => {
  window.localStorage.clear();
  mocks.loadFormalNav.mockReset().mockResolvedValue({ rows });
  mocks.loadRunSection.mockReset().mockResolvedValue([]);
  mocks.loadSecurityEvidence.mockReset().mockImplementation(async (_market: string, symbol: string) => {
    if (symbol === 'VIX') return { bars: vixBars };
    throw new Error('Unexpected market evidence read.');
  });
  mocks.loadSecurityCatalog.mockReset().mockResolvedValue({
    market: 'us',
    cutoff: '2026-01-31',
    provider_manifest_sha256: 'a'.repeat(64),
    symbols: [{
      symbol: 'AAPL', name: 'Apple', instrument_id: 'us:AAPL', path: 'symbols/AAPL.json',
      sha256: 'a'.repeat(64), source_sha256: 'a'.repeat(64), source_instruments: ['AAPL'], roles: [],
    }],
    formal_bindings: [],
    benchmark: 'QQQ',
  });
});

describe('StrategyChartHero', () => {
  it('renders the default 1Y declared comparison without requesting market evidence', async () => {
    renderHero();
    const chart = await screen.findByTestId('strategy-nav-chart');

    expect(mocks.loadFormalNav).toHaveBeenCalledTimes(1);
    expect(mocks.loadRunSection).toHaveBeenCalledWith(run, 'trades');
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledTimes(1);
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledWith('us', 'VIX');

    const horizons = within(screen.getByRole('group', { name: 'Chart horizon' }));
    expect(horizons.getAllByRole('button').map(button => button.textContent)).toEqual([
      '1W', '1M', '3M', '1Y', '2Y', '3Y', 'ALL',
    ]);
    expect(horizons.getByRole('button', { name: '1Y' })).toHaveAttribute('aria-pressed', 'true');
    expect(horizons.getByRole('button', { name: 'ALL' })).toHaveAttribute('aria-pressed', 'false');

    expect(screen.getByTestId('baseline-control')).toHaveAttribute('data-market', 'US');
    expect(screen.getByTestId('baseline-control')).toHaveAttribute('data-value', 'declared');
    expect(screen.getByTestId('hero-period-return')).toHaveTextContent('+71.6%');
    expect(screen.getByTestId('hero-window')).toHaveTextContent('2025-01-11 – 2026-01-11');
    expect(screen.getByTestId('strategy-chart-hero')).toHaveTextContent('74 observations');
    expect(screen.queryByTestId('hero-window-stale')).not.toBeInTheDocument();
    expect(screen.getByTestId('hero-excess-return')).toHaveTextContent('browser-derived, not a sealed metric');
    expect(chart.querySelector('[data-testid="nav-chart-stub"]')).toHaveAttribute('data-period', '1Y');
    expect(screen.getByTestId('nav-chart-stub').getAttribute('data-summary')).toContain('1Y window');
    expect(screen.getByTestId('nav-chart-stub').getAttribute('data-series-count')).toBe('2');
  });

  it('changes horizon without refetching the NAV projection', async () => {
    renderHero();
    await screen.findByTestId('strategy-nav-chart');

    fireEvent.click(screen.getByRole('button', { name: '1M' }));

    expect(screen.getByRole('button', { name: '1M' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('hero-period-note')).toHaveTextContent('1M window · 7 observations');
    expect(screen.getByTestId('hero-period-return')).toHaveTextContent('+3.6%');
    expect(screen.getByTestId('hero-period-return')).not.toHaveTextContent('0.0%');
    expect(mocks.loadFormalNav).toHaveBeenCalledTimes(1);
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledTimes(1);
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledWith('us', 'VIX');
  });

  it('reports a too-short weekly window as unavailable instead of a zero return', async () => {
    mocks.loadFormalNav.mockResolvedValueOnce({
      rows: [
        { date: '2025-12-20', account: 100, bench_qqq: 200 },
        { date: '2026-01-05', account: 110, bench_qqq: 202 },
        { date: '2026-01-11', account: 120, bench_qqq: 204 },
      ],
    });
    renderHero();
    await screen.findByTestId('strategy-nav-chart');

    fireEvent.click(screen.getByRole('button', { name: '1W' }));

    const value = screen.getByTestId('hero-period-return');
    expect(value).toHaveTextContent('—');
    expect(value.textContent).not.toContain('0.0%');
    expect(screen.getByTestId('hero-period-note')).toHaveTextContent('Only 2 valid observations in this window.');
    expect(screen.getByTestId('nav-chart-stub')).toHaveAttribute('data-coverage-state', 'partial');
  });

  it('scopes a market baseline failure and reverts to the declared baseline', async () => {
    mocks.loadSecurityEvidence.mockImplementation(async (_market: string, symbol: string) => {
      if (symbol === 'VIX') return { bars: vixBars };
      throw new Error('market evidence offline');
    });
    renderHero();
    await screen.findByTestId('strategy-nav-chart');

    fireEvent.click(screen.getByRole('button', { name: 'QQQ market' }));

    await waitFor(() => expect(screen.getByTestId('strategy-baseline-error')).toBeInTheDocument());
    expect(screen.getByTestId('strategy-baseline-error')).toHaveTextContent('Market baseline unavailable');
    expect(screen.getByTestId('strategy-baseline-error')).toHaveTextContent('Reverted to the declared baseline (QQQ)');
    expect(screen.getByTestId('baseline-control')).toHaveAttribute('data-value', 'declared');
    expect(screen.getByTestId('hero-period-return')).toHaveTextContent('+71.6%');
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledTimes(2);
  });

  it('loads the governed market baseline only after selection and reuses it', async () => {
    mocks.loadSecurityEvidence.mockResolvedValue({
      bars: rows.map((row, index) => ({ time: row.date, open: 200 + index })),
    });
    renderHero();
    await screen.findByTestId('strategy-nav-chart');
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledTimes(1);
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledWith('us', 'VIX');

    fireEvent.click(screen.getByRole('button', { name: 'QQQ market' }));

    await waitFor(() => expect(screen.getByTestId('baseline-control')).toHaveAttribute('data-value', 'market'));
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledWith('us', 'QQQ');
    expect(screen.getByTestId('nav-chart-stub').getAttribute('data-series-count')).toBe('2');
    expect(screen.getByTestId('nav-chart-stub').getAttribute('data-summary')).toContain('QQQ');
    expect(screen.getByTestId('hero-excess-return')).toHaveTextContent('Excess vs QQQ');

    fireEvent.click(screen.getByRole('button', { name: 'QQQ market' }));
    await waitFor(() => expect(screen.getByTestId('baseline-control')).toHaveAttribute('data-value', 'market'));
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledTimes(2);
  });

  it('shows the stale window chip when the evidence cutoff leads the last observation', async () => {
    renderHero(makeRun({ evidenceCutoff: '2026-03-01' }));
    await screen.findByTestId('strategy-nav-chart');

    expect(screen.getByTestId('hero-window-stale')).toHaveTextContent('Stale by 49 days');
    expect(screen.getByText(/As of 2026-01-11/)).toBeInTheDocument();
  });

  it('shows contract-frozen lifecycle wording instead of the stale chip', async () => {
    renderHero(makeRun({
      evidenceCutoff: '2026-03-01',
      lifecycleStatus: 'contract_frozen_prospective_pending',
      contractFrozenThrough: '2026-01-11',
      prospectiveGateStatus: 'pending',
    }));
    await screen.findByTestId('strategy-nav-chart');

    expect(screen.getByTestId('hero-window-frozen')).toHaveTextContent(
      'Frozen historical evidence through 2026-01-11 · prospective validation pending',
    );
    expect(screen.queryByTestId('hero-window-stale')).not.toBeInTheDocument();
  });

  it('keeps an unavailable declared baseline visible and defaults a CN run to none', async () => {
    const cnRows: ReportRow[] = rows.map((row, index) => ({
      date: row.date,
      account: row.account,
      benchmark_account: 100 + index,
    }));
    mocks.loadFormalNav.mockResolvedValueOnce({ rows: cnRows });
    renderHero(makeRun({ key: 'cn:cn_v1', modelVersionId: 'cn_v1', runId: 'run-cn', market: 'cn', benchmark: '000300' }));
    await screen.findByTestId('strategy-nav-chart');

    expect(screen.getByTestId('baseline-control')).toHaveAttribute('data-market', 'CN');
    expect(screen.getByTestId('baseline-control')).toHaveAttribute('data-value', 'none');
    expect(screen.getByRole('button', { name: '000300 declared' })).toBeDisabled();
    expect(screen.getByTestId('hero-baseline-return')).toHaveTextContent('No baseline');
    expect(mocks.loadSecurityEvidence).not.toHaveBeenCalled();
  });

  it('opens a selected rotation marker panel with retained trade details', async () => {
    mocks.loadRunSection.mockResolvedValue([
      {
        date: '2026-01-11',
        action: 'BUY',
        instrument: 'AAPL',
        previous_weight: 0,
        target_weight: 0.5,
        reason: 'momentum',
      },
    ]);
    renderHero();
    await screen.findByTestId('strategy-nav-chart');

    fireEvent.click(screen.getByRole('button', { name: 'select first marker' }));
    const panel = screen.getByTestId('strategy-selected-marker');
    expect(panel).toHaveTextContent('2026-01-11');
    expect(panel).toHaveTextContent('Buy / increase');
    expect(panel).toHaveTextContent('AAPL');
    expect(panel).toHaveTextContent('momentum');
    expect(panel).toHaveTextContent('+50.0%');
    expect(panel).toHaveTextContent('not establish an execution price');

    fireEvent.click(within(panel).getByRole('button', { name: 'Clear marker' }));
    expect(screen.queryByTestId('strategy-selected-marker')).not.toBeInTheDocument();
  });

  it('offers only other same-market formal models and never the base or a cross-market run', async () => {
    renderHero(run, [run, overlayRun, cnRun]);
    await screen.findByTestId('strategy-nav-chart');

    expect(screen.getByTestId('model-compare-control')).toHaveAttribute('data-max', '3');
    expect(screen.getByTestId('model-option-model:us:us_x1_3')).toBeInTheDocument();
    expect(screen.queryByTestId('model-option-model:us:qqq_v1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('model-option-model:cn:cn_27_v1_3')).not.toBeInTheDocument();
  });

  it('adds one same-market model on one indexed axis, links its legend and removes it', async () => {
    mocks.loadFormalNav.mockImplementation(async (target: GovernedRunSummary) => ({
      rows: target.modelVersionId === 'us_x1_3' ? overlayRows : rows,
    }));
    mocks.loadRunSection.mockResolvedValue([
      { date: '2026-01-11', action: 'BUY', instrument: 'AAPL', previous_weight: 0, target_weight: 0.5, reason: 'momentum' },
    ]);
    renderHero(run, [run, overlayRun]);
    await screen.findByTestId('strategy-nav-chart');

    fireEvent.click(screen.getByTestId('model-option-model:us:us_x1_3'));

    await waitFor(() => expect(screen.getByTestId('nav-chart-stub')).toHaveAttribute('data-series-count', '3'));
    const series = loadedSeries();
    expect(series.map(item => item.key)).toEqual(['base', 'baseline', 'model:us:us_x1_3']);
    // The overlay starts on 2025-02-10; the base and baseline are rebased there,
    // never on their own 2025-01-11 period start.
    expect(series.find(item => item.key === 'base')?.nav[0]).toEqual({ date: '2025-02-10', value: 100 });
    expect(series.find(item => item.key === 'model:us:us_x1_3')?.nav[0]).toEqual({ date: '2025-02-10', value: 100 });
    expect(screen.getByTestId('nav-chart-stub')).toHaveAttribute('data-marker-count', '1');
    expect(screen.getByTestId('nav-chart-stub')).toHaveAttribute('data-marker-scope', 'base model (QQQ Rotation)');

    const legend = screen.getByTestId('compare-legend');
    const link = within(legend).getByRole('link', { name: 'US x1.3' });
    expect(link).toHaveAttribute('href', '/strategies/us_x1_3');
    expect(screen.getByTestId('compare-legend-model:us:us_x1_3').querySelector('[aria-hidden="true"]'))
      .toHaveStyle({ borderTop: '2px solid hsl(var(--chart-6))' });

    const disclosure = screen.getByTestId('strategy-model-comparison-disclosure');
    expect(disclosure).toHaveTextContent('exact common window');
    expect(disclosure).toHaveTextContent('base model (QQQ Rotation) only');
    expect(screen.getByTestId('nav-chart-stub').getAttribute('data-summary')).toContain('1Y exact common window');

    fireEvent.click(within(legend).getByRole('button', { name: 'Remove US x1.3 from comparison' }));
    await waitFor(() => expect(screen.getByTestId('nav-chart-stub')).toHaveAttribute('data-series-count', '2'));
    expect(screen.queryByTestId('compare-legend-model:us:us_x1_3')).not.toBeInTheDocument();
  });

  it('enforces the three-overlay cap and says why another model cannot be added', async () => {
    const extras = ['us_a', 'us_b', 'us_c'].map(id => makeRun({
      key: `us:${id}`,
      modelFamilyId: id,
      modelVersionId: id,
      runId: `run-${id}`,
      title: id.toUpperCase(),
    }));
    renderHero(run, [run, overlayRun, ...extras]);
    await screen.findByTestId('strategy-nav-chart');

    for (const id of ['model:us:us_a', 'model:us:us_b', 'model:us:us_c']) {
      fireEvent.click(screen.getByTestId(`model-option-${id}`));
    }
    expect(screen.getByTestId('model-compare-count')).toHaveTextContent('3');
    expect(screen.getByTestId('model-compare-max')).toHaveTextContent('Compare is limited to 3 overlays.');

    const fourth = screen.getByTestId('model-option-model:us:us_x1_3');
    expect(fourth).toHaveAttribute('aria-disabled', 'true');
    fireEvent.click(fourth);
    expect(screen.getByTestId('model-compare-count')).toHaveTextContent('3');
  });

  it('never offers a model that is already displayed as the active baseline', async () => {
    const benchmark = 'US x1.3';
    const baselineRows = makeRows().map((row, index) => ({
      date: row.date,
      account: row.account,
      bench_us_x1_3: 200 + index * 0.5,
    }));
    mocks.loadFormalNav.mockResolvedValue({ rows: baselineRows });
    const baselineRun = makeRun({ benchmark });
    renderHero(baselineRun, [baselineRun, overlayRun]);
    await screen.findByTestId('strategy-nav-chart');

    expect(screen.getByTestId('baseline-control')).toHaveAttribute('data-value', 'declared');
    const duplicate = screen.getByTestId('model-option-model:us:us_x1_3');
    expect(duplicate).toHaveAttribute('aria-disabled', 'true');
    expect(duplicate).toHaveTextContent('Already displayed as the active baseline.');
  });

  it('excludes a model whose verified NAV cannot be read and never plots it partially', async () => {
    mocks.loadFormalNav.mockImplementation(async (target: GovernedRunSummary) => {
      if (target.modelVersionId === 'us_x1_3') throw new Error('overlay offline');
      return { rows };
    });
    renderHero(run, [run, overlayRun]);
    await screen.findByTestId('strategy-nav-chart');

    fireEvent.click(screen.getByTestId('model-option-model:us:us_x1_3'));

    await waitFor(() => expect(screen.getByTestId('compare-unavailable-model:us:us_x1_3'))
      .toHaveTextContent('Verified NAV projection unavailable: overlay offline'));
    expect(screen.getByTestId('nav-chart-stub')).toHaveAttribute('data-series-count', '2');
    expect(loadedSeries().some(item => item.key === 'model:us:us_x1_3')).toBe(false);
  });

  it('re-windows the exact common window when the period changes', async () => {
    mocks.loadFormalNav.mockImplementation(async (target: GovernedRunSummary) => ({
      rows: target.modelVersionId === 'us_x1_3' ? overlayRows : rows,
    }));
    renderHero(run, [run, overlayRun]);
    await screen.findByTestId('strategy-nav-chart');

    fireEvent.click(screen.getByTestId('model-option-model:us:us_x1_3'));
    await waitFor(() => expect(screen.getByTestId('nav-chart-stub')).toHaveAttribute('data-series-count', '3'));
    const yearlyStart = loadedSeries().find(item => item.key === 'base')?.nav[0]?.date;

    fireEvent.click(screen.getByRole('button', { name: '1M' }));
    await waitFor(() => expect(screen.getByTestId('nav-chart-stub').getAttribute('data-summary'))
      .toContain('1M exact common window'));
    const monthlyStart = loadedSeries().find(item => item.key === 'base')?.nav[0]?.date;
    expect(monthlyStart).not.toBe(yearlyStart);
    expect(monthlyStart && yearlyStart && monthlyStart > yearlyStart).toBe(true);
  });

  it('renders a separate US VIX context pane with exact observed dates and the governed SMA', async () => {
    renderHero();
    await screen.findByTestId('strategy-nav-chart');

    const pane = await screen.findByTestId('strategy-vix-pane');
    expect(pane).toHaveTextContent('VIX · US market context');
    expect(pane).toHaveTextContent('Separate pane · one VIX axis · never a dual axis with NAV');
    await screen.findByTestId('strategy-vix-chart');
    expect(screen.getByTestId('strategy-vix-window')).toHaveTextContent('exact VIX observation');
    expect(screen.getByTestId('strategy-vix-window')).toHaveTextContent('2025-01-15');
    expect(screen.getByTestId('strategy-vix-data')).toBeInTheDocument();
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledWith('us', 'VIX');

    const toggle = screen.getByTestId('strategy-vix-sma-toggle');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(toggle).not.toBeDisabled();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('list', { name: 'VIX series' })).toHaveTextContent('VIX SMA 20');
  });

  it('shows an absent VIX series with the route-404 reason and no substitute', async () => {
    mocks.loadSecurityEvidence.mockImplementation(async (_market: string, symbol: string) => {
      if (symbol === 'VIX') throw new Error('Security history unavailable (404).');
      throw new Error('Unexpected market evidence read.');
    });
    renderHero();
    await screen.findByTestId('strategy-nav-chart');

    const note = await screen.findByTestId('strategy-vix-unavailable');
    expect(note).toHaveTextContent('404');
    expect(note).toHaveTextContent('No substitute series is shown');
    expect(screen.queryByTestId('strategy-vix-chart')).not.toBeInTheDocument();
  });

  it('never renders or reads VIX for a CN strategy chart', async () => {
    const cnRows: ReportRow[] = rows.map((row, index) => ({
      date: row.date,
      account: row.account,
      benchmark_account: 100 + index,
    }));
    mocks.loadFormalNav.mockResolvedValueOnce({ rows: cnRows });
    renderHero(cnRun);
    await screen.findByTestId('strategy-nav-chart');

    expect(screen.queryByTestId('strategy-vix-pane')).not.toBeInTheDocument();
    expect(mocks.loadSecurityEvidence).not.toHaveBeenCalledWith('us', 'VIX');
  });
});
