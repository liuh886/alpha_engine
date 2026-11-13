import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { NavPoint } from '@/lib/nav-series';
import { Sparkline } from './Sparkline';

function sparkline(nav: NavPoint[], props: Partial<Parameters<typeof Sparkline>[0]> = {}) {
  const { container } = render(<Sparkline nav={nav} {...props} />);
  const svg = container.querySelector('svg');
  if (!svg) throw new Error('Sparkline SVG was not rendered.');
  return { svg, path: svg.querySelector('path') };
}

describe('Sparkline', () => {
  it('renders a deterministic path with stable coordinates', () => {
    const { path, svg } = sparkline([
      { date: '2026-01-01', value: 100 },
      { date: '2026-01-02', value: 110 },
    ]);
    expect(path?.getAttribute('d')).toBe('M2.00 30.00 L118.00 2.00');
    expect(path?.getAttribute('stroke')).toBe('currentColor');
    expect(path?.getAttribute('vector-effect')).toBe('non-scaling-stroke');
    expect(svg.getAttribute('preserveAspectRatio')).toBe('none');
    expect(svg.querySelectorAll('circle')).toHaveLength(0);
  });

  it('derives a signed tone from the first and last observation', () => {
    const up = sparkline([
      { date: '2026-01-01', value: 100 },
      { date: '2026-01-02', value: 110 },
    ]);
    expect(up.svg.getAttribute('class')).toContain('text-positive');
    expect(up.svg.getAttribute('data-tone')).toBe('positive');

    const down = sparkline([
      { date: '2026-01-01', value: 110 },
      { date: '2026-01-02', value: 100 },
    ]);
    expect(down.svg.getAttribute('class')).toContain('text-negative');
    expect(down.svg.getAttribute('data-tone')).toBe('negative');

    const flat = sparkline([
      { date: '2026-01-01', value: 100 },
      { date: '2026-01-02', value: 100 },
    ]);
    expect(flat.svg.getAttribute('class')).toContain('text-muted-foreground');
    expect(flat.svg.getAttribute('data-tone')).toBe('neutral');
  });

  it('honors an explicit neutral tone', () => {
    const { svg } = sparkline([
      { date: '2026-01-01', value: 100 },
      { date: '2026-01-02', value: 110 },
    ], { tone: 'neutral' });
    expect(svg.getAttribute('class')).toContain('text-muted-foreground');
    expect(svg.getAttribute('data-tone')).toBe('neutral');
  });

  it('breaks the path at invalid observations instead of connecting the gap', () => {
    const { path, svg } = sparkline([
      { date: '2026-01-01', value: 100 },
      { date: '2026-01-02', value: Number.NaN },
      { date: '2026-01-03', value: 105 },
    ]);
    expect(path?.getAttribute('d')).toBe('M2.00 30.00 L2.01 30.00 M118.00 2.00 L118.01 2.00');
    expect(svg.getAttribute('data-segment-count')).toBe('2');
    expect(svg.getAttribute('data-point-count')).toBe('2');
  });

  it('breaks the path at invalid dates and non-positive values', () => {
    const { path, svg } = sparkline([
      { date: '2026-01-01', value: 100 },
      { date: '2026-02-30', value: 101 },
      { date: '2026-01-03', value: 0 },
      { date: '2026-01-04', value: 104 },
    ]);
    expect(svg.getAttribute('data-segment-count')).toBe('2');
    expect(path?.getAttribute('d')).toBe('M2.00 30.00 L2.01 30.00 M118.00 2.00 L118.01 2.00');
  });

  it('downsamples without drawing one circle per point', () => {
    const nav = Array.from({ length: 200 }, (_, index) => ({
      date: new Date(Date.parse('2026-01-01T00:00:00Z') + index * 86_400_000).toISOString().slice(0, 10),
      value: index + 1,
    }));
    const { path, svg } = sparkline(nav);
    expect(svg.getAttribute('data-point-count')).toBe('60');
    expect(svg.querySelectorAll('circle')).toHaveLength(0);
    const commands = path?.getAttribute('d')?.match(/[ML]/g) ?? [];
    expect(commands).toHaveLength(60);
  });

  it('renders one short tick for a single observation', () => {
    const { path } = sparkline([{ date: '2026-01-01', value: 100 }]);
    expect(path?.getAttribute('d')).toBe('M60.00 16.00 L60.01 16.00');
  });

  it('renders nothing for an empty or invalid curve', () => {
    const { path, svg } = sparkline([{ date: '2026-01-01', value: Number.NaN }]);
    expect(path).toBeNull();
    expect(svg.getAttribute('data-point-count')).toBe('0');
  });

  it('is hidden from assistive technology unless a label is supplied', () => {
    const hidden = sparkline([{ date: '2026-01-01', value: 100 }]).svg;
    expect(hidden.getAttribute('aria-hidden')).toBe('true');
    expect(hidden.getAttribute('role')).toBeNull();

    const described = sparkline(
      [{ date: '2026-01-01', value: 100 }, { date: '2026-01-02', value: 110 }],
      { label: 'One month NAV trend' },
    ).svg;
    expect(described.getAttribute('role')).toBe('img');
    expect(described.getAttribute('aria-label')).toBe('One month NAV trend');
    expect(described.getAttribute('aria-hidden')).toBeNull();
  });
});
