import { useNavigate } from 'react-router-dom';
import { ArrowRight, BookOpen, Database, FileText, FolderOpen, ShieldCheck } from 'lucide-react';
import type { ModelData } from '@/lib/data-parser';
import { runtimeCapabilities } from '@/lib/runtime-capabilities';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface ArtifactHomeProps {
  models: ModelData[];
  generatedAt: string | null;
  latestModel: ModelData | null;
}

const MODE_LABEL = {
  static_artifact: 'Static bundle',
  local_artifact: 'Local bundle',
  connected_research: 'Connected research',
} as const;

export function ArtifactHome({ models, generatedAt, latestModel }: ArtifactHomeProps) {
  const navigate = useNavigate();

  return (
    <div className="space-y-8 max-w-[1400px] mx-auto pb-16">
      <section className="rounded-2xl border bg-card p-6 md:p-8 overflow-hidden relative">
        <div className="absolute inset-y-0 right-0 w-1/3 bg-gradient-to-l from-primary/10 to-transparent pointer-events-none" />
        <div className="relative max-w-3xl">
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <Badge variant="secondary" className="font-mono text-[10px] uppercase tracking-widest">
              {MODE_LABEL[runtimeCapabilities.mode]}
            </Badge>
            <Badge variant="outline" className="font-mono text-[10px] uppercase tracking-widest text-amber-600 dark:text-amber-400">
              Research only
            </Badge>
          </div>
          <h1 className="text-3xl md:text-5xl font-black tracking-tight">Research Artifact Studio</h1>
          <p className="mt-4 text-base md:text-lg leading-relaxed text-muted-foreground">
            Inspect governed Alpha Engine data, models, experiments and backtests without running the research backend.
            Every conclusion should remain traceable to its evidence bundle, contract and cutoff.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Button onClick={() => navigate('/dashboard')} className="gap-2">
              Open latest evidence <ArrowRight className="h-4 w-4" />
            </Button>
            <Button onClick={() => navigate('/models')} variant="outline" className="gap-2">
              <Database className="h-4 w-4" /> Browse models
            </Button>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-primary" /> Evidence bundle
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="text-3xl font-black font-mono">{models.length}</div>
            <p className="text-sm text-muted-foreground">Model or strategy records available in this exported bundle.</p>
            <p className="text-[11px] font-mono text-muted-foreground">
              Generated: {generatedAt ? new Date(generatedAt).toLocaleString() : 'Not declared'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <FileText className="h-4 w-4 text-primary" /> Latest record
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="text-lg font-bold break-words">{latestModel?.name || 'No model record'}</div>
            <p className="text-sm text-muted-foreground">
              {latestModel
                ? `${String(latestModel.market || 'unknown').toUpperCase()} · ${latestModel.model_type || 'research candidate'}`
                : 'Export a compatible research bundle to populate this workspace.'}
            </p>
            {latestModel && (
              <Button variant="ghost" size="sm" className="px-0 gap-2" onClick={() => navigate('/dashboard')}>
                Inspect record <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            )}
          </CardContent>
        </Card>

        <Card className="border-dashed">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <FolderOpen className="h-4 w-4 text-primary" /> Local results folder
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="text-lg font-bold">Next delivery wave</div>
            <p className="text-sm text-muted-foreground">
              Direct read-only folder and ZIP loading is tracked in Issue #302. Selected files will remain on the device.
            </p>
          </CardContent>
        </Card>
      </section>

      <section>
        <div className="flex items-end justify-between gap-4 mb-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.2em] font-bold text-muted-foreground">Research paths</p>
            <h2 className="text-xl font-bold mt-1">Continue from the evidence, not the infrastructure</h2>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <button className="text-left rounded-xl border bg-card p-5 hover:border-primary/40 transition-colors" onClick={() => navigate('/reports')}>
            <FileText className="h-5 w-5 text-primary mb-4" />
            <div className="font-bold">Reports & interpretation</div>
            <p className="text-sm text-muted-foreground mt-2">Read preserved conclusions and supporting research notes.</p>
          </button>
          <button className="text-left rounded-xl border bg-card p-5 hover:border-primary/40 transition-colors" onClick={() => navigate('/backtest')}>
            <Database className="h-5 w-5 text-primary mb-4" />
            <div className="font-bold">Backtest evidence</div>
            <p className="text-sm text-muted-foreground mt-2">Review performance, drawdown, costs, holdings and attribution.</p>
          </button>
          <button className="text-left rounded-xl border bg-card p-5 hover:border-primary/40 transition-colors" onClick={() => navigate('/methodology')}>
            <BookOpen className="h-5 w-5 text-primary mb-4" />
            <div className="font-bold">Methodology</div>
            <p className="text-sm text-muted-foreground mt-2">Understand the fixed research contract and evidence boundaries.</p>
          </button>
        </div>
      </section>
    </div>
  );
}
