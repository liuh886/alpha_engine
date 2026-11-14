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

function spxRow(): IndexRankingRow {
  return indexRowsFromBars('us', 'SPX', 'S&P 500', [
    bar('2026-11-04', 6792.3),
    bar('2026-11-06', 6815.1),
    bar('2026-11-11', 6899.62),
  ], '2026-11-12')[0];
}

function cnRow(): IndexRankingRow {
  return indexRowsFromBars('cn', '000300', 'CSI 300', [
    bar('2026-11-04', 3980),
    bar('2026-11-06', 4010),
    bar('2026-11-11', 4043.93),
  ], '2026-11-12')[0];
}

function renderCards(
  rows = [usRow(), spxRow(), cnRow()],
  issues: Parameters<typeof BenchmarkMarketCards>[0]['issues'] = [],
) {
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

  it('renders S&P 500 as a governed index card linked to its own identity', () => {
    renderCards();
    const sp500 = screen.getByTestId('benchmark-card-sp500');
    expect(sp500).toHaveAccessibleName('S&P 500 governed market evidence');
    expect(sp500).toHaveAttribute('href', '/securities/us/SPX');
    expect(sp500).toHaveTextContent('S&P 500');
    expect(sp500).toHaveTextContent('US');
    expect(sp500).toHaveTextContent('6,899.62');
    expect(sp500).toHaveTextContent('+107.32');
    expect(sp500).toHaveTextContent('+1.6%');
    expect(sp500).toHaveTextContent('As of 2026-11-11');
    expect(sp500).toHaveTextContent('Cutoff 2026-11-12');
    expect(within(sp500).getByTestId('sparkline')).toBeInTheDocument();
    expect(sp500).not.toHaveTextContent('Not governed');
  });

  it('renders exactly three cards in the existing responsive three-column grid', () => {
    const { container } = renderCards();
    const cards = screen.getAllByTestId(/^benchmark-card-/);
    expect(cards.map((card) => card.getAttribute('data-testid'))).toEqual([
      'benchmark-card-us',
      'benchmark-card-sp500',
      'benchmark-card-cn',
    ]);
    expect(cards).toHaveLength(3);
    for (const card of cards) {
      expect(card).toHaveAttribute('data-instrument');
      expect(card.className).not.toMatch(/\b(w|min-w)-\[/);
    }
    const grid = container.querySelector('.grid');
    expect(grid).toHaveClass('sm:grid-cols-3');
    expect(grid?.children).toHaveLength(3);
  });

  it('shows S&P 500 as awaiting its governed series without inventing a value', () => {
    renderCards([usRow(), cnRow()], [{
      id: 'index:us:SPX',
      kind: 'index',
      state: 'awaiting_publication',
      message: 'S&P 500: governed market evidence unavailable (Security history unavailable (404)).',
    }]);
    const sp500 = screen.getByTestId('benchmark-card-sp500');
    expect(sp500).toHaveTextContent('S&P 500');
    expect(sp500).toHaveTextContent('—');
    expect(sp500).not.toHaveTextContent('%');
    expect(sp500).not.toHaveTextContent('As of');
    expect(sp500).not.toHaveTextContent('Not governed');
    const status = within(sp500).getByRole('status');
    expect(status).toHaveTextContent('Awaiting governed series');
    // The propagated read failure remains available to assistive technology.
    expect(status).toHaveTextContent('Security history unavailable (404)');
    expect(within(sp500).queryByTestId('sparkline')).not.toBeInTheDocument();
    expect(sp500.querySelector('svg')).toBeNull();
    expect(screen.getByTestId('benchmark-card-us')).toHaveTextContent('690.38');
    expect(screen.getByTestId('benchmark-card-cn')).toHaveTextContent('4,043.93');
  });

  it('distinguishes a genuine S&P 500 parse failure from an unpublished series', () => {
    renderCards([usRow(), cnRow()], [{
      id: 'index:us:SPX',
      kind: 'index',
      state: 'unavailable',
      message: 'S&P 500: governed market evidence unavailable (Security history checksum mismatch).',
    }]);
    const sp500 = screen.getByTestId('benchmark-card-sp500');
    const status = within(sp500).getByRole('status');
    expect(status).toHaveTextContent('Security history checksum mismatch');
    expect(status).not.toHaveTextContent('Awaiting governed series');
    expect(status).toHaveClass('text-warning');
    expect(sp500).not.toHaveTextContent('Not governed');
    expect(within(sp500).queryByTestId('sparkline')).not.toBeInTheDocument();
    expect(sp500.querySelector('svg')).toBeNull();
  });

  it('keeps a failed index read scoped to its own card', () => {
    const message = 'QQQ: governed market evidence unavailable (governed closes unavailable).';
    renderCards([spxRow(), cnRow()], [{ id: 'index:us:QQQ', kind: 'index', message }]);
    const us = screen.getByTestId('benchmark-card-us');
    expect(us).toHaveTextContent('—');
    expect(within(us).getByRole('status')).toHaveTextContent(message);
    expect(screen.getByTestId('benchmark-card-sp500')).toHaveTextContent('6,899.62');
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
    expect(within(screen.getByTestId('benchmark-card-sp500')).getByRole('status'))
      .toHaveTextContent('Reading governed market evidence…');
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
    expect(screen.getByText(/Index cards use governed close-to-close price returns, not total return/)).toBeInTheDocument();
    expect(screen.getByText(/research evidence only — not trade-ready/)).toBeInTheDocument();
    expect(screen.getByText(/QQQ is the US strategy benchmark and CSI 300 the China strategy benchmark/)).toBeInTheDocument();
    expect(screen.getByText(/S&P 500 is a broad US market index reference, not a strategy benchmark/)).toBeInTheDocument();
    expect(screen.getByText(/No index is used as a cross-market substitute/)).toBeInTheDocument();
  });

  it('renders a displayed 1W coverage reason in the card instead of a hover title', () => {
    const row = usRow();
    const reason = 'First retained observation 2026-11-06; the requested window starts 2026-11-01.';
    renderCards([{
      ...row,
      cells: { ...row.cells, '1w': { ...row.cells['1w'], value: 0.012, display: true, reason } },
    }, spxRow(), cnRow()]);
    const us = screen.getByTestId('benchmark-card-us');
    const note = within(us).getByTestId('benchmark-reason-us');
    expect(note).toHaveTextContent(reason);
    expect(note).not.toHaveAttribute('title');
    const weekLine = within(us).getByText('1W').parentElement;
    expect(weekLine).not.toHaveAttribute('title');
    expect(weekLine).toHaveTextContent('+1.2%');
  });
});
