import { useMemo, useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ComposedChart, Cell, CartesianGrid } from 'recharts';
import { format, parseISO } from 'date-fns';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useNameMap } from '@/lib/useNameMap';
import type { Position, ReportRow } from '@/lib/types';

export function PositionsTable({ positions, report }: { positions: Position[], report?: ReportRow[] }) {
  const { getName } = useNameMap();
  // Get unique dates from positions
  const dates = useMemo(() => Array.from(new Set(positions.map(p => p.date))).sort(), [positions]);
  const [selectedDateIdx, setSelectedDateIdx] = useState(dates.length - 1);

  useEffect(() => {
    if (!dates.length) return;
    const nextIdx = Math.max(0, dates.length - 1);
    if (selectedDateIdx < 0 || selectedDateIdx >= dates.length) {
      setSelectedDateIdx(nextIdx);
    }
  }, [dates, selectedDateIdx]);

  const currentDate = dates[selectedDateIdx];

  const currentPositions = useMemo(() => {
    if (!currentDate) return [];
    return positions.filter(p => p.date === currentDate).sort((a, b) => (b.weight || 0) - (a.weight || 0));
  }, [positions, currentDate]);

  // Virtualization setup
  const parentRef = useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: currentPositions.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 50,
    overscan: 5,
  });

  const handleBarClick = (data: unknown) => {
    if (!data || typeof data !== 'object') return;
    const date = (data as Record<string, unknown>).date;
    if (typeof date !== 'string') return;
    const idx = dates.indexOf(date);
    if (idx !== -1) {
      setSelectedDateIdx(idx);
    }
  };

  if (!positions.length) return <div className="p-4 text-center">No position data available.</div>;

  return (
    <div className="space-y-6">
      {/* 1. Portfolio Turnover Chart (Linkage Source) */}
      <Card className="border-none shadow-lg bg-card overflow-hidden text-left">
        <CardHeader className="bg-muted/10 pb-2 border-b">
          <CardTitle className="text-xs font-black uppercase tracking-widest text-primary">Portfolio Execution Dynamics</CardTitle>
          <CardDescription className="text-[9px] uppercase font-bold text-muted-foreground">Daily Turnover. Click any bar to inspect specific holdings for that day.</CardDescription>
        </CardHeader>
        <CardContent className="h-[250px] p-4 pt-6">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={report || []}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.1} />
              <XAxis dataKey="date" tickFormatter={(d) => format(parseISO(d), 'MM/yy')} minTickGap={30} tick={{ fontSize: 8 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 8 }} axisLine={false} tickLine={false} width={30} />
              <Tooltip
                cursor={{ fill: 'hsl(var(--primary))', opacity: 0.05 }}
                contentStyle={{ fontSize: '10px', borderRadius: '8px' }}
              />
              <Bar
                dataKey="turnover"
                onClick={handleBarClick}
                cursor="pointer"
                name="Daily Turnover"
              >
                {report?.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.date === currentDate ? "hsl(var(--primary))" : "hsl(var(--primary))"}
                    fillOpacity={entry.date === currentDate ? 1 : 0.4}
                  />
                ))}
              </Bar>
            </ComposedChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* 2. Holdings Table (Linkage Target) */}
      <Card className="border-none shadow-xl overflow-hidden bg-card">
        <CardHeader className="bg-muted/20 border-b py-4">
          <CardTitle className="flex justify-between items-center text-sm font-black uppercase tracking-tight text-left">
            <span>Positions Snapshot: <span className="text-primary font-mono ml-2">{currentDate}</span></span>
            <Badge variant="secondary" className="text-[10px] font-bold">{currentPositions.length} Assets</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="mb-8 space-y-3">
            <div className="flex justify-between text-[10px] font-black uppercase text-muted-foreground tracking-widest">
              <span>{dates[0]}</span>
              <span className="text-primary bg-primary/5 px-2 py-0.5 rounded border border-primary/10">Timeline Scrubbing</span>
              <span>{dates[dates.length - 1]}</span>
            </div>
            <input
              type="range"
              min="0"
              max={dates.length - 1}
              value={selectedDateIdx}
              onChange={(e) => setSelectedDateIdx(parseInt(e.target.value))}
              className="w-full h-1.5 bg-muted rounded-full appearance-none cursor-pointer accent-primary hover:accent-primary/80 transition-all"
            />
          </div>

          {/* Windowed Virtual List for extremely fast rendering */}
          <div ref={parentRef} className="rounded-xl border border-border/50 overflow-auto shadow-sm h-[400px]">
            <table className="w-full text-sm text-left relative">
              <thead className="bg-muted/50 text-[10px] uppercase font-black text-muted-foreground border-b border-border/50 sticky top-0 z-10 w-full table-fixed">
                <tr className="flex w-full">
                  <th className="py-2 px-4 font-black tracking-widest text-left flex-1">Instrument</th>
                  <th className="py-2 px-4 font-black tracking-widest text-right flex-1">Exposure (Weight)</th>
                  <th className="py-2 px-4 font-black tracking-widest text-right flex-1">Market Price</th>
                  <th className="py-2 px-4 font-black tracking-widest text-right flex-1">Volume</th>
                </tr>
              </thead>
              <tbody
                className="divide-y divide-border/50 block relative"
                style={{ height: `${rowVirtualizer.getTotalSize()}px` }}
              >
                {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                  const pos = currentPositions[virtualRow.index];
                  return (
                    <tr
                      key={pos.instrument}
                      className="group hover:bg-muted/20 transition-all border-b last:border-0 flex w-full absolute top-0 left-0"
                      style={{
                        height: `${virtualRow.size}px`,
                        transform: `translateY(${virtualRow.start}px)`
                      }}
                    >
                      <td className="px-4 py-2 flex-1 flex items-center">
                        <div className="flex flex-col">
                          <span className="font-bold text-primary tracking-tight leading-tight">{pos.instrument_label || getName(pos.instrument)}</span>
                          <span className="text-[9px] text-muted-foreground font-mono opacity-60 leading-tight">{pos.instrument}</span>
                        </div>
                      </td>
                      <td className="px-4 py-2 text-right flex-1 flex items-center justify-end">
                        <div className="flex items-center justify-end gap-2">
                          <div className="w-16 h-1 bg-muted rounded-full overflow-hidden shrink-0">
                            <div className="h-full bg-primary" style={{ width: `${(pos.weight * 100)}%` }} />
                          </div>
                          <span className="font-mono font-black text-xs leading-tight">{(pos.weight * 100).toFixed(2)}%</span>
                        </div>
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-xs font-bold text-muted-foreground leading-tight flex-1 flex items-center justify-end">{pos.price?.toFixed(2) || '-'}</td>
                      <td className="px-4 py-2 text-right font-mono text-xs text-muted-foreground opacity-70 leading-tight flex-1 flex items-center justify-end">{pos.amount?.toLocaleString() || '-'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
