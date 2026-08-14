import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { useNameMap } from '@/lib/useNameMap';
import type { Position, ReportRow } from '@/lib/types';

const EPSILON = 0.0005;

type PositionWithChange = Position & {
  previousWeight: number | null;
  deltaWeight: number | null;
  changeKind: 'new' | 'increased' | 'reduced' | 'unchanged';
};

type TurnoverEvent = {
  date: string;
  turnover: number;
  holding_end_date?: string;
};

function formatPercent(value: number | null, digits = 1) {
  return value === null ? '—' : `${(value * 100).toFixed(digits)}%`;
}

function isProvisionalMtm(row: ReportRow) {
  return row.provisional_mtm === true || row.settlement_status === 'provisional_mtm';
}

function deriveTurnover(previous: Position[], current: Position[]) {
  const previousByInstrument = new Map(previous.map((position) => [position.instrument, Number(position.weight) || 0]));
  const currentByInstrument = new Map(current.map((position) => [position.instrument, Number(position.weight) || 0]));
  const instruments = new Set([...previousByInstrument.keys(), ...currentByInstrument.keys()]);
  return 0.5 * Array.from(instruments).reduce(
    (sum, instrument) => sum + Math.abs((currentByInstrument.get(instrument) ?? 0) - (previousByInstrument.get(instrument) ?? 0)),
    0,
  );
}

export function PositionsTable({ positions, report }: { positions: Position[]; report?: ReportRow[] }) {
  const { getName } = useNameMap();
  const dates = useMemo(() => Array.from(new Set(positions.map((position) => position.date))).sort(), [positions]);
  const [selectedDateIdx, setSelectedDateIdx] = useState(dates.length - 1);

  useEffect(() => {
    if (!dates.length) return;
    const nextIdx = Math.max(0, dates.length - 1);
    if (selectedDateIdx < 0 || selectedDateIdx >= dates.length) setSelectedDateIdx(nextIdx);
  }, [dates, selectedDateIdx]);

  const currentDate = dates[selectedDateIdx];
  const previousDate = selectedDateIdx > 0 ? dates[selectedDateIdx - 1] : null;

  const previousPositions = useMemo(
    () => previousDate ? positions.filter((position) => position.date === previousDate) : [],
    [positions, previousDate],
  );

  const currentPositions = useMemo<PositionWithChange[]>(() => {
    if (!currentDate) return [];
    const previousByInstrument = new Map(previousPositions.map((position) => [position.instrument, position]));
    return positions
      .filter((position) => position.date === currentDate)
      .map((position) => {
        const previous = previousByInstrument.get(position.instrument);
        const previousWeight = previous ? Number(previous.weight) : null;
        const deltaWeight = previousWeight === null ? Number(position.weight) : Number(position.weight) - previousWeight;
        let changeKind: PositionWithChange['changeKind'] = 'unchanged';
        if (!previous) changeKind = 'new';
        else if (deltaWeight > EPSILON) changeKind = 'increased';
        else if (deltaWeight < -EPSILON) changeKind = 'reduced';
        return { ...position, previousWeight, deltaWeight, changeKind };
      })
      .sort((left, right) => Math.abs(Number(right.weight) || 0) - Math.abs(Number(left.weight) || 0));
  }, [currentDate, positions, previousPositions]);

  const turnoverEvents = useMemo<TurnoverEvent[]>(() => {
    const events = new Map<string, TurnoverEvent>();
    for (const row of report || []) {
      if (isProvisionalMtm(row) || !Number.isFinite(Number(row.turnover))) continue;
      events.set(row.date, {
        date: row.date,
        turnover: Number(row.turnover),
        holding_end_date: row.holding_end_date,
      });
    }
    dates.forEach((date, index) => {
      if (events.has(date) || index === 0) return;
      const previous = positions.filter((position) => position.date === dates[index - 1]);
      const current = positions.filter((position) => position.date === date);
      events.set(date, { date, turnover: deriveTurnover(previous, current) });
    });
    return Array.from(events.values()).sort((left, right) => left.date.localeCompare(right.date));
  }, [dates, positions, report]);

  const latestMtmObservation = useMemo(() => {
    const rows = (report || []).filter(isProvisionalMtm);
    rows.sort((left, right) => left.date.localeCompare(right.date));
    return rows.length ? rows[rows.length - 1] : undefined;
  }, [report]);

  const snapshotStats = useMemo(() => {
    const grossExposure = currentPositions.reduce((sum, position) => sum + Math.abs(Number(position.weight) || 0), 0);
    const netExposure = currentPositions.reduce((sum, position) => sum + (Number(position.weight) || 0), 0);
    const topFiveExposure = currentPositions.slice(0, 5).reduce((sum, position) => sum + Math.abs(Number(position.weight) || 0), 0);
    const topFiveConcentration = grossExposure > 0 ? topFiveExposure / grossExposure : null;
    const currentInstruments = new Set(currentPositions.map((position) => position.instrument));
    const exited = previousPositions.filter((position) => !currentInstruments.has(position.instrument)).length;
    const added = currentPositions.filter((position) => position.changeKind === 'new').length;
    const adjusted = currentPositions.filter((position) => position.changeKind === 'increased' || position.changeKind === 'reduced').length;
    const turnoverRow = turnoverEvents.find((row) => row.date === currentDate);
    const derivedTurnover = previousDate ? deriveTurnover(previousPositions, currentPositions) : null;
    const turnover = turnoverRow ? turnoverRow.turnover : derivedTurnover;
    return { grossExposure, netExposure, topFiveConcentration, exited, added, adjusted, turnover };
  }, [currentDate, currentPositions, previousDate, previousPositions, turnoverEvents]);

  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: currentPositions.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 52,
    overscan: 5,
  });

  const handleBarClick = (data: unknown) => {
    if (!data || typeof data !== 'object') return;
    const date = (data as Record<string, unknown>).date;
    if (typeof date !== 'string') return;
    const index = dates.indexOf(date);
    if (index !== -1) setSelectedDateIdx(index);
  };

  if (!positions.length) return <div className="p-4 text-center text-sm text-muted-foreground">No position data available.</div>;

  const mtmAsOf = latestMtmObservation
    ? typeof latestMtmObservation.mtm_as_of === 'string' ? latestMtmObservation.mtm_as_of : latestMtmObservation.date
    : null;
  const mtmSignalDate = latestMtmObservation && typeof latestMtmObservation.signal_date === 'string'
    ? latestMtmObservation.signal_date
    : null;
  const mtmRebalanceTurnover = latestMtmObservation && Number.isFinite(Number(latestMtmObservation.rebalance_turnover))
    ? Number(latestMtmObservation.rebalance_turnover)
    : null;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader className="border-b pb-3">
          <CardTitle className="text-sm font-semibold">Rebalance turnover & holdings timeline</CardTitle>
          <CardDescription className="text-xs">Bars are rebalance events only. MTM valuation updates are shown separately and never create a holdings snapshot.</CardDescription>
        </CardHeader>
        <CardContent className="pt-4">
          <div className="h-[190px] sm:h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={turnoverEvents}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.1} />
                <XAxis dataKey="date" tickFormatter={(date) => format(parseISO(date), 'MM/yy')} minTickGap={30} tick={{ fontSize: 9 }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={(value) => `${(Number(value) * 100).toFixed(0)}%`} tick={{ fontSize: 9 }} axisLine={false} tickLine={false} width={42} />
                <Tooltip formatter={(value) => [`${(Number(value) * 100).toFixed(2)}%`, 'Turnover']} contentStyle={{ fontSize: '10px' }} />
                <Bar dataKey="turnover" onClick={handleBarClick} cursor="pointer" name="Turnover" maxBarSize={10}>
                  {turnoverEvents.map((entry, index) => (
                    <Cell
                      key={`${entry.date}-${index}`}
                      fill="hsl(var(--primary))"
                      fillOpacity={entry.date === currentDate || entry.holding_end_date === currentDate ? 0.9 : 0.28}
                    />
                  ))}
                </Bar>
                {currentDate && <ReferenceLine x={currentDate} stroke="hsl(var(--primary))" strokeOpacity={0.45} strokeDasharray="3 3" />}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          {latestMtmObservation && mtmAsOf && (
            <div data-testid="mtm-observation" className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3 text-[10px] text-muted-foreground">
              <Badge variant="outline" className="font-mono text-[9px]">MTM {mtmAsOf}</Badge>
              <span>No rebalance.</span>
              {mtmSignalDate && <span>Source signal: <span className="font-mono">{mtmSignalDate}</span>.</span>}
              {mtmRebalanceTurnover !== null && <span>Source rebalance turnover: <span className="font-mono">{formatPercent(mtmRebalanceTurnover)}</span>.</span>}
            </div>
          )}
        </CardContent>
      </Card>

      <Card data-testid="holdings-snapshot">
        <CardHeader className="border-b pb-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-sm font-semibold">Holdings snapshot</CardTitle>
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">{currentDate}{previousDate ? ` · vs ${previousDate}` : ' · first retained snapshot'}</p>
            </div>
            <Badge variant="secondary" className="font-mono text-[10px]">{currentPositions.length} assets</Badge>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 border-t pt-3 sm:grid-cols-4">
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Net exposure</p>
              <p className="mt-1 font-mono text-sm font-semibold tabular-nums">{formatPercent(snapshotStats.netExposure)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Gross exposure</p>
              <p className="mt-1 font-mono text-sm font-semibold tabular-nums">{formatPercent(snapshotStats.grossExposure)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Top 5 concentration</p>
              <p className="mt-1 font-mono text-sm font-semibold tabular-nums">{formatPercent(snapshotStats.topFiveConcentration)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Turnover</p>
              <p className="mt-1 font-mono text-sm font-semibold tabular-nums">{formatPercent(snapshotStats.turnover)}</p>
            </div>
          </div>
          {previousDate && (
            <p className="mt-3 text-[10px] text-muted-foreground">
              Since previous snapshot: {snapshotStats.added} added · {snapshotStats.adjusted} resized · {snapshotStats.exited} exited.
            </p>
          )}
        </CardHeader>
        <CardContent className="pt-4">
          <div className="mb-5 space-y-2">
            <div className="flex justify-between text-[10px] text-muted-foreground">
              <span>{dates[0]}</span>
              <span>{dates[dates.length - 1]}</span>
            </div>
            <input
              aria-label="Holdings snapshot date"
              type="range"
              min="0"
              max={Math.max(0, dates.length - 1)}
              value={selectedDateIdx}
              onChange={(event) => setSelectedDateIdx(Number(event.target.value))}
              className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary"
            />
          </div>

          <div ref={parentRef} className="h-[410px] overflow-auto rounded-lg border">
            <table className="relative min-w-[760px] w-full text-left text-sm">
              <thead className="sticky top-0 z-10 block border-b bg-background/95 text-[10px] text-muted-foreground backdrop-blur">
                <tr className="flex w-full">
                  <th className="flex-[1.5] px-4 py-2.5 font-medium">Instrument</th>
                  <th className="flex-1 px-4 py-2.5 text-right font-medium">Weight</th>
                  <th className="flex-1 px-4 py-2.5 text-right font-medium">Δ weight</th>
                  <th className="flex-1 px-4 py-2.5 text-right font-medium">Price</th>
                  <th className="flex-1 px-4 py-2.5 text-right font-medium">Amount</th>
                </tr>
              </thead>
              <tbody className="relative block" style={{ height: `${rowVirtualizer.getTotalSize()}px` }}>
                {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                  const position = currentPositions[virtualRow.index];
                  const delta = position.deltaWeight;
                  return (
                    <tr
                      key={position.instrument}
                      data-testid="positions-table-row"
                      className="absolute left-0 top-0 flex w-full border-b transition-colors hover:bg-muted/20"
                      style={{ height: `${virtualRow.size}px`, transform: `translateY(${virtualRow.start}px)` }}
                    >
                      <td className="flex flex-[1.5] items-center px-4 py-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="truncate font-medium">{position.instrument_label || position.name || getName(position.instrument)}</span>
                            {position.changeKind === 'new' && <Badge variant="outline" className="h-4 px-1 text-[8px] text-emerald-700 dark:text-emerald-300">New</Badge>}
                          </div>
                          <span className="block truncate font-mono text-[9px] text-muted-foreground">{position.instrument}</span>
                        </div>
                      </td>
                      <td className="flex flex-1 items-center justify-end gap-2 px-4 py-2 text-right">
                        <div className="h-1 w-14 overflow-hidden rounded-full bg-muted">
                          <div className="h-full bg-primary" style={{ width: `${Math.min(Math.abs(position.weight) * 100, 100)}%` }} />
                        </div>
                        <span className="min-w-14 font-mono text-xs font-semibold tabular-nums">{formatPercent(position.weight, 2)}</span>
                      </td>
                      <td className={cn(
                        'flex flex-1 items-center justify-end px-4 py-2 font-mono text-xs tabular-nums',
                        delta !== null && delta > EPSILON && 'text-emerald-600 dark:text-emerald-400',
                        delta !== null && delta < -EPSILON && 'text-rose-600 dark:text-rose-400',
                        (delta === null || Math.abs(delta) <= EPSILON) && 'text-muted-foreground',
                      )}>
                        {delta === null ? '—' : `${delta > 0 ? '+' : ''}${(delta * 100).toFixed(2)}%`}
                      </td>
                      <td className="flex flex-1 items-center justify-end px-4 py-2 font-mono text-xs tabular-nums text-muted-foreground">{position.price?.toFixed(2) || '—'}</td>
                      <td className="flex flex-1 items-center justify-end px-4 py-2 font-mono text-xs tabular-nums text-muted-foreground">{position.amount?.toLocaleString() || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
