import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { HoldingsSummary } from './HoldingsSummary';

vi.mock('@/lib/useNameMap', () => ({
  useNameMap: () => ({
    getName: (instrument: string) =>
      instrument === '300408'
        ? '\u4e09\u73af\u96c6\u56e2'
        : instrument === '000063'
          ? '\u4e2d\u5174\u901a\u8baf'
          : instrument,
  }),
}));

describe('HoldingsSummary', () => {
  it('shows the resolved Chinese holding name alongside its instrument code', () => {
    render(
      <HoldingsSummary
        positions={[
          { date: '2026-08-10', instrument: '300408', weight: 0.6 },
          { date: '2026-08-10', instrument: '000063', weight: 0.4 },
        ]}
      />,
    );

    const rows = screen.getAllByTestId('positions-table-row');
    expect(within(rows[0]).getByText('\u4e09\u73af\u96c6\u56e2')).toBeInTheDocument();
    expect(within(rows[0]).getByText('300408')).toBeInTheDocument();
    expect(within(rows[1]).getByText('\u4e2d\u5174\u901a\u8baf')).toBeInTheDocument();
    expect(within(rows[1]).getByText('000063')).toBeInTheDocument();
  });

  it('falls back to the raw ticker when no display name is retained', () => {
    render(
      <HoldingsSummary positions={[{ date: '2026-08-10', instrument: 'UNKNOWN', weight: 1 }]} />,
    );

    const rows = screen.getAllByTestId('positions-table-row');
    expect(within(rows[0]).getAllByText('UNKNOWN')).toHaveLength(2);
  });

  it('renders summary statistics for the latest snapshot only', () => {
    render(
      <HoldingsSummary
        positions={[
          { date: '2026-07-30', instrument: 'A', weight: 1 },
          { date: '2026-08-10', instrument: '300408', weight: 0.6 },
          { date: '2026-08-10', instrument: '000063', weight: 0.4 },
        ]}
      />,
    );

    expect(screen.getByText('Positions as of 2026-08-10')).toBeInTheDocument();
    expect(screen.queryByText('Positions as of 2026-07-30')).not.toBeInTheDocument();
    expect(screen.getByText('Max Weight')).toBeInTheDocument();
    expect(screen.getByText('60.00%')).toBeInTheDocument();
  });

  it('renders nothing without positions', () => {
    const { container } = render(<HoldingsSummary positions={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
