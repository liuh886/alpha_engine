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
  const { operations } = useOutletContext<RunWorkspaceContext>();
  const access = useAccessControl();
  const [health, setHealth] = useState<LiveSystemHealth | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setHealth(null);
    void fetchSystemHealth().then(value => { if (active) setHealth(value); });
    return () => { active = false; };
  }, [attempt]);
  return <div className="mx-auto max-w-[1200px] space-y-5 pb-16">
    <header className="flex flex-wrap items-start justify-between gap-4 border-b pb-5">
      <div>
        <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Operations · not investment research</p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight">Operating Status</h1>
        <p className="mt-2 text-sm text-muted-foreground">Verify source publication and delivery health. Reading this page does not run research jobs.</p>
      </div>
      <Button variant="outline" disabled={operations.loading} onClick={() => {
        operations.reload();
        setAttempt(value => value + 1);
      }}>Refresh status</Button>
    </header>
    <OperationsReadStatus {...operations} />
    <section className="overflow-hidden rounded-xl border bg-card" aria-label="Current strategy observations">
      <h2 className="border-b p-4 font-semibold">Current strategy observations</h2>
      {operations.formalRuns.map(run => {
        const snapshot = operations.snapshots.get(run.modelVersionId);
        const allowed = Boolean(snapshot?.strategyId) && !access.policyLoading && access.canAccess(access.requiredTier('strategy', snapshot!.strategyId));
        const observation = !snapshot?.strategyId ? describeStrategyObservation() : describeStrategyObservation(snapshot, allowed);
        const lastGoodCutoff = snapshot?.latestCompletedSession || run.evidenceCutoff;
        const failureClass = observation.kind === 'attention' ? observation.label : snapshot?.status === 'stale' ? 'Stale observation' : null;
        return <article key={run.key} className="border-b p-4 last:border-0">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Link className="font-semibold text-primary" to={'/strategies/' + encodeURIComponent(run.modelVersionId)}>{run.title}</Link>
            <div className="flex items-center gap-2">
              {failureClass && (
                <span className="rounded bg-rose-500/10 px-2 py-0.5 text-xs font-medium text-rose-700 dark:text-rose-300">
                  {failureClass}
                </span>
              )}
              <span className="text-sm">{observation.label}</span>
            </div>
          </div>
          {allowed && snapshot && (!snapshot.readState || snapshot.readState === 'retained') && (
            <p className="mt-2 text-xs text-muted-foreground">
              Observed {snapshot.latestCompletedSession || 'unknown'} · target dated {snapshot.decisionSchedule?.signalDate || snapshot.asOf || 'unknown'} · formal evidence {run.evidenceCutoff} · last-good cutoff {lastGoodCutoff}
            </p>
          )}
          <p className="mt-2 text-sm">{observation.reason}</p>
          <p className="mt-1 text-xs text-muted-foreground">{observation.nextStep}</p>
          {observation.kind === 'attention' && (
            <div className="mt-3 flex items-center gap-2 text-xs">
              <span className="text-muted-foreground">Recovery action:</span>
              <a
                className="text-primary underline"
                href={WORKFLOWS + 'formal-backtest-refresh.yml'}
                target="_blank"
                rel="noreferrer"
              >
                Trigger formal refresh workflow
              </a>
            </div>
          )}
        </article>;
      })}
    </section>
    <section className="rounded-xl border bg-card p-4" aria-label="Published source snapshot">
      <h2 className="font-semibold">Published data snapshot</h2>
      <p className="mt-2 text-xs text-muted-foreground">
        Generated {health?.health?.generated_at || 'Unavailable'} · Deployment {health?.deploymentStatus || 'unknown'}.
        Strategy decisions may advance independently of this source snapshot.
      </p>
      {health?.health?.markets.map(market => <div key={market.market} className="mt-3 rounded-lg border p-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold">{market.market.toUpperCase()} · {market.state}</h3>
          {market.state !== 'current' && (
            <span className="rounded bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-300">
              Source degraded
            </span>
          )}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">Provider cutoff {market.provider_cutoff || 'unknown'} · expected {market.market_expected_cutoff || 'unknown'}</p>
      </div>)}
      {health && !health.health && <p role="alert" className="mt-3 text-sm">{health.message}</p>}
      {health?.health?.model_data && <details className="mt-4 border-t pt-3">
        <summary className="cursor-pointer text-sm">Separate research input coverage</summary>
        <p className="mt-2 text-xs text-muted-foreground">
          {health.health.model_data.summary.ready_component_count}/{health.health.model_data.summary.component_count} components ready
          · {health.health.model_data.summary.partial_component_count} partial
          · {health.health.model_data.summary.blocked_training_profile_count} blocked profiles.
          This is not the daily strategy health verdict.
        </p>
      </details>}
    </section>
    <section className="rounded-xl border bg-card p-4" aria-label="Recovery">
      <h2 className="font-semibold">Recovery and workflows</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        Review the affected source or delivery run. Authorized operators use existing workflows;
        a browser refresh never triggers execution.
      </p>
      <div className="mt-3 flex flex-wrap gap-4 text-sm">
        <a className="text-primary underline" href={WORKFLOWS + 'formal-backtest-refresh.yml'} target="_blank" rel="noreferrer">Data refresh workflow</a>
        <a className="text-primary underline" href={WORKFLOWS + 'strategy-signal-delivery-outbox.yml'} target="_blank" rel="noreferrer">Decision delivery workflow</a>
      </div>
    </section>
    <section className="rounded-xl border bg-muted/20 p-4 text-sm" aria-label="Related research">
      Looking for RDI historical risk analysis?{' '}
      <Link className="font-semibold text-primary underline" to="/research?section=rdi">Open the independent research view</Link>.
    </section>
  </div>;
}
