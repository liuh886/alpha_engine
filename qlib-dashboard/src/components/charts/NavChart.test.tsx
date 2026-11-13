import type { ReactNode } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { NavMarker, NavPoint } from '@/lib/nav-series';
import type { HorizonCoverage } from '@/lib/performancePeriods';
import {
  NavChart,
  NavChartTooltip,
  buildNavChartModel,
  type NavChartSeries,
  type NavChartTooltipProps,
} from './NavChart';

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <>{children}</>,
  LineChart: ({ data, children }: { data: unknown[]; children: ReactNode }) => (
    <div data-testid="line-chart" data-chart={JSON.stringify(data)}>{children}</div>
  ),
  CartesianGrid: ({ stroke }: { stroke?: string }) => (
    <div data-testid="cartesian-grid" data-stroke={stroke} />
  ),
  XAxis: ({ tickFormatter, tick }: { tickFormatter?: (value: string) => string; tick?: { fill?: string } }) => (
    <div
      data-testid="x-axis"
      data-tick-fill={tick?.fill}
      data-sample={tickFormatter ? tickFormatter('2026-01-03') : undefined}
    />
  ),
  YAxis: ({ label, tick }: {
    label?: { value?: string };
    tick?: { fill?: string };
  }) => <div data-testid="y-axis" data-label={label?.value} data-tick-fill={tick?.fill} />,
  Tooltip: () => null,
  ReferenceLine: ({ x, y }: { x?: string | number; y?: string | number }) => (
    <div data-testid={x === undefined ? 'index-line' : 'activity-line'} data-x={x} data-y={y} />
  ),
  ReferenceDot: ({ x, y, fill, onClick, shape }: {
    x?: string | number;
    y?: string | number;
    fill?: string;
    onClick?: () => void;
    shape?: { props?: { side?: string } };
  }) => (
    <button
      type="button"
      data-testid="activity-dot"
      data-x={x}
      data-y={y}
      data-fill={fill}
      data-side={shape?.props?.side}
      onClick={onClick}
    />
  ),
  Line: ({ dataKey, name, stroke, strokeDasharray, strokeWidth, dot, connectNulls }: {
    dataKey?: string;
    name?: string;
    stroke?: string;
    strokeDasharray?: string;
    strokeWidth?: number;
    dot?: boolean;
    connectNulls?: boolean;
  }) => (
    <div
      data-testid="series-line"
      data-key={dataKey}
      data-name={name}
      data-stroke={stroke}
      data-dash={strokeDasharray ?? ''}
      data-width={strokeWidth}
      data-dot={String(dot)}
      data-connect-nulls={String(connectNulls)}
    />
  ),
}));

const strategy: NavPoint[] = [
  { date: '2026-01-01', value: 100 },
  { date: '2026-01-02', value: 110 },
  { date: '2026-01-03', value: 121 },
];
const benchmark: NavPoint[] = [
  { date: '2026-01-02', value: 200 },
  { date: '2026-01-03', value: 210 },
  { date: '2026-01-10', value: 220 },
];
const series: NavChartSeries[] = [
  { key: 'strategy', label: 'Strategy', nav: strategy, emphasis: 'primary' },
  { key: 'qqq', label: 'QQQ', nav: benchmark, emphasis: 'baseline' },
];

const marker: NavMarker = {
  date: '2026-01-02',
  side: 'buy',
  count: 2,
  instruments: ['AAPL', 'MSFT'],
  netWeightDelta: 0.04,
  reasons: ['rebalance'],
};

const hiddenMarker: NavMarker = {
  date: '2025-12-15',
  side: 'sell',
  count: 1,
  instruments: [],
  netWeightDelta: null,
  reasons: [],
};

function chartRows(): Array<Record<string, number | string>> {
  const raw = screen.getByTestId('line-chart').getAttribute('data-chart');
  return JSON.parse(raw ?? '[]') as Array<Record<string, number | string>>;
}

describe('buildNavChartModel', () => {
  it('aligns exact dates only and rebases each series to 100 at the first common date', () => {
    const model = buildNavChartModel(series);
    expect(model.startDate).toBe('2026-01-02');
    expect(model.endDate).toBe('2026-01-03');
    expect(model.rows).toHaveLength(2);
    expect(model.rows[0]).toEqual({ date: '2026-01-02', strategy: 100, qqq: 100 });
    expect(model.rows[1].strategy).toBeCloseTo(110, 10);
    expect(model.rows[1].qqq).toBeCloseTo(105, 10);
  });

  it('keeps single-series dates and skips invalid observations', () => {
    const model = buildNavChartModel([{
      key: 'strategy',
      label: 'Strategy',
      nav: [
        { date: '2026-01-02', value: 50 },
        { date: '2026-01-01', value: 0 },
        { date: '2026-02-30', value: 60 },
        { date: '2026-01-03', value: 75 },
      ],
    }]);
    expect(model.rows).toEqual([
      { date: '2026-01-02', strategy: 100 },
      { date: '2026-01-03', strategy: 150 },
    ]);
  });

  it('intersects more than two series and returns no rows without a common date', () => {
    const third: NavChartSeries = {
      key: 'csi300',
      label: 'CSI 300',
      nav: [
        { date: '2026-01-03', value: 10 },
        { date: '2026-01-04', value: 11 },
      ],
    };
    const model = buildNavChartModel([...series, third]);
    expect(model.rows.map(row => row.date)).toEqual(['2026-01-03']);
    expect(model.rows[0].csi300).toBe(100);

    expect(buildNavChartModel([
      { key: 'a', label: 'A', nav: [{ date: '2026-01-01', value: 1 }] },
      { key: 'b', label: 'B', nav: [{ date: '2026-01-02', value: 1 }] },
    ])).toEqual({ rows: [], startDate: null, endDate: null });
  });
});

describe('NavChart', () => {
  it('plots the exact-date model with foundation theme tokens and accessible labels', () => {
    render(<NavChart series={series} periodLabel="1M" />);
    const rows = chartRows();
    expect(rows.map(row => row.date)).toEqual(['2026-01-02', '2026-01-03']);
    expect(rows[0].strategy).toBe(100);
    expect(rows[0].qqq).toBe(100);
    expect(rows[1].strategy).toBeCloseTo(110, 10);
    expect(rows[1].qqq).toBeCloseTo(105, 10);

    const lines = screen.getAllByTestId('series-line');
    expect(lines).toHaveLength(2);
    expect(lines[0].getAttribute('data-key')).toBe('strategy');
    expect(lines[0].getAttribute('data-stroke')).toBe('hsl(var(--chart-1))');
    expect(lines[0].getAttribute('data-dash')).toBe('');
    expect(lines[0].getAttribute('data-width')).toBe('2.2');
    expect(lines[0].getAttribute('data-dot')).toBe('false');
    expect(lines[0].getAttribute('data-connect-nulls')).toBe('false');
    expect(lines[1].getAttribute('data-stroke')).toBe('hsl(var(--chart-2))');
    expect(lines[1].getAttribute('data-dash')).toBe('5 4');
    expect(lines[1].getAttribute('data-width')).toBe('1.5');

    for (const element of screen.getAllByTestId(/series-line|cartesian-grid|x-axis|y-axis/)) {
      for (const attribute of ['data-stroke', 'data-tick-fill']) {
        const value = element.getAttribute(attribute);
        if (!value) continue;
        expect(value).toMatch(/^hsl\(var\(--[a-z0-9-]+\)\)$/);
      }
    }
    expect(screen.getByTestId('cartesian-grid').getAttribute('data-stroke')).toBe('hsl(var(--chart-grid))');
    expect(screen.getByTestId('x-axis').getAttribute('data-tick-fill')).toBe('hsl(var(--chart-axis))');
    expect(screen.getByTestId('y-axis').getAttribute('data-label')).toBe('Indexed to 100');
    expect(screen.getByTestId('x-axis').getAttribute('data-sample')).toBe('Jan 3');
    expect(screen.getByTestId('index-line').getAttribute('data-y')).toBe('100');
    expect(screen.getByRole('figure', { name: '1M NAV chart indexed to 100' })).toBeInTheDocument();
  });

  it('honors only allowlisted color tokens and never emits raw colors', () => {
    render(
      <NavChart
        series={[
          { ...series[0], colorToken: '#ff0000' },
          { ...series[1], colorToken: 'positive' },
        ]}
        periodLabel="1M"
      />,
    );
    const lines = screen.getAllByTestId('series-line');
    expect(lines[0].getAttribute('data-stroke')).toBe('hsl(var(--chart-1))');
    expect(lines[1].getAttribute('data-stroke')).toBe('hsl(var(--positive))');
    for (const line of lines) {
      expect(line.getAttribute('data-stroke')).not.toContain('#');
    }
  });

  it('draws markers only on retained exact dates and discloses the hidden ones', () => {
    const onMarkerSelect = vi.fn();
    render(
      <NavChart
        series={series}
        markers={[marker, hiddenMarker]}
        periodLabel="1M"
        onMarkerSelect={onMarkerSelect}
      />,
    );

    const dots = screen.getAllByTestId('activity-dot');
    expect(dots).toHaveLength(1);
    expect(dots[0].getAttribute('data-x')).toBe('2026-01-02');
    expect(dots[0].getAttribute('data-y')).toBe('100');
    expect(dots[0].getAttribute('data-fill')).toBe('hsl(var(--positive))');
    expect(dots[0].getAttribute('data-side')).toBe('buy');
    expect(screen.getAllByTestId('activity-line')).toHaveLength(1);
    expect(screen.queryByTestId('activity-line')?.getAttribute('data-x')).toBe('2026-01-02');

    fireEvent.click(dots[0]);
    expect(onMarkerSelect).toHaveBeenCalledWith(marker);

    expect(screen.getByTestId('nav-chart-hidden-markers')).toHaveTextContent(
      '1 activity marker falls outside the aligned window or does not match a retained observation date and is not drawn.',
    );

    const details = screen.getByRole('list', { name: 'Activity marker details' });
    expect(within(details).getByText(/Buy, 2 trades/)).toBeInTheDocument();
    fireEvent.click(within(details).getByRole('button', { name: /Buy, 2 trades/ }));
    expect(onMarkerSelect).toHaveBeenCalledTimes(2);
  });

  it('encodes buy, sell and mixed activity with shapes, not color alone', () => {
    const sideMarkers: NavMarker[] = [
      { ...marker, date: '2026-01-01', side: 'buy' },
      { ...marker, date: '2026-01-02', side: 'sell' },
      { ...marker, date: '2026-01-03', side: 'mixed' },
    ];
    render(
      <NavChart
        series={[series[0]]}
        markers={sideMarkers}
        periodLabel="1M"
      />,
    );

    const dots = screen.getAllByTestId('activity-dot');
    expect(dots.map(dot => dot.getAttribute('data-side'))).toEqual(['buy', 'sell', 'mixed']);
    expect(dots.map(dot => dot.getAttribute('data-fill'))).toEqual([
      'hsl(var(--positive))',
      'hsl(var(--negative))',
      'hsl(var(--warning))',
    ]);

    const key = screen.getByRole('list', { name: 'Activity marker key' });
    expect(within(key).getByText('Buy / increase')).toBeInTheDocument();
    expect(within(key).getByText('Sell / decrease')).toBeInTheDocument();
    expect(within(key).getByText('Buy and sell')).toBeInTheDocument();
  });

  it('adds a spoken window and return summary when one is supplied', () => {
    render(
      <NavChart
        series={series}
        periodLabel="1Y"
        summaryLabel="1Y window 2026-01-02 – 2026-01-03 · Strategy +10.0% · QQQ +5.0%"
      />,
    );
    expect(screen.getByRole('figure')).toHaveAccessibleName(
      '1Y NAV chart indexed to 100 · 1Y window 2026-01-02 – 2026-01-03 · Strategy +10.0% · QQQ +5.0%',
    );
  });

  it('describes the indexed window and the exact-date comparison basis', () => {
    render(<NavChart series={series} periodLabel="1M" />);
    expect(screen.getByTestId('nav-chart-window')).toHaveTextContent(
      '1M · 2026-01-02 – 2026-01-03 · Indexed to 100 at 2026-01-02',
    );
    expect(screen.getByRole('figure')).toHaveTextContent('Exact-date observations only');
    expect(screen.getByRole('figure')).toHaveTextContent('Compare within one market');
    const legend = screen.getByRole('list', { name: 'Chart series' });
    expect(within(legend).getByText('Primary')).toBeInTheDocument();
    expect(within(legend).getByText('Baseline')).toBeInTheDocument();
  });

  it('discloses partial and unavailable coverage instead of hiding it', () => {
    const partial: HorizonCoverage = {
      state: 'partial',
      asOf: '2026-01-03',
      requestedStart: '2026-01-01',
      firstObservation: '2026-01-02',
      observations: 2,
      missingDays: 1,
      cadenceDays: 1,
      reason: 'short_history',
    };
    const { rerender } = render(<NavChart series={series} periodLabel="1M" coverage={partial} />);
    const note = screen.getByTestId('nav-chart-coverage');
    expect(note).toHaveAttribute('data-coverage-state', 'partial');
    expect(note).toHaveTextContent('Partial coverage: first observation 2026-01-02.');
    expect(note).toHaveTextContent('History starts after the requested window.');

    rerender(
      <NavChart
        series={series}
        periodLabel="1M"
        coverage={{ ...partial, state: 'none', firstObservation: null, reason: 'invalid_dates' }}
      />,
    );
    expect(screen.getByTestId('nav-chart-coverage')).toHaveTextContent(
      'Coverage unavailable: first observation unavailable. No valid observation dates are retained.',
    );

    rerender(<NavChart series={series} periodLabel="1M" coverage={{ ...partial, state: 'full', reason: 'covered' }} />);
    expect(screen.queryByTestId('nav-chart-coverage')).not.toBeInTheDocument();
  });

  it('reports an empty comparison with the caller reason', () => {
    render(
      <NavChart
        series={[
          { key: 'a', label: 'A', nav: [{ date: '2026-01-01', value: 100 }] },
          { key: 'b', label: 'B', nav: [{ date: '2026-01-01', value: 100 }] },
        ]}
        periodLabel="1W"
        emptyReason="Only one exact-date observation is retained."
      />,
    );
    const empty = screen.getByTestId('nav-chart-empty');
    expect(empty).toHaveAttribute('role', 'status');
    expect(empty).toHaveTextContent('Only one exact-date observation is retained.');
    expect(screen.queryByTestId('line-chart')).not.toBeInTheDocument();
    expect(screen.getByTestId('nav-chart-window')).toHaveTextContent('1W · No aligned observations');
  });
});

describe('NavChartTooltip', () => {
  function renderTooltip(overrides: Partial<NavChartTooltipProps> = {}) {
    render(
      <NavChartTooltip
        active
        payload={[
          { dataKey: 'strategy', name: 'Strategy', value: 112.5 },
          { dataKey: 'qqq', name: 'QQQ', value: 105 },
        ]}
        label="2026-01-03"
        labels={{ strategy: 'Strategy (primary)', qqq: 'QQQ' }}
        {...overrides}
      />,
    );
  }

  it('formats every retained value and names the series', () => {
    renderTooltip();
    const tooltip = screen.getByTestId('nav-chart-tooltip');
    expect(tooltip).toHaveTextContent('Jan 3, 2026');
    expect(screen.getByTestId('nav-chart-tooltip-date')).toHaveTextContent('Jan 3, 2026');
    expect(screen.getByTestId('nav-chart-tooltip-date')).toHaveClass('font-semibold');
    expect(tooltip).toHaveTextContent('Observation date');
    expect(tooltip).toHaveTextContent('Strategy (primary)');
    expect(tooltip).toHaveTextContent('112.50 · +12.50%');
    expect(tooltip).toHaveTextContent('QQQ');
    expect(tooltip).toHaveTextContent('105.00 · +5.00%');
  });

  it('shows marker context when the hovered date has activity', () => {
    renderTooltip({ markers: [marker], label: '2026-01-02' });
    const block = screen.getByTestId('nav-chart-tooltip-marker');
    expect(block).toHaveTextContent('Buy · 2 trades');
    expect(block).toHaveTextContent('Instruments: AAPL, MSFT');
    expect(block).toHaveTextContent('Reasons: rebalance');
    expect(block).toHaveTextContent('Net weight change: +4.00%');
  });

  it('marks missing values instead of inventing a number', () => {
    renderTooltip({ payload: [{ dataKey: 'qqq', name: 'QQQ', value: null }] });
    expect(screen.getByTestId('nav-chart-tooltip')).toHaveTextContent('—');
  });

  it('renders nothing when inactive or empty', () => {
    const { container } = render(
      <NavChartTooltip active={false} payload={[{ dataKey: 'qqq', value: 100 }]} label="2026-01-03" />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
