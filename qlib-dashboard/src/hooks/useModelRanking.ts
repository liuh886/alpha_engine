import { useEffect, useState } from 'react';
import { loadDerivedExcess } from '@/lib/derived-excess';
import { loadFormalNav } from '@/lib/formal-nav';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { readMarketEvidence } from '@/lib/market-evidence-cache';
import {
  RANKING_INDEXES,
  indexRowsFromBars,
  rankingExcessFromDerived,
  retainedExcess,
  strategyRowsFromNav,
  type ModelRankingRow,
  type RankingExcess,
  type RankingIndexIdentity,
} from '@/lib/model-ranking';
import { SecurityEvidenceUnavailableError } from '@/lib/security-evidence';

/** Why an index card has no row: simply unpublished, or unreadable evidence. */
export type ModelRankingIssueState = 'awaiting_publication' | 'unavailable';

export interface ModelRankingIssue {
  id: string;
  kind: 'strategy' | 'index';
  message: string;
  /** Index reads only: distinguishes a publication gap from a genuine failure. */
  state?: ModelRankingIssueState;
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

/** A missing governed publication keeps its distinct, non-alarming state. */
function isUnavailablePublication(error: unknown): boolean {
  return error instanceof SecurityEvidenceUnavailableError
    || (error instanceof Error && error.name === 'SecurityEvidenceUnavailableError');
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
    const [nav, excess] = await Promise.all([
      loadFormalNav(run),
      includeExcess ? excessForRun(run) : Promise.resolve(undefined),
    ]);
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

async function readIndex(index: RankingIndexIdentity): Promise<ReadResult> {
  const { market, symbol, title } = index;
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
        state: isUnavailablePublication(error) ? 'awaiting_publication' : 'unavailable',
      }],
    };
  }
}

/**
 * Load ranking rows from governed bytes only: one compact `nav.json` per formal
 * run plus governed market evidence for every declared index identity (QQQ,
 * S&P 500 and CSI 300). A declared index whose series has not been published
 * yields a scoped issue and no row; it is never substituted or synthesised.
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
      reads.push(...RANKING_INDEXES.map((index) => readIndex(index)));
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
