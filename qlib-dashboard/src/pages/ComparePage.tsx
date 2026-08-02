import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  Check,
  GitCompareArrows,
  LineChart as LineChartIcon,
  Scale,
} from 'lucide-react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ModelData } from '@/lib/data-parser';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

const MAX_COMPARE = 5;
const CHART_COLORS = ['hsl(var(--primary))', '#f59e0b', '#0ea5e9', '#8b5cf6', '#ec4899'];

const METRICS: Array<{ key: string; label: string; format: 'pct' | 'number'; higherIsBetter: boolean }> = [
  { key: 'Excess Return', label: 'Excess return', format: 'pct', higherIsBetter: true },
  { key: 'Annualized Return', label: 'Annualized return', format: 'pct', higherIsBetter: true },
  { key: 'Sharpe Ratio', label: 'Sharpe ratio', format: 'number', higherIsBetter: true },
  { key: 'Information Ratio', label: 'Information ratio', format: 'number', higherIsBetter: true },
  { key: 'Max Drawdown', label: 'Max drawdown', format: 'pct', higherIsBetter: true },
  { key: 'IC', label: 'IC', format: 'number', higherIsBetter: true },
  { key: 'Rank IC', label: 'Rank IC', format: 'number', higherIsBetter: true },
];

function numericMetric(model: ModelData, key: string): number | null {
  const value = model.backtest?.metrics?.[key] ?? model.metrics?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function formatMetric(value: number | null, format: 'pct' | 'number'): string {
  if (value === null) return '—';
  return format === 'pct' ? `${(value * 100).toFixed(2)}%` : value.toFixed(3);
}

function buildEquitySeries(models: ModelData[]) {
  const rows = new Map<string, Record<string, string | number | null>>();
  for (const model of models) {
    const report = Array.isArray(model.backtest?.report) ? model.backtest.report : [];
    const firstAccount = Number(report.find((row: any) => Number.isFinite(Number(row.account)))?.account);
    if (!Number.isFinite(firstAccount) || firstAccount <= 0) continue;

    for (const row of report) {
      if (!row?.date) continue;
      const date = String(row.date);
      const account = Number(row.account);
      const current: Record<string, string | number | null> = rows.get(date) ?? { date };
      current[model.id] = Number.isFinite(account) ? account / firstAccount - 1 : null;
      rows.set(date, current);
    }
  }
  return Array.from(rows.values()).sort((a, b) => String(a.date).localeCompare(String(b.date)));
}

function contractValue(model: ModelData, key: 'benchmark' | 'start' | 'end'): string {
  return String(model.backtest?.meta?.[key] || 'not declared');
}

function paramValue(model: ModelData, path: string[]): unknown {
  let current: unknown = model.params;
  for (const segment of path) {
    if (!current || typeof current !== 'object') return undefined;
    current = (current as Record<string, unknown>)[segment];
  }
  return current;
}

function compareIdentity(models: ModelData[]) {
  const identityRows = [
    { label: 'Market', values: models.map((model) => model.market || 'not declared') },
    { label: 'Benchmark', values: models.map((model) => contractValue(model, 'benchmark')) },
    { label: 'Start', values: models.map((model) => contractValue(model, 'start')) },
    { label: 'End', values: models.map((model) => contractValue(model, 'end')) },
    { label: 'Snapshot', values: models.map((model) => model.snapshot_id || 'not declared') },
    {
      label: 'Costs',
      values: models.map((model) => {
        const costs = paramValue(model, ['meta', 'strategy_profile', 'strategy', 'costs_bps']);
        return typeof costs === 'number' ? `${costs} bps` : 'not declared';
      }),
    },
  ];

  return identityRows.map((row) => ({
    ...row,
    aligned: new Set(row.values.map((value) => String(value).toLowerCase())).size <= 1,
  }));
}

export function ComparePage({ models }: { models: ModelData[] }) {
  const location = useLocation();
  const navigate = useNavigate();
  const initialIds = useMemo(() => {
    const params = new URLSearchParams(location.search);
    const declared = (params.get('models') || '').split(',').filter(Boolean);
    const valid = declared.filter((id) => models.some((model) => model.id === id));
    return valid.length > 0 ? valid.slice(0, MAX_COMPARE) : models.slice(0, Math.min(2, models.length)).map((model) => model.id);
  }, [location.search, models]);
  const [selectedIds, setSelectedIds] = useState<string[]>(initialIds);

  useEffect(() => {
    setSelectedIds(initialIds);
  }, [initialIds]);

  const selected = useMemo(
    () => selectedIds.map((id) => models.find((model) => model.id === id)).filter((model): model is ModelData => Boolean(model)),
    [models, selectedIds],
  );
  const identity = useMemo(() => compareIdentity(selected), [selected]);
  const equity = useMemo(() => buildEquitySeries(selected), [selected]);
  const incompatibleRows = identity.filter((row) => !row.aligned);

  const updateSelection = (nextIds: string[]) => {
    const limited = nextIds.slice(0, MAX_COMPARE);
    setSelectedIds(limited);
    const params = new URLSearchParams(location.search);
    if (limited.length) params.set('models', limited.join(','));
    else params.delete('models');
    navigate({ pathname: location.pathname, search: params.toString() ? `?${params.toString()}` : '' }, { replace: true });
  };

  const toggleModel = (id: string) => {
    if (selectedIds.includes(id)) {
      updateSelection(selectedIds.filter((current) => current !== id));
      return;
    }
    if (selectedIds.length >= MAX_COMPARE) return;
    updateSelection([...selectedIds, id]);
  };

  if (models.length === 0) {
    return (
      <div className="research-empty-state">
        <GitCompareArrows className="mx-auto h-8 w-8 text-muted-foreground" />
        <h2 className="mt-4 text-lg font-semibold">No comparable records</h2>
        <p className="mt-2 text-sm text-muted-foreground">The active research bundle does not declare any model or strategy records.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1500px] space-y-6 pb-12">
      <section>
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-primary">Like-for-like review</p>
        <h2 className="mt-2 text-2xl font-black tracking-tight">Compare candidate evidence</h2>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted-foreground">
          Select up to {MAX_COMPARE} records from the active bundle. A metric comparison is interpretable only when market, benchmark, window, snapshot and cost assumptions are aligned.
        </p>
      </section>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Evidence records</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {models.map((model) => {
            const active = selectedIds.includes(model.id);
            const disabled = !active && selectedIds.length >= MAX_COMPARE;
            return (
              <Button
                key={model.id}
                type="button"
                variant={active ? 'default' : 'outline'}
                size="sm"
                disabled={disabled}
                onClick={() => toggleModel(model.id)}
                aria-pressed={active}
                className="max-w-full gap-2"
              >
                {active && <Check className="h-3.5 w-3.5" />}
                <span className="truncate">{model.name || model.id}</span>
                <span className="text-[9px] uppercase opacity-70">{model.market || 'n/a'}</span>
              </Button>
            );
          })}
        </CardContent>
      </Card>

      {selected.length < 2 ? (
        <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
          Select at least two evidence records to compare.
        </div>
      ) : (
        <>
          <Card className={incompatibleRows.length ? 'border-amber-500/40' : 'border-emerald-500/30'}>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Scale className="h-4 w-4" /> Comparison identity
              </CardTitle>
            </CardHeader>
            <CardContent>
              {incompatibleRows.length > 0 && (
                <div className="mb-4 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-800 dark:text-amber-200">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{incompatibleRows.map((row) => row.label).join(', ')} differ across selected records. Treat performance differences as descriptive, not causal.</span>
                </div>
              )}
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="min-w-32">Identity</TableHead>
                      {selected.map((model) => <TableHead key={model.id} className="min-w-44">{model.name || model.id}</TableHead>)}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {identity.map((row) => (
                      <TableRow key={row.label}>
                        <TableCell className="font-medium">
                          {row.label} {!row.aligned && <Badge variant="outline" className="ml-2 text-[9px] text-amber-700">Differs</Badge>}
                        </TableCell>
                        {row.values.map((value, index) => <TableCell key={`${row.label}-${selected[index].id}`} className="font-mono text-xs">{value}</TableCell>)}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Metric comparison</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="min-w-44">Metric</TableHead>
                    {selected.map((model) => <TableHead key={model.id} className="min-w-44">{model.name || model.id}</TableHead>)}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {METRICS.map((metric) => {
                    const values = selected.map((model) => numericMetric(model, metric.key));
                    const finite = values.filter((value): value is number => value !== null);
                    const best = finite.length ? (metric.higherIsBetter ? Math.max(...finite) : Math.min(...finite)) : null;
                    return (
                      <TableRow key={metric.key}>
                        <TableCell>
                          <div className="font-medium">{metric.label}</div>
                          <div className="text-[10px] text-muted-foreground">{metric.key}</div>
                        </TableCell>
                        {values.map((value, index) => (
                          <TableCell key={`${metric.key}-${selected[index].id}`} className="font-mono">
                            <span className={value !== null && best !== null && value === best ? 'font-bold text-primary' : ''}>
                              {formatMetric(value, metric.format)}
                            </span>
                          </TableCell>
                        ))}
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm"><LineChartIcon className="h-4 w-4" /> Normalized equity evidence</CardTitle>
              <p className="text-xs text-muted-foreground">Each series is normalized to zero at its first declared account value. Missing observations remain gaps.</p>
            </CardHeader>
            <CardContent>
              {equity.length === 0 ? (
                <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">No comparable equity series are declared in these records.</div>
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
    </div>
  );
}
