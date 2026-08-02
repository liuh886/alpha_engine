import { AlertTriangle, Database, FileCheck2, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useActiveResearchBundle } from '@/hooks/useActiveResearchBundle';
import { formatBytes, groupArtifacts } from '@/lib/artifact-data';

export function EvidenceDataPage() {
  const bundle = useActiveResearchBundle();
  const manifest = bundle?.manifest;
  const groups = groupArtifacts(manifest?.artifacts ?? []);
  const totalBytes = groups.reduce((sum, group) => sum + group.bytes, 0);

  if (!bundle || !manifest) {
    return <div className="research-empty-state"><Database className="h-8 w-8 text-muted-foreground" /><h1 className="mt-3 text-xl font-semibold">No evidence bundle is open</h1><p className="mt-2 text-sm text-muted-foreground">Open a bundle from Library to inspect data lineage and readiness.</p></div>;
  }

  return (
    <div className="research-page space-y-6">
      <header className="research-page-header">
        <div><p className="research-kicker">Evidence / Data</p><h1>Data identity and readiness</h1><p>Inspect the declared scope, immutable file inventory, warnings and blocked evidence gates before interpreting any model result.</p></div>
        <Badge variant="outline" className="h-7 gap-1.5"><ShieldCheck className="h-3.5 w-3.5" /> {bundle.integrity === 'all_verified' ? 'Fully verified' : 'Core indexes verified'}</Badge>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Evidence cutoff</p><p className="mt-2 font-mono text-xl font-semibold">{manifest.evidence_cutoff || 'Not declared'}</p></CardContent></Card>
        <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Market scope</p><p className="mt-2 text-xl font-semibold">{manifest.scope.markets.map((market) => market.toUpperCase()).join(' · ') || 'None'}</p></CardContent></Card>
        <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Declared files</p><p className="mt-2 font-mono text-xl font-semibold">{manifest.artifacts.length}</p></CardContent></Card>
        <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Bundle size</p><p className="mt-2 font-mono text-xl font-semibold">{formatBytes(totalBytes)}</p></CardContent></Card>
      </section>

      {(manifest.warnings.length > 0 || manifest.blocked_gates.length > 0) && (
        <Card className="border-amber-500/30 bg-amber-500/5">
          <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><AlertTriangle className="h-4 w-4 text-amber-600" /> Evidence limitations</CardTitle></CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <div><p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Warnings</p>{manifest.warnings.length ? <ul className="space-y-1 text-sm">{manifest.warnings.map((warning) => <li key={warning}>• {warning}</li>)}</ul> : <p className="text-sm text-muted-foreground">No bundle warnings declared.</p>}</div>
            <div><p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Blocked gates</p>{manifest.blocked_gates.length ? <ul className="space-y-1 text-sm">{manifest.blocked_gates.map((gate) => <li key={gate}>• {gate}</li>)}</ul> : <p className="text-sm text-muted-foreground">No blocked gates declared.</p>}</div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-5 xl:grid-cols-[0.75fr_1.25fr]">
        <Card className="research-surface">
          <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><FileCheck2 className="h-4 w-4 text-primary" /> Artifact classes</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {groups.map((group) => <div key={group.kind} className="flex items-center justify-between rounded-lg border px-3 py-2"><div><p className="text-sm font-medium">{group.kind.replace(/_/g, ' ')}</p><p className="text-[11px] text-muted-foreground">{group.count} files · {group.required} required</p></div><span className="font-mono text-xs">{formatBytes(group.bytes)}</span></div>)}
          </CardContent>
        </Card>

        <Card className="research-surface overflow-hidden">
          <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><Database className="h-4 w-4 text-primary" /> Immutable inventory</CardTitle></CardHeader>
          <CardContent className="p-0">
            <div className="max-h-[560px] overflow-auto">
              <Table>
                <TableHeader className="sticky top-0 bg-card"><TableRow><TableHead>Path</TableHead><TableHead>Kind</TableHead><TableHead>Size</TableHead><TableHead>Digest</TableHead></TableRow></TableHeader>
                <TableBody>{manifest.artifacts.map((artifact) => <TableRow key={artifact.artifact_id}><TableCell className="max-w-[320px] truncate font-mono text-[11px]" title={artifact.path}>{artifact.path}</TableCell><TableCell><Badge variant="outline" className="text-[9px]">{artifact.kind}</Badge></TableCell><TableCell className="font-mono text-xs">{formatBytes(artifact.byte_size)}</TableCell><TableCell className="font-mono text-[10px] text-muted-foreground">{artifact.sha256.slice(0, 12)}…</TableCell></TableRow>)}</TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
