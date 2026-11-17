import { useEffect, useState } from 'react';
import {
  STOCK_RANKING_MARKET_LABELS,
  STOCK_RANKING_MARKETS,
  parseStockRankingsProjection,
  type StockRankingIssue,
  type StockRankingMarket,
  type StockRankingsProjection,
} from '@/lib/stock-rankings';

/**
 * One read of both generated per-market ranking projections. A failed market
 * yields a scoped issue and no rows; the other market stays readable and no
 * value is substituted across markets.
 */

export interface StockRankingsState {
  projections: Partial<Record<StockRankingMarket, StockRankingsProjection>>;
  loading: boolean;
  issues: StockRankingIssue[];
}

const root = () => `${import.meta.env.BASE_URL}data/stock-rankings/`;

async function readProjection(market: StockRankingMarket): Promise<StockRankingsProjection> {
  const response = await fetch(`${root()}${market}.json`, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`stock rankings unavailable (${response.status}).`);
  return parseStockRankingsProjection(JSON.parse(await response.text()), market);
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : String(error);
}

export function useStockRankings(): StockRankingsState {
  const [state, setState] = useState<StockRankingsState>({
    projections: {},
    loading: true,
    issues: [],
  });

  useEffect(() => {
    let active = true;
    void Promise.all(STOCK_RANKING_MARKETS.map(async (market) => {
      try {
        return { market, projection: await readProjection(market) };
      } catch (error) {
        return { market, error: errorMessage(error) };
      }
    })).then((results) => {
      if (!active) return;
      const projections: StockRankingsState['projections'] = {};
      const issues: StockRankingIssue[] = [];
      for (const result of results) {
        if (result.projection) projections[result.market] = result.projection;
        else issues.push({
          market: result.market,
          message: `${STOCK_RANKING_MARKET_LABELS[result.market]} stock rankings unavailable (${result.error}).`,
        });
      }
      setState({ projections, loading: false, issues });
    });
    return () => { active = false; };
  }, []);

  return state;
}
