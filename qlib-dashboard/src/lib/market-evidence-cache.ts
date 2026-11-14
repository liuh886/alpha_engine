import { MARKET_BASELINES, type BaselineMarket } from './baseline';
import { loadSecurityEvidence, type SecurityEvidence } from './security-evidence';

/**
 * One verified read per governed `market:symbol` for the life of the module.
 * `loadSecurityEvidence` verifies the catalog and digest on every call, so
 * Today, Strategies and the strategy chart share the same promise instead of
 * duplicating the bytes. The symbol defaults to the market baseline; governed
 * reference indices such as `us:SPX` pass their own canonical symbol. Failures
 * are evicted so an explicit remount retries.
 */
const marketEvidenceReads = new Map<string, Promise<SecurityEvidence>>();

export function readMarketEvidence(
  market: BaselineMarket,
  symbol: string = MARKET_BASELINES[market].symbol,
): Promise<SecurityEvidence> {
  const key = `${market}:${symbol}`;
  const cached = marketEvidenceReads.get(key);
  if (cached) return cached;
  const read = loadSecurityEvidence(market, symbol);
  marketEvidenceReads.set(key, read);
  void read.catch(() => {
    if (marketEvidenceReads.get(key) === read) marketEvidenceReads.delete(key);
  });
  return read;
}
