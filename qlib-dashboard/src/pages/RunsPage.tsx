import { useMemo, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import { AlertTriangle, ArrowRight, CheckCircle2, CircleSlash2, Filter, Search } from 'lucide-react';
import { formatEvidenceLabel } from '@/lib/format-evidence-label';
import { governedRunQuery, type GovernedRunSummary } from '@/lib/governed-run';
import type { RunWorkspaceContext } from '@/lib/run-workspace';
import { cn } from '@/lib/utils';

const ANY = 'all';

function unique(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean))).sort();
}

function SelectFilter(props: { label: string; value: string; values: string[]; onChange: (value: string) => void }) {
  return (
    <label className="space-y-1 text-xs font-medium text-muted-foreground">
      <span>{props.label}</span>
      <select
        className="h-9 w-full rounded-md border bg-background px-2 text-sm text-foreground"
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
      >
        <option value={ANY}>All</option>
        {props.values.map((value) => <option key={value} value={value}>{value}</option>)}
      </select>
    </label>
  );
}

function channelClasses(run: GovernedRunSummary): string {
  if (run.channel === 'formal') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300';
  if (run.channel === 'preview') return 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300';
  return 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300';
}

function EvidenceIcon({ status }: { status: GovernedRunSummary['evidenceStatus'] }) {
  if (status === 'complete') return <CheckCircle2 className="h-4 w-4" aria-label="Complete evidence" />;
  if (status === 'blocked') return <CircleSlash2 className="h-4 w-4" aria-label="Blocked evidence" />;
  return <AlertTriangle className="h-4 w-4" aria-label="Partial evidence" />;
}

export function RunsPage() {
  const workspace = useOutletContext<RunWorkspaceContext>();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [family, setFamily] = useState(ANY);
  const [version, setVersion] = useState(ANY);
  const [market, setMarket] = useState(ANY);
  const [channel, setChannel] = useState(ANY);
  const [publicationStatus, setPublicationStatus] = useState(ANY);
  const [evidenceStatus, setEvidenceStatus] = useState(ANY);
  const [decisionStatus, setDecisionStatus] = useState(ANY);
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return workspace.runs.filter((run) => {
      if (needle && ![run.title, run.modelFamilyId, run.modelVersionId, run.runId, run.market]
        .some((value) => value.toLowerCase().includes(needle))) return false;
      if (family !== ANY && run.modelFamilyId !== family) return false;
      if (version !== ANY && run.modelVersionId !== version) return false;
      if (market !== ANY && run.market !== market) return false;
      if (channel !== ANY && run.channel !== channel) return false;
      if (publicationStatus !== ANY && run.publicationStatus !== publicationStatus) return false;
      if (evidenceStatus !== ANY && run.evidenceStatus !== evidenceStatus) return false;
      if (decisionStatus !== ANY && run.decisionStatus !== decisionStatus) return false;
      if (fromDate && run.evidenceCutoff < fromDate) return false;
      if (toDate && run.evidenceCutoff > toDate) return false;
      return true;
    });
  }, [workspace.runs, query, family, version, market, channel, publicationStatus, evidenceStatus, decisionStatus, fromDate, toDate]);

  const openRun = (run: GovernedRunSummary) => {
    workspace.selectRun(run);
    navigate(`/review?${governedRunQuery(run)}`);
  };

  return (
    <div className="mx-auto max-w-[1500px] space-y-6">
      <section className="rounded-xl border bg-card p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Governed iteration catalog</p>
            <h2 className="mt-1 text-2xl font-semibold">Runs</h2>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              Formal baselines, CI-validated previews and local research bundles share one evidence contract. Channel and publication status remain explicit and never imply trade readiness.
            </p>
          </div>
          <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm">
            <div className="font-semibold">{filtered.length} visible / {workspace.runs.length} indexed</div>
            <div className="mt-1 text-xs text-muted-foreground">Summary-first loading · heavy sections on demand</div>
          </div>
        </div>
      </section>

      {workspace.runLoadErrors.length > 0 && (
        <section className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm">
          <div className="flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" />Some preview records failed closed</div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">
            {workspace.runLoadErrors.map((error) => <li key={error}>{error}</li>)}
          </ul>
        </section>
      )}

      <section className="rounded-xl border bg-card p-4 shadow-sm">
        <div className="mb-4 flex items-center gap-2 text-sm font-semibold"><Filter className="h-4 w-4" />Run filters</div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
          <label className="space-y-1 text-xs font-medium text-muted-foreground sm:col-span-2">
            <span>Search</span>
            <div className="flex h-9 items-center gap-2 rounded-md border bg-background px-2">
              <Search className="h-4 w-4" />
              <input className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Family, version, run or market" />
            </div>
          </label>
          <SelectFilter label="Family" value={family} values={unique(workspace.runs.map((run) => run.modelFamilyId))} onChange={setFamily} />
          <SelectFilter label="Version" value={version} values={unique(workspace.runs.map((run) => run.modelVersionId))} onChange={setVersion} />
          <SelectFilter label="Market" value={market} values={unique(workspace.runs.map((run) => run.market))} onChange={setMarket} />
          <SelectFilter label="Channel" value={channel} values={unique(workspace.runs.map((run) => run.channel))} onChange={setChannel} />
          <SelectFilter label="Publication" value={publicationStatus} values={unique(workspace.runs.map((run) => run.publicationStatus))} onChange={setPublicationStatus} />
          <SelectFilter label="Evidence" value={evidenceStatus} values={unique(workspace.runs.map((run) => run.evidenceStatus))} onChange={setEvidenceStatus} />
          <SelectFilter label="Decision" value={decisionStatus} values={unique(workspace.runs.map((run) => run.decisionStatus))} onChange={setDecisionStatus} />
          <label className="space-y-1 text-xs font-medium text-muted-foreground"><span>Cutoff from</span><input type="date" className="h-9 w-full rounded-md border bg-background px-2 text-sm text-foreground" value={fromDate} onChange={(event) => setFromDate(event.target.value)} /></label>
          <label className="space-y-1 text-xs font-medium text-muted-foreground"><span>Cutoff to</span><input type="date" className="h-9 w-full rounded-md border bg-background px-2 text-sm text-foreground" value={toDate} onChange={(event) => setToDate(event.target.value)} /></label>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Governed model runs">
        {filtered.map((run) => (
          <button
            key={run.key}
            type="button"
            onClick={() => openRun(run)}
            className={cn(
              'group flex min-h-56 flex-col rounded-xl border bg-card p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
              run.key === workspace.activeRunKey && 'border-primary ring-1 ring-primary/30',
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <span className={cn('rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide', channelClasses(run))}>{run.channel}</span>
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><EvidenceIcon status={run.evidenceStatus} />{run.evidenceStatus}</span>
            </div>
            <h3 className="mt-4 text-lg font-semibold leading-tight">{run.title}</h3>
            <p className="mt-1 break-all text-xs text-muted-foreground">{run.modelFamilyId} / {run.modelVersionId}</p>
            <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <div><dt className="text-muted-foreground">Market</dt><dd className="mt-0.5 font-medium">{run.market}</dd></div>
              <div><dt className="text-muted-foreground">Cutoff</dt><dd className="mt-0.5 font-medium">{run.evidenceCutoff || 'not declared'}</dd></div>
              <div><dt className="text-muted-foreground">Kind</dt><dd className="mt-0.5 font-medium">{formatEvidenceLabel(run.modelKind)}</dd></div>
              <div><dt className="text-muted-foreground">Verdict</dt><dd className="mt-0.5 font-medium">{formatEvidenceLabel(run.decisionStatus)}</dd></div>
            </dl>
            <div className="mt-auto flex items-center justify-between border-t pt-4 text-xs">
              <span className="truncate text-muted-foreground">{formatEvidenceLabel(run.publicationStatus)}</span>
              <span className="flex items-center gap-1 font-semibold text-primary">Review <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" /></span>
            </div>
          </button>
        ))}
      </section>

      {filtered.length === 0 && (
        <div className="rounded-xl border-2 border-dashed p-12 text-center text-sm text-muted-foreground">No governed runs match the current filters.</div>
      )}
    </div>
  );
}
