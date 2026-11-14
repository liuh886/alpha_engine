import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ModelRankingTable } from './ModelRankingTable';
import type { GovernedRunSummary } from '@/lib/governed-run';
import {
  indexRowsFromBars,
  strategyRowsFromNav,
  type ModelRankingRow,
  type RankingExcess,
  type RankingSignal,
} from '@/lib/model-ranking';
import type { SecurityBar } from '@/lib/security-evidence';
import type { ReportRow } from '@/lib/types';

function run(overrides: Partial<GovernedRunSummary> = {}): GovernedRunSummary {
  return {
    key: 'us_x1_3',
    modelFamilyId: 'us_x',
    modelVersionId: 'us_x1_3',
    runId: 'us_x1_3-formal',
    bundleId: 'b'.repeat(64),
    title: 'US x1.3',
    modelKind: 'cross_sectional_ranker',
    channel: 'formal',
    publicationStatus: 'accepted_formal_baseline',
    market: 'us',
    benchmark: 'QQQ',
    generatedAt: '2026-11-12',
    evidenceCutoff: '2026-11-11',
    evidenceStatus: 'complete',
    decisionStatus: 'supported',
    manifestPath: 'us_x/manifest.json',
    manifestSha256: 'a'.repeat(64),
    summary: { metrics: [] },
    manifest: null,
    loadWarnings: [],
    ...overrides,
  };
}

function nav(points: Array<[string, number]>): ReportRow[] {
  return points.map(([date, account]) => ({ date, account }));
}

function bar(time: string, close: number): SecurityBar {
  return { time, open: close, high: close, low: close, close, volume: 1000 };
}

const RETAINED: RankingExcess = {
  value: 0.25,
  source: 'retained',
  label: 'retained',
  basis: 'Retained formal excess-return metric (full_history) vs QQQ.',
};

const SIGNAL: RankingSignal = {
  label: 'Increase',
  direction: 'increase',
  note: 'New target exposure',
  attention: false,
  isNew: true,
  isHold: false,
};

function usStrategy(excess: RankingExcess | undefined = RETAINED): ModelRankingRow {
  return strategyRowsFromNav(run({ summary: { metrics: [
    { metric_id: 'max_drawdown', value: -0.1, availability_status: 'available' },
  ] } }), nav([
    ['2026-10-11', 100],
    ['2026-11-11', 110],
  ]), { excess })[0];
}

function cnStrategy(): ModelRankingRow {
  return strategyRowsFromNav(run({
    key: 'cn_27_v1_3',
    modelFamilyId: 'cn_27',
    modelVersionId: 'cn_27_v1_3',
    runId: 'cn_27_v1_3-formal',
    title: 'CN_27 V1.3',
    market: 'cn',
    benchmark: '000300',
    evidenceCutoff: '2026-11-12',
  }), nav([
    ['2023-09-01', 100],
    ['2026-09-04', 140],
  ]))[0];
}

function qqqIndex(): ModelRankingRow {
  return indexRowsFromBars('us', 'QQQ', 'QQQ', [
    bar('2026-11-04', 110),
    bar('2026-11-06', 116),
    bar('2026-11-11', 121),
  ], '2026-11-12')[0];
}

function spxIndex(): ModelRankingRow {
  return indexRowsFromBars('us', 'SPX', 'S&P 500', [
    bar('2026-11-04', 6792.3),
    bar('2026-11-06', 6815.1),
    bar('2026-11-11', 6899.62),
  ], '2026-11-12')[0];
}

function renderTable(rows: ModelRankingRow[], density: 'compact' | 'full' = 'compact', extra: Partial<Parameters<typeof ModelRankingTable>[0]> = {}) {
  return render(
    <MemoryRouter>
      <ModelRankingTable rows={rows} density={density} {...extra} />
    </MemoryRouter>,
  );
}

describe('ModelRankingTable', () => {
  it('renders market groups, every decision horizon and a per-row as-of date', () => {
    renderTable([usStrategy(), cnStrategy(), qqqIndex()]);
    expect(screen.getByTestId('ranking-group-us')).toHaveTextContent('US');
    expect(screen.getByTestId('ranking-group-cn')).toHaveTextContent('China');
    for (const label of ['1W', '1M', '3M', '1Y', '2Y', '3Y']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
    for (const [id, asOf] of [['fleet-us_x1_3', '2026-11-11'], ['fleet-cn_27_v1_3', '2026-09-04']] as const) {
      const row = screen.getByTestId(id);
      expect(within(row).getByText(`As of ${asOf}`)).toBeInTheDocument();
      expect(within(row).getByRole('link', { name: /Inspect evidence/ })).toHaveAttribute('href', `/strategies/${id.replace('fleet-', '')}`);
    }
    expect(within(screen.getByTestId('ranking-index-us-QQQ')).getByRole('link', { name: /Price history/ }))
      .toHaveAttribute('href', '/securities/us/QQQ');
  });

  it('places the governed S&P 500 row in the US group with its own benchmark and no excess', () => {
    renderTable([usStrategy(), cnStrategy(), qqqIndex(), spxIndex()], 'full');
    const group = screen.getByTestId('ranking-group-us');
    const spx = screen.getByTestId('ranking-index-us-SPX');
    const cnGroup = screen.getByTestId('ranking-group-cn');
    expect(group.compareDocumentPosition(spx) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(spx.compareDocumentPosition(cnGroup) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(spx).toHaveTextContent('S&P 500');
    expect(within(spx).getByTestId('cell-index:us:SPX-1w')).toHaveTextContent('+1.6%');
    expect(spx).toHaveTextContent('Index rows are close-to-close price returns; excess is not computed.');
    expect(spx).not.toHaveTextContent('Not governed');
    expect(within(spx).getByRole('link', { name: /Price history/ }))
      .toHaveAttribute('href', '/securities/us/SPX');
  });

  it('keeps the S&P 500 index row in the compact US group without strategy metrics', () => {
    renderTable([usStrategy(), cnStrategy(), qqqIndex(), spxIndex()], 'compact');
    const spx = screen.getByTestId('ranking-index-us-SPX');
    const cnGroup = screen.getByTestId('ranking-group-cn');
    expect(spx.compareDocumentPosition(cnGroup) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(spx).toHaveTextContent('S&P 500');
    expect(within(spx).getByTestId('cell-index:us:SPX-1w')).toHaveTextContent('+1.6%');
    expect(spx).not.toHaveTextContent('Excess');
    expect(screen.queryByRole('columnheader', { name: 'Excess' })).not.toBeInTheDocument();
  });

  it('sorts by 1M by default and changes order when another horizon is chosen', () => {
    const alpha = strategyRowsFromNav(run({ modelVersionId: 'alpha', title: 'Alpha' }), nav([
      ['2024-11-11', 50],
      ['2025-11-11', 100],
      ['2026-10-11', 200],
      ['2026-11-11', 220],
    ]))[0];
    const beta = strategyRowsFromNav(run({ modelVersionId: 'beta', title: 'Beta' }), nav([
      ['2024-11-11', 50],
      ['2025-11-11', 100],
      ['2026-10-11', 100],
      ['2026-11-11', 130],
    ]))[0];
    renderTable([alpha, beta]);

    const header = (name: string) => screen.getByRole('columnheader', { name });
    expect(header('1M')).toHaveAttribute('aria-sort', 'descending');
    expect(screen.getByRole('button', { name: '1M' })).toHaveAttribute('aria-pressed', 'true');
    const orderedIds = () => screen.getAllByTestId(/^fleet-/).map((row) => row.getAttribute('data-testid'));
    expect(orderedIds()).toEqual(['fleet-beta', 'fleet-alpha']);

    fireEvent.click(screen.getByRole('button', { name: '1Y' }));
    expect(header('1Y')).toHaveAttribute('aria-sort', 'descending');
    expect(header('1M')).toHaveAttribute('aria-sort', 'none');
    expect(orderedIds()).toEqual(['fleet-alpha', 'fleet-beta']);
  });

  it('shows stale evidence in place while keeping the row readable and linked', () => {
    renderTable([cnStrategy()]);
    const row = screen.getByTestId('fleet-cn_27_v1_3');
    expect(row).toHaveAttribute('data-stale', 'true');
    expect(row).toHaveClass('bg-warning/[0.04]');
    expect(within(row).getByTestId('stale-cn_27_v1_3')).toHaveTextContent('Stale · 69d behind cutoff');
    expect(within(row).getByText('As of 2026-09-04')).toBeInTheDocument();
    expect(within(row).getByRole('link', { name: 'CN_27 V1.3' })).toHaveAttribute('href', '/strategies/cn_27_v1_3');
  });

  it('never renders a missing horizon as 0.0% and explains the gap', () => {
    const onePoint = strategyRowsFromNav(run({ modelVersionId: 'one_point', title: 'One point' }), nav([
      ['2026-11-11', 100],
    ]))[0];
    renderTable([onePoint]);
    const row = screen.getByTestId('fleet-one_point');
    expect(row).not.toHaveTextContent('0.0%');
    expect(row).toHaveTextContent('—');
    expect(row).toHaveTextContent('Only 1 observation in the 1M window; no measured return is shown.');
  });

  it('adds excess, max drawdown and the current signal only at full density', () => {
    const handler = vi.fn();
    const derived = usStrategy({
      value: 0.16979,
      source: 'derived',
      label: 'derived',
      basis: 'Derived · vs QQQ · 699 observations.',
    });
    renderTable([
      { ...derived, id: 'derived', modelVersionId: 'derived', title: 'Derived' } as ModelRankingRow,
      { ...usStrategy(), signal: SIGNAL },
    ], 'full', { onInspectSignal: handler, selectedId: 'us_x1_3' });

    expect(screen.getByRole('columnheader', { name: 'Excess' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Max DD' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Signal' })).toBeInTheDocument();

    const retainedRow = screen.getByTestId('fleet-us_x1_3');
    expect(within(retainedRow).getByText('retained')).toBeInTheDocument();
    expect(within(retainedRow).getByText('+25.0%')).toBeInTheDocument();
    expect(within(retainedRow).getByText('-10.0%')).toBeInTheDocument();
    expect(retainedRow).toHaveClass('bg-primary/5');

    const derivedRow = screen.getByTestId('fleet-derived');
    expect(within(derivedRow).getByText('derived')).toBeInTheDocument();
    expect(within(derivedRow).getByText('+17.0%')).toBeInTheDocument();

    const signal = within(retainedRow).getByRole('button', { name: 'Inspect signal for US x1.3: Increase' });
    fireEvent.click(signal);
    expect(handler).toHaveBeenCalledWith(expect.objectContaining({ id: 'us_x1_3' }));
  });

  it('labels an unavailable excess instead of manufacturing one', () => {
    renderTable([usStrategy({
      value: null,
      source: 'unavailable',
      label: 'Excess unavailable',
      basis: '',
      reason: 'The governed formal source does not retain a finite excess-return metric.',
    }), qqqIndex()], 'full');
    const strategy = screen.getByTestId('fleet-us_x1_3');
    expect(within(strategy).getByText('Unavailable')).toBeInTheDocument();
    expect(strategy).toHaveTextContent('The governed formal source does not retain a finite excess-return metric.');
    expect(strategy).not.toHaveTextContent('+25.0%');
    const index = screen.getByTestId('ranking-index-us-QQQ');
    expect(index).toHaveTextContent('Index rows are close-to-close price returns; excess is not computed.');
  });

  it('hides the sorting table from the compact view when empty and reports issues', () => {
    renderTable([], 'compact', {
      emptyMessage: 'No strategies match these filters.',
      issues: [{ id: 'us_x1_3', kind: 'strategy', message: 'US x1.3: ranking evidence unavailable.' }],
    });
    expect(screen.getByText('No strategies match these filters.')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Model ranking read issues' })).toHaveTextContent('US x1.3: ranking evidence unavailable.');
  });

  it('sorts by excess, drawdown, signal and as-of without changing displayed values', () => {
    const alpha = { ...usStrategy(), id: 'alpha', modelVersionId: 'alpha', title: 'Alpha', asOf: '2026-11-11' } as ModelRankingRow;
    const beta = {
      ...usStrategy({ value: 0.05, source: 'retained', label: 'retained', basis: 'Beta basis.' }),
      id: 'beta', modelVersionId: 'beta', title: 'Beta', asOf: '2026-10-11',
      maxDrawdown: -0.02,
      signal: { ...SIGNAL, label: 'Attention', direction: 'attention', note: 'Needs review' },
    } as ModelRankingRow;
    renderTable([alpha, beta], 'full');
    const orderedIds = () => screen.getAllByTestId(/^fleet-/).map(row => row.getAttribute('data-testid'));
    const excessValues = () => screen.getAllByTestId(/^fleet-/).map(row => row.textContent);
    const before = excessValues();

    fireEvent.click(screen.getByRole('button', { name: 'Excess' }));
    expect(screen.getByRole('columnheader', { name: 'Excess' })).toHaveAttribute('aria-sort', 'descending');
    expect(orderedIds()).toEqual(['fleet-alpha', 'fleet-beta']);
    expect(excessValues()).toEqual(before);

    fireEvent.click(screen.getByRole('button', { name: 'Max DD' }));
    expect(orderedIds()).toEqual(['fleet-beta', 'fleet-alpha']);

    fireEvent.click(screen.getByRole('button', { name: 'Signal' }));
    expect(orderedIds()).toEqual(['fleet-beta', 'fleet-alpha']);

    fireEvent.click(screen.getByRole('button', { name: 'Sort by as-of freshness' }));
    expect(screen.getByRole('columnheader', { name: /Model/ })).toHaveAttribute('aria-sort', 'descending');
    expect(orderedIds()).toEqual(['fleet-alpha', 'fleet-beta']);
  });

  it('opens row details and value basis from keyboard-reachable disclosures', () => {
    renderTable([{ ...usStrategy(), signal: SIGNAL }], 'full');
    const row = screen.getByTestId('fleet-us_x1_3');
    const details = within(row).getByRole('button', { name: /Row details/ });
    expect(details).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(details);
    expect(details).toHaveAttribute('aria-expanded', 'true');
    const panel = document.getElementById('row-details-us_x1_3');
    expect(panel).toHaveTextContent('Evidence cutoff');
    expect(panel).toHaveTextContent('2026-11-11');
    expect(panel).toHaveTextContent('New target exposure');

    const basis = within(row).getByText('retained').closest('summary');
    expect(basis).not.toBeNull();
    fireEvent.click(basis!);
    expect(basis!.closest('details')).toHaveAttribute('open');
    expect(within(row).getByText('Retained formal excess-return metric (full_history) vs QQQ.')).toBeInTheDocument();
  });

  it('keeps the wide table inside its own scroller with a sticky header', () => {
    const { container } = renderTable([usStrategy()]);
    const wrapper = container.querySelector('table')?.parentElement;
    expect(wrapper).toHaveClass('overflow-auto');
    expect(container.querySelector('thead')).toHaveClass('sticky');
    expect(container.querySelector('table')).toHaveClass('min-w-[820px]');
    const { container: full } = renderTable([usStrategy()], 'full');
    expect(full.querySelector('table')).toHaveClass('min-w-[1040px]');
  });

  it('keeps the as-of sort in an inline cluster beside the Model label', () => {
    renderTable([usStrategy()]);
    const header = screen.getByRole('columnheader', { name: /Model/ });
    expect(header).toHaveAttribute('aria-sort', 'none');
    const button = within(header).getByRole('button', { name: 'Sort by as-of freshness' });
    expect(button).toHaveAttribute('aria-pressed', 'false');
    const cluster = button.parentElement;
    expect(cluster).not.toBeNull();
    expect(cluster).not.toHaveClass('justify-between');
    expect(cluster!.children).toHaveLength(2);
    expect(cluster!.firstElementChild).toHaveTextContent('Model');
    expect(cluster!.lastElementChild).toBe(button);
    // The Model header is the only header that carries the as-of control.
    expect(screen.getAllByRole('columnheader', { name: /as of/i })).toHaveLength(1);
  });

  it('discloses a displayed return basis without a hover-only title', () => {
    const row = usStrategy();
    const reason = 'First retained observation 2026-11-06; the requested window starts 2026-11-01.';
    renderTable([{
      ...row,
      cells: { ...row.cells, '1m': { ...row.cells['1m'], value: 0.05, display: true, reason } },
    }]);
    const cell = screen.getByTestId('cell-us_x1_3-1m');
    expect(cell).not.toHaveAttribute('title');
    expect(cell.querySelector('[title]')).toBeNull();
    const summary = cell.closest('summary');
    expect(summary).not.toBeNull();
    fireEvent.click(summary!);
    expect(summary!.closest('details')).toHaveAttribute('open');
    expect(screen.getByText(reason)).toBeInTheDocument();
  });
});
