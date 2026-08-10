import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { PerformanceCharts } from './PerformanceCharts';

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <>{children}</>,
  ComposedChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Area: () => null,
  Bar: () => null,
  Brush: () => null,
  CartesianGrid: () => null,
  Legend: () => null,
  Line: () => null,
  ReferenceLine: () => null,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));


describe('PerformanceCharts provisional MTM', () => {
  it('uses the evidence-cutoff MTM date as the latest performance observation', () => {
    render(
      <PerformanceCharts report={[
        {
          date: '2026-07-16',
          holding_end_date: '2026-07-30',
          account: 1,
          bench_qqq: 1,
        },
        {
          date: '2026-07-30',
          holding_end_date: '2026-08-07',
          account: 1.02,
          bench_qqq: 1.01,
          provisional_mtm: true,
          settlement_status: 'provisional_mtm',
        },
      ]} />,
    );

    const curve = screen.getByTestId('equity-curve-container');
    expect(curve).toHaveAttribute('data-realized-through', '2026-08-07');
    expect(curve).toHaveAttribute('data-equity-status', 'provisional_mtm');
    expect(screen.getByText('Provisional MTM through 2026-08-07')).toBeInTheDocument();
  });
});
