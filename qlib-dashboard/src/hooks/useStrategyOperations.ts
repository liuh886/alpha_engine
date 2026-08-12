import { useEffect, useMemo, useState } from 'react';
import type { GovernedRunSummary } from '@/lib/governed-run';
import {
  loadRuntimeStrategyOperation,
  loadStrategyOperations,
  type StrategyOperationsClient,
  type StrategyOperationsSnapshot,
} from '@/lib/strategy-operations';
import { useAccessControl } from './useAccessControl';
import { useAlphaMembership } from './useAlphaMembership';

export function useStrategyOperations(runs: GovernedRunSummary[]) {
  const access = useAccessControl();
  const membership = useAlphaMembership();
  const formalRuns = useMemo(() => runs.filter((run) => run.channel === 'formal'), [runs]);
  const [snapshots, setSnapshots] = useState<Map<string, StrategyOperationsSnapshot>>(new Map());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (membership.loading || access.policyLoading) return;
    let active = true;
    setLoading(true);

    void (async () => {
      const next = await loadStrategyOperations(formalRuns);
      const runtimeSnapshots = Array.from(next.values()).filter((snapshot) => {
        const requiredTier = access.requiredTier('strategy', snapshot.strategyId);
        return requiredTier === 'public' || membership.signedIn;
      });
      if (runtimeSnapshots.length) {
        const client = await membership.getClient();
        if (client) {
          await Promise.all(runtimeSnapshots.map(async (snapshot) => {
            try {
              const runtimeSnapshot = await loadRuntimeStrategyOperation(
                client as StrategyOperationsClient,
                snapshot.strategyId,
                snapshot.modelVersionId,
              );
              if (runtimeSnapshot) next.set(snapshot.modelVersionId, runtimeSnapshot);
            } catch {
              // Fail closed at the product surface: keep the redacted public identity shell.
            }
          }));
        }
      }
      if (!active) return;
      setSnapshots(next);
      setLoading(false);
    })();

    return () => { active = false; };
  }, [access.policyLoading, access.requiredTier, formalRuns, membership.getClient, membership.loading, membership.signedIn]);

  return { formalRuns, snapshots, loading };
}
