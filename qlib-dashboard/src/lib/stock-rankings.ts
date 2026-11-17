import { STALE_AFTER_DAYS, staleDays } from './metrics';

/**
 * Browser model for the Today page's per-market stock rankings. The projection
 * is generated at build time from governed market evidence; this module only
 * validates it and applies one deterministic display policy. It never fetches,
 * interpolates or fills a value.
 */

export type StockRankingMarket = 'us' | 'cn';
export const STOCK_RANKING_MARKETS = ['us', 'cn'] as const;

export type StockRankingPeriod = '1w' | '1m' | '3m' | '1y';
export const STOCK_RANKING_PERIODS = ['1w', '1m', '3m', '1y'] as const;

export const STOCK_RANKING_LIMIT = 20;
export const STOCK_RANKINGS_VIEW = 'stock_rankings_v1';
export const STOCK_RANKINGS_SCHEMA = 'stock_rankings_projection_v1';

export const STOCK_RANKING_MARKET_LABELS: Readonly<Record<StockRankingMarket, string>> = {
  us: 'US',
  cn: 'China',
};

export interface StockReturnCell {
  value: number | null;
  reason: string | null;
}

export interface StockRankingRow {
  symbol: string;
  name: string;
  asOf: string;
  cutoff: string;
  returns: Record<StockRankingPeriod, StockReturnCell>;
}

export interface StockRankingsProjection {
  market: StockRankingMarket;
  cutoff: string;
  rows: StockRankingRow[];
}

export interface StockRankingIssue {
  market: StockRankingMarket;
  message: string;
}

/** One projected row after ranking, with its market-specific link and stale state. */
export interface RankedStockRow extends StockRankingRow {
  rank: number;
  market: StockRankingMarket;
  href: string;
  /** The selected horizon's cell, identical to `returns[period]`. */
  selected: StockReturnCell;
  stale: boolean;
  staleDays: number;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const SAFE_SYMBOL = /^[A-Za-z0-9._-]+$/;

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`Invalid stock ranking ${label}.`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`Missing stock ranking ${label}.`);
  return value;
}

function isDate(value: unknown): value is string {
  if (typeof value !== 'string' || !ISO_DATE.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function date(value: unknown, label: string): string {
  if (!isDate(value)) throw new Error(`Invalid stock ranking ${label}.`);
  return value;
}

function cell(value: unknown, symbol: string, period: StockRankingPeriod): StockReturnCell {
  const raw = object(value, `return cell for ${symbol}/${period}`);
  const observed = raw.value;
  if (observed !== null && (typeof observed !== 'number' || !Number.isFinite(observed))) {
    throw new Error(`Invalid stock ranking return for ${symbol}/${period}.`);
  }
  const reason = raw.reason;
  if (reason !== null && (typeof reason !== 'string' || !reason.trim())) {
    throw new Error(`Invalid stock ranking reason for ${symbol}/${period}.`);
  }
  if (observed === null && reason === null) {
    throw new Error(`Stock ranking ${symbol}/${period} is missing both a return and a reason.`);
  }
  return { value: observed as number | null, reason: reason as string | null };
}

/**
 * Validate the generated projection and reject anything ambiguous: market or
 * boundary drift, duplicate symbols, an unsupported horizon, a return without
 * a coverage reason, or an as-of date beyond the catalog cutoff.
 */
export function parseStockRankingsProjection(
  value: unknown,
  market: StockRankingMarket,
): StockRankingsProjection {
  const raw = object(value, 'projection');
  if (raw.view !== STOCK_RANKINGS_VIEW || raw.schema_version !== STOCK_RANKINGS_SCHEMA) {
    throw new Error('Unsupported stock ranking projection contract.');
  }
  if (raw.research_only !== true || raw.trade_ready !== false) {
    throw new Error('Invalid stock ranking research boundary.');
  }
  if (raw.market !== market) throw new Error('Stock ranking market mismatch.');
  const cutoff = date(raw.cutoff, 'cutoff');
  const periods = Array.isArray(raw.periods) ? raw.periods.map(period => String(period)) : [];
  if (periods.length !== STOCK_RANKING_PERIODS.length
    || periods.some((period, index) => period !== STOCK_RANKING_PERIODS[index])) {
    throw new Error('Unsupported stock ranking horizons.');
  }
  if (!Array.isArray(raw.rows)) throw new Error('Missing stock ranking rows.');

  const seen = new Set<string>();
  const rows = raw.rows.map((item, index) => {
    const row = object(item, `row ${index}`);
    const symbol = text(row.symbol, 'symbol');
    if (!SAFE_SYMBOL.test(symbol)) throw new Error('Invalid stock ranking symbol identity.');
    if (seen.has(symbol)) throw new Error(`Duplicate stock ranking symbol: ${symbol}.`);
    seen.add(symbol);
    const name = text(row.name, 'name');
    const asOf = date(row.as_of, 'as-of date');
    if (asOf > cutoff) throw new Error(`Stock ranking ${symbol} is newer than its catalog cutoff.`);
    const rowCutoff = date(row.cutoff, 'row cutoff');
    if (rowCutoff !== cutoff) throw new Error(`Stock ranking ${symbol} has a conflicting cutoff.`);
    const returns = object(row.returns, `returns for ${symbol}`);
    for (const period of STOCK_RANKING_PERIODS) {
      if (!(period in returns)) throw new Error(`Stock ranking ${symbol} is missing ${period}.`);
    }
    return {
      symbol,
      name,
      asOf,
      cutoff: rowCutoff,
      returns: Object.fromEntries(
        STOCK_RANKING_PERIODS.map(period => [period, cell(returns[period], symbol, period)]),
      ) as Record<StockRankingPeriod, StockReturnCell>,
    };
  });

  return { market, cutoff, rows };
}

/** React Router path; the HashRouter renders it as `#/securities/<market>/<symbol>`. */
export function stockRankingHref(market: StockRankingMarket, symbol: string): string {
  return `/securities/${market}/${encodeURIComponent(symbol)}`;
}

export function formatStockRankingPeriod(period: StockRankingPeriod): string {
  return period.toUpperCase();
}

/**
 * Deterministic ranking within one market: selected return descending, rows
 * without a measured return last, ties by symbol ascending. The rank numbers
 * describe the displayed list only.
 */
export function rankStockRows(
  projection: StockRankingsProjection,
  period: StockRankingPeriod,
  limit: number = STOCK_RANKING_LIMIT,
): RankedStockRow[] {
  const rows = [...projection.rows].sort((left, right) => {
    const leftValue = left.returns[period].value;
    const rightValue = right.returns[period].value;
    if (leftValue === null && rightValue === null) return symbolOrder(left.symbol, right.symbol);
    if (leftValue === null) return 1;
    if (rightValue === null) return -1;
    if (rightValue !== leftValue) return rightValue - leftValue;
    return symbolOrder(left.symbol, right.symbol);
  });
  return rows.slice(0, Math.max(0, limit)).map((row, index) => {
    const days = staleDays(row.cutoff, row.asOf) ?? 0;
    return {
      ...row,
      rank: index + 1,
      market: projection.market,
      href: stockRankingHref(projection.market, row.symbol),
      selected: row.returns[period],
      stale: days > STALE_AFTER_DAYS,
      staleDays: days,
    };
  });
}

function symbolOrder(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}
