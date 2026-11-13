import { MARKET_BASELINES, marketNavFromBars, type BaselineMarket } from './baseline';
import { alignNavSeries, rebaseNav, type NavPoint } from './nav-series';
import {
  loadSecurityEvidence,
  type SecurityBar,
  type SecurityEvidence,
} from './security-evidence';

export type SecurityMarket = BaselineMarket;

/**
 * The governed market baseline identity for a security page. QQQ is the only US
 * baseline and CSI 300 (000300) the only CN baseline; no other index, ETF or
 * cross-market substitute is selectable here.
 */
export function marketBaseline(market: SecurityMarket): { symbol: string; label: string } {
  return MARKET_BASELINES[market];
}

export function isMarketBaselineInstrument(market: SecurityMarket, symbol: string): boolean {
  return symbol.trim().toUpperCase() === MARKET_BASELINES[market].symbol.toUpperCase();
}

export interface IndexedBaselineSeries {
  /** First exact common observation; both series are 100 here. */
  startDate: string;
  endDate: string;
  observations: number;
  instrument: NavPoint[];
  baseline: NavPoint[];
}

/**
 * Exact-date intersection of instrument and baseline opens, each rebased to 100
 * at the first common date. No interpolation, forward-fill or synthetic session
 * is introduced, and the result is open-to-open price return (not total return).
 */
export function indexedBaselineSeries(
  instrumentBars: readonly SecurityBar[],
  baselineBars: readonly SecurityBar[],
): IndexedBaselineSeries | null {
  const aligned = alignNavSeries(marketNavFromBars(instrumentBars), marketNavFromBars(baselineBars));
  if (aligned.length < 2) return null;
  const instrument = rebaseNav(aligned.map(point => ({ date: point.date, value: point.primary })));
  const baseline = rebaseNav(aligned.map(point => ({ date: point.date, value: point.baseline })));
  if (instrument.length !== aligned.length || baseline.length !== aligned.length) return null;
  return {
    startDate: aligned[0].date,
    endDate: aligned[aligned.length - 1].date,
    observations: aligned.length,
    instrument: instrument.map(point => ({ date: point.date, value: point.value * 100 })),
    baseline: baseline.map(point => ({ date: point.date, value: point.value * 100 })),
  };
}

/**
 * A baseline load is cached by market, symbol and instrument evidence cutoff so
 * toggling the mode or changing the range cannot issue a second concurrent read.
 * A rejected load is evicted, so an explicit retry is possible.
 */
const baselineRequests = new Map<string, Promise<SecurityEvidence>>();

export function securityBaselineCacheKey(
  market: SecurityMarket,
  symbol: string,
  cutoff: string,
): string {
  return `${market}:${symbol.trim().toUpperCase()}:${cutoff}`;
}

export function loadMarketBaseline(market: SecurityMarket, cutoff: string): Promise<SecurityEvidence> {
  const identity = MARKET_BASELINES[market];
  const key = securityBaselineCacheKey(market, identity.symbol, cutoff);
  const cached = baselineRequests.get(key);
  if (cached) return cached;
  const request = loadSecurityEvidence(market, identity.symbol).then(evidence => {
    if (evidence.market !== market || evidence.symbol !== identity.symbol) {
      throw new Error('The published market baseline identity does not match its governed symbol.');
    }
    return evidence;
  });
  baselineRequests.set(key, request);
  request.catch(() => {
    if (baselineRequests.get(key) === request) baselineRequests.delete(key);
  });
  return request;
}

/** Test/entry isolation helper; production pages rely on the shared cache. */
export function clearMarketBaselineCache(): void {
  baselineRequests.clear();
}
