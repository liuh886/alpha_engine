import { useEffect, useMemo, useState } from 'react';
import type { GovernedRunSummary } from '@/lib/governed-run';
import {
  loadProtectedStrategyOperation,
  loadStrategyOperations,
  type StrategyOperationsClient,
  type StrategyOperationsSnapshot,
} from '@/lib/strategy-operations';
import { useAlphaMembership } from './useAlphaMembership';

export function useStrategyOperations(runs: GovernedRunSummary[]) {
  const membership = useAlphaMembership();
  const formalRuns = useMemo(() => runs.filter((run) => run.channel === 'formal'), [runs]);
  const [snapshots, setSnapshots] = useState<Map<string, StrategyOperationsSnapshot>>(new Map());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (membership.loading) return;
    let active = true;
    setLoading(true);

    void (async () => {
      const next = await loadStrategyOperations(formalRuns);
      if (membership.signedIn) {
        const client = await membership.getClient();
        if (client) {
          const protectedSnapshots = Array.from(next.values()).filter(
            (snapshot) => snapshot.currentOperationsAccess !== 'public',
          );
          await Promise.all(protectedSnapshots.map(async (snapshot) => {
            try {
              const protectedSnapshot = await loadProtectedStrategyOperation(
                client as StrategyOperationsClient,
                snapshot.strategyId,
                snapshot.modelVersionId,
              );
              if (protectedSnapshot) next.set(snapshot.modelVersionId, protectedSnapshot);
            } catch {
              // Fail closed: keep the redacted public projection when entitlement delivery fails.
            }
          }));
        }
      }
      if (!active) return;
      setSnapshots(next);
      setLoading(false);
    })();

    return () => { active = false; };
  }, [formalRuns, membership.getClient, membership.loading, membership.signedIn]);

  return { formalRuns, snapshots, loading };
}
