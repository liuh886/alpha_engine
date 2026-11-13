import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { ReportRow } from '@/lib/types';
import { StrategyChartHero } from './StrategyChartHero';

const mocks = vi.hoisted(() => ({
  loadFormalNav: vi.fn(),
  loadRunSection: vi.fn(),
  loadSecurityEvidence: vi.fn(),
}));

vi.mock('@/lib/formal-nav', () => ({ loadFormalNav: mocks.loadFormalNav }));
vi.mock('@/lib/governed-run', () => ({ loadRunSection: mocks.loadRunSection }));
vi.mock('@/lib/security-evidence', () => ({ loadSecurityEvidence: mocks.loadSecurityEvidence }));

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

vi.mock('@/components/charts/NavChart', () => ({
  NavChart: (props: {
    series: unknown[];
    markers: Array<{ date: string }>;
    periodLabel: string;
    summaryLabel?: string;
    coverage?: { state: string };
    onMarkerSelect?: (marker: { date: string }) => void;
  }) => (
    <div
      data-testid="nav-chart-stub"
      data-period={props.periodLabel}
      data-summary={props.summaryLabel ?? ''}
      data-series={JSON.stringify(props.series)}
      data-series-count={props.series.length}
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
const run = makeRun();

function renderHero(value: GovernedRunSummary = run) {
  return render(<StrategyChartHero run={value} />);
}

beforeEach(() => {
  window.localStorage.clear();
  mocks.loadFormalNav.mockReset().mockResolvedValue({ rows });
  mocks.loadRunSection.mockReset().mockResolvedValue([]);
  mocks.loadSecurityEvidence.mockReset();
});

describe('StrategyChartHero', () => {
  it('renders the default 1Y declared comparison without requesting market evidence', async () => {
    renderHero();
    const chart = await screen.findByTestId('strategy-nav-chart');

    expect(mocks.loadFormalNav).toHaveBeenCalledTimes(1);
    expect(mocks.loadRunSection).toHaveBeenCalledWith(run, 'trades');
    expect(mocks.loadSecurityEvidence).not.toHaveBeenCalled();

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
    expect(mocks.loadSecurityEvidence).not.toHaveBeenCalled();
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
    mocks.loadSecurityEvidence.mockRejectedValueOnce(new Error('market evidence offline'));
    renderHero();
    await screen.findByTestId('strategy-nav-chart');

    fireEvent.click(screen.getByRole('button', { name: 'QQQ market' }));

    await waitFor(() => expect(screen.getByTestId('strategy-baseline-error')).toBeInTheDocument());
    expect(screen.getByTestId('strategy-baseline-error')).toHaveTextContent('Market baseline unavailable');
    expect(screen.getByTestId('strategy-baseline-error')).toHaveTextContent('Reverted to the declared baseline (QQQ)');
    expect(screen.getByTestId('baseline-control')).toHaveAttribute('data-value', 'declared');
    expect(screen.getByTestId('hero-period-return')).toHaveTextContent('+71.6%');
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledTimes(1);
  });

  it('loads the governed market baseline only after selection and reuses it', async () => {
    mocks.loadSecurityEvidence.mockResolvedValue({
      bars: rows.map((row, index) => ({ time: row.date, open: 200 + index })),
    });
    renderHero();
    await screen.findByTestId('strategy-nav-chart');
    expect(mocks.loadSecurityEvidence).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'QQQ market' }));

    await waitFor(() => expect(screen.getByTestId('baseline-control')).toHaveAttribute('data-value', 'market'));
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledWith('us', 'QQQ');
    expect(screen.getByTestId('nav-chart-stub').getAttribute('data-series-count')).toBe('2');
    expect(screen.getByTestId('nav-chart-stub').getAttribute('data-summary')).toContain('QQQ');
    expect(screen.getByTestId('hero-excess-return')).toHaveTextContent('Excess vs QQQ');

    fireEvent.click(screen.getByRole('button', { name: 'QQQ market' }));
    await waitFor(() => expect(screen.getByTestId('baseline-control')).toHaveAttribute('data-value', 'market'));
    expect(mocks.loadSecurityEvidence).toHaveBeenCalledTimes(1);
  });

  it('shows the stale window chip when the evidence cutoff leads the last observation', async () => {
    renderHero(makeRun({ evidenceCutoff: '2026-03-01' }));
    await screen.findByTestId('strategy-nav-chart');

    expect(screen.getByTestId('hero-window-stale')).toHaveTextContent('Stale by 49 days');
    expect(screen.getByText(/As of 2026-01-11/)).toBeInTheDocument();
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
});
