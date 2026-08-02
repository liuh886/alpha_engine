import { useMemo } from 'react';
import { BarChart3, Braces, ShieldQuestion } from 'lucide-react';
import type { ModelData } from '@/lib/data-parser';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

interface FactorRow {
  name: string;
  models: number;
  meanImportance: number;
  maxImportance: number;
}

export function EvidenceFactorsPage({ models }: { models: ModelData[] }) {
  const factors = useMemo<FactorRow[]>(() => {
    const values = new Map<string, number[]>();
    for (const model of models) {
      const importance = model.backtest?.featureImportance ?? {};
      for (const [name, raw] of Object.entries(importance)) {
        const value = Number(raw);
        if (!Number.isFinite(value)) continue;
        values.set(name, [...(values.get(name) ?? []), value]);
      }
    }
    return Array.from(values.entries()).map(([name, rows]) => ({
      name,
      models: rows.length,
      meanImportance: rows.reduce((sum, value) => sum + value, 0) / rows.length,
      maxImportance: Math.max(...rows),
    })).sort((a, b) => b.meanImportance - a.meanImportance);
  }, [models]);

  return (
    <div className="research-page space-y-6">
      <header className="research-page-header">
        <div><p className="research-kicker">Evidence / Factors</p><h1>Factor provenance and observed contribution</h1><p>Feature importance is model-specific diagnostic evidence. It is not equivalent to out-of-sample IC, economic causality or an active factor promotion decision.</p></div>
        <Badge variant="outline" className="h-7 gap-1.5"><ShieldQuestion className="h-3.5 w-3.5" /> Imported formulas remain unvalidated</Badge>
      </header>

      <section className="grid gap-4 md:grid-cols-3">
        <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Models inspected</p><p className="mt-2 font-mono text-2xl font-semibold">{models.length}</p></CardContent></Card>
        <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Exported features</p><p className="mt-2 font-mono text-2xl font-semibold">{factors.length}</p></CardContent></Card>
        <Card className="research-surface"><CardContent className="pt-5"><p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Evidence type</p><p className="mt-2 text-lg font-semibold">Model importance</p></CardContent></Card>
      </section>

      {factors.length === 0 ? (
        <Card className="research-surface"><CardContent className="flex min-h-72 flex-col items-center justify-center text-center"><Braces className="h-8 w-8 text-muted-foreground" /><h2 className="mt-3 text-lg font-semibold">No factor importance is exported</h2><p className="mt-2 max-w-xl text-sm text-muted-foreground">The active model records do not contain a feature-importance mapping. The studio does not reconstruct formulas or infer factor effectiveness from returns.</p></CardContent></Card>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[0.8fr_1.2fr]">
          <Card className="research-surface"><CardHeader><CardTitle className="flex items-center gap-2 text-sm"><BarChart3 className="h-4 w-4 text-primary" /> Leading diagnostic features</CardTitle></CardHeader><CardContent className="space-y-3">{factors.slice(0, 12).map((factor) => <div key={factor.name}><div className="mb-1 flex items-center justify-between gap-3 text-xs"><span className="truncate font-medium">{factor.name}</span><span className="font-mono">{factor.meanImportance.toFixed(4)}</span></div><div className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(2, (factor.meanImportance / factors[0].meanImportance) * 100)}%` }} /></div></div>)}</CardContent></Card>
          <Card className="research-surface overflow-hidden"><CardHeader><CardTitle className="text-sm">Feature evidence table</CardTitle></CardHeader><CardContent className="p-0"><div className="max-h-[560px] overflow-auto"><Table><TableHeader className="sticky top-0 bg-card"><TableRow><TableHead>Feature</TableHead><TableHead>Models</TableHead><TableHead>Mean importance</TableHead><TableHead>Maximum</TableHead><TableHead>Status</TableHead></TableRow></TableHeader><TableBody>{factors.map((factor) => <TableRow key={factor.name}><TableCell className="font-mono text-xs">{factor.name}</TableCell><TableCell>{factor.models}</TableCell><TableCell className="font-mono">{factor.meanImportance.toFixed(5)}</TableCell><TableCell className="font-mono">{factor.maxImportance.toFixed(5)}</TableCell><TableCell><Badge variant="outline" className="text-[9px]">diagnostic only</Badge></TableCell></TableRow>)}</TableBody></Table></div></CardContent></Card>
        </div>
      )}
    </div>
  );
}
