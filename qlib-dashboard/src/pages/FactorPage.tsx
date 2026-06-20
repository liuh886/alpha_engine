import { useEffect, useMemo } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Loader2,
  RefreshCw,
  BarChart3,
  Info,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatNum, useSort } from '@/lib/format';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import {
  useFactorStore,
  type FactorICResult,
} from '@/store/factorStore';

type SortKey =
  | 'none'
  | 'factor_name'
  | 'ic'
  | 'rank_ic'
  | 'ic_ir'
  | 't_stat'
  | 'positive_ic_ratio';

function icColor(v: number): string {
  if (v > 0.02) return 'text-green-500';
  if (v < -0.02) return 'text-red-500';
  return '';
}

// Shorten long Qlib expressions for display
function shortFactorName(name: string): string {
  if (name.length <= 40) return name;
  return name.slice(0, 37) + '...';
}

// Interpretation hints
function icInterpretation(ic: number, icIr: number): string {
  const parts: string[] = [];
  if (Math.abs(ic) >= 0.05) parts.push('Excellent IC');
  else if (Math.abs(ic) >= 0.03) parts.push('Good IC');
  else if (Math.abs(ic) >= 0.02) parts.push('Moderate IC');
  else parts.push('Weak IC');

  if (Math.abs(icIr) >= 0.5) parts.push('Excellent stability (IR)');
  else if (Math.abs(icIr) >= 0.3) parts.push('Good stability');
  else parts.push('Low stability');

  return parts.join(' | ');
}

const CustomTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number | string; color: string }>; label?: string }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-background/95 border shadow-lg rounded p-2.5 text-[10px] min-w-[120px]">
      <p className="font-semibold mb-1 pb-1 border-b">Lag: {label} days</p>
      {payload.map((p) => (
        <div key={p.name} className="flex justify-between gap-4 py-0.5">
          <span className="text-muted-foreground">IC</span>
          <span className="font-mono" style={{ color: p.color }}>
            {typeof p.value === 'number' ? p.value.toFixed(4) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
};

export function FactorPage() {
  const market = useFactorStore((s) => s.market);
  const report = useFactorStore((s) => s.report);
  const selectedFactor = useFactorStore((s) => s.selectedFactor);
  const decayData = useFactorStore((s) => s.decayData);
  const loading = useFactorStore((s) => s.loading);
  const decayLoading = useFactorStore((s) => s.decayLoading);
  const error = useFactorStore((s) => s.error);
  const setMarket = useFactorStore((s) => s.setMarket);
  const fetchReport = useFactorStore((s) => s.fetchReport);
  const selectFactor = useFactorStore((s) => s.selectFactor);

  const { sortKey, sortAsc, toggleSort, SortIcon } = useSort<SortKey>('rank_ic');

  useEffect(() => {
    fetchReport(market);
  }, [market, fetchReport]);

  const displayed = useMemo(() => {
    if (!report) return [];
    const list = [...report.top_factors];
    if (sortKey !== 'none') {
      list.sort((a, b) => {
        if (sortKey === 'factor_name') {
          return sortAsc
            ? a.factor_name.localeCompare(b.factor_name)
            : b.factor_name.localeCompare(a.factor_name);
        }
        const va = a[sortKey as keyof FactorICResult] as number;
        const vb = b[sortKey as keyof FactorICResult] as number;
        return sortAsc ? va - vb : vb - va;
      });
    }
    return list;
  }, [report, sortKey, sortAsc]);

  const selectedStats = useMemo(() => {
    if (!report || !selectedFactor) return null;
    return (
      report.factors.find((f) => f.factor_name === selectedFactor) ||
      report.top_factors.find((f) => f.factor_name === selectedFactor) ||
      null
    );
  }, [report, selectedFactor]);

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto pb-16">
      {/* Header */}
      <div className="border-b pb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Factor IC Analysis
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Information Coefficient for each Alpha158 factor. Higher |IC|
            indicates stronger predictive power for forward returns.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {(['us', 'cn'] as const).map((m) => (
              <Button
                key={m}
                variant={market === m ? 'default' : 'outline'}
                size="sm"
                onClick={() => setMarket(m)}
                className="h-7 text-xs uppercase"
              >
                {m}
              </Button>
            ))}
          </div>
          <Button
            onClick={() => fetchReport(market)}
            variant="outline"
            size="sm"
            className="h-7 gap-1.5 text-xs"
          >
            <RefreshCw
              className={cn('h-3 w-3', loading && 'animate-spin')}
            />
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <Card className="border-red-500/30">
          <CardContent className="p-4 text-sm text-red-500">
            {error}
          </CardContent>
        </Card>
      )}

      {/* Main layout: table left, detail right */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Section 1: Top Factors Table */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader className="pb-2 border-b flex flex-row items-center justify-between py-3">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <BarChart3 className="h-4 w-4" />
                Top Factors by |Rank IC|
              </CardTitle>
              <Badge variant="outline" className="text-xs">
                {displayed.length} factors
              </Badge>
            </CardHeader>
            <CardContent className="p-0">
              {loading ? (
                <div className="h-64 flex items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-primary opacity-50" />
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[40px] text-xs">#</TableHead>
                      <TableHead
                        className="cursor-pointer select-none text-xs"
                        onClick={() => toggleSort('factor_name')}
                      >
                        <span className="flex items-center gap-1">
                          Factor <SortIcon column="factor_name" />
                        </span>
                      </TableHead>
                      <TableHead
                        className="cursor-pointer select-none text-xs text-right"
                        onClick={() => toggleSort('ic')}
                      >
                        <span className="flex items-center gap-1 justify-end">
                          IC <SortIcon column="ic" />
                        </span>
                      </TableHead>
                      <TableHead
                        className="cursor-pointer select-none text-xs text-right"
                        onClick={() => toggleSort('rank_ic')}
                      >
                        <span className="flex items-center gap-1 justify-end">
                          Rank IC <SortIcon column="rank_ic" />
                        </span>
                      </TableHead>
                      <TableHead
                        className="cursor-pointer select-none text-xs text-right"
                        onClick={() => toggleSort('ic_ir')}
                      >
                        <span className="flex items-center gap-1 justify-end">
                          IC IR <SortIcon column="ic_ir" />
                        </span>
                      </TableHead>
                      <TableHead
                        className="cursor-pointer select-none text-xs text-right"
                        onClick={() => toggleSort('t_stat')}
                      >
                        <span className="flex items-center gap-1 justify-end">
                          t-stat <SortIcon column="t_stat" />
                        </span>
                      </TableHead>
                      <TableHead
                        className="cursor-pointer select-none text-xs text-right"
                        onClick={() => toggleSort('positive_ic_ratio')}
                      >
                        <span className="flex items-center gap-1 justify-end">
                          Pos % <SortIcon column="positive_ic_ratio" />
                        </span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {displayed.length === 0 ? (
                      <TableRow>
                        <TableCell
                          colSpan={7}
                          className="h-48 text-center text-muted-foreground text-sm"
                        >
                          {loading
                            ? 'Computing IC...'
                            : 'No data. Run data update first.'}
                        </TableCell>
                      </TableRow>
                    ) : (
                      displayed.map((f, idx) => {
                        const isSelected =
                          selectedFactor === f.factor_name;
                        return (
                          <TableRow
                            key={f.factor_name}
                            className={cn(
                              'cursor-pointer transition-colors',
                              isSelected
                                ? 'bg-primary/10'
                                : 'hover:bg-muted/50'
                            )}
                            onClick={() => selectFactor(f.factor_name)}
                          >
                            <TableCell className="text-xs text-muted-foreground font-mono">
                              {idx + 1}
                            </TableCell>
                            <TableCell>
                              <span
                                className="text-xs font-mono"
                                title={f.factor_name}
                              >
                                {shortFactorName(f.factor_name)}
                              </span>
                            </TableCell>
                            <TableCell className="text-right">
                              <span
                                className={cn(
                                  'font-mono text-xs',
                                  icColor(f.ic)
                                )}
                              >
                                {formatNum(f.ic)}
                              </span>
                            </TableCell>
                            <TableCell className="text-right">
                              <span
                                className={cn(
                                  'font-mono text-xs',
                                  icColor(f.rank_ic)
                                )}
                              >
                                {formatNum(f.rank_ic)}
                              </span>
                            </TableCell>
                            <TableCell className="text-right">
                              <span className="font-mono text-xs">
                                {formatNum(f.ic_ir, 2)}
                              </span>
                            </TableCell>
                            <TableCell className="text-right">
                              <span className="font-mono text-xs">
                                {formatNum(f.t_stat, 2)}
                              </span>
                            </TableCell>
                            <TableCell className="text-right">
                              <span className="font-mono text-xs">
                                {(f.positive_ic_ratio * 100).toFixed(0)}%
                              </span>
                            </TableCell>
                          </TableRow>
                        );
                      })
                    )}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right column: Decay chart + Info panel */}
        <div className="space-y-5">
          {/* Section 2: IC Decay Chart */}
          <Card>
            <CardHeader className="pb-2 border-b py-3">
              <CardTitle className="text-sm font-semibold">
                {selectedFactor
                  ? `IC Decay: ${shortFactorName(selectedFactor)}`
                  : 'IC Decay'}
              </CardTitle>
            </CardHeader>
            <CardContent className="h-[280px] pt-4">
              {!selectedFactor ? (
                <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
                  Select a factor from the table
                </div>
              ) : decayLoading ? (
                <div className="h-full flex items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-primary opacity-50" />
                </div>
              ) : decayData.length === 0 ? (
                <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
                  No decay data available
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={decayData}>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      vertical={false}
                      strokeOpacity={0.1}
                    />
                    <XAxis
                      dataKey="lag_days"
                      tick={{ fontSize: 10 }}
                      axisLine={false}
                      tickLine={false}
                      label={{
                        value: 'Lag (days)',
                        position: 'insideBottom',
                        offset: -2,
                        style: { fontSize: 10, fill: 'hsl(var(--muted-foreground))' },
                      }}
                    />
                    <YAxis
                      tick={{ fontSize: 10 }}
                      axisLine={false}
                      tickLine={false}
                      width={45}
                      tickFormatter={(v: number) => (v ?? 0).toFixed(3)}
                    />
                    <Tooltip content={<CustomTooltip />} />
                    <ReferenceLine
                      y={0}
                      stroke="hsl(var(--muted-foreground))"
                      strokeDasharray="3 3"
                      strokeOpacity={0.3}
                    />
                    <Line
                      type="monotone"
                      dataKey="ic"
                      stroke="hsl(var(--primary))"
                      strokeWidth={2}
                      dot={{ r: 3, fill: 'hsl(var(--primary))' }}
                      name="IC"
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Section 3: Info Panel */}
          <Card>
            <CardHeader className="pb-2 border-b py-3">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <Info className="h-4 w-4" />
                Factor Details
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-4">
              {!selectedFactor || !selectedStats ? (
                <div className="text-muted-foreground text-sm">
                  Select a factor to see details
                </div>
              ) : (
                <div className="space-y-3">
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">
                      Factor
                    </div>
                    <div
                      className="font-mono text-xs break-all bg-muted/50 p-2 rounded"
                      title={selectedStats.factor_name}
                    >
                      {selectedStats.factor_name}
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div className="bg-muted/30 p-2 rounded">
                      <div className="text-[10px] text-muted-foreground">
                        Pearson IC
                      </div>
                      <div
                        className={cn(
                          'font-mono text-sm font-medium',
                          icColor(selectedStats.ic)
                        )}
                      >
                        {formatNum(selectedStats.ic)}
                      </div>
                    </div>
                    <div className="bg-muted/30 p-2 rounded">
                      <div className="text-[10px] text-muted-foreground">
                        Rank IC
                      </div>
                      <div
                        className={cn(
                          'font-mono text-sm font-medium',
                          icColor(selectedStats.rank_ic)
                        )}
                      >
                        {formatNum(selectedStats.rank_ic)}
                      </div>
                    </div>
                    <div className="bg-muted/30 p-2 rounded">
                      <div className="text-[10px] text-muted-foreground">
                        IC IR
                      </div>
                      <div className="font-mono text-sm font-medium">
                        {formatNum(selectedStats.ic_ir, 2)}
                      </div>
                    </div>
                    <div className="bg-muted/30 p-2 rounded">
                      <div className="text-[10px] text-muted-foreground">
                        t-stat
                      </div>
                      <div className="font-mono text-sm font-medium">
                        {formatNum(selectedStats.t_stat, 2)}
                      </div>
                    </div>
                    <div className="bg-muted/30 p-2 rounded">
                      <div className="text-[10px] text-muted-foreground">
                        IC Std
                      </div>
                      <div className="font-mono text-sm font-medium">
                        {formatNum(selectedStats.ic_std)}
                      </div>
                    </div>
                    <div className="bg-muted/30 p-2 rounded">
                      <div className="text-[10px] text-muted-foreground">
                        Positive IC %
                      </div>
                      <div className="font-mono text-sm font-medium">
                        {(selectedStats.positive_ic_ratio * 100).toFixed(0)}%
                      </div>
                    </div>
                  </div>

                  <div className="bg-muted/20 p-2 rounded text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">
                      Interpretation:{' '}
                    </span>
                    {icInterpretation(
                      selectedStats.ic,
                      selectedStats.ic_ir
                    )}
                  </div>

                  <div className="text-[10px] text-muted-foreground space-y-0.5">
                    <p>IC {'>'}  0.03 is good, {'>'} 0.05 is excellent</p>
                    <p>IC IR {'>'} 0.5 is excellent stability</p>
                    <p>t-stat {'>'} 2.0 means statistically significant</p>
                    <p>Positive IC % {'>'} 60% means consistent direction</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
