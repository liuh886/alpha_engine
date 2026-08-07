import { ArrowLeft, ArrowUpRight, CalendarClock, Database, ShieldCheck } from 'lucide-react';
import { useMemo } from 'react';
import { Link, useOutletContext, useParams } from 'react-router-dom';
import { FormalBacktestReview } from '@/components/FormalBacktestReview';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useStrategyOperations } from '@/hooks/useStrategyOperations';
import { STRATEGY_STATUS_LABEL } from '@/lib/strategy-operations';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function StrategyDetailPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const { strategyId } = useParams();
  const run = workspace.runs.find((candidate) => candidate.channel === 'formal' && candidate.modelVersionId === strategyId) ?? null;
  const selectedRuns = useMemo(() => run ? [run] : [], [run]);
  const { snapshots, loading } = useStrategyOperations(selectedRuns);
  const snapshot = run ? snapshots.get(run.modelVersionId) : undefined;

  if (!run) {
    return (
      <div className="research-empty-state">
        <h1 className="text-lg font-semibold">Formal strategy not found</h1>
        <p className="mt-2 text-sm text-muted-foreground">The verified formal catalog does not declare this strategy.</p>
        <Button asChild variant="outline" className="mt-5"><Link to="/strategies">Back to strategies</Link></Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1500px] space-y-7 pb-16">
      <section className="border-b pb-6">
        <Button asChild variant="ghost" size="sm" className="mb-4 -ml-2 gap-2"><Link to="/strategies"><ArrowLeft className="h-4 w-4" />Strategies</Link></Button>
        <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-4xl">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{run.market.toUpperCase()}</Badge>
              <Badge variant="outline">Benchmark {run.benchmark}</Badge>
              <Badge variant="secondary">Formal baseline</Badge>
            </div>
            <h1 className="mt-3 text-3xl font-black tracking-tight md:text-5xl">{run.title}</h1>
            <p className="mt-3 text-sm text-muted-foreground">Evidence cutoff {run.evidenceCutoff} · {run.modelKind.replace(/_/g, ' ')}</p>
          </div>
          <div className="rounded-xl border bg-card px-4 py-3 text-sm shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground">Operating status</p>
            <p className="mt-1 font-semibold">{snapshot ? STRATEGY_STATUS_LABEL[snapshot.status] : loading ? 'Loading current operations' : 'Operating status unavailable'}</p>
            <p className="mt-1 text-xs text-muted-foreground">{snapshot?.latestCompletedSession ? `Latest session ${snapshot.latestCompletedSession}` : 'Formal evidence remains available below.'}</p>
          </div>
        </div>
      </section>

      <section aria-labelledby="strategy-now-heading" className="space-y-4">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-primary">Now</p>
            <h2 id="strategy-now-heading" className="mt-1 text-2xl font-bold">Current decision state</h2>
          </div>
          {snapshot?.sourceHref && (
            <a href={snapshot.sourceHref} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline">Source record <ArrowUpRight className="h-3.5 w-3.5" /></a>
          )}
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
          <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
            <div className="grid grid-cols-[minmax(100px,1fr)_90px_90px_90px] border-b bg-muted/25 px-4 py-2.5 text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground">
              <span>Asset</span><span className="text-right">Current</span><span className="text-right">Target</span><span className="text-right">Change</span>
            </div>
            {snapshot?.allocations.length ? snapshot.allocations.map((leg) => (
              <div key={leg.asset} className="grid grid-cols-[minmax(100px,1fr)_90px_90px_90px] border-b px-4 py-3 text-sm last:border-0">
                <span className="font-semibold">{leg.asset}</span>
                <span className="text-right font-mono">{pct(leg.current)}</span>
                <span className="text-right font-mono">{pct(leg.target)}</span>
                <span className="text-right font-mono font-semibold">{leg.delta > 0 ? '+' : ''}{pct(leg.delta)}</span>
              </div>
            )) : (
              <div className="p-6 text-sm text-muted-foreground">No governed live target is published for this strategy. Alpha Engine will not infer current holdings from a historical backtest.</div>
            )}
          </div>

          <div className="space-y-4">
            <div className="rounded-xl border bg-card p-5 shadow-sm">
              <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground">State</p>
              <p className="mt-2 text-xl font-bold">{snapshot?.stateLabel || 'Formal evidence only'}</p>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{snapshot?.decisionReason || 'A live decision reason is not published for this strategy.'}</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border bg-card p-4"><CalendarClock className="h-4 w-4 text-primary" /><p className="mt-3 text-xs text-muted-foreground">Next decision</p><p className="mt-1 text-sm font-semibold">{snapshot?.nextDecision || 'Not declared'}</p></div>
              <div className="rounded-xl border bg-card p-4"><Database className="h-4 w-4 text-primary" /><p className="mt-3 text-xs text-muted-foreground">Data</p><p className="mt-1 text-sm font-semibold">{snapshot?.dataFreshness || 'unknown'}</p></div>
            </div>
          </div>
        </div>

        {snapshot?.drivers.length ? (
          <div className="rounded-xl border bg-card p-5 shadow-sm">
            <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold">Current signal drivers</h3></div>
            <div className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
              {snapshot.drivers.map((driver) => (
                <div key={driver.label} className="flex items-baseline justify-between gap-3 border-b pb-2 text-sm">
                  <span className="text-muted-foreground">{driver.label}</span><span className="font-mono font-semibold">{driver.value}</span>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs text-muted-foreground">Factor freshness is {snapshot.factorFreshness}. #626 will replace this interim model-specific driver materialization with the canonical factor evidence contract.</p>
          </div>
        ) : null}
      </section>

      <section className="space-y-4 border-t pt-7">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-primary">Evidence</p>
          <h2 className="mt-1 text-2xl font-bold">Performance, risk, holdings and attribution</h2>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">The existing hash-verified Model Run Bundle v2 evidence is retained as the analytical depth beneath the strategy, rather than remaining a separate product mental model.</p>
        </div>
        <FormalBacktestReview run={run} />
      </section>
    </div>
  );
}
