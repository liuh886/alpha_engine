import { useCallback, useEffect, useMemo, useState } from 'react';
import type { GovernedRunSummary } from '@/lib/governed-run';
import {
  loadRuntimeStrategyOperations,
  loadStrategyOperations,
  assertStrategyOperationRun,
  type StrategyOperationsClient,
  type StrategyOperationsSnapshot,
} from '@/lib/strategy-operations';
import { useAccessControl } from './useAccessControl';
import { useAlphaMembership } from './useAlphaMembership';

export interface StrategyOperationsReadIssue {
  modelVersionId: string | null;
  message: string;
}

const EMPTY_SNAPSHOTS = new Map<string, StrategyOperationsSnapshot>();

function previousObservations(snapshots: Map<string, StrategyOperationsSnapshot>) {
  return new Map(Array.from(snapshots).filter(([, snapshot]) => snapshot.readState === 'retained'
    || !snapshot.readState && Boolean(snapshot.sourceIdentity.ledgerFingerprint))
    .map(([id, snapshot]) => [id, { ...snapshot, readState: 'retained' as const }]));
}

export function useStrategyOperations(runs: GovernedRunSummary[]) {
  const access = useAccessControl();
  const membership = useAlphaMembership();
  const formalRuns = useMemo(() => runs.filter((run) => run.channel === 'formal'), [runs]);
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => {
    if (access.policyError) void access.reloadPolicies();
    setAttempt((current) => current + 1);
  }, [access.policyError, access.reloadPolicies]);
  // Returning to this tab rechecks mutable operations; route changes reuse the verified read.
  useEffect(() => {
    const refresh = () => { if (document.visibilityState === 'visible') reload(); };
    document.addEventListener('visibilitychange', refresh);
    return () => document.removeEventListener('visibilitychange', refresh);
  }, [reload]);
  // Hide superseded evidence during render, including account and tier changes.
  const identity = useMemo(() => ({ formalRuns }), [formalRuns,
    access.policyLoading, access.requiredTier, access.tier, membership.loading, membership.userId, membership.getClient]);
  const request = useMemo(() => ({ identity, attempt }), [identity, attempt]);
  const [result, setResult] = useState<{
    request: typeof request;
    snapshots: Map<string, StrategyOperationsSnapshot>;
    issues: StrategyOperationsReadIssue[];
    loading: boolean;
  } | null>(null);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const markUnread = (snapshot: StrategyOperationsSnapshot) => snapshot.readState === 'protected'
      ? { ...snapshot, readState: 'unavailable' as const } : snapshot;
    let pendingModels: Set<string> | null = null;
    setResult(previous => ({ request,
      snapshots: previous?.request.identity === identity ? previousObservations(previous.snapshots) : EMPTY_SNAPSHOTS,
      issues: [], loading: true,
    }));
    const deadline = window.setTimeout(() => {
      active = false;
      controller.abort();
      setResult((current) => {
        const snapshots = current?.request.identity === identity ? current.snapshots : EMPTY_SNAPSHOTS;
        const message = 'Operations reading timed out. Retry to check the published records again.';
        const timedOut: StrategyOperationsReadIssue[] = pendingModels?.size
          ? Array.from(pendingModels, modelVersionId => ({ modelVersionId, message }))
          : [{ modelVersionId: null, message }];
        return { request,
          snapshots: new Map(Array.from(snapshots, ([id, snapshot]) =>
            [id, pendingModels?.has(id) ? markUnread(snapshot) : snapshot])),
          issues: [...(current?.request.identity === identity ? current.issues : []), ...timedOut], loading: false,
        };
      });
    }, 15_000);
    const cleanup = () => {
      active = false;
      window.clearTimeout(deadline);
      controller.abort();
    };
    if (!formalRuns.length || membership.loading || access.policyLoading) return cleanup;
    void (async () => {
      const next = new Map(await loadStrategyOperations(formalRuns, controller.signal));
      if (!active) return;
      const issues: StrategyOperationsReadIssue[] = formalRuns.filter((run) => !next.get(run.modelVersionId)?.sourceIdentity.formalBundleId)
        .map(run => ({ modelVersionId: run.modelVersionId, message: `${run.title}: published operations could not be verified.` }));
      if (access.policyError) issues.push({ modelVersionId: null,
        message: 'Strategy access policies could not be verified. Retry to recheck access.' });
      const publish = (loading: boolean) => {
        if (!active) return;
        setResult(previous => {
          const snapshots = new Map(next);
          if (previous?.request.identity === identity) {
            for (const [id, snapshot] of previousObservations(previous.snapshots)) {
              const replacement = next.get(id);
              const sameStrategy = !replacement?.strategyId || replacement.strategyId === snapshot.strategyId;
              if (sameStrategy && access.canAccess(access.requiredTier('strategy', snapshot.strategyId))
                && (!replacement?.sourceIdentity.formalBundleId || replacement.readState === 'protected')) snapshots.set(id, snapshot);
            }
          }
          return { request, snapshots, issues: [...issues], loading };
        });
      };
      publish(true);
      const runtimeSnapshots = Array.from(next.values()).filter((snapshot) => {
        if (!snapshot.sourceIdentity.formalBundleId) return false;
        const requiredTier = access.requiredTier('strategy', snapshot.strategyId);
        return access.canAccess(requiredTier);
      });
      pendingModels = new Set(runtimeSnapshots.map(snapshot => snapshot.modelVersionId));
      try {
        if (runtimeSnapshots.length) {
          const client = await membership.getClient();
          if (!active) return;
          if (!client) throw new Error('Account client unavailable');
          const runtime = await loadRuntimeStrategyOperations(
            client as StrategyOperationsClient, runtimeSnapshots, controller.signal,
          ).catch(() => new Map<string, StrategyOperationsSnapshot | null>());
          if (!active) return;
          for (const snapshot of runtimeSnapshots) {
            const run = formalRuns.find((candidate) => candidate.modelVersionId === snapshot.modelVersionId)!;
            try {
              const runtimeSnapshot = runtime.get(snapshot.modelVersionId);
              if (!runtimeSnapshot || runtimeSnapshot.readState) throw new Error('Current operations unavailable');
              assertStrategyOperationRun(runtimeSnapshot, run);
              next.set(snapshot.modelVersionId, runtimeSnapshot);
            } catch {
              next.set(snapshot.modelVersionId, markUnread(snapshot));
              issues.push({ modelVersionId: run.modelVersionId, message: `${run.title}: current operations could not be verified.` });
            }
            pendingModels?.delete(snapshot.modelVersionId);
          }
        }
      } catch {
        for (const snapshot of runtimeSnapshots) next.set(snapshot.modelVersionId, markUnread(snapshot));
        issues.push({ modelVersionId: null, message: 'Current operations could not be read. Retry when the account service is available.' });
      } finally {
        window.clearTimeout(deadline);
        publish(false);
      }
    })();

    return cleanup;
  }, [request, membership.getClient]);

  const current = result?.request === request ? result : null;
  const snapshots = useMemo(() => current?.snapshots
    ?? (result?.request.identity === identity ? previousObservations(result.snapshots) : EMPTY_SNAPSHOTS),
  [current, result, identity]);
  return { formalRuns, snapshots, previousRead: Array.from(snapshots.values()).some(snapshot => snapshot.readState === 'retained'),
    loading: current?.loading ?? true, issues: current?.issues ?? [], reload };
}
