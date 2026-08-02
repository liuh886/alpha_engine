import { AlertTriangle, CheckCircle2, ExternalLink, FileCheck2, GitBranch, Info } from 'lucide-react';
import type { FormalBacktestPackage } from '@/lib/formal-backtest';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

const WINDOW_COLUMNS: Array<{ keys: string[]; label: string; kind?: 'percent' | 'number' | 'text' }> = [
  { keys: ['window'], label: 'Window' },
  { keys: ['segment'], label: 'Segment' },
  { keys: ['strategy'], label: 'Strategy' },
  { keys: ['start', 'start_date'], label: 'Start' },
  { keys: ['end', 'end_date'], label: 'End' },
  { keys: ['net_strategy_return', 'total_return', 'cagr'], label: 'Strategy return', kind: 'percent' },
  { keys: ['qqq_return', 'benchmark_return'], label: 'Benchmark', kind: 'percent' },
  { keys: ['simple_excess_return'], label: 'Excess', kind: 'percent' },
  { keys: ['max_drawdown'], label: 'Max drawdown', kind: 'percent' },
  { keys: ['annual_volatility'], label: 'Volatility', kind: 'percent' },
  { keys: ['sharpe'], label: 'Sharpe', kind: 'number' },
  { keys: ['sortino'], label: 'Sortino', kind: 'number' },
  { keys: ['calmar'], label: 'Calmar', kind: 'number' },
  { keys: ['icir'], label: 'ICIR', kind: 'number' },
  { keys: ['rank_ic'], label: 'Rank IC', kind: 'number' },
  { keys: ['turnover'], label: 'Turnover', kind: 'number' },
  { keys: ['n_periods', 'periods', 'observations'], label: 'Periods', kind: 'number' },
  { keys: ['top_selected_stocks'], label: 'Final selection', kind: 'text' },
];

function firstValue(row: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (row[key] !== undefined && row[key] !== null) return row[key];
  }
  return undefined;
}

function formatValue(value: unknown, kind: 'percent' | 'number' | 'text' = 'text'): string {
  if (Array.isArray(value)) return value.map(String).join(', ');
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (kind === 'percent') return `${(value * 100).toFixed(2)}%`;
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (value === undefined || value === null || value === '') return '—';
  return String(value);
}

function displayKey(value: string): string {
  return value.split('_').join(' ');
}

export function FormalBacktestTrades({ formal }: { formal: FormalBacktestPackage }) {
  if (!formal.trades.length) {
    return (
      <div className="rounded-xl border border-dashed p-10 text-center">
        <AlertTriangle className="mx-auto h-7 w-7 text-amber-500" />
        <p className="mt-3 text-sm font-medium">Transaction ledger was not retained</p>
        <p className="mx-auto mt-1 max-w-xl text-xs leading-relaxed text-muted-foreground">
          This formal package exposes only the source evidence that actually exists. No transaction path is inferred from aggregate metrics or final selections.
        </p>
      </div>
    );
  }

  return (
    <Card>
      <CardHeader className="border-b pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm">Complete transaction ledger</CardTitle>
          <Badge variant="secondary" className="font-mono text-[10px]">{formal.trades.length.toLocaleString()} rows</Badge>
        </div>
      </CardHeader>
      <CardContent className="max-h-[620px] overflow-auto p-0">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-background">
            <TableRow>
              <TableHead>Date</TableHead>
              <TableHead>Instrument</TableHead>
              <TableHead>Action</TableHead>
              <TableHead className="text-right">Previous</TableHead>
              <TableHead className="text-right">Target</TableHead>
              <TableHead className="text-right">Delta</TableHead>
              <TableHead className="text-right">Cost</TableHead>
              <TableHead>Reason / window</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {formal.trades.map((row, index) => (
              <TableRow key={`${row.date}-${row.instrument}-${row.action}-${index}`}>
                <TableCell className="whitespace-nowrap font-mono text-xs">{row.date}</TableCell>
                <TableCell className="font-semibold">{row.instrument}</TableCell>
                <TableCell><Badge variant="outline" className="text-[9px]">{row.action}</Badge></TableCell>
                <TableCell className="text-right font-mono text-xs">{formatValue(row.previous_weight, 'percent')}</TableCell>
                <TableCell className="text-right font-mono text-xs">{formatValue(row.target_weight, 'percent')}</TableCell>
                <TableCell className="text-right font-mono text-xs">{formatValue(row.weight_delta, 'percent')}</TableCell>
                <TableCell className="text-right font-mono text-xs">{formatValue(row.transaction_cost, 'percent')}</TableCell>
                <TableCell className="max-w-[320px] truncate text-xs text-muted-foreground" title={String(row.reason ?? row.window ?? '')}>
                  {String(row.reason ?? row.window ?? '—')}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function WindowSummary({ formal }: { formal: FormalBacktestPackage }) {
  if (!formal.window_summary.length) return null;
  const columns = WINDOW_COLUMNS.filter((column) => formal.window_summary.some((row) => firstValue(row, column.keys) !== undefined));
  return (
    <Card>
      <CardHeader className="border-b pb-3"><CardTitle className="text-sm">Window and segment evidence</CardTitle></CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <Table>
          <TableHeader><TableRow>{columns.map((column) => <TableHead key={column.label}>{column.label}</TableHead>)}</TableRow></TableHeader>
          <TableBody>
            {formal.window_summary.map((row, index) => (
              <TableRow key={`${formal.model_id}-window-${index}`}>
                {columns.map((column) => (
                  <TableCell key={column.label} className={column.kind === 'percent' || column.kind === 'number' ? 'whitespace-nowrap font-mono text-xs' : 'min-w-[110px] text-xs'}>
                    {formatValue(firstValue(row, column.keys), column.kind)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

export function FormalBacktestEvidence({ formal }: { formal: FormalBacktestPackage }) {
  const complete = formal.evidence_completeness.status === 'complete';
  const workflowRun = Number(formal.evidence.workflow_run_id);
  const artifactId = formal.evidence.artifact_id;
  const digest = String(formal.evidence.artifact_digest ?? '');
  const completenessRows = Object.entries(formal.evidence_completeness)
    .filter(([key]) => key !== 'status' && key !== 'missing')
    .filter(([, value]) => typeof value === 'string');
  const evidenceRows = Object.entries(formal.evidence)
    .filter(([key]) => !['exports_sha256', 'row_counts'].includes(key))
    .filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value));
  const rowCounts = formal.evidence.row_counts && typeof formal.evidence.row_counts === 'object'
    ? Object.entries(formal.evidence.row_counts as Record<string, unknown>)
    : [];

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader className="border-b pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-sm"><FileCheck2 className="h-4 w-4 text-primary" /> Formal backtest evidence</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">Accepted named baseline only. Exploratory experiments are not part of this package.</p>
            </div>
            <Badge variant={complete ? 'secondary' : 'outline'} className={complete ? 'gap-1.5 text-emerald-700 dark:text-emerald-300' : 'gap-1.5 text-amber-700 dark:text-amber-300'}>
              {complete ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
              {complete ? 'Complete retained trace' : 'Partial retained trace'}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 pt-5 md:grid-cols-2 xl:grid-cols-4">
          <div className="research-stat"><dt>Backtest ID</dt><dd className="truncate font-mono" title={formal.backtest_id}>{formal.backtest_id}</dd></div>
          <div className="research-stat"><dt>Trace frequency</dt><dd>{displayKey(formal.trace_frequency)}</dd></div>
          <div className="research-stat"><dt>Evidence cutoff</dt><dd>{formal.evidence_cutoff}</dd></div>
          <div className="research-stat"><dt>Benchmark</dt><dd>{formal.benchmark}</dd></div>
        </CardContent>
      </Card>

      {!complete && formal.evidence_completeness.missing.length > 0 && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
          <div className="flex gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
            <div>
              <p className="text-sm font-semibold">Source evidence is incomplete</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">The frontend does not reconstruct these missing components:</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {formal.evidence_completeness.missing.map((item) => <Badge key={item} variant="outline" className="font-mono text-[10px]">{displayKey(item)}</Badge>)}
              </div>
            </div>
          </div>
        </div>
      )}

      <WindowSummary formal={formal} />

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader className="border-b pb-3"><CardTitle className="text-sm">Evidence identity</CardTitle></CardHeader>
          <CardContent className="space-y-3 pt-4 text-xs">
            {evidenceRows.map(([key, value]) => (
              <div key={key} className="flex items-start justify-between gap-4 border-b pb-2 last:border-0 last:pb-0">
                <span className="text-muted-foreground">{displayKey(key)}</span>
                <span className="max-w-[65%] break-all text-right font-mono">{String(value)}</span>
              </div>
            ))}
            {digest && <div className="rounded-lg bg-muted/45 p-3 font-mono text-[10px] break-all">{digest}</div>}
            {Number.isFinite(workflowRun) && workflowRun > 0 && (
              <a className="inline-flex items-center gap-1.5 text-primary hover:underline" href={`https://github.com/liuh886/alpha_engine/actions/runs/${workflowRun}`} target="_blank" rel="noreferrer">
                <GitBranch className="h-3.5 w-3.5" /> Open workflow run <ExternalLink className="h-3 w-3" />
              </a>
            )}
            {artifactId != null && <p className="text-muted-foreground">Artifact ID: <span className="font-mono text-foreground">{String(artifactId)}</span></p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b pb-3"><CardTitle className="text-sm">Evidence coverage</CardTitle></CardHeader>
          <CardContent className="space-y-3 pt-4 text-xs">
            {completenessRows.map(([key, value]) => (
              <div key={key} className="flex items-start justify-between gap-4 border-b pb-2 last:border-0 last:pb-0">
                <span className="text-muted-foreground">{displayKey(key)}</span>
                <span className="max-w-[65%] text-right font-medium">{displayKey(String(value))}</span>
              </div>
            ))}
            {rowCounts.length > 0 && (
              <div className="pt-2">
                <p className="mb-2 font-medium">Retained row counts</p>
                <div className="grid grid-cols-2 gap-2">
                  {rowCounts.map(([key, value]) => <div key={key} className="rounded-lg bg-muted/45 p-2"><p className="truncate text-[10px] text-muted-foreground" title={key}>{key}</p><p className="mt-1 font-mono font-semibold">{formatValue(value, 'number')}</p></div>)}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {formal.interpretation_notes.length > 0 && (
        <Card>
          <CardHeader className="border-b pb-3"><CardTitle className="flex items-center gap-2 text-sm"><Info className="h-4 w-4 text-primary" /> Interpretation limits</CardTitle></CardHeader>
          <CardContent className="space-y-2 pt-4">
            {formal.interpretation_notes.map((note) => <p key={note} className="text-sm leading-relaxed text-muted-foreground">{note}</p>)}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
