import { Link } from 'react-router-dom';
import { ArrowUpRight, ClipboardList } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAccessControl } from '@/hooks/useAccessControl';
import type { GovernedRunSummary } from '@/lib/governed-run';
import { describeStrategyObservation, type StrategyObservationBrief, type StrategyOperationsSnapshot } from '@/lib/strategy-operations';

const WORKFLOWS = 'https://github.com/liuh886/alpha_engine/actions/workflows/';
const DISPLAY_ORDER = { changed: 0, attention: 1, retained: 2, unchanged: 3, access: 4, pending: 5 };
const CHECKING_OBSERVATION: StrategyObservationBrief = {
  kind: 'pending', label: 'Checking observation', reason: 'Verifying access and current observations…',
  nextStep: 'Formal historical evidence remains available while verification completes.', recovery: null,
};

export function DailyResearchBrief({ runs, snapshots, loading, reload }: {
  runs: GovernedRunSummary[];
  snapshots: Map<string, StrategyOperationsSnapshot>;
  loading: boolean;
  reload: () => void;
}) {
  const access = useAccessControl();
  const accessPending = access.loading || access.policyLoading;
  const busy = loading || accessPending;
  const entries = runs.map(run => {
    const snapshot = snapshots.get(run.modelVersionId);
    const accessible = snapshot ? Boolean(snapshot.strategyId) && !accessPending
      && access.canAccess(access.requiredTier('strategy', snapshot.strategyId)) : true;
    const visibleSnapshot = accessible && (!snapshot?.readState || snapshot.readState === 'retained') ? snapshot : undefined;
    const checking = accessPending || (loading && !visibleSnapshot);
    return { run, snapshot: visibleSnapshot,
      brief: checking ? CHECKING_OBSERVATION : snapshot && !snapshot.strategyId ? describeStrategyObservation() : describeStrategyObservation(snapshot, accessible) };
  }).sort((a, b) => DISPLAY_ORDER[a.brief.kind] - DISPLAY_ORDER[b.brief.kind]);
  const count = (kind: string) => entries.filter(entry => entry.brief.kind === kind).length;
  const priorities = entries.slice(0, 3);
  const noNewChanges = !busy && entries.length > 0
    && entries.every(entry => entry.brief.kind === 'unchanged' || entry.brief.kind === 'retained');
  return (
    <section className="overflow-hidden rounded-2xl border bg-card shadow-sm" aria-label="Daily research brief" aria-busy={busy}>
      <header className="border-b bg-muted/15 px-5 py-4">
        <h2 className="flex items-center gap-2 font-semibold"><ClipboardList className="h-4 w-4 text-primary" />Daily research brief</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">Latest verified observations by strategy. Each market keeps its own cutoff; retained targets are dated separately.</p>
        <p className="mt-2 text-xs" role="status">{busy ? 'Reading current observations…' : `${count('changed')} changed · ${count('unchanged')} unchanged · ${count('retained')} retained · ${count('attention')} need attention · ${count('access')} require access · ${count('pending')} awaiting verification`}</p>
        {noNewChanges && <p className="mt-2 text-sm">No new model changes. Retained targets keep their recorded dates.</p>}
      </header>
      {!runs.length && <p className="p-5 text-sm text-muted-foreground">{busy ? 'Reading formal strategies…' : 'No formal strategies are available for this brief.'}</p>}
      <div className="divide-y">{priorities.map(({ run, snapshot, brief }) => (
        <article key={run.key} className="px-5 py-4" aria-label={`${run.title} daily observation`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Link to={`/strategies/${encodeURIComponent(run.modelVersionId)}`} className="font-semibold text-sm hover:text-primary">{run.title}</Link>
            <span className={brief.kind === 'attention' ? 'text-xs font-medium text-amber-700 dark:text-amber-300' : 'text-xs font-medium text-muted-foreground'}>{loading && !snapshot ? 'Checking observation' : brief.label}</span>
          </div>
          <p className="mt-1 text-[11px] text-muted-foreground">{run.market.toUpperCase()} · {snapshot
            ? `Observed ${snapshot.latestCompletedSession ?? 'unknown'} · target dated ${snapshot.decisionSchedule?.signalDate ?? snapshot.asOf ?? 'unknown'} · formal evidence ${run.evidenceCutoff}`
            : `Formal evidence ${run.evidenceCutoff}; current observation not verified`}</p>
          {snapshot?.decisionSchedule?.completedThrough && <p className="mt-1 text-[11px] text-muted-foreground">Completed market through {snapshot.decisionSchedule.completedThrough}</p>}
          <p className="mt-2 break-words text-sm">{brief.reason}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{brief.nextStep}</p>
          {snapshot?.factorEvidence.length ? <details className="mt-2 text-xs">
            <summary className="cursor-pointer font-medium">Decision evidence</summary>
            <ul className="mt-2 space-y-1 text-muted-foreground">{snapshot.factorEvidence.slice(0, 3).map(factor => (
              <li key={`${factor.factorId}:${factor.factorVersion}`}>{factor.displayName}: {factor.state} · {factor.effect} · observed {factor.observedAt}</li>
            ))}</ul>
            <Link className="mt-2 inline-block text-primary underline" to={`/strategies/${encodeURIComponent(run.modelVersionId)}`}>Inspect all evidence</Link>
          </details> : null}
          {!busy && brief.kind === 'access' && <Button variant="outline" size="sm" className="mt-3 min-h-[44px]" onClick={access.openAccount}>Check strategy access</Button>}
          {!busy && brief.recovery === 'read' && <Button variant="outline" size="sm" className="mt-3 min-h-[44px]" onClick={reload}>Retry reading observations</Button>}
          {brief.recovery && brief.recovery !== 'read' && <details className="mt-3 rounded-lg border bg-muted/15 p-3 text-xs">
            <summary className="cursor-pointer font-medium">Recovery steps</summary>
            <p className="mt-2 leading-relaxed text-muted-foreground">{brief.recovery === 'delivery'
              ? 'Review the delivery history. The existing outbox skips completed deliveries and retains ambiguous failures for review.'
              : 'Check model monitoring and the latest source run. When inputs are available, the existing refresh rechecks the frozen contract. Valid independent observations remain readable.'}</p>
            <div className="mt-3 flex flex-wrap gap-4">
              <Link className="text-primary underline" to="/system">Open operating status</Link>
              <a className="inline-flex items-center gap-1 text-primary underline" href={`${WORKFLOWS}${brief.recovery === 'delivery' ? 'strategy-signal-delivery-outbox.yml' : 'formal-backtest-refresh.yml'}`} target="_blank" rel="noreferrer">{brief.recovery === 'delivery' ? 'Open delivery workflow' : 'Open data refresh workflow'}<ArrowUpRight className="h-3 w-3" /></a>
            </div>
            <p className="mt-2 text-muted-foreground">An authorized operator can use Run workflow on main. This page reads records; it does not start jobs or send orders.</p>
          </details>}
        </article>
      ))}</div>
      {entries.length > priorities.length && <p className="border-t px-5 py-3 text-xs text-muted-foreground">Showing {priorities.length} of {entries.length} priority observations. All {entries.length} strategies remain in the fleet below.</p>}
    </section>
  );
}
