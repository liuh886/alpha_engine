import type { GovernedRunSummary } from '@/lib/governed-run';
import type { AccessResourceType, AccessTier } from '@/lib/model-access';
import {
  describeStrategyObservation,
  type StrategyObservationBrief,
  type StrategyOperationsSnapshot,
} from '@/lib/strategy-operations';

/** The subset of access-control state the brief needs; display only. */
export interface BriefAccess {
  loading?: boolean;
  policyLoading?: boolean;
  canAccess: (tier: AccessTier) => boolean;
  requiredTier: (type: AccessResourceType, id: string) => AccessTier;
}

export interface BriefEntry {
  run: GovernedRunSummary;
  snapshot: StrategyOperationsSnapshot | undefined;
  brief: StrategyObservationBrief;
  checking: boolean;
}

export interface BriefSummary {
  changed: number;
  unchanged: number;
  retained: number;
  attention: number;
  access: number;
  pending: number;
  /** Shortest cadence wait across verified observations, when one is recorded. */
  nextReviewSessions: number | null;
  noNewChanges: boolean;
  busy: boolean;
}

const DISPLAY_ORDER = { changed: 0, attention: 1, retained: 2, unchanged: 3, access: 4, pending: 5 } as const;
const CHECKING_OBSERVATION: StrategyObservationBrief = {
  kind: 'pending',
  label: 'Checking observation',
  reason: 'Verifying access and current observations…',
  nextStep: 'Formal historical evidence remains available while verification completes.',
  recovery: null,
};

/**
 * One display model shared by Today's compact header summary and the daily
 * brief. It filters access-restricted observations before producing any text;
 * no additional evidence or computation is introduced here.
 */
export function buildBriefEntries(
  runs: GovernedRunSummary[],
  snapshots: Map<string, StrategyOperationsSnapshot>,
  loading: boolean,
  access: BriefAccess,
): BriefEntry[] {
  const accessPending = Boolean(access.loading || access.policyLoading);
  return runs.map(run => {
    const snapshot = snapshots.get(run.modelVersionId);
    const accessible = snapshot
      ? Boolean(snapshot.strategyId) && !accessPending
        && access.canAccess(access.requiredTier('strategy', snapshot.strategyId))
      : true;
    const visibleSnapshot = accessible && (!snapshot?.readState || snapshot.readState === 'retained')
      ? snapshot
      : undefined;
    const checking = accessPending || (loading && !visibleSnapshot);
    return {
      run,
      snapshot: visibleSnapshot,
      checking,
      brief: checking
        ? CHECKING_OBSERVATION
        : snapshot && !snapshot.strategyId
          ? describeStrategyObservation()
          : describeStrategyObservation(snapshot, accessible),
    };
  }).sort((left, right) => DISPLAY_ORDER[left.brief.kind] - DISPLAY_ORDER[right.brief.kind]);
}

export function summarizeBrief(entries: BriefEntry[], loading: boolean, accessPending = false): BriefSummary {
  const count = (kind: string) => entries.filter(entry => entry.brief.kind === kind).length;
  const busy = loading || accessPending;
  const waits = entries
    .filter(entry => !entry.checking && entry.snapshot?.decisionSchedule)
    .map(entry => entry.snapshot?.decisionSchedule?.sessionsUntilDue)
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0);
  return {
    changed: count('changed'),
    unchanged: count('unchanged'),
    retained: count('retained'),
    attention: count('attention'),
    access: count('access'),
    pending: count('pending'),
    nextReviewSessions: waits.length ? Math.min(...waits) : null,
    noNewChanges: !busy && entries.length > 0
      && entries.every(entry => entry.brief.kind === 'unchanged' || entry.brief.kind === 'retained'),
    busy,
  };
}

/** Compact one-line change summary for Today's page header. */
export function briefHeadline(summary: BriefSummary, entryCount: number): string {
  if (summary.busy) return 'Reading current observations…';
  if (!entryCount) return 'No formal strategies are available yet.';
  if (summary.noNewChanges) return 'No new model changes since the last verified read.';
  const parts = [`${summary.changed} changed`, `${summary.attention} need attention`];
  if (summary.retained) parts.push(`${summary.retained} retained`);
  if (summary.access) parts.push(`${summary.access} require access`);
  if (summary.pending) parts.push(`${summary.pending} awaiting verification`);
  return parts.join(' · ');
}

export function nextReviewLabel(summary: BriefSummary): string | null {
  if (summary.busy || summary.nextReviewSessions === null) return null;
  return summary.nextReviewSessions === 0
    ? 'Next review due'
    : `Next review in ${summary.nextReviewSessions} session${summary.nextReviewSessions === 1 ? '' : 's'}`;
}
