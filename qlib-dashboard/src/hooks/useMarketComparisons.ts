import { useCallback, useEffect, useRef, useState } from 'react';
import {
  loadMarketEvidenceCatalog,
  loadSecurityMarketEvidence,
  type MarketBar,
  type MarketEvidenceCatalog,
  type MarketEvidenceMarket,
} from '@/lib/market-evidence';

export type MarketComparisonRequest = {
  key: string;
  market?: MarketEvidenceMarket;
  symbol?: string;
};

export function useMarketComparisons(market?: MarketEvidenceMarket) {
  const [catalogs, setCatalogs] = useState<MarketEvidenceCatalog[]>([]);
  const [marketBars, setMarketBars] = useState<Record<string, MarketBar[]>>({});
  const [loadingKeys, setLoadingKeys] = useState<string[]>([]);
  const [failedKeys, setFailedKeys] = useState<string[]>([]);
  const [catalogsLoading, setCatalogsLoading] = useState(false);
  const generationRef = useRef(0);

  useEffect(() => {
    const generation = ++generationRef.current;
    setCatalogs([]);
    setMarketBars({});
    setLoadingKeys([]);
    setFailedKeys([]);
    setCatalogsLoading(false);
    return () => {
      if (generationRef.current === generation) generationRef.current += 1;
    };
  }, [market]);

  const ensureCatalogs = useCallback(async () => {
    if (!market || catalogsLoading || catalogs.length >= 2) return;
    const generation = generationRef.current;
    const markets: MarketEvidenceMarket[] = market === 'us' ? ['us', 'cn'] : ['cn', 'us'];
    setCatalogsLoading(true);
    const results = await Promise.allSettled(markets.map(loadMarketEvidenceCatalog));
    if (generation !== generationRef.current) return;
    const loaded = results.flatMap(result => result.status === 'fulfilled' ? [result.value] : []);
    results.forEach((result, index) => {
      if (result.status === 'rejected') console.error(`Failed to load ${markets[index]} comparison catalog`, result.reason);
    });
    setCatalogs(loaded);
    setCatalogsLoading(false);
  }, [catalogs.length, catalogsLoading, market]);

  const requestComparison = useCallback(async ({ key, market: optionMarket, symbol }: MarketComparisonRequest) => {
    if (!optionMarket || !symbol || marketBars[key] || loadingKeys.includes(key)) return;
    const catalog = catalogs.find(candidate => candidate.market === optionMarket);
    if (!catalog) return;
    const generation = generationRef.current;
    setFailedKeys(current => current.filter(candidate => candidate !== key));
    setLoadingKeys(current => current.includes(key) ? current : [...current, key]);
    try {
      const evidence = await loadSecurityMarketEvidence(catalog, symbol);
      if (generation !== generationRef.current) return;
      setMarketBars(current => ({ ...current, [key]: evidence.bars }));
    } catch (error) {
      if (generation !== generationRef.current) return;
      console.error(`Failed to load comparison series ${key}`, error);
      setFailedKeys(current => current.includes(key) ? current : [...current, key]);
    } finally {
      if (generation === generationRef.current) {
        setLoadingKeys(current => current.filter(candidate => candidate !== key));
      }
    }
  }, [catalogs, loadingKeys, marketBars]);

  return {
    catalogs,
    marketBars,
    loadingKeys,
    failedKeys,
    catalogsLoading,
    ensureCatalogs,
    requestComparison,
  };
}
