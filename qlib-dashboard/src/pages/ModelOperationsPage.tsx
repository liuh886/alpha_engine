import { useEffect, useMemo, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import { Activity, AlertTriangle, RefreshCw } from 'lucide-react';
import { StrategyRuntimeStatusStrip } from '@/components/StrategyRuntimeStatusStrip';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { loadRunSection, type GovernedRunSummary } from '@/lib/governed-run';
import type { RunWorkspaceContext } from '@/lib/run-workspace';
import { fetchSystemHealth, type LiveSystemHealth } from '@/lib/system-health';

type Limits = { run: GovernedRunSummary; notes: string[]; error: string };
async function readLimits(run: GovernedRunSummary): Promise<Limits> {
  try {
    const raw = await loadRunSection(run, 'diagnostics') as Record<string, unknown>;
    if (raw?.research_only !== true || raw?.trade_ready !== false || !Array.isArray(raw.interpretation_notes) || !raw.interpretation_notes.every((note) => typeof note === 'string')) throw new Error('Invalid monitoring interpretation evidence.');
    return { run, notes: raw.interpretation_notes as string[], error: '' };
  } catch (error) {
    return { run, notes: [], error: error instanceof Error ? error.message : String(error) };
  }
}

export function ModelOperationsPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const runs = useMemo(() => workspace.runs.filter((run) => run.channel === 'formal'), [workspace.runs]);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ runs: GovernedRunSummary[]; attempt: number; health: LiveSystemHealth } | null>(null);
  const [limits, setLimits] = useState<Array<Limits & { attempt: number }>>([]);
  const settled = result?.runs === runs && result.attempt === attempt;
  useEffect(() => {
    let active = true;
    void fetchSystemHealth().then((health) => {
      if (active) setResult({ runs, attempt, health });
    });
    runs.forEach((run) => { void readLimits(run).then((value) => {
      if (active) setLimits((current) => [...current.filter((row) => row.run !== run && runs.includes(row.run)), { ...value, attempt }]);
    }); });
    return () => { active = false; };
  }, [runs, attempt]);
  return <div className="mx-auto max-w-[1500px] space-y-6 pb-16">
    <header className="flex flex-wrap items-start justify-between gap-4 border-b pb-6">
      <div className="max-w-3xl"><p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">Governed monitoring</p><h1 className="mt-2 text-3xl font-black tracking-tight">Model Operations & Monitoring</h1><p className="mt-3 text-sm text-muted-foreground">Check current data, formal evidence and decision observations for the accepted models. Operational freshness does not establish model effectiveness.</p></div>
      <Button variant="outline" size="sm" disabled={!settled} onClick={() => setAttempt((value) => value + 1)}><RefreshCw className="mr-2 h-4 w-4" />Refresh monitoring</Button>
    </header>
    <section className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm">
      <p className="flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4 shrink-0" />Statistical drift: unavailable</p>
      <p className="mt-2 text-muted-foreground">Verified baseline and current prediction/label windows are not connected. Drift health remains unknown even when operational data is current.</p>
      <p className="mt-2 text-xs text-muted-foreground">Research only · Trade readiness remains false.</p>
    </section>
    {!runs.length ? <div className="research-empty-state"><h2 className="text-lg font-semibold">No accepted model records</h2><p className="mt-2 text-sm text-muted-foreground">A verified formal catalog is required for monitoring.</p></div> : <>
      {settled ? <p className="text-xs text-muted-foreground">Health checked at {result.health.health?.generated_at || 'Not declared'} · {result.health.message}</p> : <p role="status" className="text-sm text-muted-foreground">Checking monitoring evidence...</p>}
      <section className="grid gap-5 xl:grid-cols-2">{runs.map((run) => {
        const candidates = settled ? result.health.health?.strategies.filter((row) => row.model_version_id === run.modelVersionId) ?? [] : [];
        const candidate = candidates.length === 1 ? candidates[0] : null;
        const health = candidate?.formal_bundle_id === run.bundleId && candidate?.formal_run_id === run.runId && candidate?.market === run.market && candidate?.formal_cutoff === run.evidenceCutoff ? candidate : null;
        const interpretation = limits.find((value) => value.run === run && value.attempt === attempt);
        return <Card key={run.key} className="min-w-0"><CardHeader><div className="flex flex-wrap items-start justify-between gap-2"><CardTitle className="flex items-center gap-2 text-base"><Activity className="h-4 w-4 shrink-0 text-primary" />{run.title}</CardTitle><Badge variant="outline">{health?.state ?? 'unknown'}</Badge></div><p className="break-all font-mono text-[10px] text-muted-foreground">{run.runId}</p><p className="text-xs text-muted-foreground">{run.market.toUpperCase()} · Formal evidence through {run.evidenceCutoff} · {run.evidenceStatus} evidence</p></CardHeader><CardContent className="space-y-4">
          {health ? <StrategyRuntimeStatusStrip dataThrough={health.provider_cutoff} dataState={health.stages.provider} performanceThrough={health.formal_cutoff} performanceState={health.stages.formal} signalThrough={health.last_signal_evaluation} signalState={health.stages.signal} deliveryStatus={health.delivery_status} deliveryState={health.stages.delivery} /> : !settled ? <p className="text-sm text-muted-foreground">Checking operational health...</p> : <p role="alert" className="text-sm text-muted-foreground">{candidate ? 'Monitoring identity does not match this formal run.' : 'Source-bound operational health is unavailable.'} Formal evidence remains readable at its declared cutoff.</p>}
          {health && <p className="text-xs text-muted-foreground">Factor evidence through {health.factor_cutoff || 'Not declared'} · {health.stages.factor}. Training profile binding: not declared.</p>}
          <div><h2 className="text-sm font-semibold">Retained interpretation limits</h2>{!interpretation ? <p role="status" className="mt-2 text-xs text-muted-foreground">Checking interpretation evidence...</p> : interpretation.error ? <p role="alert" className="mt-2 text-sm text-muted-foreground">{interpretation.error}</p> : interpretation.notes.length ? <ul className="mt-2 list-disc space-y-2 pl-5 text-xs text-muted-foreground">{interpretation.notes.map((note, index) => <li key={index}>{note}</li>)}</ul> : <p className="mt-2 text-xs text-muted-foreground">No interpretation notes are retained.</p>}</div>
          <Button asChild variant="outline" size="sm"><Link to={`/strategies/${run.modelVersionId}`}>Open strategy evidence</Link></Button>
        </CardContent></Card>;
      })}</section>
    </>}
  </div>;
}
