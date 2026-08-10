import { useMemo } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Info } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

type AttributionRow = { instrument?: string; name?: string; value?: number };

type NormalizedAttributionRow = {
  instrument: string;
  name: string;
  label: string;
  value: number;
};

function formatPercent(value: number) {
  return `${(value * 100).toFixed(3)}%`;
}

export function AttributionEvidence({ rows }: { rows: AttributionRow[] | null | undefined }) {
  const normalized = useMemo<NormalizedAttributionRow[]>(() => Array.isArray(rows)
    ? rows
      .filter((row) => typeof row?.value === 'number' && Number.isFinite(row.value))
      .map((row) => ({
        instrument: String(row.instrument || '—'),
        name: String(row.name || row.instrument || 'Unknown'),
        label: String(row.name || row.instrument || 'Unknown'),
        value: Number(row.value),
      }))
      .sort((left, right) => Math.abs(right.value) - Math.abs(left.value))
    : [], [rows]);

  const chartRows = useMemo(
    () => [...normalized.slice(0, 12)].sort((left, right) => left.value - right.value),
    [normalized],
  );
  const largestPositive = normalized.reduce<NormalizedAttributionRow | null>(
    (best, row) => row.value > 0 && (!best || row.value > best.value) ? row : best,
    null,
  );
  const largestNegative = normalized.reduce<NormalizedAttributionRow | null>(
    (best, row) => row.value < 0 && (!best || row.value < best.value) ? row : best,
    null,
  );

  if (!normalized.length) {
    return (
      <div className="rounded-xl border border-dashed p-10 text-center">
        <Info className="mx-auto h-7 w-7 text-muted-foreground/40" />
        <p className="mt-3 text-sm font-medium">Attribution evidence is not declared</p>
        <p className="mt-1 text-xs text-muted-foreground">The formal source package contains no retained contribution ledger. No attribution is inferred.</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <Card data-testid="attribution-drivers-chart">
        <CardHeader className="border-b pb-3">
          <CardTitle className="text-sm font-semibold">Contribution drivers</CardTitle>
          <p className="mt-1 text-xs text-muted-foreground">Largest retained positive and negative contributions. Values are source evidence; the browser does not reconstruct attribution.</p>
          <div className="mt-3 grid grid-cols-1 gap-3 border-t pt-3 sm:grid-cols-3">
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Retained rows</p>
              <p className="mt-1 font-mono text-sm font-semibold tabular-nums">{normalized.length}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Largest positive</p>
              <p className="mt-1 truncate text-xs font-medium" title={largestPositive?.name}>{largestPositive?.name || '—'}</p>
              <p className="font-mono text-xs tabular-nums text-emerald-600 dark:text-emerald-400">{largestPositive ? formatPercent(largestPositive.value) : '—'}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Largest negative</p>
              <p className="mt-1 truncate text-xs font-medium" title={largestNegative?.name}>{largestNegative?.name || '—'}</p>
              <p className="font-mono text-xs tabular-nums text-rose-600 dark:text-rose-400">{largestNegative ? formatPercent(largestNegative.value) : '—'}</p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-4">
          <div style={{ height: `${Math.max(250, Math.min(500, chartRows.length * 34 + 54))}px` }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartRows} layout="vertical" margin={{ top: 4, right: 18, bottom: 4, left: 6 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} strokeOpacity={0.1} />
                <XAxis type="number" tickFormatter={(value) => `${(Number(value) * 100).toFixed(1)}%`} tick={{ fontSize: 9 }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="label" width={118} tick={{ fontSize: 9 }} axisLine={false} tickLine={false} tickFormatter={(value) => String(value).length > 18 ? `${String(value).slice(0, 17)}…` : String(value)} />
                <Tooltip formatter={(value) => [formatPercent(Number(value)), 'Contribution']} labelFormatter={(label) => String(label)} contentStyle={{ fontSize: '10px' }} />
                <ReferenceLine x={0} stroke="hsl(var(--muted-foreground))" strokeOpacity={0.4} />
                <Bar dataKey="value" name="Contribution" maxBarSize={16}>
                  {chartRows.map((row) => (
                    <Cell key={`${row.instrument}-${row.value}`} fill={row.value >= 0 ? '#10b981' : '#f43f5e'} fillOpacity={0.75} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b pb-3"><CardTitle className="text-sm font-semibold">Contribution ledger</CardTitle></CardHeader>
        <CardContent className="overflow-x-auto pt-2">
          <Table>
            <TableHeader><TableRow><TableHead>Instrument</TableHead><TableHead>Name</TableHead><TableHead className="text-right">Contribution</TableHead></TableRow></TableHeader>
            <TableBody>
              {normalized.slice(0, 100).map((row, index) => (
                <TableRow key={`${row.instrument}-${index}`}>
                  <TableCell className="font-mono text-xs">{row.instrument}</TableCell>
                  <TableCell>{row.name}</TableCell>
                  <TableCell className={`text-right font-mono tabular-nums ${row.value >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}`}>
                    {formatPercent(row.value)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
