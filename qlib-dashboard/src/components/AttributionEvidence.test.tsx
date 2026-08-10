import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AttributionEvidence } from './AttributionEvidence';

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <>{children}</>,
  BarChart: ({ data, children }: { data: unknown[]; children: ReactNode }) => <div data-testid="attribution-chart-data" data-chart={JSON.stringify(data)}>{children}</div>,
  Bar: ({ children }: { children: ReactNode }) => <>{children}</>,
  CartesianGrid: () => null,
  Cell: () => null,
  ReferenceLine: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

describe('AttributionEvidence', () => {
  it('shows largest positive and negative retained drivers', () => {
    render(<AttributionEvidence rows={[
      { instrument: 'A', name: 'Alpha', value: 0.04 },
      { instrument: 'B', name: 'Beta', value: -0.02 },
      { instrument: 'C', name: 'Gamma', value: 0.01 },
    ]} />);

    expect(screen.getByTestId('attribution-drivers-chart')).toHaveTextContent('Alpha');
    expect(screen.getByTestId('attribution-drivers-chart')).toHaveTextContent('4.000%');
    expect(screen.getByTestId('attribution-drivers-chart')).toHaveTextContent('Beta');
    expect(screen.getByTestId('attribution-drivers-chart')).toHaveTextContent('-2.000%');
    const chart = JSON.parse(screen.getByTestId('attribution-chart-data').getAttribute('data-chart') || '[]');
    expect(chart.map((row: { value: number }) => row.value)).toEqual([-0.02, 0.01, 0.04]);
  });

  it('keeps an explicit empty evidence state', () => {
    render(<AttributionEvidence rows={[]} />);
    expect(screen.getByText('Attribution evidence is not declared')).toBeInTheDocument();
  });
});
