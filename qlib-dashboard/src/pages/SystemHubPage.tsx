import { AlertTriangle, ArrowRight, BookOpen, CheckCircle2, Database, FolderArchive, SlidersHorizontal } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import { fetchSystemHealth, type LiveSystemHealth } from '@/lib/system-health';
import type { RunWorkspaceContext } from '@/lib/run-workspace';
import { useAccessControl } from '@/hooks/useAccessControl';

const stateTone = (state: string) => state === 'current'
  ? 'text-emerald-500'
  : state === 'delayed'
    ? 'text-amber-500'
    : 'text-destructive';

export function SystemHubPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const access = useAccessControl();
  const [health, setHealth] = useState<LiveSystemHealth | null>(null);

  useEffect(() => {
    let active = true;
    void fetchSystemHealth().then((value) => { if (active) setHealth(value); });
    return () => { active = false; };
  }, []);

  const status = health?.status ?? 'unknown';
  const StatusIcon = status === 'current' ? CheckCircle2 : AlertTriangle;

  return (
    <div className="mx-auto max-w-[1200px] space-y-7 pb-16">
      <header className="max-w-3xl">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">Trust and infrastructure</p>
        <h1 className="mt-2 text-3xl font-black tracking-tight">System</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">Data lineage, freshness, local bundles and methodology live here. They support strategy decisions without dominating the normal operating workflow.</p>
      </header>

      <section className="rounded-2xl border bg-card p-5 shadow-sm">
        <div className="flex items-start gap-4">
          <StatusIcon className={`mt-0.5 h-5 w-5 shrink-0 ${stateTone(status)}`} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold">Pipeline health: {status}</p>
              <p className={`text-[10px] font-mono ${stateTone(health?.deploymentStatus ?? 'unknown')}`}>Pages: {health?.deploymentStatus ?? 'unknown'}</p>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{health?.message ?? 'System health has not been loaded.'}</p>
            <p className="mt-2 text-[10px] font-mono text-muted-foreground">{workspace.runs.filter((run) => run.channel === 'formal').length} accepted formal baselines · {workspace.runLoadErrors.length} preview load errors</p>
          </div>
        </div>

        {health?.health?.model_data ? (
          <div className="mt-4 rounded-xl border bg-muted/20 px-3 py-2.5">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-semibold">Research training data</p>
              <p className={`text-[10px] font-mono ${stateTone(health.health.model_data.state)}`}>{health.health.model_data.state}</p>
            </div>
            <p className="mt-1 text-[10px] font-mono text-muted-foreground">
              components {health.health.model_data.summary.ready_component_count}/{health.health.model_data.summary.component_count} ready
              {' · '}{health.health.model_data.summary.partial_component_count} partial
              {' · '}{health.health.model_data.summary.blocked_training_profile_count} blocked profiles
              {' · '}through {health.health.model_data.evidence_cutoff ?? '—'}
            </p>
            <p className="mt-1 text-[10px] text-muted-foreground">Reported separately from active runtime health until a frozen model contract explicitly binds a training profile.</p>
          </div>
        ) : null}

        {health?.health?.markets.length ? (
          <div className="mt-4 grid gap-2 border-t pt-4 sm:grid-cols-2">
            {health.health.markets.map((market) => (
              <div key={market.market} className="rounded-xl bg-muted/30 px-3 py-2.5">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-semibold uppercase">{market.market}</p>
                  <p className={`text-[10px] font-mono ${stateTone(market.state)}`}>{market.state}</p>
                </div>
                <p className="mt-1 text-[10px] font-mono text-muted-foreground">provider {market.provider_cutoff ?? '—'} · expected {market.market_expected_cutoff ?? '—'}</p>
                {market.state === 'delayed' && <p className="mt-1 text-[10px] text-muted-foreground">Internally consistent; provider-resolved common session is behind another governed active watermark.</p>}
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section className="overflow-hidden rounded-2xl border bg-card shadow-sm">
        <Link to="/data" className="group flex items-center gap-4 border-b p-5 hover:bg-muted/20">
          <Database className="h-5 w-5 text-primary" /><div className="flex-1"><h2 className="text-sm font-semibold">Data lineage & readiness</h2><p className="mt-1 text-xs text-muted-foreground">Provider identity, coverage, cutoff and blockers.</p></div><ArrowRight className="h-4 w-4 text-muted-foreground group-hover:text-primary" />
        </Link>
        <Link to="/library" className="group flex items-center gap-4 border-b p-5 hover:bg-muted/20">
          <FolderArchive className="h-5 w-5 text-primary" /><div className="flex-1"><h2 className="text-sm font-semibold">Bundle library</h2><p className="mt-1 text-xs text-muted-foreground">Open and validate local Alpha Engine artifact bundles.</p></div><ArrowRight className="h-4 w-4 text-muted-foreground group-hover:text-primary" />
        </Link>
        <Link to="/methodology" className="group flex items-center gap-4 p-5 hover:bg-muted/20">
          <BookOpen className="h-5 w-5 text-primary" /><div className="flex-1"><h2 className="text-sm font-semibold">Methodology & boundaries</h2><p className="mt-1 text-xs text-muted-foreground">Research contracts, execution assumptions and interpretation limits.</p></div><ArrowRight className="h-4 w-4 text-muted-foreground group-hover:text-primary" />
        </Link>
        {access.isOwner && <Link to="/settings/access" className="group flex items-center gap-4 border-t p-5 hover:bg-muted/20"><SlidersHorizontal className="h-5 w-5 text-primary" /><div className="flex-1"><h2 className="text-sm font-semibold">Access settings</h2><p className="mt-1 text-xs text-muted-foreground">Set Guest, Member, Pro or Owner access for models and modules.</p></div><ArrowRight className="h-4 w-4 text-muted-foreground group-hover:text-primary" /></Link>}
      </section>
    </div>
  );
}
