import { ArrowLeft, ArrowUpRight, CalendarClock, Crown, Database, LockKeyhole, ShieldCheck } from 'lucide-react';
import { useEffect, useMemo } from 'react';
import { Link, useOutletContext, useParams } from 'react-router-dom';
import { FormalBacktestReview } from '@/components/FormalBacktestReview';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useAccessControl } from '@/hooks/useAccessControl';
import { useStrategyOperations } from '@/hooks/useStrategyOperations';
import { STRATEGY_STATUS_LABEL } from '@/lib/strategy-operations';
import type { StrategyFactorEvidence } from '@/lib/strategy-operations';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function factorValue(factor: StrategyFactorEvidence): string {
  if (typeof factor.value === 'boolean') return factor.value ? 'Yes' : 'No';
  if (typeof factor.value === 'string') return factor.value;
  if (factor.factorId.includes('momentum') || factor.factorId.includes('drawdown') || factor.factorId.includes('qqq_vs_')) {
    return `${(factor.value * 100).toFixed(2)}%`;
  }
  return factor.value.toFixed(2);
}

interface ModelContribution {
  instrument: string;
  decisionRole: string;
  contribution: number;
}

function modelContributions(factor: StrategyFactorEvidence): ModelContribution[] {
  if (!factor.reference || typeof factor.reference !== 'object' || Array.isArray(factor.reference)) return [];
  const raw = (factor.reference as Record<string, unknown>).model_contributions;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((value) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
    const row = value as Record<string, unknown>;
    if (typeof row.instrument !== 'string' || typeof row.decision_role !== 'string' || typeof row.contribution !== 'number' || !Number.isFinite(row.contribution)) return [];
    return [{ instrument: row.instrument, decisionRole: row.decision_role, contribution: row.contribution }];
  });
}

function factorReference(factor: StrategyFactorEvidence): string | null {
  const value = factor.reference;
  if (value === null || value === undefined) return null;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value;
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .filter(([key, item]) => key !== 'model_contributions' && item !== null && item !== undefined && ['string', 'number', 'boolean'].includes(typeof item))
      .map(([key, item]) => `${key} ${String(item)}`)
      .join(' · ') || null;
  }
  return String(value);
}

function contributionSummary(factor: StrategyFactorEvidence): string | null {
  const rows = modelContributions(factor);
  if (!rows.length) return null;
  const strongest = [...rows]
    .sort((left, right) => Math.abs(right.contribution) - Math.abs(left.contribution) || left.instrument.localeCompare(right.instrument))
    .slice(0, 3)
    .map((row) => `${row.instrument} ${row.contribution >= 0 ? '+' : ''}${row.contribution.toFixed(4)}`)
    .join(' · ');
  const role = rows.some((row) => row.decisionRole === 'ranker_reference_vetoed_by_regime') ? 'ranker reference · regime vetoed' : 'selected holdings';
  return `XGBoost pred_contribs · ${role} · ${strongest}`;
}

export function StrategyDetailPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const access = useAccessControl();
  const { strategyId } = useParams();
  const run = workspace.runs.find((candidate) => candidate.channel === 'formal' && candidate.modelVersionId === strategyId) ?? null;
  const selectedRuns = useMemo(() => run ? [run] : [], [run]);
  const { snapshots, loading } = useStrategyOperations(selectedRuns);
  const snapshot = run ? snapshots.get(run.modelVersionId) : undefined;
  const requiredTier = snapshot?.currentOperationsAccess ?? 'public';
  const liveLocked = Boolean(snapshot && !access.canAccess(requiredTier));
  const protectedUnavailable = Boolean(
    snapshot
    && requiredTier !== 'public'
    && access.canAccess(requiredTier)
    && !snapshot.sourceIdentity.ledgerFingerprint,
  );

  useEffect(() => {
    if (run && run.key !== workspace.activeRunKey) workspace.selectRun(run);
  }, [run, workspace.activeRunKey, workspace.selectRun]);

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
              {requiredTier !== 'public' && <Badge variant="outline"><Crown className="mr-1 h-3 w-3" />{requiredTier === 'pro' ? 'Pro live' : requiredTier}</Badge>}
            </div>
            <h1 className="mt-3 text-3xl font-black tracking-tight md:text-5xl">{run.title}</h1>
            <p className="mt-3 text-sm text-muted-foreground">Evidence cutoff {run.evidenceCutoff} · {run.modelKind.replace(/_/g, ' ')}</p>
          </div>
          <div className="rounded-xl border bg-card px-4 py-3 text-sm shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground">Operating status</p>
            <p className="mt-1 font-semibold">{liveLocked ? 'Protected current operations' : snapshot ? STRATEGY_STATUS_LABEL[snapshot.status] : loading ? 'Loading current operations' : 'Operating status unavailable'}</p>
            <p className="mt-1 text-xs text-muted-foreground">{liveLocked ? 'Formal historical evidence remains public below.' : snapshot?.latestCompletedSession ? `Latest session ${snapshot.latestCompletedSession}` : 'Formal evidence remains available below.'}</p>
          </div>
        </div>
      </section>

      <section aria-labelledby="strategy-now-heading" className="space-y-4">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-primary">Now</p>
            <h2 id="strategy-now-heading" className="mt-1 text-2xl font-bold">{liveLocked ? 'Pro execution layer' : 'Current decision state'}</h2>
          </div>
          {!liveLocked && !protectedUnavailable && snapshot?.sourceHref && (
            <a href={snapshot.sourceHref} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline">Source record <ArrowUpRight className="h-3.5 w-3.5" /></a>
          )}
        </div>

        {liveLocked ? (
          <div className="rounded-xl border border-primary/20 bg-primary/[0.035] p-6 shadow-sm">
            <div className="flex items-start gap-4">
              <div className="rounded-full bg-primary/10 p-2 text-primary"><LockKeyhole className="h-5 w-5" /></div>
              <div className="max-w-2xl">
                <h3 className="text-lg font-semibold">Current holdings and live signals are protected</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">AlphaEngine Pro unlocks the current holdings, target allocations, current signal drivers and next-decision state for this strategy. Historical formal performance, risk, holdings and attribution remain public below.</p>
                <Button className="mt-5" onClick={access.openAccount}>View AlphaEngine Pro access</Button>
              </div>
            </div>
          </div>
        ) : protectedUnavailable ? (
          <div className="rounded-xl border bg-card p-6 text-sm text-muted-foreground shadow-sm">
            Protected current operations are unavailable. Alpha Engine will not reconstruct or infer them from public historical evidence.
          </div>
        ) : (
          <>
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
              <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
                <div className="grid grid-cols-[minmax(58px,1fr)_58px_58px_64px] border-b bg-muted/25 px-3 py-2.5 text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground sm:grid-cols-[minmax(100px,1fr)_90px_90px_90px] sm:px-4 sm:text-[10px] sm:tracking-[0.14em]">
                  <span>Asset</span><span className="text-right">Current</span><span className="text-right">Target</span><span className="text-right">Change</span>
                </div>
                {snapshot?.allocations.length ? snapshot.allocations.map((leg) => (
                  <div key={leg.asset} className="grid grid-cols-[minmax(58px,1fr)_58px_58px_64px] border-b px-3 py-3 text-xs last:border-0 sm:grid-cols-[minmax(100px,1fr)_90px_90px_90px] sm:px-4 sm:text-sm">
                    <span className="font-semibold">{leg.asset}</span>
                    <span className="text-right font-mono tabular-nums">{pct(leg.current)}</span>
                    <span className="text-right font-mono tabular-nums">{pct(leg.target)}</span>
                    <span className="text-right font-mono font-semibold tabular-nums">{leg.delta > 0 ? '+' : ''}{pct(leg.delta)}</span>
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
                  <div className="rounded-xl border bg-card p-4"><Database className="h-4 w-4 text-primary" /><p className="mt-3 text-xs text-muted-foreground">Data / factors</p><p className="mt-1 text-sm font-semibold">{snapshot ? `${snapshot.dataFreshness} / ${snapshot.factorFreshness}` : 'unknown'}</p></div>
                </div>
              </div>
            </div>

            {snapshot?.factorEvidence.length ? (
              <div className="rounded-xl border bg-card p-5 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold">Current signal drivers</h3></div>
                  <span className="text-xs text-muted-foreground">Cutoff {snapshot.latestCompletedSession} · {snapshot.factorEvidence.length} canonical factors</span>
                </div>
                <div className="mt-4 overflow-x-auto">
                  <div className="min-w-[720px]">
                    <div className="grid grid-cols-[minmax(180px,1.2fr)_100px_120px_90px_minmax(220px,1.25fr)] gap-3 border-b pb-2 text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                      <span>Factor</span><span>Value</span><span>State</span><span>Effect</span><span>Reference / model evidence</span>
                    </div>
                    {snapshot.factorEvidence.map((factor) => {
                      const reference = factorReference(factor);
                      const modelEvidence = contributionSummary(factor);
                      return (
                        <div key={factor.factorId} className="grid grid-cols-[minmax(180px,1.2fr)_100px_120px_90px_minmax(220px,1.25fr)] gap-3 border-b py-3 text-xs last:border-0">
                          <div><p className="font-semibold">{factor.displayName}</p><p className="mt-0.5 font-mono text-[10px] text-muted-foreground">{factor.factorId}</p></div>
                          <span className="font-mono font-semibold tabular-nums">{factorValue(factor)}</span>
                          <span>{factor.state}</span>
                          <span className="font-semibold">{factor.effect}</span>
                          <div className="text-muted-foreground">
                            <span>{reference ? `${reference} · ` : ''}{factor.reasonCode}</span>
                            {modelEvidence && <p className="mt-1 font-mono text-[10px] leading-relaxed text-primary">{modelEvidence}</p>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
                <p className="mt-4 text-xs text-muted-foreground">Rules-based strategies show cutoff-bound inputs and direct support/veto states. XGBoost rankers additionally show native pred_contribs for the current ranking decision. Model contributions explain the fitted score, not causality.</p>
              </div>
            ) : snapshot ? (
              <div className="rounded-xl border bg-card p-5 text-sm text-muted-foreground shadow-sm">
                Canonical factor evidence is {snapshot.factorFreshness}. A fresh operating signal is not presented as factor-explained until the signal ledger publishes a cutoff-bound factor snapshot.
              </div>
            ) : null}
          </>
        )}
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
