import { describe, expect, it } from 'vitest';
import {
  MAX_COMPARE_OVERLAYS,
  commonExactDates,
  entityOverlapsWindow,
  filterEntityOptions,
  firstFreeEntitySlot,
  instrumentEntityId,
  instrumentEntityOptions,
  rebaseEntityWindow,
  type EntitySeriesInput,
} from './entity-overlays';
import type { SecuritySymbol } from './security-evidence';

const point = (date: string, value: number) => ({ date, value });
const input = (id: string, points: Array<{ date: string; value: number }>): EntitySeriesInput => ({
  id,
  label: id,
  points,
});

describe('entity comparison window', () => {
  it('uses one global exact common start and rebases every series to 100 there', () => {
    const a = input('a', [point('2026-01-01', 50), point('2026-01-02', 55), point('2026-01-03', 66)]);
    const b = input('b', [point('2025-12-31', 10), point('2026-01-02', 20), point('2026-01-03', 40)]);
    const c = input('c', [point('2026-01-02', 5), point('2026-01-03', 10)]);
    const window = rebaseEntityWindow([a, b, c]);
    expect(window).not.toBeNull();
    expect(window?.startDate).toBe('2026-01-02');
    expect(window?.endDate).toBe('2026-01-03');
    expect(window?.observations).toBe(2);
    for (const series of window?.series ?? []) {
      expect(series.points[0]).toEqual({ date: '2026-01-02', value: 100 });
      expect(series.points).toHaveLength(2);
    }
    // No interpolation or forward fill: the 2025-12-31 observation of b is not
    // carried into the shared window.
    expect(window?.series.find(series => series.id === 'b')?.points).toEqual([
      { date: '2026-01-02', value: 100 },
      { date: '2026-01-03', value: 200 },
    ]);
  });

  it('recomputes the window when a series is added or removed, never rebasing alone', () => {
    const base = input('base', [point('2026-01-01', 100), point('2026-01-02', 101), point('2026-01-03', 102)]);
    const late = input('late', [point('2026-01-02', 50), point('2026-01-03', 60)]);
    const alone = rebaseEntityWindow([base]);
    expect(alone?.startDate).toBe('2026-01-01');
    const together = rebaseEntityWindow([base, late]);
    expect(together?.startDate).toBe('2026-01-02');
    // The base series is rebased at the new global start, not its own first date.
    expect(together?.series[0].points[0]).toEqual({ date: '2026-01-02', value: 100 });
    const removed = rebaseEntityWindow([base]);
    expect(removed?.startDate).toBe('2026-01-01');
  });

  it('returns null when the displayed series share fewer than two exact dates', () => {
    const a = input('a', [point('2026-01-01', 10), point('2026-01-02', 11)]);
    const b = input('b', [point('2026-02-01', 20), point('2026-02-02', 21)]);
    expect(commonExactDates([a, b])).toEqual([]);
    expect(rebaseEntityWindow([a, b])).toBeNull();
    expect(entityOverlapsWindow(a.points, b.points)).toBe(false);
    expect(entityOverlapsWindow(a.points, [point('2026-01-02', 9), point('2026-01-03', 10)])).toBe(false);
  });

  it('ignores invalid or unobserved rows rather than filling them', () => {
    const base = input('base', [point('2026-01-01', 100), point('2026-01-02', 0), point('2026-01-03', 102)]);
    const other = input('other', [point('2026-01-01', 50), point('2026-01-02', 55), point('2026-01-03', 60)]);
    const window = rebaseEntityWindow([base, other]);
    // The zero base value is not a valid observation, so 2026-01-02 drops out.
    expect(window?.observations).toBe(2);
    expect(window?.series[0].points.map(item => item.date)).toEqual(['2026-01-01', '2026-01-03']);
  });
});

describe('comparison entity pickers', () => {
  const symbols: SecuritySymbol[] = [
    { symbol: 'AAPL', name: 'Apple', instrument_id: 'us:AAPL', path: 'symbols/AAPL.json', sha256: 'a'.repeat(64), source_sha256: 'a'.repeat(64), source_instruments: ['AAPL'], roles: [] },
    { symbol: 'MSFT', name: 'Microsoft', instrument_id: 'us:MSFT', path: 'symbols/MSFT.json', sha256: 'b'.repeat(64), source_sha256: 'b'.repeat(64), source_instruments: ['MSFT'], roles: [] },
  ];

  it('never offers the page instrument or another market', () => {
    const options = instrumentEntityOptions('us', symbols, 'AAPL');
    expect(options.map(option => option.label)).toEqual(['MSFT']);
    expect(options[0].id).toBe(instrumentEntityId('us', 'MSFT'));
    // A CN page reads only its own catalog; a US symbol cannot enter.
    expect(instrumentEntityOptions('cn', [], '002594')).toEqual([]);
  });

  it('searches by symbol and name', () => {
    const options = instrumentEntityOptions('us', symbols, 'AAPL');
    expect(filterEntityOptions(options, 'msf')).toHaveLength(1);
    expect(filterEntityOptions(options, 'microsoft')).toHaveLength(1);
    expect(filterEntityOptions(options, 'AAPL')).toHaveLength(0);
  });

  it('caps entity colours at four stable slots and reuses a freed slot', () => {
    expect(MAX_COMPARE_OVERLAYS).toBe(4);
    expect(firstFreeEntitySlot([])).toBe(0);
    expect(firstFreeEntitySlot([0, 2])).toBe(1);
    expect(firstFreeEntitySlot([0, 1, 2, 3])).toBeNull();
    // Removing slot 1 frees only that slot; existing identities keep theirs.
    expect(firstFreeEntitySlot([0, 2, 3])).toBe(1);
  });
});
