import { useEffect, useState } from 'react';
import { loadDerivedExcess } from '@/lib/derived-excess';
import { loadFormalNav } from '@/lib/formal-nav';
import type { GovernedRunSummary } from '@/lib/governed-run';
import {
  RANKING_INDEX_SYMBOLS,
  RANKING_INDEX_TITLES,
  indexRowsFromBars,
  rankingExcessFromDerived,
  retainedExcess,
  strategyRowsFromNav,
  type ModelRankingRow,
  type RankingExcess,
  type RankingMarket,
} from '@/lib/model-ranking';
import { loadSecurityEvidence, type SecurityEvidence } from '@/lib/security-evidence';

export interface ModelRankingIssue {
  id: string;
  kind: 'strategy' | 'index';
  message: string;
}

export interface ModelRankingState {
  rows: ModelRankingRow[];
  loading: boolean;
  issues: ModelRankingIssue[];
}

export interface ModelRankingOptions {
  includeIndices: boolean;
  includeExcess: boolean;
}

interface ReadResult {
  rows: ModelRankingRow[];
  issues: ModelRankingIssue[];
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : String(error);
}

// `loadSecurityEvidence` verifies the catalog and digest on every call. Share
// one promise per governed market/symbol so Today and Strategies cannot
// duplicate the same read; failures are evicted so an explicit remount retries.
const marketEvidenceReads = new Map<string, Promise<SecurityEvidence>>();

function readMarketEvidence(market: RankingMarket, symbol: string): Promise<SecurityEvidence> {
  const key = `${market}:${symbol}`;
  const cached = marketEvidenceReads.get(key);
  if (cached) return cached;
  const read = loadSecurityEvidence(market, symbol);
  marketEvidenceReads.set(key, read);
  read.catch(() => {
    if (marketEvidenceReads.get(key) === read) marketEvidenceReads.delete(key);
  });
  return read;
}

/** Retained metric first; a derived artifact only fills a genuinely absent value. */
async function excessForRun(run: GovernedRunSummary): Promise<RankingExcess | undefined> {
  const retained = retainedExcess(run);
  if (retained.value !== null) return retained;
  try {
    const derived = await loadDerivedExcess(run);
    return derived ? rankingExcessFromDerived(derived) : retained;
  } catch (error) {
    return {
      ...retained,
      reason: `${retained.reason ?? 'The retained excess metric is unavailable.'} Derived excess unavailable: ${errorMessage(error)}`,
    };
  }
}

async function readStrategyRun(
  run: GovernedRunSummary,
  includeExcess: boolean,
): Promise<ReadResult> {
  try {
    const nav = await loadFormalNav(run);
    const excess = includeExcess ? await excessForRun(run) : undefined;
    return { rows: strategyRowsFromNav(run, nav.rows, { excess }), issues: [] };
  } catch (error) {
    return {
      rows: [],
      issues: [{
        id: run.modelVersionId,
        kind: 'strategy',
        message: `${run.title}: ranking evidence unavailable (${errorMessage(error)}).`,
      }],
    };
  }
}

async function readIndex(market: RankingMarket): Promise<ReadResult> {
  const symbol = RANKING_INDEX_SYMBOLS[market];
  const title = RANKING_INDEX_TITLES[market];
  try {
    const evidence = await readMarketEvidence(market, symbol);
    return {
      rows: indexRowsFromBars(market, symbol, title, evidence.bars, evidence.cutoff),
      issues: [],
    };
  } catch (error) {
    return {
      rows: [],
      issues: [{
        id: `index:${market}:${symbol}`,
        kind: 'index',
        message: `${title}: governed market evidence unavailable (${errorMessage(error)}).`,
      }],
    };
  }
}

/**
 * Load ranking rows from governed bytes only: one compact `nav.json` per formal
 * run plus governed market evidence for the two declared baseline indices.
 * SP500 is not governed and is never requested here.
 */
export function useModelRanking(
  runs: GovernedRunSummary[],
  options: ModelRankingOptions,
): ModelRankingState {
  const { includeIndices, includeExcess } = options;
  const [state, setState] = useState<ModelRankingState>(() => ({
    rows: [],
    loading: runs.length > 0,
    issues: [],
  }));

  useEffect(() => {
    let active = true;
    if (!runs.length && !includeIndices) {
      setState((previous) => previous.loading || previous.rows.length || previous.issues.length
        ? { rows: [], loading: false, issues: [] }
        : previous);
      return () => { active = false; };
    }
    setState((previous) => ({ rows: previous.rows, loading: true, issues: [] }));
    const reads: Array<Promise<ReadResult>> = runs.map((run) => readStrategyRun(run, includeExcess));
    if (includeIndices) {
      reads.push(readIndex('us'), readIndex('cn'));
    }
    void Promise.all(reads).then((results) => {
      if (!active) return;
      setState({
        rows: results.flatMap((result) => result.rows),
        loading: false,
        issues: results.flatMap((result) => result.issues),
      });
    });
    return () => { active = false; };
  }, [runs, includeIndices, includeExcess]);

  return state;
}
