import { useEffect, useState } from 'react';
import { AlertTriangle, BarChart3, Boxes, CheckCircle2, Gauge, Layers3, Loader2, ShieldAlert } from 'lucide-react';
import { PerformanceCharts } from '@/components/PerformanceCharts';
import { formatEvidenceLabel } from '@/lib/format-evidence-label';
import { loadRunSection, type GovernedRunSummary } from '@/lib/governed-run';
import type { ReportRow } from '@/lib/types';
import { cn } from '@/lib/utils';

type ReviewTab = 'summary' | 'alpha' | 'risk' | 'robustness' | 'portfolio';

interface SectionState {
  loading: boolean;
  value: unknown;
  error: string | null;
}

const TABS: Array<{ id: ReviewTab; label: string; icon: typeof BarChart3 }> = [
  { id: 'summary', label: 'Summary', icon: CheckCircle2 },
  { id: 'alpha', label: 'Alpha', icon: BarChart3 },
  { id: 'risk', label: 'Risk', icon: ShieldAlert },
  { id: 'robustness', label: 'Robustness', icon: Gauge },
  { id: 'portfolio', label: 'Portfolio', icon: Boxes },
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function asEvidenceRows(rows: unknown[]): Array<Record<string, unknown>> {
  return rows.filter(isRecord);
}

function formatNumber(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value ?? 'not retained');
  if (Math.abs(numeric) <= 2) return `${(numeric * 100).toFixed(2)}%`;
  return numeric.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function SourceNote({ source, scope, computation }: { source: string; scope: string; computation?: string }) {
  return (
    <div className="mt-3 rounded-md border bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
      <span className="font-semibold text-foreground">Source:</span> {source} · <span className="font-semibold text-foreground">Scope:</span> {scope}
      {computation ? <> · <span className="font-semibold text-foreground">Computation:</span> {computation}</> : null}
    </div>
  );
}

function Unavailable({ title, reason }: { title: string; reason: string }) {
  return (
    <div className="rounded-xl border-2 border-dashed p-8 text-center">
      <AlertTriangle className="mx-auto h-7 w-7 text-amber-500" />
      <h3 className="mt-3 font-semibold">{title} unavailable</h3>
      <p className="mx-auto mt-2 max-w-2xl text-sm text-muted-foreground">{reason}</p>
    </div>
  );
}

function MetricGrid({ metrics, source, scope }: { metrics: Record<string, unknown>; source: string; scope: string }) {
  const rows = Object.entries(metrics);
  if (!rows.length) return <Unavailable title="Metrics" reason="The source declares no retained metrics for this scope." />;
  return (
    <section className="rounded-xl border bg-card p-5 shadow-sm">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {rows.map(([key, value]) => (
          <div key={key} className="rounded-lg border bg-muted/20 p-3">
            <div className="text-[11px] text-muted-foreground">{key}</div>
            <div className="mt-1 text-lg font-semibold">{formatNumber(value)}</div>
          </div>
        ))}
      </div>
      <SourceNote source={source} scope={scope} computation="Values are displayed as retained; no browser estimator is substituted." />
    </section>
  );
}

function EvidenceTable({ rows, source, scope, maxRows = 200 }: { rows: Array<Record<string, unknown>>; source: string; scope: string; maxRows?: number }) {
  if (!rows.length) return <Unavailable title="Evidence table" reason="No retained rows are available for this evidence scope." />;
  const visible = rows.slice(0, maxRows);
  const columns = Array.from(new Set(visible.flatMap((row) => Object.keys(row)))).slice(0, 10);
  return (
    <section className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="overflow-auto">
        <table className="min-w-full border-collapse text-left text-xs">
          <thead><tr className="border-b bg-muted/30">{columns.map((column) => <th key={column} className="whitespace-nowrap px-3 py-2 font-semibold">{formatEvidenceLabel(column)}</th>)}</tr></thead>
          <tbody>
            {visible.map((row, index) => (
              <tr key={`${index}-${String(row.date ?? row.instrument ?? '')}`} className="border-b last:border-0">
                {columns.map((column) => <td key={column} className="max-w-64 whitespace-nowrap px-3 py-2 font-mono">{typeof row[column] === 'number' ? formatNumber(row[column]) : String(row[column] ?? '—')}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > visible.length && <p className="mt-2 text-[11px] text-muted-foreground">Showing {visible.length} of {rows.length} retained rows.</p>}
      <SourceNote source={source} scope={scope} computation="Tabular alternative mirrors retained rows without inferred fields." />
    </section>
  );
}

function JsonEvidence({ value, source, scope }: { value: unknown; source: string; scope: string }) {
  if (Array.isArray(value) && value.every(isRecord)) return <EvidenceTable rows={value} source={source} scope={scope} />;
  if (isRecord(value)) {
    const metrics = value.metrics;
    const other = Object.fromEntries(Object.entries(value).filter(([key]) => key !== 'metrics'));
    return (
      <div className="space-y-4">
        {isRecord(metrics) && <MetricGrid metrics={metrics} source={`${source}#metrics`} scope={scope} />}
        {Object.keys(other).length > 0 && (
          <section className="rounded-xl border bg-card p-4 shadow-sm">
            <pre className="max-h-[560px] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/30 p-4 text-xs">{JSON.stringify(other, null, 2)}</pre>
            <SourceNote source={source} scope={scope} computation="Structured source payload; no narrative inference." />
          </section>
        )}
      </div>
    );
  }
  return <Unavailable title={scope} reason="The declared section did not contain an object or tabular JSON payload." />;
}

function useLazyRunSection(run: GovernedRunSummary, sectionId: string, enabled: boolean): SectionState {
  const [state, setState] = useState<SectionState>({ loading: false, value: null, error: null });
  useEffect(() => {
    let active = true;
    if (!enabled || !run.manifest) {
      setState({ loading: false, value: null, error: null });
      return () => { active = false; };
    }
    const declaration = run.manifest.sections.find((section) => section.section_id === sectionId);
    if (!declaration || declaration.availability_status !== 'available') {
      setState({ loading: false, value: null, error: declaration?.reason || `${sectionId} is not declared as available.` });
      return () => { active = false; };
    }
    setState({ loading: true, value: null, error: null });
    void loadRunSection(run, sectionId).then(
      (value) => { if (active) setState({ loading: false, value, error: null }); },
      (error) => { if (active) setState({ loading: false, value: null, error: error instanceof Error ? error.message : String(error) }); },
    );
    return () => { active = false; };
  }, [enabled, run, sectionId]);
  return state;
}

function drawdownStats(report: ReportRow[]): { depth: number; duration: number } | null {
  if (!report.length) return null;
  let peak = Number(report[0].account);
  let depth = 0;
  let duration = 0;
  let current = 0;
  for (const row of report) {
    const value = Number(row.account);
    if (!Number.isFinite(value) || value <= 0) continue;
    if (value >= peak) {
      peak = value;
      current = 0;
    } else {
      current += 1;
      duration = Math.max(duration, current);
      depth = Math.min(depth, value / peak - 1);
    }
  }
  return { depth, duration };
}

function formalMetricSubset(run: GovernedRunSummary, matcher: RegExp): Record<string, unknown> {
  const metrics = run.formalPackage?.metrics ?? {};
  return Object.fromEntries(Object.entries(metrics).filter(([key]) => matcher.test(key)));
}

function SummaryEvidence({ run }: { run: GovernedRunSummary }) {
  const source = run.formalPackage ? 'formal v1 package identity and retained metrics' : `${run.manifestPath ?? 'manifest.json'} + summary.json`;
  return (
    <div className="space-y-4">
      <section className="rounded-xl border bg-card p-5 shadow-sm">
        <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div><dt className="text-xs text-muted-foreground">Family</dt><dd className="mt-1 break-all font-semibold">{run.modelFamilyId}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Version</dt><dd className="mt-1 break-all font-semibold">{run.modelVersionId}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Run</dt><dd className="mt-1 break-all font-semibold">{run.runId}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Cutoff</dt><dd className="mt-1 font-semibold">{run.evidenceCutoff}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Channel</dt><dd className="mt-1 font-semibold uppercase">{run.channel}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Publication</dt><dd className="mt-1 font-semibold">{formatEvidenceLabel(run.publicationStatus)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Evidence</dt><dd className="mt-1 font-semibold">{run.evidenceStatus}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Trace</dt><dd className="mt-1 font-semibold">{run.formalPackage?.trace_frequency || run.manifest?.comparability_key.trace_frequency || 'not declared'}</dd></div>
        </dl>
        <SourceNote source={source} scope="run identity, cutoff and authoritative boundary" />
      </section>
      {run.formalPackage
        ? <MetricGrid metrics={run.formalPackage.metrics} source="formalPackage.metrics" scope="accepted formal package" />
        : <JsonEvidence value={run.summary} source="summary.json" scope="manifest-bound summary" />}
    </div>
  );
}

function AlphaEvidence({ run, section }: { run: GovernedRunSummary; section: SectionState }) {
  if (run.formalPackage) {
    if (!run.formalPackage.report.length) return <Unavailable title="Alpha" reason="The formal package does not retain a performance path." />;
    return (
      <div className="space-y-4">
        <section className="rounded-xl border bg-card p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between gap-3"><h3 className="font-semibold">Strategy, benchmark and excess paths</h3><span className="text-xs text-muted-foreground">Trace: {run.formalPackage.trace_frequency}</span></div>
          <PerformanceCharts report={run.formalPackage.report} />
          <SourceNote source="formalPackage.report" scope={`${run.formalPackage.date_range.start} to ${run.formalPackage.date_range.end}`} computation="Existing formal chart normalizes retained account and benchmark paths; rolling evidence is not added when frequency is insufficient." />
        </section>
        <EvidenceTable rows={asEvidenceRows(run.formalPackage.report)} source="formalPackage.report" scope="accessible performance-path alternative" />
      </div>
    );
  }
  if (section.loading) return <LoadingSection label="Alpha" />;
  if (section.error) return <Unavailable title="Alpha" reason={section.error} />;
  return <JsonEvidence value={section.value} source="performance.json" scope="declared alpha evidence" />;
}

function RiskEvidence({ run, section }: { run: GovernedRunSummary; section: SectionState }) {
  if (run.formalPackage) {
    const drawdown = drawdownStats(run.formalPackage.report);
    const maxWeight = run.formalPackage.positions.reduce((maximum, row) => Math.max(maximum, Number(row.weight) || 0), 0);
    const metrics: Record<string, unknown> = {
      ...(drawdown ? { 'Drawdown depth': drawdown.depth, 'Drawdown duration (retained observations)': drawdown.duration } : {}),
      'Maximum retained position weight': maxWeight,
      ...formalMetricSubset(run, /drawdown|turnover|transaction cost|volatil|risk/i),
    };
    return (
      <div className="space-y-4">
        <MetricGrid metrics={metrics} source="formalPackage.report, positions and metrics" scope="retained formal risk evidence" />
        <Unavailable title="Declared tail evidence" reason="The formal v1 source does not retain a separate tail-risk section. No tail statistic is reconstructed in the browser." />
      </div>
    );
  }
  if (section.loading) return <LoadingSection label="Risk" />;
  if (section.error) return <Unavailable title="Risk" reason={section.error} />;
  return <JsonEvidence value={section.value} source="risk.json" scope="declared risk evidence" />;
}

function RobustnessEvidence({ run, section }: { run: GovernedRunSummary; section: SectionState }) {
  if (run.formalPackage) {
    return (
      <div className="space-y-4">
        <EvidenceTable rows={asEvidenceRows(run.formalPackage.window_summary)} source="formalPackage.window_summary" scope="walk-forward/window evidence" />
        <div className="grid gap-4 md:grid-cols-2">
          <Unavailable title="Cost sensitivity" reason="A separate cost-sensitivity grid is not retained in this formal v1 package." />
          <Unavailable title="Failure and regime ledger" reason="No distinct failure/regime section is retained; window rows remain visible without inferred regime labels." />
        </div>
      </div>
    );
  }
  if (section.loading) return <LoadingSection label="Robustness" />;
  if (section.error) return <Unavailable title="Robustness" reason={section.error} />;
  return <JsonEvidence value={section.value} source="robustness.json" scope="declared robustness evidence" />;
}

function PortfolioEvidence({ run, portfolio, trades, attribution }: { run: GovernedRunSummary; portfolio: SectionState; trades: SectionState; attribution: SectionState }) {
  if (run.formalPackage) {
    const kindMetrics = run.modelKind === 'cross_sectional_ranker'
      ? formalMetricSubset(run, /\bic\b|rank ic|spread|decay|exposure/i)
      : formalMetricSubset(run, /state|transition|allocation|turnover|transaction cost/i);
    return (
      <div className="space-y-4">
        <MetricGrid metrics={kindMetrics} source="formalPackage.metrics" scope={`${formatEvidenceLabel(run.modelKind)} capability evidence`} />
        <EvidenceTable rows={asEvidenceRows(run.formalPackage.positions)} source="formalPackage.positions" scope="retained holdings and concentration" />
        {run.formalPackage.trades.length
          ? <EvidenceTable rows={asEvidenceRows(run.formalPackage.trades)} source="formalPackage.trades" scope="signal/execution changes and retained cost drag" />
          : <Unavailable title="Trade ledger" reason={String(run.formalPackage.evidence_completeness.trades || 'The formal source did not retain a transaction ledger.')} />}
        {run.formalPackage.attribution.length
          ? <EvidenceTable rows={asEvidenceRows(run.formalPackage.attribution)} source="formalPackage.attribution" scope="retained contribution evidence" />
          : <Unavailable title="Attribution" reason={String(run.formalPackage.evidence_completeness.attribution || 'The formal source did not retain contribution rows.')} />}
        {run.modelKind === 'cross_sectional_ranker' && <Unavailable title="Decay and cross-sectional exposure" reason="Only retained ranker metrics are shown; missing decay/exposure evidence is not reconstructed." />}
      </div>
    );
  }
  const states = [portfolio, trades, attribution];
  if (states.some((state) => state.loading)) return <LoadingSection label="Portfolio" />;
  return (
    <div className="space-y-4">
      {portfolio.error ? <Unavailable title="Portfolio" reason={portfolio.error} /> : <JsonEvidence value={portfolio.value} source="portfolio.json" scope="declared holdings and concentration" />}
      {trades.error ? <Unavailable title="Trades" reason={trades.error} /> : <JsonEvidence value={trades.value} source="trades.json" scope="declared signal/execution and cost evidence" />}
      {attribution.error ? <Unavailable title="Attribution" reason={attribution.error} /> : <JsonEvidence value={attribution.value} source="attribution.json" scope="declared contribution evidence" />}
    </div>
  );
}

function LoadingSection({ label }: { label: string }) {
  return <div className="flex min-h-52 items-center justify-center rounded-xl border"><Loader2 className="mr-2 h-5 w-5 animate-spin" />Loading verified {label.toLowerCase()} section…</div>;
}

export function RunCapabilityReview({ run }: { run: GovernedRunSummary }) {
  const [tab, setTab] = useState<ReviewTab>('summary');
  const performance = useLazyRunSection(run, 'performance', tab === 'alpha');
  const risk = useLazyRunSection(run, 'risk', tab === 'risk');
  const robustness = useLazyRunSection(run, 'robustness', tab === 'robustness');
  const portfolio = useLazyRunSection(run, 'portfolio', tab === 'portfolio');
  const trades = useLazyRunSection(run, 'trades', tab === 'portfolio');
  const attribution = useLazyRunSection(run, 'attribution', tab === 'portfolio');

  return (
    <div className="space-y-5">
      <section className="rounded-xl border bg-card p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2 text-xs"><span className="rounded-full border px-2 py-1 font-bold uppercase">{run.channel}</span><span className="text-muted-foreground">{formatEvidenceLabel(run.publicationStatus)}</span></div>
            <h2 className="mt-2 text-2xl font-semibold">{run.title}</h2>
            <p className="mt-1 break-all text-xs text-muted-foreground">{run.modelFamilyId} / {run.modelVersionId} / {run.runId}</p>
          </div>
          <div className="flex items-center gap-2 rounded-lg border bg-muted/20 px-3 py-2 text-xs"><Layers3 className="h-4 w-4 text-primary" />{formatEvidenceLabel(run.modelKind)} · {run.evidenceStatus} evidence</div>
        </div>
      </section>

      <div className="flex gap-1 overflow-x-auto rounded-lg border bg-card p-1" role="tablist" aria-label="Run capability evidence">
        {TABS.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} onClick={() => setTab(item.id)} className={cn('flex min-w-max items-center gap-2 rounded-md px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary', tab === item.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted')}>
              <Icon className="h-4 w-4" />{item.label}
            </button>
          );
        })}
      </div>

      <div role="tabpanel">
        {tab === 'summary' && <SummaryEvidence run={run} />}
        {tab === 'alpha' && <AlphaEvidence run={run} section={performance} />}
        {tab === 'risk' && <RiskEvidence run={run} section={risk} />}
        {tab === 'robustness' && <RobustnessEvidence run={run} section={robustness} />}
        {tab === 'portfolio' && <PortfolioEvidence run={run} portfolio={portfolio} trades={trades} attribution={attribution} />}
      </div>
    </div>
  );
}
