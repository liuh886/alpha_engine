import { ArrowRight, BarChart3, FileCheck2, GitCompareArrows, ScrollText } from 'lucide-react';
import { Link, useOutletContext } from 'react-router-dom';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

const links = [
  { to: '/runs', label: 'Research runs', description: 'Inspect formal, preview and local governed iterations.', icon: BarChart3 },
  { to: '/compare', label: 'Compare runs', description: 'Compare only runs with compatible market, benchmark and contract identity.', icon: GitCompareArrows },
  { to: '/decisions', label: 'Research decisions', description: 'Review supported, rejected and blocked conclusions without losing the evidence chain.', icon: FileCheck2 },
  { to: '/factors', label: 'Factor evidence', description: 'Inspect validated factor evidence while the canonical #626 factor contract converges.', icon: ScrollText },
  { to: '/reports', label: 'Reports & notebooks', description: 'Open durable interpretation and reproducible research artifacts.', icon: ScrollText },
];

export function ResearchHubPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const previews = workspace.runs.filter((run) => run.channel === 'preview');
  const local = workspace.runs.filter((run) => run.channel === 'local');

  return (
    <div className="mx-auto max-w-[1200px] space-y-7 pb-16">
      <header className="max-w-3xl">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">Strategy evolution</p>
        <h1 className="mt-2 text-3xl font-black tracking-tight">Research</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">Research is where a formal strategy earns its next version. Runs, factors, comparisons and decision receipts stay subordinate to that lifecycle instead of competing as separate top-level products.</p>
      </header>

      <section className="rounded-2xl border bg-card shadow-sm">
        <div className="border-b p-5">
          <p className="text-sm font-semibold">Current research inventory</p>
          <p className="mt-1 text-xs text-muted-foreground">{previews.length} CI-validated preview runs · {local.length} local bundle runs · {workspace.runs.length} total indexed records</p>
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
