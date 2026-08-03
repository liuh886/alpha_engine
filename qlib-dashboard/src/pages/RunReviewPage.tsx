import { AlertTriangle, Archive, BadgeCheck, CircleSlash2, FileCheck2 } from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import { Dashboard } from '@/components/Dashboard';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

function StatusPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="rounded-xl border bg-card p-5 shadow-sm"><h3 className="text-sm font-semibold">{title}</h3><div className="mt-3">{children}</div></section>;
}

export function RunReviewPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const run = workspace.activeRun;

  if (!run) {
    return <div className="rounded-xl border-2 border-dashed p-12 text-center text-sm text-muted-foreground">Select a governed run from Runs.</div>;
  }

  if (run.modelData?.backtest) {
    return (
      <div className="space-y-4">
        <section className="flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-sm md:flex-row md:items-center md:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full border px-2 py-1 text-[10px] font-bold uppercase">{run.channel}</span>
              <span className="text-xs text-muted-foreground">{run.publicationStatus.replaceAll('_', ' ')}</span>
            </div>
            <h2 className="mt-2 text-xl font-semibold">{run.title}</h2>
            <p className="mt-1 text-xs text-muted-foreground">Run {run.runId} · evidence cutoff {run.evidenceCutoff}</p>
          </div>
          <div className="text-xs text-muted-foreground">Research evidence only · not trade ready</div>
        </section>
        {run.loadWarnings.length > 0 && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-muted-foreground">
            {run.loadWarnings.join(' ')}
          </div>
        )}
        <Dashboard
          data={run.modelData.backtest}
          params={{ ...run.modelData.params, id: run.modelData.run_id || run.modelData.id }}
        />
      </div>
    );
  }

  const sections = run.manifest?.sections ?? [];
  return (
    <div className="mx-auto max-w-[1400px] space-y-5">
      <section className="rounded-xl border bg-card p-6 shadow-sm">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-1 font-bold uppercase text-amber-700 dark:text-amber-300">{run.channel}</span>
              <span className="text-muted-foreground">{run.publicationStatus.replaceAll('_', ' ')}</span>
            </div>
            <h2 className="mt-3 text-2xl font-semibold">{run.title}</h2>
            <p className="mt-1 break-all text-sm text-muted-foreground">{run.modelFamilyId} / {run.modelVersionId} / {run.runId}</p>
          </div>
          <dl className="grid grid-cols-2 gap-4 rounded-lg border bg-muted/20 p-4 text-xs">
            <div><dt className="text-muted-foreground">Market</dt><dd className="mt-1 font-semibold">{run.market}</dd></div>
            <div><dt className="text-muted-foreground">Cutoff</dt><dd className="mt-1 font-semibold">{run.evidenceCutoff}</dd></div>
            <div><dt className="text-muted-foreground">Evidence</dt><dd className="mt-1 font-semibold">{run.evidenceStatus}</dd></div>
            <div><dt className="text-muted-foreground">Decision</dt><dd className="mt-1 font-semibold">{run.decisionStatus.replaceAll('_', ' ')}</dd></div>
          </dl>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        <StatusPanel title="Authoritative summary">
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/40 p-3 text-xs">{JSON.stringify(run.summary, null, 2)}</pre>
        </StatusPanel>
        <StatusPanel title="Declared evidence sections">
          <div className="space-y-2 text-xs">
            {sections.map((section) => (
              <div key={section.section_id} className="flex items-start justify-between gap-3 rounded-lg border p-3">
                <div className="flex min-w-0 items-start gap-2">
                  {section.availability_status === 'available' ? <FileCheck2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" /> : section.required_for_model_kind ? <CircleSlash2 className="mt-0.5 h-4 w-4 shrink-0 text-red-500" /> : <Archive className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />}
                  <div><div className="font-semibold">{section.section_id}</div><div className="mt-0.5 text-muted-foreground">{section.reason || section.availability_status.replaceAll('_', ' ')}</div></div>
                </div>
                <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px]">{section.required_for_model_kind ? 'required' : 'optional'}</span>
              </div>
            ))}
          </div>
        </StatusPanel>
        <StatusPanel title="Boundary and lineage">
          <div className="space-y-3 text-xs text-muted-foreground">
            <p className="flex items-start gap-2"><BadgeCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />Manifest and summary hashes were verified before this run entered the workspace.</p>
            <p className="flex items-start gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />Heavy sections remain unloaded until their review surface requests them.</p>
            <p>Bundle ID: <span className="break-all font-mono text-foreground">{run.bundleId}</span></p>
            {run.loadWarnings.map((warning) => <p key={warning}>{warning}</p>)}
          </div>
        </StatusPanel>
      </div>
    </div>
  );
}
