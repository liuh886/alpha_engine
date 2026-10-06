import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useOutletContext } from 'react-router-dom';
import { AlertTriangle, Check, GitCompareArrows, LineChart as LineChartIcon, Scale } from 'lucide-react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ModelData } from '@/lib/data-parser';
import { evidenceAvailabilityLabel, formatDeclaredValue } from '@/lib/evidence-availability';
import type { FormalMetricProjection } from '@/lib/formal-evidence';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { RiskReturnMap } from '@/components/RiskReturnMap';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { loadRunSection, type GovernedRunSummary } from '@/lib/governed-run';
import { parseCanonicalMetricV2 } from '@/lib/model-run-bundle-v2';
import type { RunWorkspaceContext } from '@/lib/run-workspace';

const MAX_COMPARE = 5;
const CHART_COLORS = ['hsl(var(--primary))', '#f59e0b', '#0ea5e9', '#8b5cf6', '#ec4899'];

const METRICS: Array<{ aliases: string[]; label: string; format: 'pct' | 'number'; higherIsBetter: boolean }> = [
  { aliases: ['Compounded Relative Excess Return', 'Excess Return'], label: 'Excess return', format: 'pct', higherIsBetter: true },
  { aliases: ['Annualized Return', 'CAGR'], label: 'Annualized return', format: 'pct', higherIsBetter: true },
  { aliases: ['Sharpe Ratio'], label: 'Sharpe ratio', format: 'number', higherIsBetter: true },
  { aliases: ['Information Ratio'], label: 'Information ratio', format: 'number', higherIsBetter: true },
  { aliases: ['Max Drawdown'], label: 'Max drawdown', format: 'pct', higherIsBetter: true },
  { aliases: ['IC'], label: 'IC', format: 'number', higherIsBetter: true },
  { aliases: ['Rank IC'], label: 'Rank IC', format: 'number', higherIsBetter: true },
];

type EquityReportRow = { date?: unknown; account?: unknown };
type ComparisonModel = ModelData & { run: GovernedRunSummary };
type CheckedSection = { run: GovernedRunSummary; section: string; value: Record<string, unknown> | null; error: string };
const METRIC_ALIASES: Record<string, string> = { total_return: 'Total Return', excess_return: 'Excess Return', annualized_return: 'Annualized Return', sharpe_ratio: 'Sharpe Ratio', information_ratio: 'Information Ratio', max_drawdown: 'Max Drawdown', ic: 'IC', rank_ic: 'Rank IC' };

async function checkedSection(run: GovernedRunSummary, section: string): Promise<CheckedSection> {
  try {
    const value = await loadRunSection(run, section);
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid evidence section.');
    const payload = value as Record<string, unknown>;
    if (payload.research_only !== true || payload.trade_ready !== false) throw new Error('Invalid research boundary.');
    if (section === 'diagnostics' && (!Array.isArray(payload.interpretation_notes) || !payload.interpretation_notes.every((note) => typeof note === 'string'))) throw new Error('Invalid interpretation notes.');
    if (section === 'performance' && (!Array.isArray(payload.report) || !payload.report.every((row) => row && typeof row === 'object' && typeof row.date === 'string' && typeof row.account === 'number' && Number.isFinite(row.account) && row.account > 0))) throw new Error('Invalid performance observations.');
    return { run, section, value: payload, error: '' };
  } catch (error) { return { run, section, value: null, error: error instanceof Error ? error.message : String(error) }; }
}

function formatMetric(row: FormalMetricProjection, format: 'pct' | 'number'): string {
  if (row.value === null) return evidenceAvailabilityLabel(row.availability);
  return format === 'pct' ? `${(row.value * 100).toFixed(2)}%` : row.value.toFixed(3);
}

function buildEquitySeries(models: ModelData[]) {
  const rows = new Map<string, Record<string, string | number | null>>();
  for (const model of models) {
    const report: EquityReportRow[] = Array.isArray(model.backtest?.report) ? model.backtest.report : [];
    const firstAccount = Number(report.find((row) => Number.isFinite(Number(row.account)))?.account);
    if (!Number.isFinite(firstAccount) || firstAccount <= 0) continue;
    for (const row of report) {
      if (!row.date) continue;
      const date = String(row.date);
      const account = Number(row.account);
      const current = rows.get(date) ?? { date };
      current[model.id] = Number.isFinite(account) ? account / firstAccount - 1 : null;
      rows.set(date, current);
    }
  }
  return Array.from(rows.values()).sort((left, right) => String(left.date).localeCompare(String(right.date)));
}

function contractValue(model: ModelData, key: 'benchmark' | 'start' | 'end'): string {
  return formatDeclaredValue(model.backtest?.meta?.[key]);
}

function compareIdentity(models: ComparisonModel[]) {
  const identityRows = [
    { label: 'Market', values: models.map((model) => formatDeclaredValue(model.market)) },
    { label: 'Benchmark', values: models.map((model) => contractValue(model, 'benchmark')) },
    { label: 'Start', values: models.map((model) => contractValue(model, 'start')) },
    { label: 'End', values: models.map((model) => contractValue(model, 'end')) },
    ...([['Pool', 'universe_id'], ['Trace frequency', 'trace_frequency'], ['Horizon', 'horizon'], ['Rebalance contract', 'rebalance_contract_id'], ['Cost contract', 'cost_contract_id']] as const).map(([label, key]) => ({ label, values: models.map((model) => formatDeclaredValue(model.run.manifest?.comparability_key[key])) })),
  ];
  return identityRows.map((row) => ({
    ...row,
    aligned: row.values.every((value) => value.trim() && value !== formatDeclaredValue(undefined))
      && new Set(row.values.map((value) => String(value).toLowerCase())).size <= 1,
  }));
}

export function ComparePage() {
  const { runs } = useOutletContext<RunWorkspaceContext>();
  const [sections, setSections] = useState<CheckedSection[]>([]);
  const models = useMemo<ComparisonModel[]>(() => runs.map((run) => {
    const canonical = Array.isArray(run.summary.metrics) ? run.summary.metrics.map(parseCanonicalMetricV2) : [];
    const metrics = Object.fromEntries(canonical.filter((row) => row.availability_status === 'available' && row.value !== null && METRIC_ALIASES[row.metric_id]).map((row) => [METRIC_ALIASES[row.metric_id], row.value]));
    const identity = run.manifest?.comparability_key;
    return { id: run.key, name: `${run.title} · ${run.runId}`, market: identity?.market ?? run.market, model_type: run.modelKind, run, metrics,
      backtest: { metrics, meta: { benchmark: identity?.benchmark_id, start: identity?.start, end: identity?.end }, report: [], positions: [], attribution: [] },
    } as unknown as ComparisonModel;
  }), [runs]);
  const location = useLocation();
  const navigate = useNavigate();

  const initialIds = useMemo(() => {
    const params = new URLSearchParams(location.search);
    const declared = (params.get('runs') ?? params.get('models') ?? '').split(',').filter(Boolean);
    const valid = models.filter((model) => declared.includes(model.id) || declared.includes(model.run.modelVersionId)).map((model) => model.id);
    return valid.length > 0 || params.has('runs')
      ? valid.slice(0, MAX_COMPARE)
      : models.slice(0, Math.min(2, models.length)).map((model) => model.id);
  }, [models, location.search]);
  const [selectedIds, setSelectedIds] = useState<string[]>(initialIds);

  useEffect(() => setSelectedIds(initialIds), [initialIds]);

  const selected = useMemo(
    () => selectedIds.map((id) => models.find((model) => model.id === id)).filter((model): model is ComparisonModel => Boolean(model)),
    [models, selectedIds],
  );
  const identity = useMemo(() => compareIdentity(selected), [selected]);
  useEffect(() => {
    let active = true;
    void Promise.all(selected.flatMap((model) => ['performance', 'diagnostics'].map((section) => checkedSection(model.run, section))))
      .then((values) => { if (active) setSections(values); });
    return () => { active = false; };
  }, [selected]);
  const sectionFor = (model: ComparisonModel, section: string) => sections.find((value) => value.run === model.run && value.section === section);
  const equity = buildEquitySeries(selected.map((model) => ({ ...model, backtest: { ...model.backtest, report: sectionFor(model, 'performance')?.value?.report ?? [] } } as ModelData)));
  const incompatibleRows = identity.filter((row) => !row.aligned);
  const comparable = incompatibleRows.length === 0;

  const updateSelection = (nextIds: string[]) => {
    const limited = nextIds.filter((id) => models.some((model) => model.id === id)).slice(0, MAX_COMPARE);
    setSelectedIds(limited);
    const params = new URLSearchParams(location.search);
    params.delete('models');
    params.set('runs', limited.join(','));
    navigate({ pathname: location.pathname, search: params.toString() ? `?${params.toString()}` : '' }, { replace: true });
  };

  const toggleModel = (id: string) => {
    if (selectedIds.includes(id)) updateSelection(selectedIds.filter((current) => current !== id));
    else if (selectedIds.length < MAX_COMPARE) updateSelection([...selectedIds, id]);
  };

  if (models.length === 0) {
    return (
      <div className="research-empty-state">
        <GitCompareArrows className="mx-auto h-8 w-8 text-muted-foreground" />
        <h2 className="mt-4 text-lg font-semibold">No comparable records</h2>
        <p className="mt-2 text-sm text-muted-foreground">No retained comparison records are available for the active research bundle.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 pb-12">
      <section>
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-primary">Like-for-like review</p>
        <h2 className="mt-2 text-2xl font-black tracking-tight">Compare formal evidence</h2>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">
          Select up to {MAX_COMPARE} governed records. Metrics are descriptive unless market, pool, benchmark, window, horizon, rebalance and cost contracts align.
        </p>
      </section>

      <Card>
        <CardHeader className="pb-3"><CardTitle className="text-sm">Evidence records</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {models.map((model) => {
            const active = selectedIds.includes(model.id);
            return (
              <Button
                key={model.id}
                type="button"
                variant={active ? 'default' : 'outline'}
                size="sm"
                disabled={!active && selectedIds.length >= MAX_COMPARE}
                onClick={() => toggleModel(model.id)}
                aria-pressed={active}
                className="max-w-full gap-2"
              >
                {active && <Check className="h-3.5 w-3.5" />}
                <span className="truncate">{model.name || model.id}</span>
                <span className="text-[9px] uppercase opacity-70">{model.market ?? 'n/a'}</span>
              </Button>
            );
          })}
        </CardContent>
      </Card>

      {selected.length < 2 ? (
        <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">Select at least two evidence records to compare.</div>
      ) : (
        <>
          <Card className={comparable ? 'border-emerald-500/30' : 'border-amber-500/40'}>
            <CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-sm"><Scale className="h-4 w-4" /> Comparison identity</CardTitle></CardHeader>
            <CardContent>
              {!comparable && (
                <div className="mb-4 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-800 dark:text-amber-200">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{incompatibleRows.map((row) => row.label).join(', ')} differ or are not declared. No winner is inferred.</span>
                </div>
              )}
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader><TableRow><TableHead className="min-w-32">Identity</TableHead>{selected.map((model) => <TableHead key={model.id} className="min-w-44">{model.name || model.id}</TableHead>)}</TableRow></TableHeader>
                  <TableBody>
                    {identity.map((row) => (
                      <TableRow key={row.label}>
                        <TableCell className="font-medium">{row.label} {!row.aligned && <Badge variant="outline" className="ml-2 text-[9px] text-amber-700">Differs</Badge>}</TableCell>
                        {row.values.map((value, index) => <TableCell key={`${row.label}-${selected[index].id}`} className="font-mono text-xs">{value}</TableCell>)}
                      </TableRow>
                    ))}
                    {['Evidence cutoff', 'Evidence completeness'].map((label) => (
                      <TableRow key={label}><TableCell className="font-medium">{label}</TableCell>{selected.map((model) => {
                        return <TableCell key={model.id} className="font-mono text-xs">{label === 'Evidence cutoff' ? formatDeclaredValue(model.run.evidenceCutoff) : model.run.evidenceStatus}</TableCell>;
                      })}</TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-sm">Metric comparison</CardTitle><p className="text-xs text-muted-foreground">Highlighting also requires matching metric units, estimator, annualization, sample count and evidence scope.</p></CardHeader>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader><TableRow><TableHead className="min-w-44">Metric</TableHead>{selected.map((model) => <TableHead key={model.id} className="min-w-44">{model.name || model.id}</TableHead>)}</TableRow></TableHeader>
                <TableBody>
                  {METRICS.map((metric) => {
                    const canonical = selected.map((model) => (Array.isArray(model.run.summary.metrics) ? model.run.summary.metrics.map(parseCanonicalMetricV2) : []).find((row) => metric.aliases.includes(METRIC_ALIASES[row.metric_id])));
                    const projected: FormalMetricProjection[] = canonical.map((row) => ({ value: row?.value ?? null, availability: row?.availability_status ?? 'not_retained', reason: row?.unavailable_reason ?? 'Metric is not declared by this run.' }));
                    const finite = projected.map((row) => row.value).filter((value): value is number => value !== null);
                    const aligned = canonical.every((row) => row?.availability_status === 'available' && row.value !== null) && new Set(canonical.map((row) => JSON.stringify([row?.unit, row?.estimator, row?.annualization, row?.sample_count, row?.scope, row?.direction]))).size === 1;
                    const best = comparable && aligned && finite.length && canonical[0]?.direction !== 'descriptive' ? (canonical[0]?.direction === 'lower_is_better' ? Math.min(...finite) : Math.max(...finite)) : null;
                    return (
                      <TableRow key={metric.label}>
                        <TableCell><div className="font-medium">{metric.label}</div><div className="text-[10px] text-muted-foreground">{metric.aliases.join(' / ')}</div></TableCell>
                        {projected.map((row, index) => (
                          <TableCell key={`${metric.label}-${selected[index].id}`} className="font-mono" title={row.reason}>
                            <span className={row.value !== null && best !== null && row.value === best ? 'font-bold text-primary' : ''}>{formatMetric(row, metric.format)}</span>
                          </TableCell>
                        ))}
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <RiskReturnMap models={selected} comparable={comparable} />

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm"><LineChartIcon className="h-4 w-4" /> Normalized equity evidence</CardTitle>
              <p className="text-xs text-muted-foreground">Each retained series is normalized at its first declared account value. Missing observations remain gaps.</p>
            </CardHeader>
            <CardContent>
              {selected.map((model) => { const result = sectionFor(model, 'performance'); return !result || result.error ? <p key={model.id} className="mb-3 text-xs text-muted-foreground">{model.run.title}: {result?.error || 'Checking performance evidence...'}</p> : null; })}
              {equity.length === 0 ? (
                <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">No verified equity series are loaded.</div>
              ) : (
                <div className="h-[380px] w-full" aria-label="Normalized equity comparison chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={equity} margin={{ top: 8, right: 12, bottom: 8, left: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                      <XAxis dataKey="date" minTickGap={48} tick={{ fontSize: 10 }} />
                      <YAxis tickFormatter={(value) => `${(Number(value) * 100).toFixed(0)}%`} tick={{ fontSize: 10 }} width={52} />
                      <Tooltip formatter={(value) => [`${(Number(value) * 100).toFixed(2)}%`, 'Return']} />
                      <Legend />
                      {selected.map((model, index) => (
                        <Line
                          key={model.id}
                          type="monotone"
                          dataKey={model.id}
                          name={model.name || model.id}
                          stroke={CHART_COLORS[index % CHART_COLORS.length]}
                          dot={false}
                          connectNulls={false}
                          strokeWidth={2}
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
      {selected.map((model) => {
        const result = sectionFor(model, 'diagnostics');
        const notes = result?.value?.interpretation_notes as string[] | undefined;
        return <Card key={model.id}><CardHeader><CardTitle className="text-sm">Interpretation limits · {model.name || model.id}</CardTitle></CardHeader><CardContent className="text-sm text-muted-foreground">
          {!result ? <p role="status">Checking interpretation evidence...</p> : result.error ? <p role="alert">{result.error}</p> : notes?.length
            ? <ul className="list-disc space-y-2 pl-5">{notes.map((note, index) => <li key={index}>{note}</li>)}</ul>
            : <p>No interpretation notes are retained in this package.</p>}
        </CardContent></Card>;
      })}
    </div>
  );
}
