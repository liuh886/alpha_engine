import { describe, expect, it } from 'vitest';
import {
  STOCK_RANKING_PERIODS,
  parseStockRankingsProjection,
  rankStockRows,
  stockRankingHref,
  type StockRankingsProjection,
  type StockReturnCell,
} from './stock-rankings';

const boundary = {
  schema_version: 'stock_rankings_projection_v1',
  view: 'stock_rankings_v1',
  research_only: true,
  trade_ready: false,
  periods: [...STOCK_RANKING_PERIODS],
};

function cells(value: number | null, reason: string | null = null): Record<string, StockReturnCell> {
  return Object.fromEntries(STOCK_RANKING_PERIODS.map((period) => [period, { value, reason }]));
}

function row(symbol: string, value: number | null, asOf = '2026-11-13', reason: string | null = null) {
  return {
    symbol,
    name: `${symbol} name`,
    as_of: asOf,
    cutoff: '2026-11-13',
    returns: cells(value, reason),
  };
}

function payload(rows: unknown[], market = 'us') {
  return { ...boundary, market, cutoff: '2026-11-13', rows };
}

function projection(market: 'us' | 'cn' = 'us'): StockRankingsProjection {
  return parseStockRankingsProjection(payload([
    row('BBB', 0.05),
    row('AAA', 0.05),
    row('CCC', 0.2),
    row('DDD', null, '2026-10-01', 'Only 1 observation in the 1M window; no measured return is shown.'),
  ], market), market);
}

describe('stock rankings projection parsing', () => {
  it('accepts the generated contract and preserves each row as-of and cutoff', () => {
    const parsed = projection();
    expect(parsed.market).toBe('us');
    expect(parsed.cutoff).toBe('2026-11-13');
    expect(parsed.rows).toHaveLength(4);
    expect(parsed.rows[0]).toMatchObject({ symbol: 'BBB', asOf: '2026-11-13', cutoff: '2026-11-13' });
  });

  it('rejects contract drift, duplicates, unsafe symbols and values without a basis', () => {
    expect(() => parseStockRankingsProjection({ ...payload([]), trade_ready: true }, 'us'))
      .toThrow(/research boundary/);
    expect(() => parseStockRankingsProjection(payload([], 'cn'), 'us')).toThrow(/market mismatch/);
    expect(() => parseStockRankingsProjection({ ...payload([]), view: 'other' }, 'us'))
      .toThrow(/contract/);
    expect(() => parseStockRankingsProjection({ ...payload([]), periods: ['1w'] }, 'us'))
      .toThrow(/horizons/);
    expect(() => parseStockRankingsProjection(payload([row('AAA', 0.1), row('AAA', 0.2)]), 'us'))
      .toThrow(/Duplicate/);
    expect(() => parseStockRankingsProjection(payload([{ ...row('AAA', 0.1), symbol: '../QQQ' }]), 'us'))
      .toThrow(/symbol identity/);
    expect(() => parseStockRankingsProjection(payload([row('AAA', null, '2026-11-13', null)]), 'us'))
      .toThrow(/missing both a return and a reason/);
    expect(() => parseStockRankingsProjection(payload([row('AAA', 0.1, '2026-11-20')]), 'us'))
      .toThrow(/newer than its catalog cutoff/);
  });
});

describe('stock ranking order and links', () => {
  it('ranks by selected return descending with symbol tie-break and missing values last', () => {
    const ranked = rankStockRows(projection(), '1m');
    expect(ranked.map((entry) => entry.symbol)).toEqual(['CCC', 'AAA', 'BBB', 'DDD']);
    expect(ranked.map((entry) => entry.rank)).toEqual([1, 2, 3, 4]);
    expect(ranked[3].selected.value).toBeNull();
    expect(ranked[3].selected.reason).toContain('Only 1 observation');
    expect(ranked.every((entry) => entry.market === 'us')).toBe(true);
  });

  it('limits the displayed list without reordering the remainder', () => {
    const ranked = rankStockRows(projection(), '1m', 2);
    expect(ranked.map((entry) => entry.symbol)).toEqual(['CCC', 'AAA']);
    expect(ranked.map((entry) => entry.rank)).toEqual([1, 2]);
  });

  it('keeps each market isolated and builds its own security link', () => {
    const ranked = rankStockRows(projection('cn'), '1m');
    expect(ranked.every((entry) => entry.market === 'cn')).toBe(true);
    expect(ranked.every((entry) => entry.href.startsWith('/securities/cn/'))).toBe(true);
    expect(stockRankingHref('us', 'BRK.B')).toBe('/securities/us/BRK.B');
    expect(stockRankingHref('cn', '000001')).toBe('/securities/cn/000001');
    expect(stockRankingHref('us', 'A/B')).toBe('/securities/us/A%2FB');
  });

  it('uses the selected horizon and applies the shared 14-day stale policy', () => {
    const value = parseStockRankingsProjection(payload([
      { ...row('OLD', 0.1, '2026-10-01'), returns: { ...cells(0.1), '1w': { value: 0.3, reason: null } } },
      { ...row('FRESH', 0.2, '2026-11-05'), returns: { ...cells(0.2), '1w': { value: 0.1, reason: null } } },
    ]), 'us');
    const ranked = rankStockRows(value, '1w');
    expect(ranked.map((entry) => entry.symbol)).toEqual(['OLD', 'FRESH']);
    expect(ranked[0].stale).toBe(true);
    expect(ranked[0].staleDays).toBe(43);
    expect(ranked[1].stale).toBe(false);
    expect(ranked[0].selected.value).toBe(0.3);
  });
});
