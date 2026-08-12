import { ArrowRight, BarChart3, FileCheck2, GitCompareArrows, ScrollText, ShieldCheck } from 'lucide-react';
import { Link, useOutletContext } from 'react-router-dom';
import { governedRunQuery } from '@/lib/governed-run';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

const links = [
  { to: '/runs', label: 'Research runs', description: 'Inspect formal, preview and explicitly opened local governed iterations.', icon: BarChart3 },
  { to: '/compare', label: 'Compare runs', description: 'Compare only runs with compatible market, benchmark and contract identity.', icon: GitCompareArrows },
  { to: '/decisions', label: 'Research decisions', description: 'Review supported, rejected and blocked conclusions without losing the evidence chain.', icon: FileCheck2 },
  { to: '/factors', label: 'Factor evidence', description: 'Inspect historical factor diagnostics, current strategy drivers and model-specific evidence.', icon: ScrollText },
  { to: '/reports', label: 'Reports & notebooks', description: 'Open durable interpretation and reproducible research artifacts declared by the active bundle.', icon: ScrollText },
];

export function ResearchHubPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const formal = workspace.runs.filter((run) => run.channel === 'formal');
  const previews = workspace.runs.filter((run) => run.channel === 'preview');
  const local = workspace.runs.filter((run) => run.channel === 'local');

  return (
    <div className="mx-auto max-w-[1200px] space-y-7 pb-16">
      <header className="max-w-3xl">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">Strategy evolution</p>
        <h1 className="mt-2 text-3xl font-black tracking-tight">Research</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">Research is where a formal strategy earns its next version. Current baselines come from the governed formal catalog; previews and local bundles remain subordinate research evidence rather than competing sources of truth.</p>
      </header>

      <section className="rounded-2xl border bg-card shadow-sm">
        <div className="border-b p-5">
          <p className="text-sm font-semibold">Current research inventory</p>
          <p className="mt-1 text-xs text-muted-foreground">{formal.length} formal baselines · {previews.length} CI-validated preview runs · {local.length} explicitly opened local runs</p>
        </div>

        <div className="border-b p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold">Current formal baselines</p>
              <p className="mt-1 text-xs text-muted-foreground">Canonical model identity and evidence cutoff from Formal Bundle v2.</p>
            </div>
            <ShieldCheck className="h-5 w-5 text-primary" />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {formal.map((run) => (
              <Link
                key={run.key}
                to={`/review?${governedRunQuery(run)}`}
                className="group rounded-xl border bg-muted/10 p-4 transition-colors hover:border-primary/40 hover:bg-muted/20"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate text-sm font-semibold">{run.title}</h2>
                    <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{run.modelVersionId}</p>
                  </div>
                  <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                </div>
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                  <span>{run.market.toUpperCase()}</span>
                  <span>Cutoff {run.evidenceCutoff || 'not declared'}</span>
                  <span>{run.publicationStatus}</span>
                </div>
              </Link>
            ))}
          </div>
        </div>

        <div className="divide-y">
          {links.map(({ to, label, description, icon: Icon }) => (
            <Link key={to} to={to} className="group flex items-center gap-4 p-5 transition-colors hover:bg-muted/20">
              <div className="rounded-lg border bg-muted/20 p-2 text-primary"><Icon className="h-4 w-4" /></div>
              <div className="min-w-0 flex-1"><h2 className="text-sm font-semibold">{label}</h2><p className="mt-1 text-xs text-muted-foreground">{description}</p></div>
              <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
