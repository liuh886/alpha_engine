import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { StockRankingsSection } from './StockRankingsSection';
import {
  STOCK_RANKING_PERIODS,
  type StockRankingPeriod,
  type StockRankingsProjection,
  type StockReturnCell,
} from '@/lib/stock-rankings';

type Values = Partial<Record<StockRankingPeriod, number | null>>;

function cells(defaultValue: number | null, overrides: Values = {}, reason: string | null = null) {
  return Object.fromEntries(STOCK_RANKING_PERIODS.map((period) => [period, {
    value: period in overrides ? overrides[period] : defaultValue,
    reason: (period in overrides ? overrides[period] : defaultValue) === null
      ? reason ?? 'No measured return is available.'
      : null,
  }])) as Record<StockRankingPeriod, StockReturnCell>;
}

function row(symbol: string, asOf: string, returns: Record<StockRankingPeriod, StockReturnCell>) {
  return { symbol, name: `${symbol} name`, asOf, cutoff: '2026-11-13', returns };
}

function usProjection(): StockRankingsProjection {
  return {
    market: 'us',
    cutoff: '2026-11-13',
    rows: [
      row('AAPL', '2026-11-13', cells(0.1, { '1w': 0.05 })),
      row('MSFT', '2026-11-13', cells(0.2, { '1w': 0.01 })),
      row('OLD', '2026-09-01', cells(0.3, { '1w': null }, 'Only 1 observation in the 1W window; no measured return is shown.')),
      row('MISSING', '2026-11-13', cells(null, {}, 'Only 1 observation in the 1M window; no measured return is shown.')),
    ],
  };
}

function cnProjection(): StockRankingsProjection {
  return {
    market: 'cn',
    cutoff: '2026-11-13',
    rows: [
      row('000001', '2026-11-13', cells(0.15, { '1w': 0.2 })),
      row('600000', '2026-11-13', cells(0.05, { '1w': null }, 'History begins 2026-11-01; the 1W window is missing its first 5 calendar days.')),
    ],
  };
}

function renderSection(props: Partial<Parameters<typeof StockRankingsSection>[0]> = {}) {
  return render(
    <MemoryRouter>
      <StockRankingsSection
        projections={props.projections ?? { us: usProjection(), cn: cnProjection() }}
        loading={props.loading}
        issues={props.issues}
      />
    </MemoryRouter>,
  );
}

describe('StockRankingsSection', () => {
  it('renders one Top-20 panel per market with the visible return-basis caption', () => {
    renderSection();
    const region = screen.getByRole('region', { name: 'Stock rankings' });
    expect(region).toHaveAttribute('aria-busy', 'false');
    expect(within(region).getByRole('heading', { name: 'Stock rankings' })).toBeInTheDocument();
    expect(screen.getByTestId('stock-rankings-caption')).toHaveTextContent(
      'Close-to-close price return, not total return. Ranked within each market; not a recommendation.',
    );
    expect(within(screen.getByTestId('stock-ranking-us')).getByRole('heading', { name: 'US stocks · Top 20' })).toBeInTheDocument();
    expect(within(screen.getByTestId('stock-ranking-cn')).getByRole('heading', { name: 'China stocks · Top 20' })).toBeInTheDocument();
  });

  it('ranks each market by the default 1M return and never links across markets', () => {
    renderSection();
    const us = screen.getByTestId('stock-ranking-us');
    const usRows = within(us).getAllByRole('link');
    expect(usRows.map((link) => link.getAttribute('data-testid'))).toEqual([
      'stock-row-us-OLD',
      'stock-row-us-MSFT',
      'stock-row-us-AAPL',
      'stock-row-us-MISSING',
    ]);
    for (const link of usRows) expect(link.getAttribute('href')).toMatch(/^\/securities\/us\//);
    expect(within(us).getByTestId('stock-row-us-MSFT')).toHaveAttribute('href', '/securities/us/MSFT');
    expect(within(us).getByTestId('stock-row-us-MSFT')).toHaveTextContent('+20.0%');
    expect(within(us).getByTestId('stock-row-us-MSFT')).toHaveTextContent('As of 2026-11-13');

    const cn = screen.getByTestId('stock-ranking-cn');
    const cnRows = within(cn).getAllByRole('link');
    expect(cnRows.map((link) => link.getAttribute('data-testid'))).toEqual([
      'stock-row-cn-000001',
      'stock-row-cn-600000',
    ]);
    for (const link of cnRows) expect(link.getAttribute('href')).toMatch(/^\/securities\/cn\//);
    expect(within(cn).queryByText('AAPL', { exact: true })).not.toBeInTheDocument();
  });

  it('shares one horizon selector and re-ranks both panels on change', () => {
    renderSection();
    const selector = screen.getByRole('group', { name: 'Stock ranking horizon' });
    expect(within(selector).getByRole('button', { name: '1M' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(within(selector).getByRole('button', { name: '1W' }));
    expect(within(selector).getByRole('button', { name: '1W' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(selector).getByRole('button', { name: '1M' })).toHaveAttribute('aria-pressed', 'false');

    const us = screen.getByTestId('stock-ranking-us');
    expect(within(us).getAllByRole('link').map((link) => link.getAttribute('data-testid'))).toEqual([
      'stock-row-us-AAPL',
      'stock-row-us-MSFT',
      'stock-row-us-MISSING',
      'stock-row-us-OLD',
    ]);
    expect(within(us).getByTestId('stock-row-us-AAPL')).toHaveTextContent('+5.0%');
    expect(within(screen.getByTestId('stock-ranking-cn')).getByTestId('stock-row-cn-000001')).toHaveTextContent('+20.0%');
  });

  it('renders a missing return as a dash with its reason and a stale as-of chip', () => {
    renderSection();
    const us = screen.getByTestId('stock-ranking-us');
    const missing = within(us).getByTestId('stock-row-us-MISSING');
    expect(missing).toHaveTextContent('—');
    expect(within(us).getByTestId('stock-missing-us-MISSING')).toHaveTextContent('Only 1 observation in the 1M window');
    expect(within(us).getByTestId('stock-stale-us-OLD')).toHaveTextContent('Stale · 73d behind cutoff');
    expect(missing).toHaveAttribute('data-stale', 'false');
    expect(within(us).getByTestId('stock-row-us-OLD')).toHaveAttribute('data-stale', 'true');
  });

  it('shows scoped loading, empty and unavailable states', () => {
    const { rerender } = renderSection({ loading: true, projections: {} });
    expect(screen.getByTestId('stock-ranking-loading-us')).toHaveTextContent('Reading US stock rankings…');
    expect(screen.getByTestId('stock-ranking-loading-cn')).toHaveTextContent('Reading China stock rankings…');

    rerender(
      <MemoryRouter>
        <StockRankingsSection projections={{ us: { market: 'us', cutoff: '2026-11-13', rows: [] }, cn: cnProjection() }} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('stock-ranking-empty-us')).toHaveTextContent('No US candidates have a projected return.');

    rerender(
      <MemoryRouter>
        <StockRankingsSection
          projections={{ cn: cnProjection() }}
          issues={[{ market: 'us', message: 'US stock rankings unavailable (404).' }]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('stock-ranking-unavailable-us')).toHaveTextContent('US stock rankings unavailable (404).');
    expect(screen.getByTestId('stock-ranking-cn').querySelectorAll('a')).toHaveLength(2);
  });
});
