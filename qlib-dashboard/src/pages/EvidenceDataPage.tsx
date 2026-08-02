import { useEffect, useState } from 'react';
import { AlertTriangle, Database, FileCheck2, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useActiveResearchBundle } from '@/hooks/useActiveResearchBundle';
import {
  formatBytes,
  groupArtifacts,
  loadDataReadinessEvidence,
  type DataComponentStatus,
  type DataReadinessEvidence,
} from '@/lib/artifact-data';

function statusVariant(status: DataComponentStatus | 'ready' | 'blocked'): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'ready') return 'default';
  if (status === 'blocked') return 'destructive';
  if (status === 'partial') return 'secondary';
  return 'outline';
}

function exceptionText(values: string[]): string {
  if (!values.length) return 'None';
  const visible = values.slice(0, 3).join(', ');
  return values.length > 3 ? `${visible} +${values.length - 3}` : visible;
}

export function EvidenceDataPage() {
  const bundle = useActiveResearchBundle();
  const manifest = bundle?.manifest;
  const groups = groupArtifacts(manifest?.artifacts ?? []);
  const totalBytes = groups.reduce((sum, group) => sum + group.bytes, 0);
  const [readiness, setReadiness] = useState<DataReadinessEvidence | null>(null);
  const [readinessError, setReadinessError] = useState('');

  useEffect(() => {
    let active = true;
    setReadiness(null);
    setReadinessError('');
    if (!bundle) return () => { active = false; };
    void loadDataReadinessEvidence(bundle)
      .then((value) => { if (active) setReadiness(value); })
      .catch((error: unknown) => { if (active) setReadinessError(error instanceof Error ? error.message : String(error)); });
    return () => { active = false; };
  }, [bundle]);

  if (!bundle || !manifest) {
    return <div className="research-empty-state"><Database className="h-8 w-8 text-muted-foreground" /><h1 className="mt-3 text-xl font-semibold">No evidence bundle is open</h1><p className="mt-2 text-sm text-muted-foreground">Open a bundle from Library to inspect data lineage and readiness.</p></div>;
  }

  const readinessSummary = readiness?.readiness.summary;

  return (
    <div className="research-page space-y-6">
      <header className="research-page-header">
        <div><p className="research-kicker">Evidence / Data</p><h1>Data identity and readiness</h1><p>Inspect the exact data components and training gates used by Alpha Engine before interpreting any model result.</p></div>
        <Badge variant="outline" className="h-7 gap-1.5"><ShieldCheck className="h-3.5 w-3.5" /> {bundle.integrity === 'all_verified' ? 'Fully verified' : 'Core indexes verified'}</Badge>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Evidence cutoff</p><p className="mt-2 font-mono text-xl font-semibold">{readiness?.readiness.evidence_cutoff || manifest.evidence_cutoff || 'Not declared'}</p></CardContent></Card>
        <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Ready components</p><p className="mt-2 font-mono text-xl font-semibold">{readinessSummary ? `${readinessSummary.ready_component_count}/${readinessSummary.component_count}` : 'Not indexed'}</p></CardContent></Card>
        <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Ready training profiles</p><p className="mt-2 font-mono text-xl font-semibold">{readinessSummary?.ready_training_profiles.length ?? 'Not indexed'}</p></CardContent></Card>
        <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Blocked profiles</p><p className="mt-2 font-mono text-xl font-semibold">{readinessSummary?.blocked_training_profiles.length ?? 'Not indexed'}</p></CardContent></Card>
      </section>

      {readinessError && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><AlertTriangle className="h-4 w-4 text-destructive" /> Data readiness index rejected</CardTitle></CardHeader>
          <CardContent><p className="text-sm">{readinessError}</p></CardContent>
        </Card>
      )}

      {!readiness && !readinessError && (
        <Card className="border-dashed"><CardContent className="py-6 text-sm text-muted-foreground">This bundle does not declare model-data readiness indexes. Artifact identity remains visible below, but the frontend will not infer training readiness.</CardContent></Card>
      )}

      {readiness && (
        <section className="space-y-5">
          <Card className="research-surface overflow-hidden">
            <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><Database className="h-4 w-4 text-primary" /> Governed data components</CardTitle></CardHeader>
            <CardContent className="p-0">
              <div className="overflow-auto">
                <Table>
                  <TableHeader><TableRow><TableHead>Component</TableHead><TableHead>Status</TableHead><TableHead>Coverage</TableHead><TableHead>Dates</TableHead><TableHead>Provider</TableHead><TableHead>Exceptions</TableHead></TableRow></TableHeader>
                  <TableBody>{readiness.components.map((component) => {
                    const exceptions = [...component.missing_symbols, ...component.invalid_symbols, ...component.quarantined_symbols];
                    return <TableRow key={component.component_id}>
                      <TableCell><p className="font-mono text-xs">{component.component_id}</p><p className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">{component.market} · {component.component_kind.replace(/_/g, ' ')}</p></TableCell>
                      <TableCell><Badge variant={statusVariant(component.status)} className="text-[9px]">{component.status}</Badge></TableCell>
                      <TableCell><p className="font-mono text-xs">{component.ready_symbol_count}/{component.expected_symbol_count}</p><p className="text-[10px] text-muted-foreground">{(component.coverage_ratio * 100).toFixed(1)}%</p></TableCell>
                      <TableCell className="font-mono text-[10px]"><p>{component.first_date || '—'} → {component.last_date || '—'}</p><p className="mt-1 text-muted-foreground">cutoff {component.evidence_cutoff || '—'}</p></TableCell>
                      <TableCell><p className="text-xs">{component.providers.join(', ') || 'Not declared'}</p>{component.professional_source_ready !== null && <Badge variant={component.professional_source_ready ? 'default' : 'outline'} className="mt-1 text-[9px]">{component.professional_source_ready ? 'Professional ready' : 'Research fallback'}</Badge>}</TableCell>
                      <TableCell className="max-w-[220px] text-xs" title={exceptions.join(', ')}>{exceptionText(exceptions)}</TableCell>
                    </TableRow>;
                  })}</TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>

          <Card className="research-surface overflow-hidden">
            <CardHeader><CardTitle className="flex items-center gap-2 text-sm"><FileCheck2 className="h-4 w-4 text-primary" /> Training readiness profiles</CardTitle></CardHeader>
            <CardContent className="p-0">
              <div className="overflow-auto">
                <Table>
                  <TableHeader><TableRow><TableHead>Profile</TableHead><TableHead>Status</TableHead><TableHead>Pool</TableHead><TableHead>References</TableHead><TableHead>Failed gates</TableHead></TableRow></TableHeader>
                  <TableBody>{readiness.profiles.map((profile) => <TableRow key={profile.profile_id}>
                    <TableCell><p className="font-mono text-xs">{profile.profile_id}</p><p className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">{profile.market} · {profile.candidate_count} candidates</p></TableCell>
                    <TableCell><Badge variant={statusVariant(profile.status)} className="text-[9px]">{profile.status}</Badge></TableCell>
                    <TableCell className="font-mono text-xs">{profile.candidate_pool_id}</TableCell>
                    <TableCell className="text-xs">{profile.references.join(', ') || 'None'}</TableCell>
                    <TableCell className="max-w-[360px] text-xs">{profile.failed_gates.length ? profile.failed_gates.join(' · ') : 'All declared gates passed'}</TableCell>
                  </TableRow>)}</TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </section>
      )}

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
          <CardHeader><CardTitle className="flex items-center justify-between gap-2 text-sm"><span className="flex items-center gap-2"><FileCheck2 className="h-4 w-4 text-primary" /> Artifact classes</span><span className="font-mono text-[10px] text-muted-foreground">{formatBytes(totalBytes)}</span></CardTitle></CardHeader>
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
