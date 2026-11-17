import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CompareLegend, type CompareLegendItem } from './CompareLegend';

const items: CompareLegendItem[] = [
  { id: 'base:instrument', label: 'AAPL · indexed price', colorRole: 'primary', dashed: false, kind: 'instrument' },
  { id: 'baseline:market', label: 'QQQ', detail: 'indexed price', colorRole: 'baseline', dashed: true, kind: 'baseline' },
  {
    id: 'model:us:qqq_v1',
    label: 'QQQ Rotation',
    detail: 'model NAV',
    colorRole: 'model-1',
    dashed: false,
    kind: 'model',
    onRemove: vi.fn(),
  },
  {
    id: 'instrument:us:MSFT',
    label: 'MSFT',
    detail: 'indexed price',
    colorRole: 'entity-1',
    dashed: true,
    kind: 'instrument',
    onRemove: vi.fn(),
    unavailableReason: 'No exact common dates with the other displayed series in this range.',
  },
  {
    id: 'instrument:us:NVDA',
    label: 'NVDA',
    detail: 'indexed price',
    colorRole: 'entity-2',
    dashed: true,
    kind: 'instrument',
    onRemove: vi.fn(),
    loading: true,
  },
];

describe('CompareLegend', () => {
  it('names every entity in ink text with the swatch carrying identity', () => {
    render(<CompareLegend items={items} />);
    const list = screen.getByRole('list', { name: 'Comparison entities' });
    expect(list).toHaveTextContent('AAPL · indexed price');
    expect(list).toHaveTextContent('QQQ');
    expect(list).toHaveTextContent('QQQ Rotation');
    expect(list).toHaveTextContent('MSFT');
    expect(list).toHaveTextContent('NVDA');
    expect(screen.getByTestId('compare-legend-model:us:qqq_v1').querySelector('[aria-hidden="true"]'))
      .toHaveStyle({ borderTop: '2px solid hsl(var(--chart-4))' });
    expect(screen.getByTestId('compare-legend-instrument:us:NVDA').querySelector('[aria-hidden="true"]'))
      .toHaveStyle({ borderTop: '2px dashed hsl(var(--entity-2))' });
  });

  it('shows unavailable and loading states without plotting a fabricated series', () => {
    render(<CompareLegend items={items} />);
    expect(screen.getByTestId('compare-unavailable-instrument:us:MSFT')).toHaveTextContent(
      'Not plotted: No exact common dates with the other displayed series in this range.',
    );
    expect(screen.getByTestId('compare-loading-instrument:us:NVDA')).toHaveTextContent('Loading…');
    expect(screen.getByTestId('compare-legend-instrument:us:MSFT').querySelector('[aria-hidden="true"]'))
      .toHaveStyle({ borderTop: '2px dotted hsl(var(--muted-foreground))' });
  });

  it('removes an overlay by entity identity and never removes the base or baseline', () => {
    render(<CompareLegend items={items} />);
    fireEvent.click(screen.getByRole('button', { name: 'Remove QQQ Rotation from comparison' }));
    expect(items[2].onRemove).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: /Remove AAPL/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Remove QQQ$/ })).not.toBeInTheDocument();
  });
});
