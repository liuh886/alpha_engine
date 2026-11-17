import { describe, expect, it } from 'vitest';
import {
  STOCK_RANKING_PERIODS,
  buildStockRankingsProjection,
  normalizeCloses,
  stockHorizonCoverage,
  stockNavReturn,
  stockPeriodStart,
} from './stock-rankings-projection.mjs';
import { horizonCoverage, performancePeriodStart } from '../src/lib/performancePeriods.ts';
import { navHorizonCoverage, navReturn } from '../src/lib/nav-returns.ts';

function bar(time, close) {
  return { time, open: close, high: close, low: close, close, volume: 1 };
}

/** Closes at the exact start of every horizon plus a few intra-week sessions. */
function fullSeries() {
  return [
    bar('2025-11-13', 100),
    bar('2026-08-13', 110),
    bar('2026-10-13', 120),
    bar('2026-11-06', 130),
    bar('2026-11-10', 135),
    bar('2026-11-13', 140),
  ];
}

const candidate = (symbol, bars, roles = ['selected_pool_candidate']) => ({
  symbol,
  name: symbol,
  roles,
  bars,
});

describe('stock ranking projection', () => {
  it('projects only selected-pool candidates, sorted by symbol, deterministically', () => {
    const symbols = [
      candidate('ZZZ', fullSeries()),
      candidate('AAA', fullSeries().map((row) => ({ ...row, close: row.close + 1 })), ['selected_pool_candidate', 'formal_traded']),
      candidate('QQQ', fullSeries(), ['benchmark']),
      candidate('TQQQ', fullSeries(), ['formal_traded']),
      candidate('SPX', fullSeries(), ['formal_auxiliary']),
      candidate('000300', fullSeries(), ['benchmark']),
    ];
    const projection = buildStockRankingsProjection({ market: 'us', cutoff: '2026-11-13', symbols });
    expect(projection.research_only).toBe(true);
    expect(projection.trade_ready).toBe(false);
    expect(projection.periods).toEqual([...STOCK_RANKING_PERIODS]);
    expect(projection.rows.map((row) => row.symbol)).toEqual(['AAA', 'ZZZ']);
    expect(projection.rows[0].as_of).toBe('2026-11-13');
    expect(projection.rows[0].cutoff).toBe('2026-11-13');
    for (const row of projection.rows) {
      expect(Object.keys(row.returns)).toEqual([...STOCK_RANKING_PERIODS]);
    }
    const again = buildStockRankingsProjection({ market: 'us', cutoff: '2026-11-13', symbols });
    expect(JSON.stringify(again)).toBe(JSON.stringify(projection));
  });

  it('rejects an empty candidate series and duplicate identities instead of dropping them', () => {
    expect(() => buildStockRankingsProjection({
      market: 'us', cutoff: '2026-11-13',
      symbols: [candidate('AAA', [])],
    })).toThrow(/no usable closes for us:AAA/);
    expect(() => buildStockRankingsProjection({
      market: 'cn', cutoff: '2026-11-13',
      symbols: [candidate('000001', fullSeries()), candidate('000001', fullSeries())],
    })).toThrow(/duplicate symbol/);
  });

  it('computes exact-date close-to-close returns for every horizon', () => {
    const points = normalizeCloses(fullSeries());
    expect(stockPeriodStart('2026-11-13', '1w')).toBe('2026-11-06');
    expect(stockPeriodStart('2026-11-13', '1m')).toBe('2026-10-13');
    expect(stockPeriodStart('2026-11-13', '3m')).toBe('2026-08-13');
    expect(stockPeriodStart('2026-11-13', '1y')).toBe('2025-11-13');
    expect(stockNavReturn(points, '1w')).toBeCloseTo(140 / 130 - 1, 12);
    expect(stockNavReturn(points, '1m')).toBeCloseTo(140 / 120 - 1, 12);
    expect(stockNavReturn(points, '3m')).toBeCloseTo(140 / 110 - 1, 12);
    expect(stockNavReturn(points, '1y')).toBeCloseTo(140 / 100 - 1, 12);

    const projection = buildStockRankingsProjection({
      market: 'us', cutoff: '2026-11-13', symbols: [candidate('AAA', fullSeries())],
    });
    expect(projection.rows[0].returns['1w']).toEqual({ value: 140 / 130 - 1, reason: null });
    expect(projection.rows[0].returns['1y']).toEqual({ value: 140 / 100 - 1, reason: null });
  });

  it('never interpolates or forward-fills a missing start', () => {
    // Requested 1W start is 2026-11-06 but the first observed close is 11-13.
    // The raw window degenerates to one observation (a zero from itself); the
    // display cell must refuse it rather than publish a fabricated 0%.
    const points = normalizeCloses([bar('2026-11-05', 100), bar('2026-11-13', 120)]);
    expect(stockNavReturn(points, '1w')).toBe(0);
    const coverage = stockHorizonCoverage(points, '1w');
    expect(coverage.observations).toBe(1);
    expect(stockNavReturn(points, '1m')).toBeCloseTo(120 / 100 - 1, 12);

    const projection = buildStockRankingsProjection({
      market: 'us', cutoff: '2026-11-13',
      symbols: [candidate('AAA', [bar('2026-11-05', 100), bar('2026-11-13', 120)])],
    });
    expect(projection.rows[0].returns['1w'].value).toBeNull();
    expect(projection.rows[0].returns['1w'].reason).toMatch(/1 observation|days apart/);
  });

  it('emits null with a reason for short history, coarse cadence and truncated windows', () => {
    const shortHistory = normalizeCloses([bar('2026-10-21', 100), bar('2026-11-13', 120)]);
    const short = buildStockRankingsProjection({
      market: 'us', cutoff: '2026-11-13', symbols: [candidate('SHORT', [bar('2026-10-21', 100), bar('2026-11-13', 120)])],
    }).rows[0].returns['1m'];
    expect(short.value).toBeNull();
    expect(short.reason).toContain('8 calendar days');

    const coarse = buildStockRankingsProjection({
      market: 'us', cutoff: '2026-11-13', symbols: [candidate('COARSE', [bar('2026-10-28', 100), bar('2026-11-13', 120)])],
    }).rows[0].returns['1w'];
    expect(coarse.value).toBeNull();
    expect(coarse.reason).toContain('16 days apart');

    const truncated = buildStockRankingsProjection({
      market: 'us', cutoff: '2026-11-13', symbols: [candidate('LATE', [bar('2025-12-20', 100), bar('2026-11-13', 120)])],
    }).rows[0].returns['1y'];
    expect(truncated.value).toBeNull();
    expect(truncated.reason).toContain('return is not shown');
    expect(shortHistory).toHaveLength(2);
  });

  it('keeps normalized closes ascending with last duplicate date winning', () => {
    const points = normalizeCloses([
      bar('2026-11-13', 120),
      bar('2026-11-06', 100),
      { ...bar('2026-11-13', 0), close: 0 },
      bar('2026-11-10', 110),
    ]);
    expect(points).toEqual([
      { date: '2026-11-06', value: 100 },
      { date: '2026-11-10', value: 110 },
      { date: '2026-11-13', value: 120 },
    ]);
  });

  it('pins period starts, coverage and returns to the TypeScript primitives', () => {
    const dates = ['2026-11-13', '2024-03-31', '2026-01-31', '2026-03-01', '2024-02-29', '2025-12-31'];
    for (const asOf of dates) {
      for (const period of STOCK_RANKING_PERIODS) {
        expect(stockPeriodStart(asOf, period), `${asOf}/${period}`)
          .toBe(performancePeriodStart(asOf, period));
      }
    }

    const series = [
      fullSeries(),
      [bar('2026-10-21', 100), bar('2026-11-13', 120)],
      [bar('2026-10-28', 100), bar('2026-11-13', 120)],
      [bar('2026-09-01', 100), bar('2026-11-13', 120)],
      [bar('2025-11-25', 100), bar('2026-11-13', 150)],
      [bar('2026-11-05', 100), bar('2026-11-13', 120)],
      [bar('2024-02-29', 80), bar('2025-02-28', 90), bar('2026-02-27', 110), bar('2026-11-13', 130)],
    ];
    for (const bars of series) {
      const points = normalizeCloses(bars);
      const rows = points.map((point) => ({ date: point.date, account: point.value }));
      for (const period of STOCK_RANKING_PERIODS) {
        expect(stockHorizonCoverage(points, period), `${JSON.stringify(bars)}/${period}`)
          .toEqual(horizonCoverage(rows, period));
        expect(stockHorizonCoverage(points, period)).toEqual(navHorizonCoverage(points, period));
        const expected = navReturn(points, period);
        const actual = stockNavReturn(points, period);
        if (expected === null) expect(actual).toBeNull();
        else expect(actual).toBeCloseTo(expected, 12);
      }
    }
  });
});
