import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Database,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  fetchV42RuntimeSnapshot,
  type V42Asset,
  type V42HorizonOutcome,
  type V42RuntimeSnapshot,
  type V42Weights,
} from '@/lib/v42-runtime';
import {
  fetchV42WorkflowHealth,
  workflowHealthLabel,
  type V42WorkflowHealthEntry,
} from '@/lib/v42-workflow-health';

const ASSETS: V42Asset[] = ['QQQI', 'QQQ', 'TQQQ'];

const STATUS_LABELS: Record<string, string> = {
  awaiting_next_open: 'Awaiting next open',
  observing_outcomes: 'Observing outcomes',
  active_precursor: 'Research precursor active',
  mature_40_sessions: '40-session evidence complete',
};

const STATE_LABELS: Record<number, string> = {
  0: 'Defensive',
  1: 'Transition',
  2: 'Risk-on',
};

const WORKFLOW_TONE_CLASS = {
  healthy: 'text-emerald-600 dark:text-emerald-400',
  running: 'text-blue-600 dark:text-blue-400',
  attention: 'text-amber-600 dark:text-amber-400',
  unknown: 'text-muted-foreground',
} as const;

function formatPercent(value: unknown, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${(value * 100).toFixed(digits)}%`
    : '—';
}

function formatNumber(value: unknown, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? value.toFixed(digits)
    : '—';
}

function featureNumber(features: Record<string, unknown>, key: string): number | null {
  const value = features[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function AllocationPanel({ title, subtitle, weights }: {
  title: string;
  subtitle: string;
  weights: V42Weights;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">{title}</CardTitle>
        <p className="text-xs leading-relaxed text-muted-foreground">{subtitle}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        {ASSETS.map((asset) => {
          const value = weights[asset] ?? 0;
          const width = `${Math.max(0, Math.min(100, value * 100))}%`;
          return (
            <div key={asset}>
              <div className="mb-1.5 flex items-center justify-between text-sm">
                <span className="font-semibold">{asset}</span>
                <span className="font-mono text-xs">{formatPercent(value)}</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary" style={{ width }} />
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function HorizonCell({ outcome }: { outcome?: V42HorizonOutcome }) {
  if (!outcome) return <span className="text-muted-foreground">Pending</span>;
  return (
    <div className="space-y-1 font-mono text-xs">
      <div>QQQ {formatPercent(outcome.qqq_return, 2)}</div>
      <div>TQQQ {formatPercent(outcome.tqqq_return, 2)}</div>
    </div>
  );
}

function WorkflowHealthCard({ entry }: { entry: V42WorkflowHealthEntry }) {
  const health = workflowHealthLabel(entry);
  return (
    <div className="rounded-xl border bg-muted/15 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold">{entry.label}</p>
          <p className="mt-1 font-mono text-[10px] text-muted-foreground">{entry.workflowFile}</p>
        </div>
        <Badge variant="outline" className={WORKFLOW_TONE_CLASS[health.tone]}>{health.label}</Badge>
      </div>
      {entry.run ? (
        <div className="mt-4 space-y-2 text-xs text-muted-foreground">
          <p>Started {entry.run.run_started_at ? new Date(entry.run.run_started_at).toLocaleString() : 'time not declared'}</p>
          <p className="font-mono">run {entry.run.id} · {entry.run.event} · {entry.run.head_sha.slice(0, 8)}</p>
          <a
            href={entry.run.html_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-semibold text-primary hover:underline"
          >
            Open workflow run <ArrowUpRight className="h-3 w-3" />
          </a>
        </div>
      ) : (
        <p className="mt-4 text-xs leading-relaxed text-muted-foreground">{entry.error || 'No workflow run is available.'}</p>
      )}
    </div>
  );
}

export function StrategyOperationsPage() {
  const [snapshot, setSnapshot] = useState<V42RuntimeSnapshot | null>(null);
  const [workflowHealth, setWorkflowHealth] = useState<V42WorkflowHealthEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextSnapshot, nextWorkflowHealth] = await Promise.all([
        fetchV42RuntimeSnapshot(),
        fetchV42WorkflowHealth(),
      ]);
      setSnapshot(nextSnapshot);
      setWorkflowHealth(nextWorkflowHealth);
    } catch (runtimeError) {
      setSnapshot(null);
      setWorkflowHealth([]);
      setError(runtimeError instanceof Error ? runtimeError.message : 'The v4.2 ledger is unavailable.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const event = snapshot?.latestStateChange ?? null;
  const record = event?.record ?? null;
  const observation = snapshot?.observation ?? null;
  const features = record?.signal_close_features ?? {};
  const completed = useMemo(
    () => new Set(observation?.completed_horizons ?? []),
    [observation?.completed_horizons],
  );

  if (loading && !snapshot) {
    return (
      <div className="research-empty-state">
        <RefreshCw className="mx-auto h-7 w-7 animate-spin text-primary/70" />
        <h1 className="mt-4 text-lg font-semibold">Loading the public v4.2 ledger</h1>
        <p className="mt-2 text-sm text-muted-foreground">Reading durable signals, outcomes and workflow health from GitHub.</p>
      </div>
    );
  }

  if (error || !record || !event) {
    return (
      <div className="research-empty-state">
        <AlertTriangle className="mx-auto h-8 w-8 text-amber-500" />
        <h1 className="mt-4 text-lg font-semibold">v4.2 operating evidence unavailable</h1>
        <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">
          {error || 'No valid state-change marker was found. The interface will not infer a position from prose.'}
        </p>
        <Button variant="outline" className="mt-5 gap-2" onClick={() => void refresh()}>
          <RefreshCw className="h-4 w-4" /> Retry
        </Button>
      </div>
    );
  }

  const status = observation?.status || record.status;
  const statusLabel = STATUS_LABELS[status] || status.replaceAll('_', ' ');
  const execution = observation?.execution;
  const monthly = snapshot.latestMonthlySummary?.summary;

  return (
    <div className="mx-auto max-w-[1400px] space-y-6 pb-16">
      <section className="relative overflow-hidden rounded-2xl border bg-card p-6 md:p-8">
        <div className="pointer-events-none absolute inset-y-0 right-0 w-2/5 bg-gradient-to-l from-primary/10 to-transparent" />
        <div className="relative flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className="gap-1.5"><Activity className="h-3 w-3" /> v4.2 active baseline</Badge>
              <Badge variant="outline">Research only</Badge>
              <Badge variant="outline">Not trade-ready</Badge>
              <Badge variant="secondary">Read-only ledger</Badge>
            </div>
            <p className="mt-5 text-xs font-bold uppercase tracking-[0.22em] text-primary">Operating evidence</p>
            <h1 className="mt-2 text-3xl font-black tracking-tight md:text-4xl">{statusLabel}</h1>
            <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground md:text-base">
              This page reports what the scheduled v4.2 workflows recorded. It does not run the model, place an order, or assume that a close-time target was executed.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" className="gap-2" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh ledger
            </Button>
            <Button asChild className="gap-2">
              <a href={event.issue.html_url} target="_blank" rel="noreferrer">
                Open evidence issue <ArrowUpRight className="h-4 w-4" />
              </a>
            </Button>
          </div>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardContent className="p-5">
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">Signal close</p>
            <div className="mt-2 font-mono text-xl font-bold">{record.signal_date}</div>
            <p className="mt-1 text-xs text-muted-foreground">Latest governed data: {observation?.as_of_data_date || record.latest_data_date_at_creation}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">State transition</p>
            <div className="mt-2 text-xl font-bold">
              {STATE_LABELS[record.current_state] || record.current_state} → {STATE_LABELS[record.target_state] || record.target_state}
            </div>
            <p className="mt-1 font-mono text-xs text-muted-foreground">{record.transition_type || 'transition not declared'}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">Execution evidence</p>
            <div className="mt-2 flex items-center gap-2 text-xl font-bold">
              {execution?.execution_date ? <CheckCircle2 className="h-5 w-5 text-emerald-500" /> : <Clock3 className="h-5 w-5 text-amber-500" />}
              {execution?.execution_date ? execution.execution_date : 'Not observed'}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">The ledger records theoretical next-open evidence, not brokerage execution.</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">Evidence progress</p>
            <div className="mt-2 font-mono text-xl font-bold">{observation?.available_sessions ?? 0} sessions</div>
            <p className="mt-1 text-xs text-muted-foreground">{completed.size}/7 declared outcome horizons complete.</p>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Automation health</CardTitle>
          <p className="text-sm text-muted-foreground">Latest public GitHub Actions runs for the decision-alert and evidence-ledger chains.</p>
        </CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-2">
          {workflowHealth.length > 0
            ? workflowHealth.map((entry) => <WorkflowHealthCard key={entry.key} entry={entry} />)
            : <p className="text-sm text-muted-foreground">Workflow health could not be loaded.</p>}
        </CardContent>
      </Card>

      <section className="grid gap-4 lg:grid-cols-2">
        <AllocationPanel
          title="Last executed allocation at signal close"
          subtitle="Immutable signal-time record. It may differ from a later brokerage position or a theoretical next-open transition."
          weights={record.current_weights}
        />
        <AllocationPanel
          title="Close-time target allocation"
          subtitle="Decision target for the next session open. A target is not displayed as executed until outcome evidence exists."
          weights={record.target_weights}
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Decision context</CardTitle>
            <p className="text-sm text-muted-foreground">Only fields retained at the signal close are shown.</p>
          </CardHeader>
          <CardContent>
            <div className="rounded-lg border bg-muted/25 p-4">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">Rule</p>
              <p className="mt-2 font-mono text-sm font-semibold">{record.decision_reason || 'not declared'}</p>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[
                ['VIX close', formatNumber(featureNumber(features, 'vix_close'))],
                ['VIX 5D', formatPercent(featureNumber(features, 'vix_return_5d'), 2)],
                ['VXN close', formatNumber(featureNumber(features, 'vxn_close'))],
                ['VXN 1D', formatPercent(featureNumber(features, 'vxn_return_1d'), 2)],
                ['VXN 5D', formatPercent(featureNumber(features, 'vxn_return_5d'), 2)],
                ['QQQ vs MA20', formatPercent(featureNumber(features, 'qqq_distance_ma_short'), 2)],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg border p-3">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{label}</p>
                  <p className="mt-1 font-mono text-sm font-bold">{value}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="h-4 w-4 text-primary" /> Operating boundary</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm leading-relaxed text-muted-foreground">
            <div className="flex gap-3">
              <Database className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <p>Source: public GitHub Issue machine markers created by the scheduled v4.2 evidence workflow.</p>
            </div>
            <div className="flex gap-3">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <p>Fresh governed data at signal creation: <strong className="text-foreground">{record.data_freshness_ok ? 'passed' : 'failed'}</strong>.</p>
            </div>
            <div className="flex gap-3">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
              <p>25% and 50% TQQQ precursor allocations remain research comparators. They are not promoted targets.</p>
            </div>
            <p className="border-t pt-4 font-mono text-[10px]">
              event {record.event_id} · fingerprint {record.fingerprint || 'not declared'}
            </p>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Prospective outcome horizons</CardTitle>
          <p className="text-sm text-muted-foreground">Returns are appended only after the declared number of trading sessions exists.</p>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b text-[10px] uppercase tracking-wider text-muted-foreground">
                <th className="px-3 py-3">Horizon</th>
                <th className="px-3 py-3">Status</th>
                <th className="px-3 py-3">Observed return</th>
                <th className="px-3 py-3">Directional component</th>
                <th className="px-3 py-3">Tracking / compounding</th>
              </tr>
            </thead>
            <tbody>
              {record.outcome_horizons_sessions.map((horizon) => {
                const outcome = observation?.outcomes?.[String(horizon)];
                return (
                  <tr key={horizon} className="border-b last:border-0">
                    <td className="px-3 py-4 font-mono font-semibold">{horizon} sessions</td>
                    <td className="px-3 py-4">
                      <Badge variant={completed.has(horizon) ? 'secondary' : 'outline'}>
                        {completed.has(horizon) ? 'Complete' : 'Pending'}
                      </Badge>
                    </td>
                    <td className="px-3 py-4"><HorizonCell outcome={outcome} /></td>
                    <td className="px-3 py-4 font-mono text-xs">{formatPercent(outcome?.directional_leverage_component, 2)}</td>
                    <td className="px-3 py-4 font-mono text-xs">{formatPercent(outcome?.tracking_compounding_component, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {monthly && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Monthly evidence accumulation · {monthly.month}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div><p className="text-xs text-muted-foreground">New events</p><p className="mt-1 font-mono text-2xl font-bold">{monthly.event_count}</p></div>
            <div><p className="text-xs text-muted-foreground">State changes</p><p className="mt-1 font-mono text-2xl font-bold">{monthly.state_change_event_count}</p></div>
            <div><p className="text-xs text-muted-foreground">Recovery precursors</p><p className="mt-1 font-mono text-2xl font-bold">{monthly.recovery_precursor_event_count}</p></div>
            <div><p className="text-xs text-muted-foreground">40-session unresolved</p><p className="mt-1 font-mono text-2xl font-bold">{monthly.unresolved_40_session_count}</p></div>
          </CardContent>
        </Card>
      )}

      <p className="text-center font-mono text-[10px] text-muted-foreground">
        Ledger fetched {new Date(snapshot.fetchedAt).toLocaleString()} · source {snapshot.source}
      </p>
    </div>
  );
}
