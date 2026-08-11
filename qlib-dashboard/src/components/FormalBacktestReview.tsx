import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  BarChart3,
  BookOpenCheck,
  Boxes,
  CalendarDays,
  CheckCircle2,
  FileSearch,
  Loader2,
  ReceiptText,
  ShieldAlert,
} from 'lucide-react';
import { AttributionInterpretation } from '@/components/AttributionInterpretation';
import { HoldingsSummary } from '@/components/HoldingsSummary';
import { PerformanceCharts } from '@/components/PerformanceCharts';
import { PositionsTable } from '@/components/PositionsTable';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { formatEvidenceLabel } from '@/lib/format-evidence-label';
import {
  loadFormalRunEvidence,
  metricById,
  type FormalRunEvidence,
} from '@/lib/formal-run-evidence';
import { governedRunQuery, type GovernedRunSummary } from '@/lib/governed-run';
import type { CanonicalMetricV2 } from '@/lib/model-run-bundle-v2';

const SUMMARY_METRICS = [
  'total_return',
  'benchmark_return',
  'excess_return',
  'max_drawdown',
  'turnover',
  'transaction_cost',
] as const;

const METRIC_LABELS: Record<string, string> = {
  total_return: 'Total return',
  annualized_return: 'Annualized return',
  benchmark_return: 'Benchmark return',
  excess_return: 'Excess return',
  annualized_volatility: 'Annualized volatility',
  sharpe_ratio: 'Sharpe ratio',
  information_ratio: 'Information ratio',
  max_drawdown: 'Max drawdown',
  turnover: 'Turnover',
  transaction_cost: 'Transaction cost',
  ic: 'IC',
  rank_ic: 'Rank IC',
  icir: 'ICIR',
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function formatMetric(metric: CanonicalMetricV2 | null): string {
  if (!metric || metric.availability_status !== 'available' || metric.value === null) return 'Unavailable';
  if (['total_return', 'annualized_return', 'benchmark_return', 'excess_return', 'annualized_volatility', 'max_drawdown', 'transaction_cost'].includes(metric.metric_id)) {
    return `${(metric.value * 100).toFixed(2)}%`;
  }
  if (metric.unit === 'bps') return `${metric.value.toFixed(1)} bps`;
  if (metric.unit === 'count') return metric.value.toLocaleString();
  return metric.value.toFixed(3);
}

function MetricCard({ metricId, metrics }: { metricId: string; metrics: CanonicalMetricV2[] }) {
  const metric = metricById(metrics, metricId);
  const available = metric?.availability_status === 'available' && metric.value !== null;
  return (
    <Card className="min-w-0">
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium text-muted-foreground">{METRIC_LABELS[metricId] || formatEvidenceLabel(metricId)}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className={available ? 'text-xl font-semibold tabular-nums' : 'text-sm font-semibold text-muted-foreground'}>
          {formatMetric(metric)}
        </div>
        <p className="mt-1 line-clamp-2 min-h-8 text-[10px] leading-relaxed text-muted-foreground" title={metric?.unavailable_reason || metric?.scope || ''}>
          {available
            ? `Retained source metric${metric?.sample_count ? ` · ${metric.sample_count.toLocaleString()} observations` : ''}`
            : metric?.unavailable_reason || 'The bundle does not declare this metric.'}
        </p>
      </CardContent>
    </Card>
  );
}

function EmptyEvidence({ title, reason }: { title: string; reason: string }) {
  return (
    <div className="rounded-xl border-2 border-dashed bg-muted/10 p-8 text-center">
      <AlertTriangle className="mx-auto h-7 w-7 text-amber-500" />
      <h3 className="mt-3 font-semibold">{title} unavailable</h3>
      <p className="mx-auto mt-2 max-w-2xl text-sm text-muted-foreground">{reason}</p>
    </div>
  );
}

function formatEvidenceCell(column: string, value: unknown): string {
  if (value === undefined || value === null || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value !== 'number') return String(value);
  if (['execution_price', 'entry_price', 'exit_price', 'price', 'reference_price'].includes(column)) {
    return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  }
  if (column.includes('weight') || column.includes('return') || column === 'transaction_cost' || column === 'normalized_notional') {
    return `${(value * 100).toFixed(2)}%`;
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 5 });
}

function EvidenceTable({
  rows,
  columns,
  maxRows = 200,
}: {
  rows: Array<Record<string, unknown>>;
  columns: string[];
  maxRows?: number;
}) {
  const visible = rows.slice(0, maxRows);
  if (!visible.length) return null;
  return (
    <div className="overflow-x-auto rounded-xl border bg-card">
      <table className="min-w-full border-collapse text-left text-xs">
        <thead>
          <tr className="border-b bg-muted/30">
            {columns.map((column) => <th key={column} className="whitespace-nowrap px-3 py-2.5 font-semibold">{formatEvidenceLabel(column)}</th>)}
          </tr>
        </thead>
        <tbody>
          {visible.map((row, index) => (
            <tr key={`${String(row.date ?? row.instrument ?? row.window ?? index)}-${index}`} className="border-b last:border-0">
              {columns.map((column) => (
                <td key={column} className="max-w-72 whitespace-nowrap px-3 py-2 font-mono">
                  {formatEvidenceCell(column, row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > visible.length && <p className="border-t px-3 py-2 text-[11px] text-muted-foreground">Showing {visible.length} of {rows.length} retained rows.</p>}
    </div>
  );
}

function PerformancePanel({ evidence }: { evidence: FormalRunEvidence }) {
  const semantics = evidence.performance.semantics;
  const cost = typeof semantics.cost === 'object' && semantics.cost !== null && !Array.isArray(semantics.cost)
    ? semantics.cost as Record<string, unknown>
    : {};
  const methodologyRows: Array<[string, unknown]> = [
    ['Signal time', semantics.signal_time],
    ['Execution time', semantics.execution_time ?? semantics.execution_model],
    ['Return measurement', semantics.return_measurement ?? semantics.return_basis],
    ['Price basis', semantics.price_basis],
    ['Holding-end offset', typeof semantics.holding_end_offset_sessions === 'number' ? `${semantics.holding_end_offset_sessions} sessions` : 'not declared'],
    ['Cost rate', typeof cost.rate_bps === 'number' ? `${cost.rate_bps} bps` : typeof semantics.cost_bps === 'number' ? `${semantics.cost_bps} bps` : 'not declared'],
    ['Turnover formula', cost.turnover_formula],
    ['Net return', cost.net_return_formula],
  ];
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4 border-b pb-3">
          <div>
            <CardTitle className="text-sm">Strategy, benchmark and excess path</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">Retained trace only; the browser does not interpolate or recompute missing observations.</p>
          </div>
          <Badge variant="outline" className="shrink-0 font-mono text-[10px]">{formatEvidenceLabel(evidence.performance.traceFrequency)}</Badge>
        </CardHeader>
        <CardContent className="pt-4"><PerformanceCharts report={evidence.performance.report} /></CardContent>
      </Card>
      <Card>
        <CardHeader className="border-b pb-3">
          <CardTitle className="text-sm">Governed performance methodology</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">Read directly from the formal evidence contract; the browser does not supply timing or cost defaults.</p>
        </CardHeader>
        <CardContent className="grid gap-x-6 pt-2 sm:grid-cols-2 lg:grid-cols-3">
          {methodologyRows.map(([label, value]) => (
            <div key={String(label)} className="flex items-start justify-between gap-4 border-b py-2 text-xs">
              <span className="text-muted-foreground">{label}</span>
              <span className="max-w-[60%] break-words text-right font-mono">{String(value || 'not declared')}</span>
            </div>
          ))}
        </CardContent>
      </Card>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {['annualized_return', 'annualized_volatility', 'sharpe_ratio', 'information_ratio'].map((metricId) => (
          <MetricCard key={metricId} metricId={metricId} metrics={evidence.metrics} />
        ))}
      </div>
    </div>
  );
}

function RiskPanel({ evidence }: { evidence: FormalRunEvidence }) {
  const windowColumns = ['window', 'periods', 'positive_periods', 'net_strategy_return', 'qqq_return', 'simple_excess_return', 'max_drawdown', 'turnover', 'transaction_cost'];
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {['max_drawdown', 'annualized_volatility', 'turnover', 'transaction_cost'].map((metricId) => (
          <MetricCard key={metricId} metricId={metricId} metrics={evidence.risk.metrics} />
        ))}
      </div>
      <Card>
        <CardHeader className="border-b pb-3">
          <CardTitle className="text-sm">Retained window robustness</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">Window evidence exposes regime variation, cost drag and negative periods without parameter retuning.</p>
        </CardHeader>
        <CardContent className="pt-4">
          {evidence.robustness.windowSummary.length
            ? <EvidenceTable rows={evidence.robustness.windowSummary} columns={windowColumns} />
            : <EmptyEvidence title="Window robustness" reason={evidence.sectionReasons.robustness || 'No retained window ledger is available.'} />}
        </CardContent>
      </Card>
      {(evidence.risk.interpretationLimit || evidence.robustness.interpretationLimit) && (
        <Card className="border-amber-500/20 bg-amber-500/5">
          <CardContent className="space-y-2 pt-5 text-sm text-muted-foreground">
            {evidence.risk.interpretationLimit && <p><strong className="text-foreground">Risk limit:</strong> {evidence.risk.interpretationLimit}</p>}
            {evidence.robustness.interpretationLimit && <p><strong className="text-foreground">Robustness limit:</strong> {evidence.robustness.interpretationLimit}</p>}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function PortfolioPanel({ evidence }: { evidence: FormalRunEvidence }) {
  const contractRows = Object.entries(evidence.portfolio.contract);
  const latestSignal = evidence.portfolio.latestSignal;
  const rankedTargets = latestSignal && Array.isArray(latestSignal.ranked_targets)
    ? latestSignal.ranked_targets.filter(isRecord)
    : [];
  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <PositionsTable positions={evidence.portfolio.positions} report={evidence.performance.report} />
        <div className="space-y-4">
          <HoldingsSummary positions={evidence.portfolio.positions} />
          <Card>
            <CardHeader className="border-b pb-3"><CardTitle className="text-sm">Frozen portfolio contract</CardTitle></CardHeader>
            <CardContent className="divide-y pt-2">
              {contractRows.map(([key, value]) => (
                <div key={key} className="flex items-start justify-between gap-4 py-2 text-xs">
                  <span className="text-muted-foreground">{formatEvidenceLabel(key)}</span>
                  <span className="max-w-[55%] break-words text-right font-mono">{String(value)}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
      {latestSignal && (
        <Card>
          <CardHeader className="border-b pb-3">
            <CardTitle className="text-sm">Latest retained rebalance signal</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">Signal {String(latestSignal.signal_date ?? '—')} · {latestSignal.holding_end_date ? `holding realized through ${String(latestSignal.holding_end_date)}` : String(latestSignal.signal_state ?? 'outcome pending')} · hash {String(latestSignal.signal_sha256 ?? '').slice(0, 12)}…</p>
          </CardHeader>
          <CardContent className="pt-4">
            <EvidenceTable rows={rankedTargets} columns={['rank', 'instrument', 'sector', 'score', 'target_weight', 'reference_price']} maxRows={20} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function TradesPanel({ evidence }: { evidence: FormalRunEvidence }) {
  const rows = useMemo(
    () => [...evidence.trades].sort((left, right) => String(right.date ?? '').localeCompare(String(left.date ?? ''))),
    [evidence.trades],
  );
  if (!rows.length) return <EmptyEvidence title="Trade ledger" reason={evidence.sectionReasons.trades || String(evidence.diagnostics.completeness.trades || 'No retained transaction ledger is available.')} />;
  const analytics = evidence.tradeAnalytics;
  const analyticsRows: Array<[string, string]> = [
    ['Completed holdings', Number(analytics.episode_count ?? 0).toLocaleString()],
    ['Win rate', typeof analytics.win_rate === 'number' ? `${(analytics.win_rate * 100).toFixed(1)}%` : 'Unavailable'],
    ['Alpha hit rate', typeof analytics.alpha_hit_rate === 'number' ? `${(analytics.alpha_hit_rate * 100).toFixed(1)}%` : 'Unavailable'],
    ['Average winner', typeof analytics.average_winner === 'number' ? `${(analytics.average_winner * 100).toFixed(2)}%` : 'Unavailable'],
    ['Average loser', typeof analytics.average_loser === 'number' ? `${(analytics.average_loser * 100).toFixed(2)}%` : 'Unavailable'],
    ['Profit factor', typeof analytics.profit_factor === 'number' ? analytics.profit_factor.toFixed(2) : 'Unavailable'],
  ];
  return (
    <div className="space-y-4">
      {Object.keys(analytics).length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {analyticsRows.map(([label, value]) => <Card key={label}><CardContent className="pt-4"><p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p><p className="mt-1 text-lg font-semibold tabular-nums">{value}</p></CardContent></Card>)}
        </div>
      )}
      {(evidence.tradeSemantics.price || evidence.tradeSemantics.amount) && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs leading-relaxed text-muted-foreground">
          <p><strong className="text-foreground">Price:</strong> {evidence.tradeSemantics.price}</p>
          <p className="mt-1"><strong className="text-foreground">Amount:</strong> {evidence.tradeSemantics.amount}</p>
        </div>
      )}
      <EvidenceTable rows={rows} columns={['date', 'instrument', 'action', 'execution_price', 'entry_price', 'exit_price', 'previous_weight', 'target_weight', 'normalized_notional', 'amount', 'quantity', 'realized_return', 'profitable', 'transaction_cost', 'holding_end_date', 'window']} />
    </div>
  );
}

function AttributionPanel({ evidence }: { evidence: FormalRunEvidence }) {
  const rows = useMemo(
    () => [...evidence.attribution].sort((left, right) => Math.abs(Number(right.value) || 0) - Math.abs(Number(left.value) || 0)),
    [evidence.attribution],
  );
  const reason = evidence.sectionReasons.attribution || String(evidence.diagnostics.completeness.attribution || 'No retained attribution ledger is available.');
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      {rows.length
        ? <EvidenceTable rows={rows} columns={['instrument', 'name', 'value', 'gross_contribution', 'transaction_cost', 'periods_held', 'win_rate', 'average_rank', 'windows_held']} />
        : <EmptyEvidence title="Attribution" reason={reason} />}
      <AttributionInterpretation
        rows={rows}
        modelKind={evidence.run.modelKind === 'rules_based_allocation' ? 'rules_based_allocation' : 'cross_sectional_ranker'}
        availabilityReason={reason}
      />
    </div>
  );
}

function EvidencePanel({ evidence }: { evidence: FormalRunEvidence }) {
  const declarations = evidence.run.manifest?.sections ?? [];
  const lineageRows = Object.entries(evidence.lineage).filter(([key]) => !['research_only', 'trade_ready'].includes(key));
  const missing = Array.isArray(evidence.diagnostics.completeness.missing)
    ? evidence.diagnostics.completeness.missing.map(String)
    : [];
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="border-b pb-3"><CardTitle className="flex items-center gap-2 text-sm"><BookOpenCheck className="h-4 w-4 text-primary" />Section availability</CardTitle></CardHeader>
          <CardContent className="divide-y pt-2">
            {declarations.map((section) => (
              <div key={section.section_id} className="flex items-start justify-between gap-4 py-2.5 text-xs">
                <div><div className="font-medium">{formatEvidenceLabel(section.section_id)}</div>{section.reason && <div className="mt-1 max-w-md text-muted-foreground">{section.reason}</div>}</div>
                <Badge variant="outline" className={section.availability_status === 'available' ? 'text-emerald-700 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-300'}>{formatEvidenceLabel(section.availability_status)}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="border-b pb-3"><CardTitle className="flex items-center gap-2 text-sm"><FileSearch className="h-4 w-4 text-primary" />Manifest and lineage</CardTitle></CardHeader>
          <CardContent className="divide-y pt-2">
            {lineageRows.map(([key, value]) => (
              <div key={key} className="grid grid-cols-[140px_minmax(0,1fr)] gap-3 py-2 text-xs">
                <span className="text-muted-foreground">{formatEvidenceLabel(key)}</span>
                {isRecord(value) || Array.isArray(value) ? (
                  <details className="min-w-0">
                    <summary className="cursor-pointer font-medium text-primary">
                      View {Array.isArray(value) ? `${value.length} retained items` : `${Object.keys(value).length} retained fields`}
                    </summary>
                    <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted/30 p-2 font-mono text-[10px] leading-relaxed text-foreground">{JSON.stringify(value, null, 2)}</pre>
                  </details>
                ) : <span className="break-all font-mono">{String(value ?? '—')}</span>}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader className="border-b pb-3"><CardTitle className="flex items-center gap-2 text-sm"><ReceiptText className="h-4 w-4 text-primary" />Interpretation and missing evidence</CardTitle></CardHeader>
        <CardContent className="space-y-3 pt-4 text-sm text-muted-foreground">
          {evidence.diagnostics.interpretationNotes.map((note) => <p key={note}>• {note}</p>)}
          {missing.length > 0 && <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3"><strong className="text-foreground">Missing retained evidence:</strong> {missing.map(formatEvidenceLabel).join(', ')}</div>}
        </CardContent>
      </Card>
    </div>
  );
}

export function FormalBacktestReview({ run }: { run: GovernedRunSummary }) {
  const [state, setState] = useState<{ loading: boolean; value: FormalRunEvidence | null; error: string | null }>({ loading: true, value: null, error: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, value: null, error: null });
    void loadFormalRunEvidence(run).then(
      (value) => { if (active) setState({ loading: false, value, error: null }); },
      (error) => { if (active) setState({ loading: false, value: null, error: error instanceof Error ? error.message : String(error) }); },
    );
    return () => { active = false; };
  }, [run.key]);

  if (state.loading) {
    return <div className="flex min-h-[420px] items-center justify-center rounded-xl border bg-card"><Loader2 className="mr-2 h-5 w-5 animate-spin text-primary" />Loading verified governed evidence…</div>;
  }
  if (state.error || !state.value) {
    return <EmptyEvidence title="Governed backtest" reason={state.error || 'The governed evidence loader returned no review data.'} />;
  }

  const evidence = state.value;
  const complete = String(evidence.diagnostics.completeness.status) === 'complete';
  return (
    <div className="space-y-5" data-testid="formal-backtest-review">
      <section className="flex flex-col gap-4 border-b pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={run.channel === 'formal' ? 'bg-emerald-600 text-white hover:bg-emerald-600' : 'bg-blue-600 text-white hover:bg-blue-600'}>{run.channel === 'formal' ? 'Accepted formal baseline' : 'Active research preview'}</Badge>
            <Badge variant="outline" className={complete ? 'text-emerald-700 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-300'}>{complete ? 'Complete retained evidence' : 'Partial retained evidence'}</Badge>
            <Badge variant="outline" className="text-amber-700 dark:text-amber-300">Research only · read only</Badge>
          </div>
          <h2 className="mt-3 text-2xl font-black tracking-tight">{run.title}</h2>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span className="flex items-center gap-1"><CalendarDays className="h-3.5 w-3.5" />{evidence.performance.dateRange.start} → {evidence.performance.dateRange.end}</span>
            <span>{run.market.toUpperCase()} · benchmark {evidence.performance.benchmark}</span>
            <span>Cutoff {run.evidenceCutoff}</span>
            <span className="font-mono">{run.runId}</span>
          </div>
        </div>
        <div className="flex flex-col items-stretch gap-2 sm:items-end">
          <div className="rounded-lg border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
            Bundle identity verified · {run.bundleId?.slice(0, 12)}…
          </div>
          <Button asChild variant="outline" size="sm" className="gap-2">
            <Link to={`/decisions?${governedRunQuery(run)}`}><ShieldAlert className="h-3.5 w-3.5" />Open decision receipt</Link>
          </Button>
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" aria-label="Formal backtest headline metrics">
        {SUMMARY_METRICS.map((metricId) => <MetricCard key={metricId} metricId={metricId} metrics={evidence.metrics} />)}
      </section>

      <Tabs defaultValue="performance" className="w-full">
        <TabsList className="mb-4 flex h-auto w-full max-w-full justify-start gap-1 overflow-x-auto p-1" aria-label="Formal backtest evidence views">
          <TabsTrigger value="performance" className="shrink-0 gap-1.5"><BarChart3 className="h-3.5 w-3.5" />Performance</TabsTrigger>
          <TabsTrigger value="risk" className="shrink-0 gap-1.5"><ShieldAlert className="h-3.5 w-3.5" />Risk & robustness</TabsTrigger>
          <TabsTrigger value="portfolio" className="shrink-0 gap-1.5"><Boxes className="h-3.5 w-3.5" />Portfolio</TabsTrigger>
          <TabsTrigger value="trades" className="shrink-0 gap-1.5"><ReceiptText className="h-3.5 w-3.5" />Trades</TabsTrigger>
          <TabsTrigger value="attribution" className="shrink-0 gap-1.5"><CheckCircle2 className="h-3.5 w-3.5" />Attribution</TabsTrigger>
          <TabsTrigger value="evidence" className="shrink-0 gap-1.5"><FileSearch className="h-3.5 w-3.5" />Evidence boundary</TabsTrigger>
        </TabsList>
        <TabsContent value="performance"><PerformancePanel evidence={evidence} /></TabsContent>
        <TabsContent value="risk"><RiskPanel evidence={evidence} /></TabsContent>
        <TabsContent value="portfolio"><PortfolioPanel evidence={evidence} /></TabsContent>
        <TabsContent value="trades"><TradesPanel evidence={evidence} /></TabsContent>
        <TabsContent value="attribution"><AttributionPanel evidence={evidence} /></TabsContent>
        <TabsContent value="evidence"><EvidencePanel evidence={evidence} /></TabsContent>
      </Tabs>
    </div>
  );
}
