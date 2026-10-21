import { useEffect, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { OperationsReadStatus } from '@/components/OperationsReadStatus';
import { useAccessControl } from '@/hooks/useAccessControl';
import { describeStrategyObservation } from '@/lib/strategy-operations';
import { fetchSystemHealth, type LiveSystemHealth } from '@/lib/system-health';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

const WORKFLOWS = 'https://github.com/liuh886/alpha_engine/actions/workflows/';
export function SystemHubPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const access = useAccessControl();
  const operations = workspace.operations;
  const [health, setHealth] = useState<LiveSystemHealth | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setHealth(null);
    void fetchSystemHealth().then(value => { if (active) setHealth(value); });
    return () => { active = false; };
  }, [attempt]);
  return <div className="mx-auto max-w-[1200px] space-y-6 pb-16">
    <header className="flex flex-wrap items-start justify-between gap-4 border-b pb-6">
      <div><h1 className="text-3xl font-black tracking-tight">Operating Status</h1><p className="mt-3 text-sm text-muted-foreground">Current decisions and dated source publication. Reading this page does not run research jobs.</p></div>
      <Button variant="outline" disabled={operations.loading} onClick={() => { operations.reload(); setAttempt(value => value + 1); }}>Refresh status</Button>
    </header>
    <OperationsReadStatus {...operations} />
    <section className="overflow-hidden rounded-xl border bg-card" aria-label="Current strategy observations">
      <h2 className="border-b p-4 font-semibold">Current observations</h2>
      {operations.formalRuns.map(run => {
        const snapshot = operations.snapshots.get(run.modelVersionId);
        const allowed = Boolean(snapshot?.strategyId) && !access.policyLoading && access.canAccess(access.requiredTier('strategy', snapshot!.strategyId));
        const observation = !snapshot?.strategyId ? describeStrategyObservation() : describeStrategyObservation(snapshot, allowed);
        return <article key={run.key} className="border-b p-4 last:border-0">
          <div className="flex flex-wrap justify-between gap-2"><Link className="font-semibold text-primary" to={'/strategies/' + encodeURIComponent(run.modelVersionId)}>{run.title}</Link><span className="text-sm">{observation.label}</span></div>
          {allowed && snapshot && (!snapshot.readState || snapshot.readState === 'retained') && <p className="mt-2 text-xs text-muted-foreground">Observed {snapshot.latestCompletedSession || 'unknown'} · target dated {snapshot.decisionSchedule?.signalDate || snapshot.asOf || 'unknown'} · formal evidence {run.evidenceCutoff}</p>}
          <p className="mt-2 text-sm">{observation.reason}</p>
          <p className="mt-1 text-xs text-muted-foreground">{observation.nextStep}</p>
        </article>;
      })}
    </section>
    <section className="rounded-xl border bg-card p-4" aria-label="Published source snapshot">
      <h2 className="font-semibold">Published data snapshot</h2>
      <p className="mt-2 text-xs text-muted-foreground">Generated {health?.health?.generated_at || 'Unavailable'} · Deployment {health?.deploymentStatus || 'unknown'}. Current observations above can advance independently.</p>
      {health?.health?.markets.map(market => <p key={market.market} className="mt-3 text-sm">{market.market.toUpperCase()} · provider {market.provider_cutoff || 'unknown'} · expected {market.market_expected_cutoff || 'unknown'} · {market.state}</p>)}
      {health && !health.health && <p role="alert" className="mt-3 text-sm">{health.message}</p>}
      {health?.health?.model_data && <details className="mt-4 border-t pt-3"><summary className="cursor-pointer text-sm">Separate research input coverage</summary><p className="mt-2 text-xs text-muted-foreground">{health.health.model_data.summary.ready_component_count}/{health.health.model_data.summary.component_count} components ready · {health.health.model_data.summary.partial_component_count} partial · {health.health.model_data.summary.blocked_training_profile_count} blocked profiles. Component cutoffs and experiment gates remain separate from daily observations.</p></details>}
    </section>
    <section className="rounded-xl border bg-card p-4 text-sm">
      <h2 className="font-semibold">Recovery</h2><p className="mt-2 text-muted-foreground">Review the affected source or delivery run. Authorized operators use the existing workflows; valid independent observations remain readable.</p>
      <div className="mt-3 flex flex-wrap gap-4"><a className="text-primary underline" href={WORKFLOWS + 'formal-backtest-refresh.yml'} target="_blank" rel="noreferrer">Data refresh</a><a className="text-primary underline" href={WORKFLOWS + 'strategy-signal-delivery-outbox.yml'} target="_blank" rel="noreferrer">Decision delivery</a></div>
    </section>
  </div>;
}
