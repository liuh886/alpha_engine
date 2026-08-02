import { useMemo, useState } from 'react';
import { BookOpen, ExternalLink, FileCode2, FileText, NotebookTabs } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useActiveResearchBundle } from '@/hooks/useActiveResearchBundle';
import { formatBytes } from '@/lib/artifact-data';
import type { BundleArtifact } from '@/lib/research-bundle';

const ALLOWED_KINDS = new Set(['report', 'notebook', 'methodology']);

function iconFor(artifact: BundleArtifact) {
  if (artifact.kind === 'notebook') return NotebookTabs;
  if (artifact.kind === 'methodology') return BookOpen;
  return FileText;
}

export function EvidenceReportsPage() {
  const bundle = useActiveResearchBundle();
  const [error, setError] = useState('');
  const artifacts = useMemo(() => (bundle?.manifest.artifacts ?? []).filter((artifact) => ALLOWED_KINDS.has(artifact.kind)), [bundle]);

  const openArtifact = async (artifact: BundleArtifact) => {
    if (!bundle) return;
    setError('');
    try {
      const blob = await bundle.source.read(artifact.path);
      const url = URL.createObjectURL(blob);
      const opened = window.open(url, '_blank', 'noopener,noreferrer');
      if (!opened) {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = artifact.path.split('/').pop() || 'artifact';
        anchor.click();
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  return (
    <div className="research-page space-y-6">
      <header className="research-page-header">
        <div><p className="research-kicker">Evidence / Reports</p><h1>Reports, notebooks and methodology</h1><p>Open only files declared by the active bundle. The studio does not search the local directory outside the manifest or rewrite notebook outputs.</p></div>
        <Badge variant="outline" className="h-7 gap-1.5"><FileCode2 className="h-3.5 w-3.5" /> {artifacts.length} declared documents</Badge>
      </header>

      {error && <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}

      {artifacts.length === 0 ? (
        <div className="research-empty-state"><FileText className="h-8 w-8 text-muted-foreground" /><h1 className="mt-3 text-xl font-semibold">No durable documents are declared</h1><p className="mt-2 max-w-xl text-sm text-muted-foreground">Export reports or executed notebooks into the bundle before expecting them to appear here.</p></div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {artifacts.map((artifact) => {
            const Icon = iconFor(artifact);
            return <Card key={artifact.artifact_id} className="research-surface"><CardHeader><div className="flex items-start justify-between gap-3"><div className="flex min-w-0 gap-3"><div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Icon className="h-4 w-4" /></div><div className="min-w-0"><CardTitle className="truncate text-sm" title={artifact.path}>{artifact.path.split('/').pop()}</CardTitle><p className="mt-1 truncate font-mono text-[10px] text-muted-foreground" title={artifact.path}>{artifact.path}</p></div></div><Badge variant="outline" className="text-[9px] uppercase">{artifact.kind}</Badge></div></CardHeader><CardContent className="space-y-4"><div className="grid grid-cols-2 gap-3 text-xs"><div><p className="text-muted-foreground">Size</p><p className="mt-1 font-mono font-semibold">{formatBytes(artifact.byte_size)}</p></div><div><p className="text-muted-foreground">Digest</p><p className="mt-1 font-mono font-semibold">{artifact.sha256.slice(0, 10)}…</p></div></div><Button variant="outline" size="sm" className="w-full gap-2" onClick={() => void openArtifact(artifact)}><ExternalLink className="h-3.5 w-3.5" /> Open declared artifact</Button></CardContent></Card>;
          })}
        </div>
      )}
    </div>
  );
}
