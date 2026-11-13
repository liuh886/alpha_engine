import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { BenchmarkMarketCards } from './BenchmarkMarketCards';
import { indexRowsFromBars, type IndexRankingRow } from '@/lib/model-ranking';
import type { SecurityBar } from '@/lib/security-evidence';

function bar(time: string, close: number): SecurityBar {
  return { time, open: close, high: close, low: close, close, volume: 1000 };
}

function usRow(): IndexRankingRow {
  return indexRowsFromBars('us', 'QQQ', 'QQQ', [
    bar('2026-11-04', 679.38),
    bar('2026-11-06', 685),
    bar('2026-11-11', 690.38),
  ], '2026-11-12')[0];
}

function cnRow(): IndexRankingRow {
  return indexRowsFromBars('cn', '000300', 'CSI 300', [
    bar('2026-11-04', 3980),
    bar('2026-11-06', 4010),
    bar('2026-11-11', 4043.93),
  ], '2026-11-12')[0];
}

function renderCards(rows = [usRow(), cnRow()], issues: Parameters<typeof BenchmarkMarketCards>[0]['issues'] = []) {
  return render(
    <MemoryRouter>
      <BenchmarkMarketCards rows={rows} issues={issues} />
    </MemoryRouter>,
  );
}

describe('BenchmarkMarketCards', () => {
  it('renders governed QQQ and CSI 300 closes with a one-week change and sparkline', () => {
    renderCards();
    expect(screen.getByRole('region', { name: 'Benchmark markets' })).toBeInTheDocument();

    const us = screen.getByTestId('benchmark-card-us');
    expect(us).toHaveAccessibleName('QQQ governed market evidence');
    expect(us).toHaveAttribute('href', '/securities/us/QQQ');
    expect(us).toHaveTextContent('QQQ');
    expect(us).toHaveTextContent('690.38');
    expect(us).toHaveTextContent('+11.00');
    expect(us).toHaveTextContent('+1.6%');
    expect(us).toHaveTextContent('1W');
    expect(us).toHaveTextContent('As of 2026-11-11');
    expect(us).toHaveTextContent('Cutoff 2026-11-12');
    expect(within(us).getByTestId('sparkline')).toHaveAttribute('aria-hidden', 'true');
    expect(within(us).getByTestId('sparkline-endpoint')).toBeInTheDocument();
    expect(within(us).getByText('+1.6%')).toHaveClass('text-positive');

    const cn = screen.getByTestId('benchmark-card-cn');
    expect(cn).toHaveAccessibleName('CSI 300 governed market evidence');
    expect(cn).toHaveAttribute('href', '/securities/cn/000300');
    expect(cn).toHaveTextContent('CSI 300');
    expect(cn).toHaveTextContent('4,043.93');
    expect(cn).toHaveTextContent('+63.93');
  });

  it('renders SP500 as dashed, not governed and without a series or substitute request', () => {
    renderCards();
    const sp500 = screen.getByTestId('benchmark-card-sp500');
    expect(sp500).toHaveClass('border-dashed');
    expect(sp500).toHaveTextContent('S&P 500');
    expect(sp500).toHaveTextContent('Not governed');
    expect(within(sp500).getByRole('link', { name: 'Review governance' })).toHaveAttribute('href', '/system');
    expect(within(sp500).queryByTestId('sparkline')).not.toBeInTheDocument();
    expect(within(sp500).queryByTestId('sparkline-endpoint')).not.toBeInTheDocument();
    expect(sp500.querySelector('svg')).toBeNull();
    expect(screen.queryByText(/SPY|VOO|IVV|GSPC/i)).not.toBeInTheDocument();
  });

  it('keeps a failed index read scoped to its own card', () => {
    const message = 'QQQ: governed market evidence unavailable (governed closes unavailable).';
    renderCards([cnRow()], [{ id: 'index:us:QQQ', kind: 'index', message }]);
    const us = screen.getByTestId('benchmark-card-us');
    expect(us).toHaveTextContent('—');
    expect(within(us).getByText(message)).toHaveClass('sr-only');
    expect(screen.getByTestId('benchmark-card-cn')).toHaveTextContent('4,043.93');
  });

  it('announces loading without inventing a close', () => {
    render(
      <MemoryRouter>
        <BenchmarkMarketCards rows={[]} loading />
      </MemoryRouter>,
    );
    expect(screen.getByRole('region', { name: 'Benchmark markets' })).toHaveAttribute('aria-busy', 'true');
    const us = screen.getByTestId('benchmark-card-us');
    expect(us).toHaveTextContent('—');
    expect(within(us).getByRole('status')).toHaveTextContent('Reading governed market evidence…');
    expect(within(us).getByRole('status')).not.toHaveClass('sr-only');
  });

  it('discloses a stale index feed in text and in the card accessible name', () => {
    const stale = indexRowsFromBars('us', 'QQQ', 'QQQ', [bar('2026-09-04', 690)], '2026-11-12')[0];
    renderCards([stale, cnRow()]);
    const us = screen.getByTestId('benchmark-card-us');
    expect(us).toHaveAccessibleName('QQQ governed market evidence, stale 69 days behind cutoff');
    const chip = within(us).getByTestId('benchmark-stale-us');
    expect(chip).toHaveTextContent('Stale · 69d behind cutoff');
    expect(chip).toHaveClass('text-warning');
    expect(within(us).getByText('As of 2026-09-04')).toBeInTheDocument();
    expect(within(screen.getByTestId('benchmark-card-cn')).queryByTestId('benchmark-stale-cn')).not.toBeInTheDocument();
  });

  it('discloses that index returns are price returns, not total return', () => {
    renderCards();
    expect(screen.getByText(/Index cards use governed close-to-close price returns, not total return\./)).toBeInTheDocument();
    expect(screen.getByText(/neither is used as a cross-market substitute/)).toBeInTheDocument();
  });

  it('renders a displayed 1W coverage reason in the card instead of a hover title', () => {
    const row = usRow();
    const reason = 'First retained observation 2026-11-06; the requested window starts 2026-11-01.';
    renderCards([{
      ...row,
      cells: { ...row.cells, '1w': { ...row.cells['1w'], value: 0.012, display: true, reason } },
    }, cnRow()]);
    const us = screen.getByTestId('benchmark-card-us');
    const note = within(us).getByTestId('benchmark-reason-us');
    expect(note).toHaveTextContent(reason);
    expect(note).not.toHaveAttribute('title');
    const weekLine = within(us).getByText('1W').parentElement;
    expect(weekLine).not.toHaveAttribute('title');
    expect(weekLine).toHaveTextContent('+1.2%');
  });
});
