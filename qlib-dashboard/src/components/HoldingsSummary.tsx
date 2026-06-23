import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { Position } from "@/lib/types";

export function HoldingsSummary({
  positions,
  title,
}: {
  positions: Position[];
  title?: string;
}) {
  if (!positions.length) return null;

  const byDate: Record<string, Position[]> = {};
  for (const p of positions) {
    const d = p.date;
    if (!byDate[d]) byDate[d] = [];
    byDate[d].push(p);
  }
  const dates = Object.keys(byDate).sort();
  const lastDate = dates[dates.length - 1];
  const lastPositions = byDate[lastDate] || [];
  const uniqueInstruments = new Set(positions.map((p) => p.instrument)).size;
  const maxWeight = Math.max(...positions.map((p) => p.weight || 0));
  const avgWeight =
    positions.reduce((acc, p) => acc + (p.weight || 0), 0) / positions.length;

  // approximate turnover: sum abs(delta weight) / 2 over time
  let turnover = 0;
  const instruments = new Set(positions.map((p) => p.instrument));
  for (const inst of instruments) {
    const series = positions
      .filter((p) => p.instrument === inst)
      .sort((a, b) => a.date.localeCompare(b.date));
    for (let i = 1; i < series.length; i++) {
      turnover += Math.abs((series[i].weight || 0) - (series[i - 1].weight || 0));
    }
  }
  turnover = turnover / 2;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title || "Holdings Summary"}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm mb-6 pb-6 border-b">
          <div className="flex flex-col">
            <span className="text-muted-foreground">Last Date</span>
            <span className="font-medium">{lastDate}</span>
          </div>
          <div className="flex flex-col">
            <span className="text-muted-foreground">Holdings (Last)</span>
            <span className="font-medium">{lastPositions.length}</span>
          </div>
          <div className="flex flex-col">
            <span className="text-muted-foreground">Unique Instruments</span>
            <span className="font-medium">{uniqueInstruments}</span>
          </div>
          <div className="flex flex-col">
            <span className="text-muted-foreground">Max Weight</span>
            <span className="font-medium">{(maxWeight * 100).toFixed(2)}%</span>
          </div>
          <div className="flex flex-col">
            <span className="text-muted-foreground">Avg Weight</span>
            <span className="font-medium">{(avgWeight * 100).toFixed(2)}%</span>
          </div>
          <div className="flex flex-col">
            <span className="text-muted-foreground">Turnover (approx)</span>
            <span className="font-medium">{(turnover ?? 0).toFixed(2)}</span>
          </div>
        </div>
        
        <h3 className="text-xs font-bold uppercase tracking-widest text-muted-foreground mb-3">Positions as of {lastDate}</h3>
        <div className="border rounded-md max-h-[300px] overflow-y-auto">
          <Table>
            <TableHeader className="bg-muted/50 sticky top-0">
              <TableRow>
                <TableHead className="font-black uppercase text-[10px] tracking-wider">Instrument</TableHead>
                <TableHead className="font-black uppercase text-[10px] tracking-wider text-right">Weight</TableHead>
                <TableHead className="font-black uppercase text-[10px] tracking-wider text-right">Price</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {lastPositions.sort((a, b) => (b.weight || 0) - (a.weight || 0)).map((p, idx) => (
                <TableRow key={`${p.instrument}-${idx}`} data-testid="positions-table-row">
                  <TableCell className="font-mono text-xs font-bold">
                    {p.instrument}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs">
                    <Badge variant="outline" className="font-black">
                      {((p.weight || 0) * 100).toFixed(2)}%
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs text-muted-foreground">
                    {p.price ? p.price.toFixed(2) : '-'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}
