import { useEffect, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { OperationsReadStatus } from '@/components/OperationsReadStatus';
import { useAccessControl } from '@/hooks/useAccessControl';
import { describeStrategyObservation, type StrategyObservationBrief } from '@/lib/strategy-operations';
import { fetchSystemHealth, type LiveSystemHealth } from '@/lib/system-health';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

const WORKFLOWS = 'https://github.com/liuh886/alpha_engine/actions/workflows/';

type ObservationBadgeVariant = 'positive' | 'warning' | 'negative' | 'info' | 'muted';

function observationVariant(observation: StrategyObservationBrief): ObservationBadgeVariant {
  if (observation.kind === 'attention') return observation.label === 'Delivery failed' ? 'negative' : 'warning';
  if (observation.kind === 'changed') return 'info';
  if (observation.kind === 'pending') return 'warning';
  return 'muted';
}

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
    <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border/80 pb-5">
      <div className="min-w-0">
        <p className="ae-kicker">Operations · not investment research</p>
        <h1 className="ae-page-title mt-2">Operating Status</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">Verify source publication and delivery health. Reading this page does not run research jobs.</p>
      </div>
      <Button variant="outline" disabled={operations.loading} onClick={() => {
        operations.reload();
        setAttempt(value => value + 1);
      }}>Refresh status</Button>
    </header>
    <OperationsReadStatus {...operations} runs={operations.formalRuns} showRefresh={false} />
    <section className="ae-surface overflow-hidden" aria-label="Current strategy observations">
      <header className="border-b border-border/70 px-4 py-3 sm:px-5">
        <h2 className="ae-section-title">Current strategy observations</h2>
      </header>
      <div className="hidden grid-cols-[minmax(0,15rem)_minmax(0,1fr)_10rem] gap-4 border-b border-border/70 bg-muted/30 px-4 py-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground sm:px-5 lg:grid">
        <span>Strategy</span>
        <span>Latest observation</span>
        <span className="text-right">Status</span>
      </div>
      <div className="divide-y divide-border/70">
        {operations.formalRuns.map(run => {
          const snapshot = operations.snapshots.get(run.modelVersionId);
          const allowed = Boolean(snapshot?.strategyId) && !access.policyLoading && access.canAccess(access.requiredTier('strategy', snapshot!.strategyId));
          const observation = !snapshot?.strategyId ? describeStrategyObservation() : describeStrategyObservation(snapshot, allowed);
          const lastGoodCutoff = snapshot?.latestCompletedSession ?? null;
          const failureClass = observation.kind === 'attention' ? observation.label : snapshot?.status === 'stale' ? 'Stale observation' : null;
          // Only a source-backed operational status can justify a recovery workflow.
          // Attention due to access or verification failure is not an instruction to refresh data.
          const recoveryWorkflow = snapshot?.status === 'delivery_failed'
            ? { file: 'strategy-signal-delivery-outbox.yml', label: 'Inspect delivery workflow' }
            : snapshot?.status === 'stale' || snapshot?.status === 'blocked' || snapshot?.status === 'pipeline_unavailable'
              ? { file: 'formal-backtest-refresh.yml', label: 'Inspect formal refresh workflow' }
              : null;
          return <article key={run.key}
            className="grid gap-x-4 gap-y-2 px-4 py-3.5 sm:px-5 lg:grid-cols-[minmax(0,15rem)_minmax(0,1fr)_10rem] lg:items-start">
            <div className="flex min-w-0 flex-wrap items-center gap-2 lg:items-start">
              <Link className="text-sm font-semibold text-primary hover:underline" to={'/strategies/' + encodeURIComponent(run.modelVersionId)}>{run.title}</Link>
            </div>
            <div className="min-w-0 space-y-1">
              {allowed && snapshot && (!snapshot.readState || snapshot.readState === 'retained') && (
                <p className="text-xs leading-5 text-muted-foreground">
                  Observed {snapshot.latestCompletedSession || 'unknown'} · target dated {snapshot.decisionSchedule?.signalDate || snapshot.asOf || 'unknown'} · formal evidence {run.evidenceCutoff}{lastGoodCutoff ? ` · last-good observed session ${lastGoodCutoff}` : ''}
                </p>
              )}
              <p className="text-[13px] leading-5">{observation.reason}</p>
              <p className="text-xs leading-5 text-muted-foreground">{observation.nextStep}</p>
              {recoveryWorkflow && allowed && (
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 pt-1 text-xs">
                  <span className="text-muted-foreground">Recovery action:</span>
                  <a
                    className="text-primary underline underline-offset-2"
                    href={WORKFLOWS + recoveryWorkflow.file}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {recoveryWorkflow.label}
                  </a>
                </div>
              )}
            </div>
            <div className="flex flex-wrap items-start gap-1.5 lg:flex-col lg:items-end">
              {failureClass && failureClass !== observation.label && (
                <Badge variant="warning">{failureClass}</Badge>
              )}
              <Badge variant={observationVariant(observation)}>{observation.label}</Badge>
            </div>
          </article>;
        })}
      </div>
    </section>
    <section className="ae-surface p-4 sm:p-5" aria-label="Published source snapshot">
      <h2 className="ae-section-title">Published data snapshot</h2>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">
        Generated {health?.health?.generated_at || 'Unavailable'} · Deployment {health?.deploymentStatus || 'unknown'}.
        Strategy decisions may advance independently of this source snapshot.
      </p>
      {health?.health?.markets.length ? <div className="mt-3 divide-y divide-border/70 rounded-lg border border-border/70">
        {health.health.markets.map(market => <div key={market.market} className="px-3 py-2.5 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">{market.market.toUpperCase()} · {market.state}</h3>
            {market.state !== 'current' && <Badge variant="warning">Source degraded</Badge>}
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">Provider cutoff {market.provider_cutoff || 'unknown'} · expected {market.market_expected_cutoff || 'unknown'}</p>
        </div>)}
      </div> : null}
      {health && !health.health && <p role="alert" className="mt-3 text-sm">{health.message}</p>}
      {health?.health?.model_data && <details className="mt-4 border-t border-border/70 pt-3">
        <summary className="cursor-pointer text-sm">Separate research input coverage</summary>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">
          {health.health.model_data.summary.ready_component_count}/{health.health.model_data.summary.component_count} components ready
          · {health.health.model_data.summary.partial_component_count} partial
          · {health.health.model_data.summary.blocked_training_profile_count} blocked profiles.
          This is not the daily strategy health verdict.
        </p>
      </details>}
    </section>
    <section className="ae-surface p-4 sm:p-5" aria-label="Recovery">
      <h2 className="ae-section-title">Recovery and workflows</h2>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        Review the affected source or delivery run. Authorized operators use existing workflows;
        a browser refresh never triggers execution.
      </p>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm">
        <a className="text-primary underline underline-offset-2" href={WORKFLOWS + 'formal-backtest-refresh.yml'} target="_blank" rel="noreferrer">Data refresh workflow</a>
        <a className="text-primary underline underline-offset-2" href={WORKFLOWS + 'strategy-signal-delivery-outbox.yml'} target="_blank" rel="noreferrer">Decision delivery workflow</a>
      </div>
    </section>
    <section className="ae-surface-muted p-4 text-sm" aria-label="Related research">
      Looking for RDI historical risk analysis?{' '}
      <Link className="font-semibold text-primary underline underline-offset-2" to="/research?section=rdi">Open the independent research view</Link>.
    </section>
  </div>;
}
