import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ModelData } from '@/lib/data-parser';
import { RiskReturnMap } from './RiskReturnMap';

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <>{children}</>,
  ScatterChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Scatter: ({ data, children }: { data: unknown[]; children: ReactNode }) => <div data-testid="risk-points" data-points={JSON.stringify(data)}>{children}</div>,
  CartesianGrid: () => null,
  Cell: () => null,
  LabelList: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

function model(id: string, annualReturn: number, maxDrawdown: number, sharpe: number): ModelData {
  return {
    id,
    name: id,
    backtest: {
      metrics: {
        'Annualized Return': annualReturn,
        'Max Drawdown': maxDrawdown,
        'Sharpe Ratio': sharpe,
      },
    },
  } as ModelData;
}

describe('RiskReturnMap', () => {
  it('plots annualized return against absolute max drawdown', () => {
    render(<RiskReturnMap models={[model('A', 0.2, -0.1, 1.2), model('B', 0.15, -0.08, 1.1)]} comparable />);

    const points = JSON.parse(screen.getByTestId('risk-points').getAttribute('data-points') || '[]');
    expect(points).toHaveLength(2);
    expect(points[0]).toMatchObject({ id: 'A', annualReturn: 0.2, drawdown: 0.1, sharpe: 1.2 });
    expect(screen.getByText(/Upper-left is more efficient/)).toBeInTheDocument();
  });

  it('does not render without at least two complete points', () => {
    const { container } = render(<RiskReturnMap models={[model('A', 0.2, -0.1, 1.2)]} comparable />);
    expect(container).toBeEmptyDOMElement();
  });
});
