import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PositionsTable } from './PositionsTable';

vi.mock('@/lib/useNameMap', () => ({ useNameMap: () => ({ getName: (instrument: string) => instrument }) }));
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 52,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, size: 52, start: index * 52 })),
  }),
}));
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <>{children}</>,
  ComposedChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Bar: ({ children }: { children: ReactNode }) => <>{children}</>,
  CartesianGrid: () => null,
  Cell: () => null,
  ReferenceLine: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

describe('PositionsTable snapshot diagnostics', () => {
  it('shows retained turnover, transaction cost and changes versus the previous snapshot', () => {
    render(
      <PositionsTable
        positions={[
          { date: '2026-01-01', instrument: 'A', weight: 0.6, trade_status: 'trade', transaction_cost: 0.001 },
          { date: '2026-01-01', instrument: 'B', weight: 0.4, trade_status: 'trade', transaction_cost: 0.001 },
          { date: '2026-01-11', instrument: 'A', weight: 0.5, trade_status: 'trade', trade_action: 'DECREASE', transaction_cost: 0.001 },
          { date: '2026-01-11', instrument: 'C', weight: 0.5, trade_status: 'trade', trade_action: 'BUY', transaction_cost: 0.002 },
        ]}
        report={[
          { date: '2026-01-01', account: 1, turnover: 0.2, transaction_cost: 0.002 },
          { date: '2026-01-11', account: 1.05, turnover: 0.3, transaction_cost: 0.003 },
        ]}
      />,
    );

    const snapshot = screen.getByTestId('holdings-snapshot');
    expect(snapshot).toHaveTextContent('Net exposure');
    expect(snapshot).toHaveTextContent('100.0%');
    expect(snapshot).toHaveTextContent('Top 5 concentration');
    expect(snapshot).toHaveTextContent('Turnover');
    expect(snapshot).toHaveTextContent('30.0%');
    expect(snapshot).toHaveTextContent('Transaction cost');
    expect(snapshot).toHaveTextContent('0.300%');
    expect(snapshot).toHaveTextContent('1 added · 1 resized · 1 exited');
    expect(screen.getByText('-10.00%')).toBeInTheDocument();
    expect(screen.getByText('+50.00%')).toBeInTheDocument();
    expect(screen.getByText('0.100%')).toBeInTheDocument();
    expect(screen.getByText('0.200%')).toBeInTheDocument();
    expect(screen.getByText('DECREASE')).toBeInTheDocument();
    expect(screen.getByText('BUY')).toBeInTheDocument();
  });

  it('shows the retained Chinese holding name alongside its instrument code', () => {
    render(
      <PositionsTable
        positions={[
          { date: '2026-08-10', instrument: '300408', name: '\u4e09\u73af\u96c6\u56e2', weight: 1 },
        ]}
      />,
    );

    expect(screen.getByText('\u4e09\u73af\u96c6\u56e2')).toBeInTheDocument();
    expect(screen.getByText('300408')).toBeInTheDocument();
  });

  it('does not derive turnover when the retained performance row is absent', () => {
    render(
      <PositionsTable
        positions={[
          { date: '2026-07-16', instrument: 'A', weight: 0.5 },
          { date: '2026-07-16', instrument: 'B', weight: 0.5 },
          { date: '2026-07-30', instrument: 'A', weight: 0.5 },
          { date: '2026-07-30', instrument: 'C', weight: 0.5 },
        ]}
        report={[{ date: '2026-07-16', holding_end_date: '2026-07-30', account: 1.05, turnover: 0.1 }]}
      />,
    );

    const snapshot = screen.getByTestId('holdings-snapshot');
    expect(snapshot).toHaveTextContent('Turnover');
    expect(snapshot).not.toHaveTextContent('50.0%');
  });

  it('distinguishes a retained no-trade holding from missing trade evidence', () => {
    render(
      <PositionsTable
        positions={[
          { date: '2026-08-12', instrument: 'A', weight: 0.5, trade_status: 'no_trade' },
          { date: '2026-08-12', instrument: 'B', weight: 0.5 },
        ]}
        report={[{ date: '2026-08-12', account: 1, turnover: 0, transaction_cost: 0 }]}
      />,
    );

    expect(screen.getByText('No trade')).toBeInTheDocument();
  });
});
