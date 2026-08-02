import { useNavigate } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  BookOpen,
  Boxes,
  Database,
  FileText,
  GitCompareArrows,
  ShieldCheck,
} from 'lucide-react';
import type { ModelData } from '@/lib/data-parser';
import { runtimeCapabilities } from '@/lib/runtime-capabilities';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { BundleOpenPanel } from '@/components/BundleOpenPanel';

interface ArtifactHomeProps {
  models: ModelData[];
  generatedAt: string | null;
  latestModel: ModelData | null;
}

const MODE_LABEL = {
  static_artifact: 'Published artifact',
  local_artifact: 'Local artifact',
} as const;

export function ArtifactHome({ models, generatedAt, latestModel }: ArtifactHomeProps) {
  const navigate = useNavigate();

  return (
    <div className="mx-auto max-w-[1400px] space-y-8 pb-16">
      <section className="relative overflow-hidden rounded-2xl border bg-card p-6 md:p-9">
        <div className="pointer-events-none absolute inset-y-0 right-0 w-2/5 bg-gradient-to-l from-primary/10 to-transparent" />
        <div className="relative grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-end">
          <div className="max-w-3xl">
            <div className="mb-5 flex flex-wrap items-center gap-2">
              <Badge variant="secondary" className="font-mono text-[10px] uppercase tracking-widest">
                {MODE_LABEL[runtimeCapabilities.mode]}
              </Badge>
              <Badge variant="outline" className="font-mono text-[10px] uppercase tracking-widest text-amber-700 dark:text-amber-300">
                Research only
              </Badge>
              <Badge variant="outline" className="font-mono text-[10px] uppercase tracking-widest">
                Read only
              </Badge>
            </div>
            <p className="text-xs font-bold uppercase tracking-[0.22em] text-primary">Evidence-first workspace</p>
            <h1 className="mt-3 text-3xl font-black tracking-tight md:text-5xl">
              Decide what the evidence supports.
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-relaxed text-muted-foreground md:text-lg">
              Review accepted formal backtests, governed data lineage and the read-only v4.2 operating ledger. Every conclusion stays bound to its scope, cutoff, benchmark and retained source evidence.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Button onClick={() => navigate('/dashboard')} className="gap-2">
                Review formal backtests <ArrowRight className="h-4 w-4" />
              </Button>
              <Button onClick={() => navigate('/operations')} variant="outline" className="gap-2">
                <Activity className="h-4 w-4" /> Open v4.2 operations
              </Button>
              <Button onClick={() => navigate('/compare')} variant="ghost" className="gap-2">
                <GitCompareArrows className="h-4 w-4" /> Compare formal baselines
              </Button>
            </div>
          </div>

          <div className="rounded-xl border bg-background/70 p-5 backdrop-blur-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Repository evidence</p>
            <div className="mt-4 text-3xl font-black font-mono">{models.length}</div>
            <p className="mt-1 text-sm text-muted-foreground">Versioned model or strategy records in the shared research bundle.</p>
            <div className="mt-5 border-t pt-4">
              <p className="truncate text-sm font-semibold">{latestModel?.name || 'No record loaded'}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {latestModel
                  ? `${String(latestModel.market || 'unknown').toUpperCase()} · ${latestModel.model_type || 'formal research record'}`
                  : 'Open a compatible bundle to begin review.'}
              </p>
              <p className="mt-3 font-mono text-[10px] text-muted-foreground">
                Exported {generatedAt ? new Date(generatedAt).toLocaleString() : 'time not declared'}
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <button
          type="button"
          className="rounded-xl border bg-card p-5 text-left transition-colors hover:border-primary/40"
          onClick={() => navigate('/dashboard')}
        >
          <FileText className="mb-4 h-5 w-5 text-primary" />
          <div className="font-bold">Review retained performance</div>
          <p className="mt-2 text-sm text-muted-foreground">Inspect the governed path, holdings, trades, attribution and evidence limits of each accepted formal baseline.</p>
        </button>
        <button
          type="button"
          className="rounded-xl border bg-card p-5 text-left transition-colors hover:border-primary/40"
          onClick={() => navigate('/operations')}
        >
          <Activity className="mb-4 h-5 w-5 text-primary" />
          <div className="font-bold">Read the v4.2 operating ledger</div>
          <p className="mt-2 text-sm text-muted-foreground">See the latest governed state-change record, target allocation, evidence progress and workflow health without executing the model.</p>
        </button>
        <button
          type="button"
          className="rounded-xl border bg-card p-5 text-left transition-colors hover:border-primary/40"
          onClick={() => navigate('/data')}
        >
          <Database className="mb-4 h-5 w-5 text-primary" />
          <div className="font-bold">Confirm the evidence boundary</div>
          <p className="mt-2 text-sm text-muted-foreground">Check provider lineage, market scope, cutoff, missing files and integrity before interpreting results.</p>
        </button>
        <button
          type="button"
          className="rounded-xl border bg-card p-5 text-left transition-colors hover:border-primary/40"
          onClick={() => navigate('/compare')}
        >
          <GitCompareArrows className="mb-4 h-5 w-5 text-primary" />
          <div className="font-bold">Compare governed baselines</div>
          <p className="mt-2 text-sm text-muted-foreground">Compare only the named formal strategies admitted by the publication allow-list.</p>
        </button>
      </section>

      <Card className="border-primary/20">
        <CardHeader>
          <div className="flex items-start gap-3">
            <div className="rounded-lg border bg-primary/5 p-2 text-primary"><Boxes className="h-5 w-5" /></div>
            <div>
              <CardTitle className="text-base">Open a local Alpha Engine bundle</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                Choose a bundle root folder, a complete file set or a ZIP export. Files are read locally in the browser and are never uploaded.
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent><BundleOpenPanel /></CardContent>
      </Card>

      <section className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm"><ShieldCheck className="h-4 w-4 text-primary" /> Product boundary</CardTitle>
          </CardHeader>
          <CardContent className="text-sm leading-relaxed text-muted-foreground">
            The studio does not refresh market data, train models, run backtests, mutate registries or execute trades. Python CLI commands and scheduled workflows produce the evidence; this interface reviews it.
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm"><BookOpen className="h-4 w-4 text-primary" /> Interpretation boundary</CardTitle>
          </CardHeader>
          <CardContent className="text-sm leading-relaxed text-muted-foreground">
            A positive historical result or a current model target is not a brokerage instruction. Use Methodology to verify the fixed contract, benchmark, costs, universe validity and evidence completeness.
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
