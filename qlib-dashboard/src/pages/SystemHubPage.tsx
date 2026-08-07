import { AlertTriangle, ArrowRight, BookOpen, CheckCircle2, Database, FolderArchive } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import { fetchFormalFreshness, type FormalFreshnessSnapshot } from '@/lib/formal-freshness';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

export function SystemHubPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const [freshness, setFreshness] = useState<FormalFreshnessSnapshot | null>(null);

  useEffect(() => {
    let active = true;
    void fetchFormalFreshness().then((value) => { if (active) setFreshness(value); });
    return () => { active = false; };
  }, []);

  const status = freshness?.status ?? 'unknown';
  const StatusIcon = status === 'current' ? CheckCircle2 : AlertTriangle;

  return (
    <div className="mx-auto max-w-[1200px] space-y-7 pb-16">
      <header className="max-w-3xl">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">Trust and infrastructure</p>
        <h1 className="mt-2 text-3xl font-black tracking-tight">System</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">Data lineage, freshness, local bundles and methodology live here. They support strategy decisions without dominating the normal operating workflow.</p>
      </header>

      <section className="flex items-start gap-4 rounded-2xl border bg-card p-5 shadow-sm">
        <StatusIcon className={`mt-0.5 h-5 w-5 shrink-0 ${status === 'current' ? 'text-emerald-500' : 'text-amber-500'}`} />
        <div className="min-w-0">
          <p className="text-sm font-semibold">Formal evidence freshness: {status}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{freshness?.message ?? 'Freshness policy has not been loaded.'}</p>
          <p className="mt-2 text-[10px] font-mono text-muted-foreground">{workspace.runs.filter((run) => run.channel === 'formal').length} accepted formal baselines · {workspace.runLoadErrors.length} preview load errors</p>
        </div>
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
      </section>
    </div>
  );
}
