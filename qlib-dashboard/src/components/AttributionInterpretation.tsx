import { useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Lightbulb, TrendingUp, TrendingDown, AlertCircle } from "lucide-react";
import type { Position, ReportRow } from "@/lib/types";

export function AttributionInterpretation({ positions, report }: { positions: Position[], report?: ReportRow[] }) {
  const labelByInstrument = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of positions) {
      if (!row?.instrument) continue;
      const code = String(row.instrument);
      const label = row.instrument_label ? String(row.instrument_label) : code;
      if (!map.has(code)) map.set(code, label);
    }
    return map;
  }, [positions]);

  const accountByDate = useMemo(() => {
    const map = new Map<string, number>();
    if (!report) return map;
    for (const row of report) {
      if (row?.date && typeof row.account === "number") {
        map.set(row.date, row.account);
      }
    }
    return map;
  }, [report]);

  const contributionRows = useMemo(() => {
    if (!positions.length) return [];
    const instrumentData: Record<string, Position[]> = {};
    positions.forEach(p => {
        if (!instrumentData[p.instrument]) instrumentData[p.instrument] = [];
        instrumentData[p.instrument].push(p);
    });
    const contributions: Record<string, number> = {};

    Object.entries(instrumentData).forEach(([inst, data]) => {
        data.sort((a, b) => a.date.localeCompare(b.date));
        let totalContrib = 0;
        for (let i = 1; i < data.length; i++) {
            const prev = data[i-1];
            const curr = data[i];
            const prevPrice = typeof prev.price === "number" ? prev.price : Number(prev.price);
            const currPrice = typeof curr.price === "number" ? curr.price : Number(curr.price);
            if (Number.isFinite(prevPrice) && Number.isFinite(currPrice) && prevPrice !== 0) {
                const ret = (currPrice / prevPrice) - 1;
                if (prev.amount !== undefined && prev.amount !== null) {
                    const amt = typeof prev.amount === "number" ? prev.amount : Number(prev.amount);
                    if (Number.isFinite(amt)) totalContrib += (currPrice - prevPrice) * amt;
                } else if (prev.weight !== undefined && prev.weight !== null) {
                    const account = accountByDate.get(prev.date);
                    if (account) {
                        const w = typeof prev.weight === "number" ? prev.weight : Number(prev.weight);
                        if (Number.isFinite(w)) totalContrib += ret * w * account;
                    }
                }
            }
        }
        contributions[inst] = totalContrib;
    });

    return Object.entries(contributions)
        .map(([instrument, val]) => ({ instrument, name: labelByInstrument.get(instrument) || instrument, value: val }));
  }, [positions, accountByDate, labelByInstrument]);

  const topContributors = useMemo(() => contributionRows.filter(d => d.value > 0).sort((a, b) => b.value - a.value).slice(0, 3), [contributionRows]);
  const topLosers = useMemo(() => contributionRows.filter(d => d.value < 0).sort((a, b) => a.value - b.value).slice(0, 3), [contributionRows]);

  if (topContributors.length === 0 && topLosers.length === 0) return null;

  const totalPositive = contributionRows.filter(d => d.value > 0).reduce((acc, d) => acc + d.value, 0);
  const totalNegative = contributionRows.filter(d => d.value < 0).reduce((acc, d) => acc + Math.abs(d.value), 0);
  const winRatio = contributionRows.length > 0 ? (contributionRows.filter(d => d.value > 0).length / contributionRows.length) : 0;

  return (
    <Card className="border-none shadow-lg bg-card overflow-hidden">
      <CardHeader className="bg-muted/10 pb-2 border-b">
        <CardTitle className="text-xs font-black uppercase tracking-widest flex items-center gap-2">
          <Lightbulb className="h-4 w-4 text-amber-500" /> Analyst Interpretation
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-4 space-y-4">
        <div className="space-y-2">
            <div className="flex justify-between items-center text-xs border-b border-dashed pb-1 border-border/50">
                <span className="text-muted-foreground uppercase font-bold">Winning Trades</span>
                <span className="font-mono font-bold text-green-500">{(winRatio * 100).toFixed(1)}%</span>
            </div>
            <div className="flex justify-between items-center text-xs border-b border-dashed pb-1 border-border/50">
                <span className="text-muted-foreground uppercase font-bold">Profit/Loss Ratio</span>
                <span className="font-mono font-bold">{(totalPositive / (totalNegative || 1)).toFixed(2)}x</span>
            </div>
        </div>

        <div className="space-y-3">
          {topContributors.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 text-[10px] uppercase font-bold text-green-500 mb-1.5"><TrendingUp className="h-3 w-3" /> Alpha Drivers</div>
              <ul className="space-y-1">
                {topContributors.map((c, i) => (
                  <li key={i} className="flex justify-between items-center text-xs">
                    <span className="font-medium truncate max-w-[140px] text-muted-foreground">{c.name}</span>
                    <span className="font-mono text-green-500">+{(c.value ?? 0).toFixed(0)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {topLosers.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 text-[10px] uppercase font-bold text-red-500 mb-1.5 mt-3"><TrendingDown className="h-3 w-3" /> Alpha Drags</div>
              <ul className="space-y-1">
                {topLosers.map((c, i) => (
                  <li key={i} className="flex justify-between items-center text-xs">
                    <span className="font-medium truncate max-w-[140px] text-muted-foreground">{c.name}</span>
                    <span className="font-mono text-red-500">{(c.value ?? 0).toFixed(0)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="p-3 bg-muted/30 rounded-lg text-[10px] leading-relaxed text-muted-foreground italic border border-border/50 mt-4">
          <AlertCircle className="h-3 w-3 inline mr-1 -mt-0.5" />
          {winRatio > 0.55 ? 
             `Strategy exhibits strong stock picking ability with ${(winRatio*100).toFixed(1)}% win rate. Top performer ${topContributors[0]?.name} provided significant tailwind.` : 
             winRatio < 0.45 ? 
             `Win rate is below average (${(winRatio*100).toFixed(1)}%). Profitability relies heavily on outsized winners covering multiple small losses. Monitor ${topLosers[0]?.name} drawdowns.` : 
             `Balanced win rate (${(winRatio*100).toFixed(1)}%). Alpha generation is symmetrical, indicating robust cross-sectional selection without extreme single-stock reliance.`
          }
        </div>
      </CardContent>
    </Card>
  );
}
