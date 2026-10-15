import { useCallback, useEffect, useMemo, useState } from 'react';
import type { GovernedRunSummary } from '@/lib/governed-run';
import {
  loadRuntimeStrategyOperation,
  loadStrategyOperations,
  assertStrategyOperationRun,
  type StrategyOperationsClient,
  type StrategyOperationsSnapshot,
} from '@/lib/strategy-operations';
import { useAccessControl } from './useAccessControl';
import { useAlphaMembership } from './useAlphaMembership';

const EMPTY_SNAPSHOTS = new Map<string, StrategyOperationsSnapshot>();

export function useStrategyOperations(runs: GovernedRunSummary[]) {
  const access = useAccessControl();
  const membership = useAlphaMembership();
  const formalRuns = useMemo(() => runs.filter((run) => run.channel === 'formal'), [runs]);
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt((current) => current + 1), []);
  // Hide superseded evidence during render, including account and tier changes.
  const request = useMemo(() => ({ formalRuns, attempt }), [formalRuns, attempt,
    access.policyLoading, access.requiredTier, access.tier, membership.loading, membership.userId, membership.getClient]);
  const [result, setResult] = useState<{
    request: typeof request;
    snapshots: Map<string, StrategyOperationsSnapshot>;
    issues: string[];
    loading: boolean;
  } | null>(null);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const deadline = window.setTimeout(() => {
      active = false;
      controller.abort();
      setResult((current) => ({ request,
        snapshots: current?.request === request ? current.snapshots : EMPTY_SNAPSHOTS,
        issues: [...(current?.request === request ? current.issues : []), 'Operations reading timed out. Retry to check the published records again.'],
        loading: false,
      }));
    }, 15_000);
    const cleanup = () => {
      active = false;
      window.clearTimeout(deadline);
      controller.abort();
    };
    if (membership.loading || access.policyLoading) return cleanup;
    void (async () => {
      const next = await loadStrategyOperations(formalRuns, controller.signal);
      if (!active) return;
      const issues = formalRuns.filter((run) => !next.get(run.modelVersionId)?.sourceIdentity.formalBundleId)
        .map((run) => `${run.title}: published operations could not be verified.`);
      const publish = (loading: boolean) => {
        if (active) setResult({ request, snapshots: new Map(next), issues: [...issues], loading });
      };
      publish(true);
      const runtimeSnapshots = Array.from(next.values()).filter((snapshot) => {
        if (!snapshot.sourceIdentity.formalBundleId) return false;
        const requiredTier = access.requiredTier('strategy', snapshot.strategyId);
        return access.canAccess(requiredTier);
      });
      try {
        if (runtimeSnapshots.length) {
          const client = await membership.getClient();
          if (!active) return;
          if (!client) throw new Error('Account client unavailable');
          await Promise.all(runtimeSnapshots.map(async (snapshot) => {
            const run = formalRuns.find((candidate) => candidate.modelVersionId === snapshot.modelVersionId)!;
            try {
              const runtimeSnapshot = await loadRuntimeStrategyOperation(
                client as StrategyOperationsClient,
                snapshot.strategyId,
                snapshot.modelVersionId,
              );
              if (!active) return;
              if (!runtimeSnapshot) throw new Error('Current operations unavailable');
              assertStrategyOperationRun(runtimeSnapshot, run);
              next.set(snapshot.modelVersionId, runtimeSnapshot);
            } catch {
              issues.push(`${run.title}: current operations could not be verified.`);
            }
            publish(true);
          }));
        }
      } catch {
        issues.push('Current operations could not be read. Retry when the account service is available.');
      } finally {
        window.clearTimeout(deadline);
        publish(false);
      }
    })();

    return cleanup;
  }, [request, membership.getClient]);

  const current = result?.request === request ? result : null;
  return { formalRuns, snapshots: current?.snapshots ?? EMPTY_SNAPSHOTS,
    loading: current?.loading ?? true, issues: current?.issues ?? [], reload };
}
