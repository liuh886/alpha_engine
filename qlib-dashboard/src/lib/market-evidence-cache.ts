import { MARKET_BASELINES, type BaselineMarket } from './baseline';
import { loadSecurityEvidence, type SecurityEvidence } from './security-evidence';

/**
 * One verified read per governed market baseline for the life of the module.
 * `loadSecurityEvidence` verifies the catalog and digest on every call, so Today,
 * Strategies and the strategy chart share the same promise instead of
 * duplicating the bytes. Failures are evicted so an explicit remount retries.
 */
const marketEvidenceReads = new Map<string, Promise<SecurityEvidence>>();

export function readMarketEvidence(market: BaselineMarket): Promise<SecurityEvidence> {
  const symbol = MARKET_BASELINES[market].symbol;
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
